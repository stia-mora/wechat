from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .admin import router as admin_router
from .auth import current_user
from .auth import router as auth_router
from .db import db, initialize
from .repository import ACCOUNT_SELECT, rank_account


@asynccontextmanager
async def lifespan(app):
    initialize()
    yield


app = FastAPI(title="WeChat Source", lifespan=lifespan)
app.include_router(auth_router)


@app.middleware("http")
async def same_origin(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin:
        host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        if urlparse(origin).netloc != host:
            return JSONResponse({"detail": "不允许跨站写入"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


def ranked(conn, rows):
    weights = conn.execute("SELECT value FROM settings WHERE key='ranking'").fetchone()["value"]
    return [rank_account(row, weights) for row in rows]


@app.get("/api/health")
def health():
    with db() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "database": "postgresql"}


@app.get("/api/stats")
def stats():
    with db() as conn:
        return conn.execute("""SELECT (SELECT count(*) FROM official_accounts WHERE status='approved') AS accounts,
          (SELECT count(*) FROM articles ar JOIN official_accounts a ON a.id=ar.account_id WHERE a.status='approved' AND ar.status<>'hidden') AS articles,
          (SELECT count(*) FROM articles ar JOIN official_accounts a ON a.id=ar.account_id WHERE a.status='approved' AND ar.status='ready') AS readable,
          (SELECT max(last_crawled_at) FROM official_accounts WHERE status='approved') AS last_crawled_at""").fetchone()


@app.get("/api/categories")
def categories():
    with db() as conn:
        return conn.execute("""SELECT c.*, (SELECT count(*) FROM official_accounts a WHERE a.status='approved' AND
          (a.primary_category_id=c.id OR a.id IN(SELECT account_id FROM official_account_categories WHERE category_id=c.id))) AS account_count
          FROM categories c WHERE c.status='active' ORDER BY c.parent_id NULLS FIRST,c.sort_order""").fetchall()


@app.get("/api/accounts")
def accounts(
    q: str = Query("", max_length=200),
    category: int | None = None,
    tag: str = "",
    account_type: str = "",
    frequency: str = "",
    sort: str = "recommended",
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    where, args = ["a.status='approved'"], []
    if q:
        where.append("""(a.id IN (SELECT target_id FROM search_documents WHERE kind='account' AND
          (body ILIKE %s OR document @@ plainto_tsquery('simple',%s) OR body %% %s)) OR
          a.id IN (SELECT ar.account_id FROM search_documents d JOIN articles ar ON ar.id=d.target_id WHERE d.kind='article' AND ar.status<>'hidden' AND d.body ILIKE %s))""")
        args.extend(["%" + q + "%", q, q, "%" + q + "%"])
    if category:
        where.append(
            "(a.primary_category_id=%s OR a.id IN(SELECT account_id FROM official_account_categories WHERE category_id=%s))"
        )
        args.extend([category, category])
    if tag:
        where.append(
            "a.id IN(SELECT at.account_id FROM official_account_tags at JOIN tags t ON t.id=at.tag_id WHERE t.name=%s)"
        )
        args.append(tag)
    if account_type:
        where.append("a.account_type=%s")
        args.append(account_type)
    if frequency in ("high", "medium", "low"):
        where.append(
            {
                "high": "s.articles_last_30d>=20",
                "medium": "s.articles_last_30d BETWEEN 5 AND 19",
                "low": "s.articles_last_30d<5",
            }[frequency]
        )
    filtered = ACCOUNT_SELECT + " WHERE " + " AND ".join(where)
    order = {
        "recommended": "score DESC",
        "quality": "quality DESC",
        "active": "articles_last_30d DESC",
        "growth": "growth DESC",
        "popular": "following_count+collection_count DESC",
        "latest": "last_article_at DESC NULLS LAST",
        "relevance": "name_match DESC,score DESC",
    }.get(sort, "score DESC")
    # Rank and paginate in PostgreSQL, so a growing catalog never loads in full per request.
    query = (
        """WITH candidates AS ("""
        + filtered
        + """), factors AS (
      SELECT candidates.*,
      coalesce((SELECT avg(value::numeric)*20 FROM jsonb_each_text(coalesce(profile->'quality_scores','{}'::jsonb))),0) AS quality,
      ((name<>'')::int+(wechat_id<>'')::int+(avatar_url<>'')::int+(description<>'')::int+(category IS NOT NULL)::int)*20 AS completeness,
      name ILIKE %s AS name_match FROM candidates
    ), scored AS (SELECT factors.*,
      quality*(w.value->>'quality')::numeric+active_score*(w.value->>'activity')::numeric+
      completeness*(w.value->>'completeness')::numeric+least(100,following_count*5)*(w.value->>'following')::numeric AS score
      FROM factors CROSS JOIN settings w WHERE w.key='ranking')
      SELECT * FROM scored ORDER BY """
        + order
        + ",id ASC LIMIT %s OFFSET %s"
    )
    with db() as conn:
        total = conn.execute(
            "SELECT count(*) AS n FROM (" + filtered + ") counted", args
        ).fetchone()["n"]
        rows = ranked(
            conn, conn.execute(query, args + ["%" + q + "%", limit, (page - 1) * limit]).fetchall()
        )
    return {"items": rows, "total": total, "page": page, "limit": limit}


def remember(conn, user, kind, target_id):
    if user:
        conn.execute(
            "INSERT INTO browsing_history(user_id,kind,target_id) VALUES (%s,%s,%s) ON CONFLICT(user_id,kind,target_id) DO UPDATE SET visited_at=now()",
            (user["id"], kind, target_id),
        )


@app.get("/api/accounts/{account_id}")
def account(account_id: int, request: Request):
    user = current_user(request, False)
    with db() as conn:
        row = conn.execute(
            ACCOUNT_SELECT + " WHERE a.id=%s AND a.status='approved'", (account_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "公众号未收录或已隐藏")
        row = ranked(conn, [row])[0]
        remember(conn, user, "account", account_id)
        row["following"] = bool(
            user
            and conn.execute(
                "SELECT 1 FROM user_following WHERE user_id=%s AND account_id=%s",
                (user["id"], account_id),
            ).fetchone()
        )
        row["collected"] = bool(
            user
            and conn.execute(
                "SELECT 1 FROM collections WHERE user_id=%s AND account_id=%s",
                (user["id"], account_id),
            ).fetchone()
        )
        row["subcategories"] = conn.execute(
            "SELECT c.* FROM official_account_categories ac JOIN categories c ON c.id=ac.category_id WHERE ac.account_id=%s",
            (account_id,),
        ).fetchall()
        others = ranked(
            conn,
            conn.execute(
                ACCOUNT_SELECT
                + " WHERE a.status='approved' AND a.id<>%s AND a.primary_category_id=%s",
                (account_id, row["primary_category_id"]),
            ).fetchall(),
        )
        for other in others:
            # A category copied into tags must not count twice as topic evidence.
            category_labels = {row["category"], other["category"]}
            row_tags = set(row["tags"]) - category_labels
            other_tags = set(other["tags"]) - category_labels
            shared = other_tags & row_tags
            union = other_tags | row_tags
            other["similarity"] = round((0.4 + 0.6 * len(shared) / max(1, len(union))) * 100)
            other["similarity_reason"] = (
                "共同分类："
                + (row["category"] or "未分类")
                + ("；共同标签：" + "、".join(sorted(shared)) if shared else "；暂无共同标签")
            )
            other["difference"] = "对方标签：" + (
                "、".join(sorted(set(other["tags"]) - set(row["tags"]))) or "暂未发现明显差异"
            )
        row["similar"] = sorted(others, key=lambda r: r["similarity"], reverse=True)[:4]
    return row


@app.get("/api/articles")
def articles(
    q: str = Query("", max_length=200),
    account_id: int | None = None,
    category: int | None = None,
    sort: str = "latest",
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    clauses, args = ["a.status='approved'", "ar.status<>'hidden'"], []
    if q:
        clauses.append(
            "ar.id IN(SELECT target_id FROM search_documents WHERE kind='article' AND (body ILIKE %s OR document @@ plainto_tsquery('simple',%s)))"
        )
        args.extend(["%" + q + "%", q])
    if account_id:
        clauses.append("ar.account_id=%s")
        args.append(account_id)
    if category:
        clauses.append("a.primary_category_id=%s")
        args.append(category)
    base = (
        " FROM articles ar JOIN official_accounts a ON a.id=ar.account_id LEFT JOIN ai_article_summaries ai ON ai.article_id=ar.id WHERE "
        + " AND ".join(clauses)
    )
    order = {
        "latest": "ar.publish_time DESC NULLS LAST,ar.id DESC",
        "popular": "collection_count DESC,ar.publish_time DESC NULLS LAST",
        "recommended": "coalesce((ai.data->>'quality_score')::numeric,0) DESC,ar.publish_time DESC NULLS LAST",
    }.get(sort, "ar.publish_time DESC NULLS LAST,ar.id DESC")
    with db() as conn:
        total = conn.execute("SELECT count(*) AS n" + base, args).fetchone()["n"]
        rows = conn.execute(
            "SELECT ar.id,ar.account_id,ar.title,ar.author,ar.source_url,ar.cover_url,ar.publish_time,ar.summary,ar.status,ar.word_count,a.name AS account_name,ai.data AS ai_summary,(SELECT count(*) FROM collections c WHERE c.article_id=ar.id) AS collection_count"
            + base
            + " ORDER BY "
            + order
            + " LIMIT %s OFFSET %s",
            args + [limit, (page - 1) * limit],
        ).fetchall()
    return {"items": rows, "total": total, "page": page, "limit": limit}


@app.get("/api/articles/{article_id}")
def article(article_id: int, request: Request):
    user = current_user(request, False)
    with db() as conn:
        row = conn.execute(
            "SELECT ar.*,a.name AS account_name,a.primary_category_id,c.name AS category,ai.data AS ai_summary,ai.model_name,ai.prompt_version,ai.generated_at FROM articles ar JOIN official_accounts a ON a.id=ar.account_id LEFT JOIN categories c ON c.id=a.primary_category_id LEFT JOIN ai_article_summaries ai ON ai.article_id=ar.id WHERE ar.id=%s AND a.status='approved' AND ar.status<>'hidden'",
            (article_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "文章不存在或已隐藏")
        remember(conn, user, "article", article_id)
        row["collected"] = bool(
            user
            and conn.execute(
                "SELECT 1 FROM collections WHERE user_id=%s AND article_id=%s",
                (user["id"], article_id),
            ).fetchone()
        )
        row["related"] = conn.execute(
            "SELECT ar.id,ar.title,a.name AS account_name FROM articles ar JOIN official_accounts a ON a.id=ar.account_id WHERE ar.id<>%s AND a.primary_category_id=%s AND a.status='approved' AND ar.status<>'hidden' ORDER BY (ar.account_id=%s) DESC,ar.publish_time DESC NULLS LAST LIMIT 5",
            (article_id, row["primary_category_id"], row["account_id"]),
        ).fetchall()
    return row


class Action(BaseModel):
    kind: str
    target_id: int
    enabled: bool


@app.put("/api/me/actions")
def user_action(data: Action, request: Request):
    user = current_user(request)
    if data.kind not in ("follow", "account", "article"):
        raise HTTPException(422, "未知操作")
    table = "user_following" if data.kind == "follow" else "collections"
    column = "article_id" if data.kind == "article" else "account_id"
    with db() as conn:
        if column == "article_id":
            exists = conn.execute(
                "SELECT 1 FROM articles ar JOIN official_accounts a ON a.id=ar.account_id WHERE ar.id=%s AND ar.status<>'hidden' AND a.status='approved'",
                (data.target_id,),
            ).fetchone()
        else:
            exists = conn.execute(
                "SELECT 1 FROM official_accounts WHERE id=%s AND status='approved'",
                (data.target_id,),
            ).fetchone()
        if not exists:
            raise HTTPException(404, "内容不存在")
        if data.enabled:
            conn.execute(
                f"INSERT INTO {table}(user_id,{column}) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                (user["id"], data.target_id),
            )
        else:
            conn.execute(
                f"DELETE FROM {table} WHERE user_id=%s AND {column}=%s",
                (user["id"], data.target_id),
            )
    return {"ok": True}


@app.get("/api/me/library")
def library(request: Request, view: str = "following"):
    user = current_user(request)
    with db() as conn:
        if view == "history":
            return {
                "history": conn.execute(
                    """SELECT h.*,CASE WHEN h.kind='account' THEN a.name ELSE ar.title END AS title FROM browsing_history h
              LEFT JOIN official_accounts a ON h.kind='account' AND a.id=h.target_id
              LEFT JOIN articles ar ON h.kind='article' AND ar.id=h.target_id
              LEFT JOIN official_accounts owner ON owner.id=ar.account_id
              WHERE h.user_id=%s AND ((h.kind='account' AND a.status='approved') OR (h.kind='article' AND ar.status<>'hidden' AND owner.status='approved')) ORDER BY visited_at DESC LIMIT 100""",
                    (user["id"],),
                ).fetchall()
            }
        relation = "user_following" if view == "following" else "collections"
        rows = ranked(
            conn,
            conn.execute(
                ACCOUNT_SELECT
                + f" WHERE a.status='approved' AND a.id IN(SELECT account_id FROM {relation} WHERE user_id=%s)",
                (user["id"],),
            ).fetchall(),
        )
        saved = (
            conn.execute(
                "SELECT ar.id,ar.title,a.name AS account_name,ar.publish_time,ar.status,ar.summary FROM collections c JOIN articles ar ON ar.id=c.article_id JOIN official_accounts a ON a.id=ar.account_id WHERE c.user_id=%s AND ar.status<>'hidden' AND a.status='approved' ORDER BY c.created_at DESC",
                (user["id"],),
            ).fetchall()
            if view != "following"
            else []
        )
    return {"accounts": rows, "articles": saved}


app.include_router(admin_router)
