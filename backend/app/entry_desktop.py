"""Windows collector. Run with a private JSON config, never tokens in CLI arguments."""

import argparse
import html
import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .entry_collection import public_article_url


class CollectionError(Exception):
    def __init__(self, category):
        self.category = category
        super().__init__(category)  # Never retain raw errors containing upstream URLs or keys.


def classify(status, payload):
    if isinstance(payload, dict) and payload.get("ret") in (-3, -6, 200003):
        return "auth"
    message = str(payload).lower()
    wrapped = re.search(r"\bstatus\s+(401|403|429)\b", message)
    if wrapped:
        status = int(wrapped.group(1))
    if status == 404 and "account" in message:
        return "unknown"
    if status == 429 or "200013" in message or "频繁" in message or "rate limit" in message:
        return "rate_limit"
    if "验证" in message or "captcha" in message:
        return "verification"
    if status in (401, 403) or "expired" in message or "credential" in message or "200003" in message:
        return "auth"
    if any(word in message for word in ("timeout", "connection refused", "connection reset", "no such host")):
        return "network"
    return "invalid"


def read_credentials(path):
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CollectionError("invalid")
    return value


def verify_page(content, expected_biz):
    text = content.decode("utf-8", errors="replace")
    if any(word in text for word in ("环境异常", "完成验证", "访问过于频繁", "wappoc_appmsgcaptcha")):
        raise CollectionError("verification")
    soup = BeautifulSoup(text, "html.parser")
    if not soup.select_one("#js_content") or not soup.select_one("#activity-name, #js_article_title, .rich_media_title"):
        raise CollectionError("invalid")
    matches = re.findall(r'''(?:\b(?:biz|bizuin)|["'](?:biz|bizuin)["'])\s*[:=]\s*["']([^"']+)["']''', text)
    if expected_biz not in matches or any(biz != expected_biz for biz in matches):
        raise CollectionError("identity")


def message_articles(data):
    """Normalize only the first-page formats supported by pinned wx_channel."""
    found_list = False
    for field in ("general_msg_list", "home_page_list"):
        raw = data.get(field)
        if raw in (None, ""):
            continue
        for _ in range(2):
            if isinstance(raw, str):
                raw = json.loads(raw)
        if isinstance(raw, dict):
            raw = next((raw[k] for k in ("list", "items", "articles") if k in raw), None)
        if not isinstance(raw, list):
            raise CollectionError("invalid")
        found_list = True
        articles = []
        for item in raw:
            if not isinstance(item, dict):
                raise CollectionError("invalid")
            article = item.get("app_msg_ext_info") or item
            url = article.get("content_url") or article.get("url") or article.get("source_url")
            if url:
                articles.append({**article, "content_url": url,
                                 "publish_time": (item.get("comm_msg_info") or {}).get("datetime")
                                 or article.get("publish_time") or article.get("create_time")})
        if articles:
            return articles
        if raw:
            raise CollectionError("invalid")
    if not found_list:
        raise CollectionError("invalid")
    return []


