import base64
import binascii
import json
from urllib.parse import urlencode

from psycopg.types.json import Jsonb


def enqueue(conn, kind, payload, key=None):
    if kind == "sync" and not payload.get("cache_only"):
        key = "weread-sync:" + str(payload["target_id"])
    key = key or kind + ":" + json.dumps(payload, sort_keys=True, ensure_ascii=False)
    row = conn.execute(
        "INSERT INTO jobs(kind,payload,dedupe_key) VALUES (%s,%s,%s) ON CONFLICT(dedupe_key) WHERE status IN ('queued','running') DO NOTHING RETURNING id",
        (kind, Jsonb(payload), key),
    ).fetchone()
    return row["id"] if row else None


def index_account(conn, account_id):
    conn.execute(
        """INSERT INTO search_documents(kind,target_id,body,document)
      SELECT 'account',a.id, concat_ws(' ',a.name,a.wechat_id,a.description,c.name,
        (SELECT string_agg(t.name,' ') FROM official_account_tags at JOIN tags t ON t.id=at.tag_id WHERE at.account_id=a.id),
        (SELECT data::text FROM ai_account_profiles WHERE account_id=a.id)), NULL
      FROM official_accounts a LEFT JOIN categories c ON c.id=a.primary_category_id WHERE a.id=%s
      ON CONFLICT(kind,target_id) DO UPDATE SET body=EXCLUDED.body""",
        (account_id,),
    )
    conn.execute(
        "UPDATE search_documents SET document=to_tsvector('simple',body) WHERE kind='account' AND target_id=%s",
        (account_id,),
    )


def index_article(conn, article_id):
    conn.execute(
        """INSERT INTO search_documents(kind,target_id,body,document)
      SELECT 'article',id,concat_ws(' ',title,author,summary,content_text),to_tsvector('simple',concat_ws(' ',title,author,summary,content_text))
      FROM articles WHERE id=%s ON CONFLICT(kind,target_id) DO UPDATE SET body=EXCLUDED.body,document=EXCLUDED.document""",
        (article_id,),
    )


def set_tags(conn, account_id, tags):
    conn.execute("DELETE FROM official_account_tags WHERE account_id=%s", (account_id,))
    for name in dict.fromkeys(tags):
        tag_id = conn.execute(
            "INSERT INTO tags(name) VALUES (%s) ON CONFLICT(name) DO UPDATE SET name=EXCLUDED.name RETURNING id",
            (name.strip(),),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO official_account_tags(account_id,tag_id) VALUES (%s,%s)",
            (account_id, tag_id),
        )


ACCOUNT_SELECT = """SELECT a.*, c.name AS category, s.article_count,s.articles_last_7d,s.articles_last_30d,
 s.readable_count,s.active_score,p.data AS profile,p.model_name,p.prompt_version,p.source_article_count,p.generated_at,
 coalesce((SELECT json_agg(t.name ORDER BY t.name) FROM official_account_tags at JOIN tags t ON t.id=at.tag_id WHERE at.account_id=a.id),'[]') AS tags,
 (SELECT ar.source_url FROM articles ar WHERE ar.account_id=a.id AND ar.status<>'hidden' AND ar.source_url<>''
  ORDER BY ar.publish_time DESC NULLS LAST,ar.id DESC LIMIT 1) AS external_article_url,
 (SELECT count(*) FROM user_following f WHERE f.account_id=a.id)::int AS following_count,
 (SELECT count(*) FROM user_following f WHERE f.account_id=a.id AND f.created_at>now()-interval '7 days')::int AS growth,
 (SELECT count(*) FROM collections f WHERE f.account_id=a.id)::int AS collection_count
 FROM official_accounts a LEFT JOIN categories c ON c.id=a.primary_category_id
 JOIN account_stats s ON s.account_id=a.id LEFT JOIN ai_account_profiles p ON p.account_id=a.id"""


def wechat_profile_url(source_id):
    try:
        identity = base64.b64decode(source_id, validate=True).decode('ascii')
    except (binascii.Error, UnicodeError, ValueError):
        return ''
    if not identity.isascii() or not identity.isdigit():
        return ''
    return 'https://mp.weixin.qq.com/mp/profile_ext?' + urlencode(
        {'action': 'home', '__biz': source_id}
    ) + '#wechat_redirect'


def rank_account(row, weights):
    if row.get('platform') == 'wechat' and not row.get('source_url'):
        row['source_url'] = wechat_profile_url(row['source_id'])
    profile = row.get('profile') or {}
    from .scoring import VERSION
    overall = profile.get('overall_score') if profile.get('scoring_version') == VERSION else None
    quality = overall if overall is not None else 0
    completeness = (
        sum(
            bool(row.get(k)) for k in ("name", "wechat_id", "avatar_url", "description", "category")
        )
        * 20
    )
    factors = {
        "quality": round(quality, 1),
        "activity": float(row["active_score"]),
        "completeness": completeness,
        "following": min(100, row["following_count"] * 5),
    }
    row["rank_score"] = round(sum(factors[key] * weights[key] for key in factors), 1)
    row["rank_factors"] = factors
    row["quality_score"] = round(quality, 1) if overall is not None else None
    row["recommendation_reason"] = (row.get("profile") or {}).get("recommendation_reason") or (
        "已收录公众号资料，可前往微信查看内容。" if not row.get('article_collection_enabled', True)
        else "已收录于" + row["category"] + "目录，可先浏览账号和近期文章。" if row.get("category")
        else "已收录公众号资料，可先浏览账号和近期文章。"
    )
    return row
