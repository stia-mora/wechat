"""Legacy local-cache import only. Active collection lives in weread_crawler."""

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlencode, urlparse

from psycopg.types.json import Jsonb

from .content import article_key, clean_content
from .db import db
from .repository import enqueue, index_account, index_article


def import_article(account_id, item):
    html, text = clean_content(item.get("content") or "")
    published = item.get("publish_time")
    with db() as conn:
        row = conn.execute(
            """INSERT INTO articles(account_id,source_key,title,author,source_url,cover_url,summary,publish_time)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(source_key) DO UPDATE SET
            title=EXCLUDED.title,cover_url=EXCLUDED.cover_url,
            author=coalesce(nullif(EXCLUDED.author,''),articles.author),
            summary=coalesce(nullif(EXCLUDED.summary,''),articles.summary),
            source_url=EXCLUDED.source_url,publish_time=coalesce(articles.body_publish_time,EXCLUDED.publish_time,articles.publish_time),
            updated_at=now() RETURNING id,content_text""",
            (
                account_id,
                article_key(item["link"]),
                item["title"],
                item.get("author") or "",
                item["link"],
                item.get("cover") or "",
                item.get("digest") or "",
                datetime.fromtimestamp(published, UTC) if published else None,
            ),
        ).fetchone()
        if text.strip() and text != row["content_text"]:
            conn.execute(
                """UPDATE articles SET content_html=%s,content_text=%s,word_count=%s,
                status=CASE WHEN status='hidden' THEN 'hidden' ELSE 'ready' END,
                crawl_time=now(),updated_at=now() WHERE id=%s""",
                (html, text, len(text), row["id"]),
            )
            enqueue(conn, "article_ai", {"target_id": row["id"]})
        index_article(conn, row["id"])
        biz = parse_qs(urlparse(item["link"]).query).get("__biz")
        if biz:
            conn.execute(
                "UPDATE official_accounts SET source_url=%s WHERE id=%s",
                (
                    "https://mp.weixin.qq.com/mp/profile_ext?"
                    + urlencode({"action": "home", "__biz": biz[0]}),
                    account_id,
                ),
            )
    return row["id"]


def run(source, payload):
    with db() as conn:
        account = conn.execute(
            "SELECT * FROM official_accounts WHERE id=%s", (payload["target_id"],)
        ).fetchone()
    if not account:
        raise ValueError("公众号不存在")
    progress = dict(payload.get("_progress") or {})
    progress.update(account_id=account["id"], account_name=account["name"])

    def checkpoint(stage, **values):
        progress.update(stage=stage, **values)
        if payload.get("_job_id"):
            with db() as conn:
                conn.execute(
                    "UPDATE jobs SET result=%s WHERE id=%s", (Jsonb(progress), payload["_job_id"])
                )

    def cached_import():
        after, items = 0, []
        while True:
            page = source.bridge(
                "GET", "/articles", params={"fakeid": account["source_id"], "after": after}
            )
            for item in page["items"]:
                import_article(account["id"], item)
                items.append(item)
            if not page["items"]:
                break
            after = page["next_after"]
        checkpoint(
            progress.get("stage", "导入缓存"),
            cached_articles=len(items),
            cached_bodies=sum(bool(i.get("content")) for i in items),
            imported=len(items),
        )
        return items

    checkpoint("导入缓存")
    items = cached_import()
    checkpoint("检查导出")
    items = cached_import()
    with db() as conn:
        conn.execute(
            """UPDATE official_accounts SET last_crawled_at=CASE WHEN %s THEN last_crawled_at ELSE now() END,
                     last_article_at=(SELECT max(publish_time) FROM articles WHERE account_id=%s)
                     WHERE id=%s""",
            (bool(payload.get("cache_only")), account["id"], account["id"]),
        )
        count = conn.execute(
            "SELECT count(*) AS n FROM articles WHERE account_id=%s AND status='ready'",
            (account["id"],),
        ).fetchone()["n"]
        previous = conn.execute(
            "SELECT source_total_count,reviewed FROM ai_account_profiles WHERE account_id=%s",
            (account["id"],),
        ).fetchone()
        if count >= 3 and (
            not previous
            or (not previous["reviewed"] and count >= previous["source_total_count"] + 10)
        ):
            enqueue(conn, "account_ai", {"target_id": account["id"]})
        index_account(conn, account["id"])
    checkpoint(
        "已完成", readable_articles=count, export_available=any(i.get("content") for i in items)
    )
    return progress
