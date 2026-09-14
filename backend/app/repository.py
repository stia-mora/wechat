import json

from psycopg.types.json import Jsonb


def enqueue(conn, kind, payload, key=None):
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
 (SELECT count(*) FROM user_following f WHERE f.account_id=a.id)::int AS following_count,
 (SELECT count(*) FROM user_following f WHERE f.account_id=a.id AND f.created_at>now()-interval '7 days')::int AS growth,
 (SELECT count(*) FROM collections f WHERE f.account_id=a.id)::int AS collection_count
 FROM official_accounts a LEFT JOIN categories c ON c.id=a.primary_category_id
 JOIN account_stats s ON s.account_id=a.id LEFT JOIN ai_account_profiles p ON p.account_id=a.id"""


def rank_account(row, weights):
    scores = (row.get("profile") or {}).get("quality_scores", {})
    quality = sum(scores.values()) / len(scores) * 20 if scores else 0
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
    row["quality_score"] = round(quality, 1) if scores else None
    row["recommendation_reason"] = (row.get("profile") or {}).get("recommendation_reason") or (
        "已收录于" + (row.get("category") or "待分类") + "目录，可先浏览账号和近期文章。"
    )
    return row
