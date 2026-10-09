# SPDX-License-Identifier: AGPL-3.0-only
"""Isolated MP QR login: upstream cookies never cross the HTTP boundary."""

import base64
import secrets
import threading
import time
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import HTTPException


class MPLogin:
    def __init__(self, manager, client_factory=None):
        self.manager = manager
        self.client_factory = client_factory or (lambda: httpx.Client(
            base_url="https://mp.weixin.qq.com", timeout=25, trust_env=False,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                     "Referer": "https://mp.weixin.qq.com/", "Origin": "https://mp.weixin.qq.com"}))
        self.lock = threading.Lock()
        self.session = None

    def close(self):
        if self.session:
            self.session["client"].close()
            self.session = None

    @staticmethod
    def checked(response):
        response.raise_for_status()
        data = response.json()
        if data.get("base_resp", {}).get("ret") != 0:
            raise HTTPException(409, "微信拒绝当前登录请求，请重新扫码或处理验证")
        return data

    def start(self):
        with self.lock:
            if self.session and time.monotonic() < self.session["expires"]:
                raise HTTPException(409, "已有扫码会话，请先取消或等待过期")
            self.close()
            client = self.client_factory()
            try:
                self.checked(client.post("/cgi-bin/bizlogin", params={"action": "startlogin"}, data={
                    "userlang": "zh_CN", "redirect_url": "", "login_type": 3,
                    "sessionid": secrets.token_hex(16), "token": "", "lang": "zh_CN", "f": "json", "ajax": 1}))
                qr = client.get("/cgi-bin/scanloginqrcode", params={"action": "getqrcode", "random": int(time.time() * 1000)})
                qr.raise_for_status()
                image_type = "image/png" if qr.content.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg" if qr.content.startswith(b"\xff\xd8\xff") else ""
                if not image_type or len(qr.content) > 1024 * 1024:
                    raise HTTPException(502, "微信没有返回有效二维码图片")
                session_id = secrets.token_urlsafe(24)
                self.session = {"id": session_id, "client": client, "expires": time.monotonic() + 300, "last_poll": 0}
                return {"session_id": session_id, "qr": "data:" + image_type + ";base64," + base64.b64encode(qr.content).decode(), "state": "waiting", "expires_in": 300}
            except (httpx.HTTPError, ValueError):
                client.close()
                raise HTTPException(502, "公众平台登录服务暂不可连接") from None
            except Exception:
                client.close()
                raise

    def poll(self, session_id):
        with self.lock:
            session = self.session
            if not session or not secrets.compare_digest(session["id"], session_id):
                raise HTTPException(404, "扫码会话不存在")
            if time.monotonic() >= session["expires"]:
                self.close()
                raise HTTPException(410, "扫码会话已过期，请重新开始")
            if time.monotonic() - session["last_poll"] < 3:
                raise HTTPException(429, "请稍后再检查扫码状态")
            session["last_poll"] = time.monotonic()
            client = session["client"]
            try:
                data = self.checked(client.get("/cgi-bin/scanloginqrcode", params={"action": "ask", "token": "", "lang": "zh_CN", "f": "json", "ajax": 1}))
                if data.get("status") != 1:
                    return {"state": "scanned" if data.get("status") in (4, 6) else "waiting"}
                login = self.checked(client.post("/cgi-bin/bizlogin", params={"action": "login"}, data={
                    "userlang": "zh_CN", "redirect_url": "", "cookie_forbidden": 0,
                    "cookie_cleaned": 0, "plugin_used": 0, "login_type": 3,
                    "token": "", "lang": "zh_CN", "f": "json", "ajax": 1}))
                token = parse_qs(urlparse(login.get("redirect_url", "")).query).get("token", [""])[0]
                if not token.isdigit() or not client.cookies:
                    raise HTTPException(502, "微信未返回完整登录凭据")
                # A fresh authenticated API response is required before persistence.
                self.checked(client.get("/cgi-bin/searchbiz", params={
                    "action": "search_biz", "token": token, "lang": "zh_CN", "f": "json",
                    "ajax": 1, "query": "人工智能", "begin": 0, "count": 1}))
                cookie = "; ".join(f"{c.name}={c.value}" for c in client.cookies.jar
                                   if c.domain.lstrip(".") in ("weixin.qq.com", "mp.weixin.qq.com"))
                if not cookie or not self.manager.save_credentials(token, cookie, "", "公众平台来源", int((time.time() + 4 * 86400) * 1000)):
                    raise HTTPException(502, "有效凭据未能保存，请重试")
                self.close()
                return {"state": "verified", "message": "登录已通过接口验证并保存"}
            except (httpx.HTTPError, ValueError):
                raise HTTPException(502, "公众平台登录检查失败，未确认恢复") from None

    def cancel(self):
        with self.lock:
            self.close()
        return {"ok": True}
