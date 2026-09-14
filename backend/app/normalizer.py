"""Standardized article storage independent of acquisition provider."""

from .db import db
from .pipeline import import_article
from .repository import enqueue


def save_article(account_id, book, item):
    with db() as conn:
        origin = conn.execute(
            """SELECT a.account_id,a.source_url FROM article_origins o
            JOIN articles a ON a.id=o.article_id WHERE o.source_id='weread' AND o.external_id=%s""",
            (item["external_id"],),
        ).fetchone()
    if origin:
        if origin["account_id"] != account_id:
            raise ValueError("数据源文章已属于其他公众号")
        # Preserve identity if upstream switches between short and long article URLs.
        item = {**item, "link": origin["source_url"]}
    article_id = import_article(account_id, item)
    with db() as conn:
        existing = conn.execute(
            "SELECT article_id FROM article_origins WHERE source_id='weread' AND external_id=%s",
            (item["external_id"],),
        ).fetchone()
        if existing and existing["article_id"] != article_id:
            raise ValueError("数据源文章映射发生冲突")
        conn.execute(
            """INSERT INTO article_origins(source_id,external_id,article_id,book_id)
            VALUES ('weread',%s,%s,%s) ON CONFLICT(source_id,external_id) DO UPDATE SET fetched_at=now()""",
            (item["external_id"], article_id, book),
        )
        if item.get("content"):
            enqueue(conn, "embedding", {"target_id": article_id})
    return article_id
