"""Independent WeRead adapter. Protocol reference: rachelos/we-mp-rss (MIT).

No imports from the reference application, database, or singleton login driver.
"""

import base64
import re
from http.cookies import SimpleCookie
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup


class SourceError(Exception):
    def __init__(self, code, message, category="transient"):
        super().__init__(message)
        self.code = str(code)
        self.category = category


def book_id(fakeid):
    if re.fullmatch(r"MP_WXS_\d+", fakeid):
        return fakeid
    try:
        numeric = base64.b64decode(fakeid, validate=True).decode("ascii")
    except (ValueError, UnicodeError):
        raise SourceError("identity", "公众号标识无法转换为微信读书 bookId", "target")
    if not numeric.isdigit():
        raise SourceError("identity", "公众号标识不是数字编码", "target")
    return "MP_WXS_" + numeric


def cookie_values(raw):
    if "\r" in raw or "\n" in raw:
        raise SourceError("cookie", "Cookie 不能包含换行", "auth")
    parsed = SimpleCookie()
    parsed.load(raw)
    values = {k: v.value for k, v in parsed.items()}
    if not values.get("wr_vid") or not values.get("wr_skey"):
        raise SourceError("cookie", "Cookie 缺少 wr_vid 或 wr_skey", "auth")
    return values


def article_url(review_id, book):
    prefix = book + "_"
    if not review_id.startswith(prefix):
        raise SourceError("identity", "reviewId 与公众号 bookId 不一致", "target")
    # Tokens may contain underscores; never split on the last underscore.
    return "https://mp.weixin.qq.com/s/" + quote(review_id[len(prefix) :], safe="~_")


