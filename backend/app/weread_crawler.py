"""Task-scoped WeRead collection, with persisted metadata and missing-body retries."""

import os

from psycopg.types.json import Jsonb

from . import account_pool as pool
from .collection_policy import body_since, eligible
from .db import db
from .normalizer import save_article
from .repository import enqueue
from .sources.weread import SourceError, WeReadAdapter


def collect(payload):
    job_id, target = payload["_job_id"], payload["target_id"]
    with db() as conn:
        subscription = pool.subscribe(conn, target)
    lease = pool.acquire(job_id, target, payload.get("_execution_token"))
    adapter = None
    progress = dict(payload.get("_progress") or {})
    capability = "history"
    skipped_bodies = []

    def checkpoint(stage, **values):
        pool.heartbeat(lease)
        progress.update(
            stage=stage, account_id=target, source_account_id=lease["account"]["id"], **values
        )
        with db() as conn:
            conn.execute(
                "UPDATE jobs SET result=%s WHERE id=%s AND lease_token=%s",
                (Jsonb(progress), job_id, lease["token"]),
            )

    try:
        adapter = WeReadAdapter(
            pool.credentials(lease), before_request=lambda: pool.throttle(lease)
        )
        book = subscription["external_id"]
        checkpoint("检查登录与加入微信读书书架")
        adapter.verify_or_renew()
        pool.save_credentials(lease, adapter.credentials())
        adapter.ensure_subscription(book)
        with db() as conn:
            conn.execute(
                "INSERT INTO source_memberships(source_account_id,account_id) VALUES (%s,%s) ON CONFLICT(source_account_id,account_id) DO UPDATE SET last_used_at=now()",
                (lease["account"]["id"], target),
            )
        # Backfill has its own durable cursor; normal incremental checks start at zero.
        offset = subscription["history_offset"] if payload.get("backfill") else 0
        # Check the newest page even while older history is still being backfilled.
        refresh_head = offset > 0
        exhausted = False
        reached_known = False
        for page_index in range(payload.get("pages", 3) + int(refresh_head)):
            head_only = refresh_head and page_index == 0
            request_offset = 0 if head_only else offset
            checkpoint("获取微信读书文章列表", offset=request_offset)
            try:
                page = adapter.articles(book, request_offset)
            except SourceError as exc:
                if exc.code not in ("-2041", "404", "list_unavailable"):
                    raise
                # A healthy shelf + failed list means degraded capability, not history success.
                adapter.shelf()
                page = {"items": [adapter.latest(book)], "next_offset": 0, "exhausted": False}
                capability = "latest_only"
            with db() as conn:
                ids = [i["external_id"] for i in page["items"]]
                known = (
                    conn.execute(
                        "SELECT count(*) n FROM article_origins WHERE source_id='weread' AND external_id=ANY(%s)",
                        (ids,),
                    ).fetchone()["n"]
                    if ids
                    else 0
                )
            reached_known = (
                bool(ids)
                and known == len(ids)
                and subscription["history_complete"]
                and not payload.get("backfill")
            )
            for item in page["items"]:
                save_article(target, book, item)
            if head_only and capability == "history":
                continue
            exhausted = page["exhausted"]
            offset = page["next_offset"]
            checkpoint("文章元数据已入库", offset=offset, capability=capability)
            if capability == "history":
                with db() as conn:
                    conn.execute(
                        "UPDATE source_subscriptions SET history_offset=greatest(history_offset,%s),history_complete=history_complete OR %s WHERE account_id=%s AND source_id='weread'",
                        (offset, exhausted or reached_known, target),
                    )
            if exhausted or reached_known or capability == "latest_only":
                break
        # Scan missing bodies in PostgreSQL, not only this response's new rows.
        with db() as conn:
            missing = conn.execute(
                """SELECT a.*,o.external_id FROM articles a JOIN article_origins o ON o.article_id=a.id
                WHERE a.account_id=%s AND o.source_id='weread' AND a.content_text='' AND a.publish_time>=%s
                AND (a.body_retry_after IS NULL OR a.body_retry_after<=now())
                ORDER BY a.publish_time DESC NULLS LAST,a.id DESC LIMIT %s""",
                (target, body_since(), payload.get("parse_limit", 20)),
            ).fetchall()
        for article in missing:
            checkpoint("补全文章正文", article_id=article["id"])
            try:
                body = adapter.content(article["external_id"])
            except SourceError as exc:
                with db() as conn:
                    conn.execute(
                        """UPDATE articles SET body_error=%s,body_failures=body_failures+1,
                        body_retry_after=CASE WHEN %s='content' THEN now()+interval '24 hours' ELSE NULL END WHERE id=%s""",
                        (str(exc), exc.category, article["id"]),
                    )
                if exc.category != "content":
                    raise
                skipped_bodies.append({"article_id": article["id"], "error": str(exc)})
                checkpoint("跳过单篇异常，继续补采", skipped_bodies=skipped_bodies)
                continue
            with db() as conn:
                conn.execute(
                    "UPDATE articles SET body_error=NULL,body_retry_after=NULL WHERE id=%s",
                    (article["id"],),
                )
            if body.get("publish_time"):
                with db() as conn:
                    conn.execute(
                        "UPDATE articles SET publish_time=to_timestamp(%s),body_publish_time=to_timestamp(%s),updated_at=now() WHERE id=%s",
                        (body["publish_time"], body["publish_time"], article["id"]),
                    )
            if not eligible(body.get("publish_time") or article["publish_time"]):
                continue
            save_article(
                target,
                book,
                {
                    "external_id": article["external_id"],
                    "title": article["title"],
                    "link": article["source_url"],
                    "cover": article["cover_url"],
                    "digest": article["summary"],
                    "author": body.get("author") or article["author"],
                    "content": body["content"],
                    "publish_time": body.get("publish_time")
                    or (article["publish_time"].timestamp() if article["publish_time"] else None),
                },
            )
        with db() as conn:
            counts = conn.execute(
                "SELECT count(*) total,count(*) FILTER(WHERE content_text<>'') readable FROM articles WHERE account_id=%s",
                (target,),
            ).fetchone()
            remaining = conn.execute(
                """SELECT count(*) n FROM articles a JOIN article_origins o ON o.article_id=a.id
                WHERE a.account_id=%s AND o.source_id='weread' AND a.content_text='' AND a.publish_time>=%s""",
                (target, body_since()),
            ).fetchone()["n"]
            hours = max(1, int(os.getenv("SYNC_INTERVAL_HOURS", "24")))
            conn.execute(
                """UPDATE source_subscriptions SET last_sync_at=now(),last_error=NULL,capability=%s,
                next_sync_at=now()+(%s*interval '1 hour') WHERE account_id=%s AND source_id='weread'""",
                (capability, hours, target),
            )
            conn.execute(
                "UPDATE official_accounts SET last_crawled_at=now(),last_article_at=(SELECT max(publish_time) FROM articles WHERE account_id=%s) WHERE id=%s",
                (target, target),
            )
            if counts["readable"] >= 3:
                previous = conn.execute(
                    "SELECT reviewed,source_total_count FROM ai_account_profiles WHERE account_id=%s",
                    (target,),
                ).fetchone()
                if not previous or (
                    not previous["reviewed"]
                    and counts["readable"] >= previous["source_total_count"] + 10
                ):
                    enqueue(conn, "account_ai", {"target_id": target})
        checkpoint(
            "仅最新文章：历史能力降级" if capability == "latest_only" else "本批完成",
            capability=capability,
            imported=counts["total"],
            readable_articles=counts["readable"],
            missing_bodies=remaining,
            skipped_bodies=skipped_bodies,
            body_since=body_since().isoformat(),
            history_complete=(exhausted or reached_known) if capability == "history" else False,
        )
        pool.release(lease, capability=capability)
        return progress
    except Exception as exc:
        with db() as conn:
            conn.execute(
                "UPDATE source_subscriptions SET last_failure_at=now(),last_error=%s WHERE account_id=%s AND source_id='weread'",
                (str(exc)[:500], target),
            )
        pool.release(lease, error=exc)
        raise
    finally:
        if adapter:
            adapter.close()
