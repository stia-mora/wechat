import os
import time
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .content import article_key, clean_content
from .db import db
from .repository import enqueue, index_account, index_article


class SourceBlocked(Exception):
    pass


class SourceClient:
    def __init__(self):
        self.last_request = 0
        self.client = httpx.Client(
            base_url=os.environ["SOURCE_API_URL"].rstrip("/"), timeout=150, trust_env=False
        )

    def request(self, method, path, **kwargs):
        delay = max(13, float(os.getenv("CRAWL_INTERVAL_SECONDS", "13"))) - (
            time.monotonic() - self.last_request
        )
        if delay > 0:
            time.sleep(delay)
        self.last_request = time.monotonic()
        response = self.client.request(method, path, **kwargs)
        if response.status_code in (401, 403, 429):
            raise SourceBlocked(f"采集服务要求认证或限流，HTTP {response.status_code}")
        response.raise_for_status()
        result = response.json()
        if not result.get("success"):
            message = result.get("error") or "数据源返回失败"
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
        return result.get("data") or {}

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

    def sync(self, payload):
        with db() as conn:
            account = conn.execute(
                "SELECT * FROM official_accounts WHERE id=%s", (payload["target_id"],)
            ).fetchone()
        if not account:
            raise ValueError("公众号不存在")
        seen = []
        parse_enqueued = 0
        for page in range(payload.get("pages", 1)):
            data = self.request(
                "GET",
                "/api/public/articles",
                params={"fakeid": account["source_id"], "begin": page * 10, "count": 10},
            )
            items = data.get("articles", [])
            with db() as conn:
                for item in items:
                    url = item.get("link", "")
                    if not url:
                        continue
                    published = item.get("create_time") or item.get("update_time")
                    row = conn.execute(
                        """INSERT INTO articles(account_id,source_key,title,author,source_url,cover_url,summary,publish_time)
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(source_key) DO UPDATE SET title=EXCLUDED.title,cover_url=EXCLUDED.cover_url,updated_at=now() RETURNING id,status""",
                        (
                            account["id"],
                            article_key(url),
                            item["title"],
                            item.get("author") or "",
                            url,
                            item.get("cover") or "",
                            item.get("digest") or "",
                            datetime.fromtimestamp(published, UTC) if published else None,
                        ),
                    ).fetchone()
                    index_article(conn, row["id"])
                    if (
                        row["status"] not in ("ready", "hidden")
                        and parse_enqueued < payload.get("parse_limit", 3)
                        and enqueue(conn, "parse", {"target_id": row["id"]})
                    ):
                        parse_enqueued += 1
                    biz = parse_qs(urlparse(url).query).get("__biz")
                    if biz:
                        profile_url = "https://mp.weixin.qq.com/mp/profile_ext?" + urlencode(
                            {"action": "home", "__biz": biz[0]}
                        )
                        conn.execute(
                            "UPDATE official_accounts SET source_url=%s WHERE id=%s",
                            (profile_url, account["id"]),
                        )
                    seen.append(row["id"])
                conn.execute(
                    "UPDATE official_accounts SET last_crawled_at=now(),last_article_at=(SELECT max(publish_time) FROM articles WHERE account_id=%s) WHERE id=%s",
                    (account["id"], account["id"]),
                )
            if not items or (page + 1) * 10 >= data.get("total", 0):
                break
        return {"account_id": account["id"], "articles": len(set(seen))}

    def parse(self, payload):
        with db() as conn:
            article = conn.execute(
                "SELECT * FROM articles WHERE id=%s", (payload["target_id"],)
            ).fetchone()
        if not article:
            raise ValueError("文章不存在")
        data = self.request("POST", "/api/article", json={"url": article["source_url"]})
        html, text = clean_content(data.get("content", ""))
        if not text.strip():
            raise ValueError("未返回可读正文")
        with db() as conn:
            conn.execute(
                "UPDATE articles SET content_html=%s,content_text=%s,word_count=%s,status=CASE WHEN status='hidden' THEN 'hidden' ELSE 'ready' END,crawl_time=now(),updated_at=now() WHERE id=%s",
                (html, text, len(text), article["id"]),
            )
            index_article(conn, article["id"])
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