class WeReadAdapter:
    def __init__(self, credentials=None, before_request=None, transport=None):
        self.before_request = before_request or (lambda: None)
        self.on_credentials_changed = lambda credentials: None
        self.client = httpx.Client(
            base_url="https://weread.qq.com",
            timeout=35,
            trust_env=False,
            transport=transport,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://weread.qq.com/",
                "Origin": "https://weread.qq.com",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )
        for key, value in (credentials or {}).get("cookies", {}).items():
            self.client.cookies.set(key, value, domain=".weread.qq.com", path="/")
        if (credentials or {}).get("ticket"):
            self.client.headers["x-wr-ticket"] = credentials["ticket"]

    def close(self):
        self.client.close()

    def credentials(self):
        return {
            "cookies": {c.name: c.value for c in self.client.cookies.jar},
            "ticket": self.client.headers.get("x-wr-ticket", ""),
        }

    def request(self, method, path, html=False, **kwargs):
        try:
            return self._request(method, path, html=html, **kwargs)
        except SourceError as exc:
            # Retry a read once after renewal, never replay shelf writes or login calls.
            recoverable = exc.category == "auth" or (exc.category == "ambiguous" and path == "/web/shelf/sync" and self.credentials()["cookies"].get("wr_rt"))
            if not recoverable or method != "GET" or "/auth/" in path:
                raise
            self.renew()
            return self._request(method, path, html=html, **kwargs)

    def _request(self, method, path, html=False, **kwargs):
        previous = self.credentials()
        try:
            result = self._checked_request(method, path, html=html, **kwargs)
            if self.credentials() != previous:
                self.on_credentials_changed(self.credentials())
            return result
        except Exception:
            self.client.cookies.clear()
            for key, value in previous["cookies"].items():
                self.client.cookies.set(key, value, domain=".weread.qq.com", path="/")
            raise

    def _accept_credentials(self, response):
        values = self.credentials()["cookies"]
        # The response wins even if httpx retained an older host-only cookie.
        for cookie in response.cookies.jar:
            values[cookie.name] = cookie.value
        self.client.cookies.clear()
        for key, value in values.items():
            self.client.cookies.set(key, value, domain=".weread.qq.com", path="/")

    def _checked_request(self, method, path, html=False, **kwargs):
        self.before_request()
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx.TimeoutException:
            raise SourceError("timeout", "微信读书请求超时")
        except httpx.HTTPError:
            raise SourceError("network", "微信读书网络请求失败")
        if response.status_code == 401:
            raise SourceError(401, "微信读书登录已失效", "auth")
        if response.status_code in (403, 429):
            raise SourceError(
                response.status_code, "微信读书限制请求，请等待冷却或完成验证", "cooldown"
            )
        if response.status_code >= 400:
            raise SourceError(response.status_code, f"微信读书接口 HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            if html:
                self._accept_credentials(response)
                return response.text
            raise SourceError("invalid_json", "微信读书返回非 JSON 数据")
        if not isinstance(data, dict):
            raise SourceError("invalid_response", "微信读书响应结构不合法")
        code = str(data.get("errCode", data.get("errcode", 0)) or 0)
        if code != "0":
            category = (
                "auth"
                if code in ("-2012", "-2010", "-2013")
                else "ambiguous"
                if code == "-2041"
                else "transient"
            )
            # Do not persist raw upstream responses: they may contain credentials.
            raise SourceError(code, f"微信读书返回错误 {code}", category)
        if html:
            raise SourceError("invalid_content", "正文接口未返回 HTML")
        if path == "/web/login/renewal" and data.get("succ") != 1:
            raise SourceError("renewal_failed", "登录续期未确认成功，请重新登录", "auth")
        self._accept_credentials(response)
        return data

    def shelf(self):
        data = self.request(
            "GET", "/web/shelf/sync", params={"userVid": "", "synckey": 0, "lectureSynckey": 0}
        )
        if not isinstance(data.get("books"), list):
            raise SourceError("invalid_shelf", "未取得有效书架，不能判定登录成功")
        return data["books"]

    def ensure_subscription(self, book):
        shelf = self.shelf()
        if not any(str(i.get("bookId")) == book for i in shelf):
            self.request("POST", "/web/shelf/add", json={"bookIds": [book]})
            if not any(str(i.get("bookId")) == book for i in self.shelf()):
                raise SourceError("shelf_add", "加入书架后未找到公众号", "target")

    def articles(self, book, offset=0):
        data = self.request("GET", "/web/mp/articles", params={"bookId": book, "offset": offset})
        groups = data.get("reviews")
        if not isinstance(groups, list):
            raise SourceError("list_unavailable", "微信读书未返回历史列表结构", "capability")
        items = []
        for group in groups:
            for sub in group.get("subReviews", []):
                review = sub.get("review") or {}
                info = review.get("mpInfo") or {}
                rid = review.get("reviewId") or sub.get("reviewId")
                if not rid:
                    raise SourceError("invalid_article", "历史列表文章缺少唯一标识")
                items.append(
                    {
                        "external_id": rid,
                        "title": info.get("title") or "未命名文章",
                        "link": "https://mp.weixin.qq.com/s/" + quote(info["originalId"], safe="~_")
                        if info.get("originalId")
                        else article_url(rid, book),
                        "cover": info.get("pic_url") or "",
                        "digest": info.get("content") or review.get("content") or "",
                        "author": info.get("author") or "",
                        "publish_time": info.get("time")
                        or review.get("createTime")
                        or group.get("createTime")
                        or None,
                    }
                )
        return {"items": items, "next_offset": offset + len(groups), "exhausted": not groups}

    def latest(self, book):
        data = self.request("GET", "/api/mp/cover", params={"bookId": book})
        rid = data.get("reviewId")
        if not rid:
            raise SourceError("empty_cover", "公众号未返回最新文章", "target")
        return {
            "external_id": rid,
            "title": data.get("title") or "未命名文章",
            "link": article_url(rid, book),
            "cover": data.get("pic") or "",
            "digest": data.get("digest") or "",
            "publish_time": None,
        }

    def content(self, review_id):
        html = self.request("GET", "/web/mp/content", html=True, params={"reviewId": review_id})
        soup = BeautifulSoup(html, "html.parser")
        body = soup.select_one("#js_content") or soup.select_one(".rich_media_content")
        if body is None or not body.get_text(strip=True):
            for hidden in soup.select("script,style,noscript,template"):
                hidden.decompose()
            visible = soup.get_text(" ", strip=True)
            if any(
                message in visible
                for message in (
                    "环境异常",
                    "完成验证后",
                    "请完成安全验证",
                    "请输入验证码",
                    "拖动滑块",
                )
            ):
                raise SourceError(
                    "verification", "正文页面要求验证，请人工打开原文处理后检测账号", "verification"
                )
            raise SourceError("invalid_content", "正文页面没有可读内容", "content")
        timestamp = re.search(r'(?:var\s+)?ct\s*=\s*["\'](\d{10})["\']', html)
        author = soup.select_one("#js_name")
        return {
            "content": str(body),
            "publish_time": int(timestamp[1]) if timestamp else None,
            "author": author.get_text(strip=True) if author else "",
        }

    def login_start(self):
        data = self.request("GET", "/api/auth/getLoginUid")
        uid = data.get("uid") or (data.get("data") or {}).get("uid")
        if not uid:
            raise SourceError("login_uid", "微信读书未返回登录二维码标识")
        return str(uid)

    def login_poll(self, uid):
        data = self.request(
            "GET", "/api/auth/getLoginInfo", params={"uid": uid, "otp": ""}, timeout=55
        )
        inner = data.get("data") or data
        if not (data.get("succeed") or inner.get("succeed")):
            return {"status": "waiting", "message": "等待扫码确认"}
        vid = inner.get("webLoginVid") or inner.get("vid") or data.get("vid")
        if vid:
            self.client.cookies.set("wr_vid", str(vid), domain=".weread.qq.com", path="/")
        self.verify_or_renew()
        return {"status": "done", "message": "登录与书架验证成功"}

    def renew(self):
        if not self.credentials()["cookies"].get("wr_rt"):
            raise SourceError("expired", "登录凭据无效，请重新扫码或导入完整 Cookie", "auth")
        self._request("POST", "/web/login/renewal", json={"rq": "%2Fweb%2Fbook%2Fread", "ql": False})

    def verify_or_renew(self):
        return self.shelf()