class DesktopCollector:
    def __init__(self, config):
        self.config = config
        base = config["server"]
        parsed = urlparse(base)
        if parsed.scheme != "https" or parsed.path.rstrip("/") != "/wechat":
            raise ValueError("server must be the HTTPS /wechat site")
        self.server = httpx.Client(base_url=base.rstrip("/") + "/api/entry-collector/", timeout=15,
                                   trust_env=False, headers={"Authorization": "Bearer " + config["collector_token"]})
        self.wx = httpx.Client(base_url="http://127.0.0.1:2026", timeout=45, trust_env=False,
                               headers={"X-Local-Auth": config["wx_token"]})
        self.public = httpx.Client(timeout=45, trust_env=False, follow_redirects=False)

    def close(self):
        self.server.close()
        self.wx.close()
        self.public.close()

    def api(self, endpoint, payload=None):
        response = self.server.post(endpoint, json=payload or {})
        response.raise_for_status()
        return response.json()

    def reserve_request(self, job, lease):
        while True:
            data = self.api(f"jobs/{job['id']}/request-permit", lease)
            if data["allowed"]:
                return
            # The heartbeat thread keeps the lease alive while the daily budget waits.
            time.sleep(min(60, max(1, data["wait_seconds"])))

    def collect(self, job, lease):
        credentials = read_credentials(Path(self.config["credentials_file"]))
        biz = job["source_id"]
        own = credentials.get(biz) or {}
        pre_captured = bool(own.get("key"))
        result = {**lease, "outcome": "invalid", "pre_captured": pre_captured, "request_count": 0}
        try:
            inventory_response = self.wx.get("/api/mp/list", params={"keyword": biz, "page_size": 100})
            if inventory_response.status_code != 200:
                raise CollectionError(classify(inventory_response.status_code, {}))
            inventory = inventory_response.json().get("data")
            if not isinstance(inventory, dict) or not isinstance(inventory.get("items"), list):
                raise CollectionError("invalid")
            inventory = inventory["items"]
            if not pre_captured:
                # v5.7.11 requires credentials for each biz. Fail closed instead of
                # fabricating a key or allowing an unmetered implicit refresh.
                result["outcome"] = "unknown"
                return result
            if not any(a.get("biz") == biz for a in inventory):
                raise CollectionError("invalid")
            # Same wx_channel protocol, explicit single-hop transport: no implicit
            # cookie refresh or redirects bypassing the shared request budget.
            self.reserve_request(job, lease)
            result["request_count"] += 1
            response = self.public.get("https://mp.weixin.qq.com/mp/profile_ext", params={
                "action": "getmsg", "__biz": biz, "uin": own.get("uin", ""),
                "key": own["key"], "pass_ticket": own.get("pass_ticket", ""),
                "wxtoken": "", "x5": "0", "count": 10, "offset": 0, "f": "json"},
                headers={"Cookie": own.get("cookie", ""), "X-Requested-With": "XMLHttpRequest",
                         "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781 UnifiedPCWindowsWechat XWEB/16467",
                         "Referer": "https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz=" + biz})
            if response.is_redirect:
                raise CollectionError("auth")
            if response.status_code != 200:
                raise CollectionError(classify(response.status_code, response.text))
            if any(word in response.text for word in ("环境异常", "完成验证", "wappoc_appmsgcaptcha")):
                raise CollectionError("verification")
            data = response.json()
            if not isinstance(data, dict) or data.get("ret") != 0:
                raise CollectionError(classify(response.status_code, data))
            articles = message_articles(data)
            if not articles:
                result["outcome"] = "empty"
                return result
            article = articles[0]
            url = html.unescape(article.get("content_url") or article.get("url") or "")
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.netloc != "mp.weixin.qq.com" or not (parsed.path == "/s" or parsed.path.startswith("/s/")):
                raise CollectionError("invalid")
            link_biz = parse_qs(parsed.query).get("__biz", [None])[0]
            if link_biz and link_biz != biz:
                raise CollectionError("identity")
            # Every redirect and identity request consumes the same persistent budget.
            for _ in range(4):
                self.reserve_request(job, lease)
                result["request_count"] += 1
                with self.public.stream("GET", url) as page_response:
                    if page_response.is_redirect:
                        next_url = urljoin(url, page_response.headers.get("location", ""))
                        if urlparse(next_url).scheme != "https" or urlparse(next_url).netloc != "mp.weixin.qq.com":
                            raise CollectionError("invalid")
                        url = next_url
                        continue
                    if page_response.status_code != 200:
                        raise CollectionError(classify(page_response.status_code, {}))
                    content = bytearray()
                    for chunk in page_response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > 2 * 1024 * 1024:
                            raise CollectionError("invalid")
                    verify_page(bytes(content), biz)
                    break
            else:
                raise CollectionError("invalid")
            public_url = public_article_url(url)
            published = article.get("publish_time")
            result.update(outcome="success", url=public_url, verified_biz=biz, link_verified=True,
                          title=article.get("title", ""),
                          publish_time=datetime.fromtimestamp(int(published), timezone.utc).isoformat() if published else None)
        except CollectionError as exc:
            result["outcome"] = exc.category
        except httpx.RequestError:
            result["outcome"] = "network"
        except (ValueError, TypeError, KeyError):
            result["outcome"] = "invalid"
        return result

    def run_job(self, job):
        lease = {"execution_token": job["execution_token"]}
        stopped = threading.Event()
        failed = threading.Event()

        def heartbeat():
            with httpx.Client(timeout=10, trust_env=False, headers=self.server.headers) as client:
                while not stopped.wait(20):
                    try:
                        reply = client.post(str(self.server.base_url) + f"jobs/{job['id']}/heartbeat", json=lease)
                        if reply.status_code != 200:
                            failed.set()
                            return
                    except httpx.HTTPError:
                        failed.set()
                        return

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            result = self.collect(job, lease)
            if failed.is_set():
                raise CollectionError("lease_lost")
            saved = self.api(f"jobs/{job['id']}/result", result)
            print(json.dumps({"job_id": job["id"], "outcome": saved["outcome"]}))
        finally:
            stopped.set()
            thread.join(timeout=11)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    collector = DesktopCollector(json.loads(args.config.read_text(encoding="utf-8")))
    try:
        while True:
            job = collector.api("claim")["job"]
            if job:
                collector.run_job(job)
            if args.once:
                break
            time.sleep(5)
    except (httpx.HTTPError, CollectionError, ValueError, OSError):
        print("采集端已停止：连接、配置或租约需要检查；未输出凭据或上游原始响应。")
        raise SystemExit(1) from None
    finally:
        collector.close()


if __name__ == "__main__":
    main()
