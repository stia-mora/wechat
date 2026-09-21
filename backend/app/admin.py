import os
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .auth import require_admin
from .content import article_key
from .db import db
from .repository import ACCOUNT_SELECT, enqueue, index_account, set_tags

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


@router.get("/overview")
def overview():
    with db() as conn:
        counts = conn.execute(
            "SELECT status,count(*) AS count FROM official_accounts GROUP BY status"
        ).fetchall()
        jobs = conn.execute("SELECT status,count(*) AS count FROM jobs GROUP BY status").fetchall()
        source_counts = conn.execute(
            "SELECT count(*) AS accounts,count(DISTINCT source_id) AS unique_accounts,max(last_crawled_at) AS last_crawled_at FROM official_accounts"
        ).fetchone()
        articles = conn.execute(
            "SELECT status,count(*) AS count FROM articles GROUP BY status"
        ).fetchall()
    try:
        response = httpx.get(
            os.environ["SOURCE_API_URL"] + "/api/admin/status", timeout=5, trust_env=False
        )
        response.raise_for_status()
        source = response.json()
    except (httpx.HTTPError, ValueError):
        source = {"loggedIn": False, "status": "采集服务不可连接"}
    return {
        "accounts": counts,
        "articles": articles,
        "jobs": jobs,
        "source": source,
        "source_counts": source_counts,
        "llm_configured": bool(os.getenv("LLM_API_KEY") and os.getenv("LLM_MODEL")),
    }


@router.get("/accounts")
def accounts(q: str = "", status: str = "", page: int = Query(1, ge=1)):
    where, args = ["TRUE"], []
    if q:
        where.append("a.name ILIKE %s")
        args.append("%" + q + "%")
    if status:
        where.append("a.status=%s")
        args.append(status)
    with db() as conn:
        rows = conn.execute(
            ACCOUNT_SELECT
            + " WHERE "
            + " AND ".join(where)
            + " ORDER BY a.id DESC LIMIT 100 OFFSET %s",
            args + [(page - 1) * 100],
        ).fetchall()
        if rows:
            links = conn.execute(
                "SELECT ac.account_id,c.* FROM official_account_categories ac JOIN categories c ON c.id=ac.category_id WHERE ac.account_id=ANY(%s)",
                ([r["id"] for r in rows],),
            ).fetchall()
            for row in rows:
                row["subcategories"] = [c for c in links if c["account_id"] == row["id"]]
    return rows


class AccountEdit(BaseModel):
    description: str = Field(max_length=4000)
    primary_category_id: int | None = None
    account_type: str = Field(default="", max_length=80)
    status: str = Field(pattern="^(pending|approved|hidden|error)$")
    tags: list[str] = Field(default_factory=list, max_length=30)
    category_ids: list[int] = Field(default_factory=list, max_length=20)


@router.patch("/accounts/{account_id}")
def edit_account(account_id: int, data: AccountEdit):
    with db() as conn:
        for cid in [data.primary_category_id, *data.category_ids]:
            if cid and not conn.execute("SELECT 1 FROM categories WHERE id=%s", (cid,)).fetchone():
                raise HTTPException(422, "分类不存在")
        row = conn.execute(
            "UPDATE official_accounts SET description=%s,primary_category_id=%s,account_type=%s,status=%s,updated_at=now() WHERE id=%s RETURNING id",
            (
                data.description,
                data.primary_category_id,
                data.account_type,
                data.status,
                account_id,
            ),
        ).fetchone()
        if not row:
            raise HTTPException(404)
        set_tags(conn, account_id, [t.strip()[:60] for t in data.tags if t.strip()])
        conn.execute("DELETE FROM official_account_categories WHERE account_id=%s", (account_id,))
        for cid in set(data.category_ids):
            conn.execute(
                "INSERT INTO official_account_categories VALUES (%s,%s)", (account_id, cid)
            )
        index_account(conn, account_id)
    return {"ok": True}


class Task(BaseModel):
    kind: str = Field(pattern="^(discover|sync|parse|account_ai|article_ai|embedding)$")
    query: str = Field(default="", max_length=200)
    category_id: int | None = None
    target_id: int | None = None
    pages: int = Field(default=1, ge=1, le=30)
    parse_limit: int = Field(default=3, ge=0, le=100)
    cache_only: bool = False
    backfill: bool = False


