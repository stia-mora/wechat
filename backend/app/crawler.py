import os
import time
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .content import clean_content
from .db import db
from .repository import enqueue, index_account, index_article


class SourceBlocked(RuntimeError):
    pass


class SourceClient:
    def __init__(self):
        self.last_request = 0
        self.client = httpx.Client(
            base_url=os.environ["SOURCE_API_URL"].rstrip("/"), timeout=150, trust_env=False
        )

    def request(self, method, path, remote=True, **kwargs):
        delay = max(13, float(os.getenv("CRAWL_INTERVAL_SECONDS", "13"))) - (
            time.monotonic() - self.last_request
        )
        if remote and delay > 0:
            time.sleep(delay)
        if remote:
            self.last_request = time.monotonic()
        response = self.client.request(method, path, **kwargs)
        if response.status_code in (401, 403, 429):
            raise SourceBlocked(f"采集服务要求认证或限流，HTTP {response.status_code}")
        response.raise_for_status()
        result = response.json()
        if not result.get("success"):
            message = result.get("error") or result.get("message") or "数据源返回失败"
            if any(
                word in message.lower()
                for word in (
                    "登录",
                    "验证",
                    "credential",
                    "login",
                    "频繁",
                    "rate limit",
                    "频率",
                    "freq control",
                    "200013",
                )
            ):
                raise SourceBlocked(message)
            raise RuntimeError(message)
        return result.get("data") if "data" in result else result

    def discover(self, payload):
        data = self.request("GET", "/api/public/searchbiz", params={"query": payload["query"]})
        found = []
        with db() as conn:
            category = payload.get("category_id")
            if (
                category
                and not conn.execute(
                    "SELECT id FROM categories WHERE id=%s", (category,)
                ).fetchone()
            ):
                raise ValueError("分类不存在")
            for item in data.get("list", []):
                if not item.get("fakeid") or not item.get("nickname"):
                    continue
                row = conn.execute(
                    """INSERT INTO official_accounts(source_id,name,wechat_id,avatar_url,description,original_description,primary_category_id,source_url,last_crawled_at)
                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now()) ON CONFLICT(platform,source_id) DO UPDATE SET
                  name=EXCLUDED.name,wechat_id=EXCLUDED.wechat_id,avatar_url=EXCLUDED.avatar_url,
                  description=CASE WHEN official_accounts.description='' THEN EXCLUDED.description ELSE official_accounts.description END,
                  original_description=CASE WHEN EXCLUDED.original_description<>'' THEN EXCLUDED.original_description ELSE official_accounts.original_description END,
                  primary_category_id=coalesce(official_accounts.primary_category_id,EXCLUDED.primary_category_id),last_crawled_at=now(),updated_at=now()
                  RETURNING id,name,source_id""",
                    (
                        item["fakeid"],
                        item["nickname"],
                        item.get("alias") or "",
                        item.get("round_head_img") or "",
                        item.get("signature") or "",
                        item.get("signature") or "",
                        category,
                        "",
                    ),
                ).fetchone()
                index_account(conn, row["id"])
                found.append(row)
        return {"count": len(found), "accounts": found, "query": payload["query"]}

    def bridge(self, method, path, remote=False, **kwargs):
        return self.request(
            method,
            "/api/bridge" + path,
            remote=remote,
            headers={"Authorization": "Bearer " + os.environ["ADMIN_TOKEN"]},
            **kwargs,
        )

    def sync(self, payload):
        if payload.get("cache_only"):
            from .pipeline import run

            return run(self, payload)
        from .weread_crawler import collect

        return collect(payload)

    def parse(self, payload):
        from .collection_policy import eligible

        with db() as conn:
            article = conn.execute(
                "SELECT * FROM articles WHERE id=%s", (payload["target_id"],)
            ).fetchone()
        if not article:
            raise ValueError("文章不存在")
        if not eligible(article["publish_time"]):
            raise SourceBlocked("仅采集 2026-06-01 起的正文；此文章日期过早或尚未确认")
        with db() as conn:
            account = conn.execute(
                "SELECT * FROM official_accounts WHERE id=%s", (article["account_id"],)
            ).fetchone()
        cached = self.bridge(
            "POST",
            "/articles",
            json={
                "fakeid": account["source_id"],
                "nickname": account["name"],
                "title": article["title"],
                "link": article["source_url"],
                "publish_time": int(article["publish_time"].timestamp())
                if article["publish_time"]
                else 0,
                "author": article["author"],
                "cover": article["cover_url"],
                "digest": article["summary"],
            },
        )
        data = (
            cached
            if cached.get("content")
            else self.bridge("POST", f"/articles/{cached['id']}/body", remote=True)
        )
        if not eligible(data.get("publish_time") or article["publish_time"]):
            raise SourceBlocked("仅采集 2026-06-01 起的正文；解析后的日期不在采集范围")
        html, text = clean_content(data.get("content", ""))
        if not text.strip():
            raise ValueError("未返回可读正文")
        with db() as conn:
            conn.execute(
                "UPDATE articles SET title=%s,author=%s,publish_time=%s,content_html=%s,content_text=%s,word_count=%s,status=CASE WHEN status='hidden' THEN 'hidden' ELSE 'ready' END,crawl_time=now(),updated_at=now() WHERE id=%s",
                (
                    data.get("title") or article["title"],
                    data.get("author") or article["author"],
                    datetime.fromtimestamp(data["publish_time"], UTC)
                    if data.get("publish_time")
                    else article["publish_time"],
                    html,
                    text,
                    len(text),
                    article["id"],
                ),
            )
            index_article(conn, article["id"])
            biz = parse_qs(urlparse(article["source_url"]).query).get("__biz")
            conn.execute(
                "UPDATE official_accounts SET last_article_at=(SELECT max(publish_time) FROM articles WHERE account_id=%s) WHERE id=%s",
                (article["account_id"], article["account_id"]),
            )
            if biz:
                conn.execute(
                    "UPDATE official_accounts SET source_url=%s WHERE id=%s",
                    (
                        "https://mp.weixin.qq.com/mp/profile_ext?"
                        + urlencode({"action": "home", "__biz": biz[0]}),
                        article["account_id"],
                    ),
                )
            enqueue(conn, "article_ai", {"target_id": article["id"]})
            count = conn.execute(
                "SELECT count(*) AS n FROM articles WHERE account_id=%s AND status='ready'",
                (article["account_id"],),
            ).fetchone()["n"]
            previous = conn.execute(
                "SELECT source_total_count,reviewed FROM ai_account_profiles WHERE account_id=%s",
                (article["account_id"],),
            ).fetchone()
            if count >= 3 and (
                not previous
                or (not previous["reviewed"] and count >= previous["source_total_count"] + 10)
            ):
                enqueue(conn, "account_ai", {"target_id": article["account_id"]})
        return {"article_id": article["id"], "word_count": len(text)}
