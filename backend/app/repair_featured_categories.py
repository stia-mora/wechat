"""Fill missing categories for the existing, curated homepage accounts."""
import json

from .db import db
from .repository import index_account


FEATURED_CATEGORIES = {
    "MjM5MjAxNDM4MA==": "媒体与时政",  # 人民日报
    "MTI0MDU3NDYwMQ==": "媒体与时政",  # 央视新闻
    "MzA4NDI3NjcyNA==": "媒体与时政",  # 新华社
    "MjM5NzI3NDg4MA==": "媒体与时政",  # 人民网
    "MzA4MDA0MzcwMA==": "媒体与时政",  # 中国政府网
    "MjM5ODA4OTIyMA==": "媒体与时政",  # 中国新闻网
    "MjM5NzM0MzQ4MQ==": "媒体与时政",  # 光明日报
    "MzAxNzE1OTA1MA==": "媒体与时政",  # 中国日报
    "MjM5NjY3NjEyMA==": "媒体与时政",  # 中国青年报
    "MjM5NzQ5MTkyMA==": "财经",  # 央视财经
}


def repair_featured_categories(conn):
    conn.execute(
        """INSERT INTO categories(name,slug,sort_order)
        SELECT '媒体与时政','媒体与时政',coalesce(max(sort_order),-1)+1
        FROM categories WHERE parent_id IS NULL ON CONFLICT(slug) DO NOTHING"""
    )
    changed = []
    for source_id, slug in FEATURED_CATEGORIES.items():
        row = conn.execute(
            """UPDATE official_accounts a SET primary_category_id=c.id,updated_at=now()
            FROM categories c WHERE c.slug=%s AND c.status='active'
            AND a.platform='wechat' AND a.source_id=%s AND a.status='approved'
            AND a.primary_category_id IS NULL AND a.source_id IN
              (SELECT jsonb_array_elements_text(value) FROM settings WHERE key='homepage_accounts')
            RETURNING a.id,a.name,c.name AS category""",
            (slug, source_id),
        ).fetchone()
        if row:
            index_account(conn, row["id"])
            changed.append(row)
    return changed


if __name__ == "__main__":
    with db() as conn:
        changed = repair_featured_categories(conn)
    print(json.dumps(changed, ensure_ascii=False))