@router.post("/jobs")
def create_job(data: Task):
    if data.kind == "discover" and not data.query.strip():
        raise HTTPException(422, "请输入搜索关键词")
    if data.kind != "discover" and not data.target_id:
        raise HTTPException(422, "缺少目标 ID")
    payload = (
        {"query": data.query.strip(), "category_id": data.category_id}
        if data.kind == "discover"
        else {
            "target_id": data.target_id,
            "pages": data.pages,
            "parse_limit": data.parse_limit,
            "cache_only": data.cache_only,
            "backfill": data.backfill,
        }
    )
    with db() as conn:
        if (
            data.kind in ("sync", "account_ai")
            and not conn.execute(
                "SELECT 1 FROM official_accounts WHERE id=%s", (data.target_id,)
            ).fetchone()
        ):
            raise HTTPException(404, "公众号不存在")
        job_id = enqueue(conn, data.kind, payload)
    return {"id": job_id, "message": "任务已排队" if job_id else "相同任务已在队列中"}


@router.get("/jobs")
def jobs(status: str = "", page: int = Query(1, ge=1)):
    with db() as conn:
        return conn.execute(
            "SELECT * FROM jobs WHERE (%s='' OR status=%s) ORDER BY id DESC LIMIT 100 OFFSET %s",
            (status, status, (page - 1) * 100),
        ).fetchall()


@router.post("/jobs/{job_id}/retry")
def retry(job_id: int):
    with db() as conn:
        job = conn.execute(
            "SELECT * FROM jobs WHERE id=%s AND status IN ('failed','blocked')", (job_id,)
        ).fetchone()
        if not job:
            raise HTTPException(409, "只能重试失败或阻塞的任务")
        payload = dict(job["payload"])
        if job["kind"] == "sync":
            payload["_progress"] = job["result"] or payload.get("_progress")
        new_id = enqueue(conn, job["kind"], payload, job["dedupe_key"])
    return {"id": new_id}


@router.get("/accounts/{account_id}/source")
def source_state(account_id: int):
    with db() as conn:
        if not conn.execute(
            "SELECT 1 FROM official_accounts WHERE id=%s", (account_id,)
        ).fetchone():
            raise HTTPException(404, "公众号不存在")
        counts = conn.execute(
            "SELECT count(*) articles,count(*) FILTER(WHERE content_text<>'') bodies FROM articles WHERE account_id=%s",
            (account_id,),
        ).fetchone()
        subscription = conn.execute(
            "SELECT * FROM source_subscriptions WHERE account_id=%s AND source_id='weread'",
            (account_id,),
        ).fetchone()
        job = conn.execute(
            """SELECT * FROM jobs WHERE
            (kind='sync' AND (payload->>'target_id')::bigint=%s) OR
            (kind='parse' AND (payload->>'target_id')::bigint IN (SELECT id FROM articles WHERE account_id=%s))
            ORDER BY id DESC LIMIT 1""",
            (account_id, account_id),
        ).fetchone()
    return {**counts, "subscription": subscription, "job": job, "provider": "weread"}


class ArticleLinks(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=20)


@router.post("/accounts/{account_id}/links")
def add_article_links(account_id: int, data: ArticleLinks):
    try:
        links = {article_key(url.strip()): url.strip() for url in data.urls}
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    with db() as conn:
        account = conn.execute(
            "SELECT source_url FROM official_accounts WHERE id=%s", (account_id,)
        ).fetchone()
        if not account:
            raise HTTPException(404, "公众号不存在")
        known_biz = parse_qs(urlparse(account["source_url"]).query).get("__biz")
        jobs = []
        for key, url in links.items():
            link_biz = parse_qs(urlparse(url).query).get("__biz")
            if known_biz and link_biz and known_biz != link_biz:
                raise HTTPException(422, "文章链接的公众号标识与当前账号不一致")
            row = conn.execute(
                """INSERT INTO articles(account_id,source_key,title,source_url)
                VALUES (%s,%s,'待解析文章',%s) ON CONFLICT(source_key) DO NOTHING RETURNING id""",
                (account_id, key, url),
            ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT id,account_id FROM articles WHERE source_key=%s", (key,)
                ).fetchone()
                if row["account_id"] != account_id:
                    raise HTTPException(409, "文章已归属于其他公众号，请检查链接")
            job = enqueue(conn, "parse", {"target_id": row["id"]})
            if job:
                jobs.append(job)
    return {"ids": jobs, "message": f"已排队 {len(jobs)} 篇，正文保存后可导出；进度见采集任务页"}


@router.get("/accounts/{account_id}/export/{format}")
def export_account(account_id: int, format: str):
    from .exports import export_account as export_stored

    return export_stored(account_id, format)


class CategoryEdit(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    parent_id: int | None = None
    status: str = Field(default="active", pattern="^(active|hidden)$")


@router.post("/categories")
def add_category(data: CategoryEdit):
    with db() as conn:
        if (
            data.parent_id
            and not conn.execute(
                "SELECT 1 FROM categories WHERE id=%s AND parent_id IS NULL", (data.parent_id,)
            ).fetchone()
        ):
            raise HTTPException(422, "父分类必须为一级分类")
        return conn.execute(
            "INSERT INTO categories(name,slug,parent_id,status) VALUES (%s,%s,%s,%s) ON CONFLICT(slug) DO UPDATE SET name=EXCLUDED.name,status=EXCLUDED.status RETURNING *",
            (
                data.name,
                str(data.parent_id or "root") + "/" + data.name,
                data.parent_id,
                data.status,
            ),
        ).fetchone()


@router.get("/tags")
def tags():
    with db() as conn:
        return conn.execute(
            "SELECT t.*, (SELECT count(*) FROM official_account_tags WHERE tag_id=t.id) AS account_count FROM tags t ORDER BY name"
        ).fetchall()


class TagEdit(BaseModel):
    name: str = Field(min_length=1, max_length=60)


@router.patch("/tags/{tag_id}")
def edit_tag(tag_id: int, data: TagEdit):
    with db() as conn:
        if conn.execute(
            "SELECT id FROM tags WHERE name=%s AND id<>%s", (data.name, tag_id)
        ).fetchone():
            raise HTTPException(409, "标签名称已存在")
        conn.execute("UPDATE tags SET name=%s WHERE id=%s", (data.name, tag_id))
        for row in conn.execute(
            "SELECT account_id FROM official_account_tags WHERE tag_id=%s", (tag_id,)
        ).fetchall():
            index_account(conn, row["account_id"])
    return {"ok": True}


@router.get("/articles")
def articles(page: int = Query(1, ge=1)):
    with db() as conn:
        return conn.execute(
            "SELECT ar.id,ar.title,ar.account_id,ar.status,ar.word_count,ar.publish_time,a.name AS account_name FROM articles ar JOIN official_accounts a ON a.id=ar.account_id ORDER BY ar.id DESC LIMIT 100 OFFSET %s",
            ((page - 1) * 100,),
        ).fetchall()


class ArticleEdit(BaseModel):
    status: str = Field(pattern="^(metadata|ready|hidden|error)$")


@router.patch("/articles/{article_id}")
def edit_article(article_id: int, data: ArticleEdit):
    with db() as conn:
        row = conn.execute(
            "SELECT content_text FROM articles WHERE id=%s", (article_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404)
        if data.status == "ready" and not row["content_text"]:
            raise HTTPException(422, "文章没有正文，无法设为可读")
        conn.execute("UPDATE articles SET status=%s,updated_at=now() WHERE id=%s", (data.status, article_id))
    return {"ok": True}


@router.get("/ranking")
def ranking():
    with db() as conn:
        return conn.execute("SELECT value FROM settings WHERE key='ranking'").fetchone()["value"]


class Ranking(BaseModel):
    quality: float = Field(ge=0, le=1)
    activity: float = Field(ge=0, le=1)
    completeness: float = Field(ge=0, le=1)
    following: float = Field(ge=0, le=1)


@router.put("/ranking")
def save_ranking(data: Ranking):
    if abs(sum(data.model_dump().values()) - 1) > 0.001:
        raise HTTPException(422, "权重之和必须为 1")
    with db() as conn:
        conn.execute(
            "UPDATE settings SET value=%s WHERE key='ranking'", (Jsonb(data.model_dump()),)
        )
    return {"ok": True}


@router.put("/profiles/{account_id}")
def edit_profile(account_id: int, data: dict):
    from .ai import Profile

    try:
        validated = Profile.model_validate(data).model_dump()
    except ValueError:
        raise HTTPException(422, "画像结构或评分不合法")
    with db() as conn:
        from .scoring import finalize
        stored = conn.execute('SELECT data FROM ai_account_profiles WHERE account_id=%s',(account_id,)).fetchone()
        if not stored:
            raise HTTPException(404, '请先生成画像')
        samples = conn.execute("SELECT id,content_text FROM articles WHERE account_id=%s AND status='ready' AND id=ANY(%s)",
            (account_id,stored['data'].get('sample_article_ids',[]))).fetchall()
        try:
            validated = finalize(validated,samples)
        except ValueError:
            raise HTTPException(422,'证据必须来自已分析文章的原文')
        row = conn.execute(
            "UPDATE ai_account_profiles SET data=%s,reviewed=true WHERE account_id=%s RETURNING account_id",
            (Jsonb(validated), account_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "请先生成画像")
        index_account(conn, account_id)
    return {"ok": True}


class ApiAccessEdit(BaseModel):
    subscription_limit: int = Field(ge=0, le=10000)


@router.get("/api-users")
def api_users(q: str = Query("", max_length=100), page: int = Query(1, ge=1)):
    with db() as conn:
        return conn.execute(
            """SELECT u.id,u.email,u.display_name,u.created_at,
            coalesce(access.subscription_limit,3) AS subscription_limit,
            (SELECT count(*) FROM api_subscriptions s WHERE s.user_id=u.id) AS subscriptions_used,
            (SELECT count(*) FROM api_keys k WHERE k.user_id=u.id AND k.revoked_at IS NULL) AS key_count,
            (SELECT max(last_used_at) FROM api_keys k WHERE k.user_id=u.id) AS last_used_at
            FROM users u LEFT JOIN user_api_access access ON access.user_id=u.id
            WHERE (%s='' OR u.email ILIKE %s OR u.display_name ILIKE %s)
            ORDER BY u.id DESC LIMIT 100 OFFSET %s""",
            (q, "%" + q + "%", "%" + q + "%", (page - 1) * 100),
        ).fetchall()


@router.put("/api-users/{user_id}/access")
def edit_api_access(user_id: int, data: ApiAccessEdit):
    with db() as conn:
        user = conn.execute("SELECT id FROM users WHERE id=%s FOR UPDATE", (user_id,)).fetchone()
        if not user:
            raise HTTPException(404, "用户不存在")
        used = conn.execute(
            "SELECT count(*) AS count FROM api_subscriptions WHERE user_id=%s", (user_id,)
        ).fetchone()["count"]
        if data.subscription_limit < used:
            raise HTTPException(409, "订阅数高于新上限，请先移除该用户的 API 订阅")
        conn.execute(
            """INSERT INTO user_api_access(user_id,subscription_limit,updated_at) VALUES (%s,%s,now())
            ON CONFLICT(user_id) DO UPDATE SET subscription_limit=EXCLUDED.subscription_limit,updated_at=now()""",
            (user_id, data.subscription_limit),
        )
    return {"ok": True, "subscription_limit": data.subscription_limit}


@router.get("/api-users/{user_id}/subscriptions")
def user_api_subscriptions(user_id: int):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE id=%s", (user_id,)).fetchone():
            raise HTTPException(404, "用户不存在")
        return conn.execute(
            """SELECT a.id,a.name,a.wechat_id,a.status,s.created_at FROM api_subscriptions s
            JOIN official_accounts a ON a.id=s.account_id WHERE s.user_id=%s
            ORDER BY a.name,a.id""",
            (user_id,),
        ).fetchall()


@router.delete("/api-users/{user_id}/subscriptions/{account_id}")
def remove_user_api_subscription(user_id: int, account_id: int):
    with db() as conn:
        row = conn.execute(
            "DELETE FROM api_subscriptions WHERE user_id=%s AND account_id=%s RETURNING account_id",
            (user_id, account_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "API 订阅不存在")
    return {"ok": True}
