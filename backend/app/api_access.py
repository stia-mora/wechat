import base64
import hashlib
import json
import secrets
from binascii import Error as BinasciiError
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .auth import current_user
from .db import db

router = APIRouter()
DEFAULT_SUBSCRIPTION_LIMIT = 3


def plan_for_user(conn, user_id: int):
    return conn.execute(
        """SELECT p.code,p.name,p.description FROM api_plans p WHERE p.code=coalesce(
        (SELECT plan_code FROM user_api_access WHERE user_id=%s),'basic')""",
        (user_id,),
    ).fetchone()


def capabilities_for_user(conn, user_id: int):
    return conn.execute(
        """SELECT c.code,c.name,c.layer,o.capability IS NOT NULL AS customized,
        CASE WHEN o.capability IS NOT NULL THEN o.enabled ELSE pc.capability IS NOT NULL END AS enabled,
        coalesce(o.requests_per_minute,pc.requests_per_minute,c.default_requests_per_minute) AS requests_per_minute,
        coalesce(o.requests_per_day,pc.requests_per_day,c.default_requests_per_day) AS requests_per_day
        FROM api_capabilities c
        LEFT JOIN api_plan_capabilities pc ON pc.capability=c.code AND pc.plan_code=coalesce(
          (SELECT plan_code FROM user_api_access WHERE user_id=%s),'basic')
        LEFT JOIN user_api_capabilities o ON o.user_id=%s AND o.capability=c.code
        WHERE c.active ORDER BY c.layer,c.code""",
        (user_id, user_id),
    ).fetchall()


def capability_for_user(conn, user_id: int, capability: str):
    return conn.execute(
        """SELECT c.code,c.name,o.capability IS NOT NULL AS customized,
        CASE WHEN o.capability IS NOT NULL THEN o.enabled ELSE pc.capability IS NOT NULL END AS enabled,
        coalesce(o.requests_per_minute,pc.requests_per_minute,c.default_requests_per_minute) AS requests_per_minute,
        coalesce(o.requests_per_day,pc.requests_per_day,c.default_requests_per_day) AS requests_per_day
        FROM api_capabilities c
        LEFT JOIN api_plan_capabilities pc ON pc.capability=c.code AND pc.plan_code=coalesce(
          (SELECT plan_code FROM user_api_access WHERE user_id=%s),'basic')
        LEFT JOIN user_api_capabilities o ON o.user_id=%s AND o.capability=c.code
        WHERE c.code=%s AND c.active""",
        (user_id, user_id, capability),
    ).fetchone()


def usage_snapshot(conn, user_id: int):
    plan = plan_for_user(conn, user_id)
    timing = conn.execute("SELECT date_trunc('day',now()) AS day_start").fetchone()
    usage = {
        row["capability"]: row["calls"]
        for row in conn.execute(
            """SELECT capability,calls FROM api_usage_counters
            WHERE user_id=%s AND period='day' AND period_start=%s""",
            (user_id, timing["day_start"]),
        ).fetchall()
    }
    capabilities = capabilities_for_user(conn, user_id)
    for row in capabilities:
        row["calls_today"] = usage.get(row["code"], 0)
        row["remaining_today"] = max(0, row["requests_per_day"] - row["calls_today"])
    return {"plan": plan, "capabilities": capabilities}


def subscription_limit(conn, user_id: int) -> int:
    row = conn.execute(
        "SELECT subscription_limit FROM user_api_access WHERE user_id=%s", (user_id,)
    ).fetchone()
    return row["subscription_limit"] if row else DEFAULT_SUBSCRIPTION_LIMIT


def api_snapshot(conn, user_id: int):
    limit = subscription_limit(conn, user_id)
    subscriptions = conn.execute(
        """SELECT a.id,a.name,a.wechat_id,a.avatar_url,a.description,a.status,s.created_at
        FROM api_subscriptions s JOIN official_accounts a ON a.id=s.account_id
        WHERE s.user_id=%s ORDER BY a.status='approved' DESC,a.name,a.id""",
        (user_id,),
    ).fetchall()
    keys = conn.execute(
        """SELECT id,name,key_prefix,scope_mode,created_at,last_used_at,revoked_at FROM api_keys
        WHERE user_id=%s ORDER BY created_at DESC,id DESC""",
        (user_id,),
    ).fetchall()
    if keys:
        scopes = conn.execute(
            "SELECT api_key_id,capability FROM api_key_capabilities WHERE api_key_id=ANY(%s) ORDER BY capability",
            ([key["id"] for key in keys],),
        ).fetchall()
        for key in keys:
            key["capabilities"] = [
                scope["capability"] for scope in scopes if scope["api_key_id"] == key["id"]
            ]
    return {
        "subscription_limit": limit,
        "subscriptions_used": len(subscriptions),
        "subscriptions_remaining": max(0, limit - len(subscriptions)),
        "subscriptions": subscriptions,
        "keys": keys,
    }


class KeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    capabilities: list[str] | None = Field(default=None, max_length=30)


@router.get("/api/me/api")
def my_api_access(request: Request):
    user = current_user(request)
    with db() as conn:
        return {**api_snapshot(conn, user["id"]), **usage_snapshot(conn, user["id"])}


@router.get("/api/me/api/usage")
def my_api_usage(request: Request):
    user = current_user(request)
    with db() as conn:
        return usage_snapshot(conn, user["id"])


@router.get("/api/me/api/candidates")
def api_candidates(request: Request, q: str = Query("", max_length=100)):
    user = current_user(request)
    with db() as conn:
        return conn.execute(
            """SELECT a.id,a.name,a.wechat_id,a.avatar_url,a.description,
            EXISTS(SELECT 1 FROM user_following f WHERE f.user_id=%s AND f.account_id=a.id) AS following,
            EXISTS(SELECT 1 FROM api_subscriptions s WHERE s.user_id=%s AND s.account_id=a.id) AS subscribed
            FROM official_accounts a WHERE a.status='approved' AND
            (%s='' OR a.name ILIKE %s OR a.wechat_id ILIKE %s)
            ORDER BY following DESC,a.name,a.id LIMIT 100""",
            (user["id"], user["id"], q, "%" + q + "%", "%" + q + "%"),
        ).fetchall()


@router.post("/api/me/api/keys", status_code=201)
def create_key(data: KeyCreate, request: Request):
    user = current_user(request)
    name = data.name.strip()
    if not name:
        raise HTTPException(422, "Key 名称不能为空")
    scopes = sorted(set(data.capabilities or []))
    key = "ws_live_" + secrets.token_urlsafe(32)
    with db() as conn:
        if scopes:
            known = conn.execute(
                "SELECT code FROM api_capabilities WHERE code=ANY(%s) AND active", (scopes,)
            ).fetchall()
            if {row["code"] for row in known} != set(scopes):
                raise HTTPException(422, "包含未知 API 能力")
        row = conn.execute(
            """INSERT INTO api_keys(user_id,name,key_prefix,token_hash,scope_mode) VALUES (%s,%s,%s,%s,%s)
            RETURNING id,name,key_prefix,scope_mode,created_at,last_used_at,revoked_at""",
            (
                user["id"],
                name,
                key[:16],
                hashlib.sha256(key.encode()).hexdigest(),
                "restricted" if data.capabilities is not None else "inherit",
            ),
        ).fetchone()
        for capability in scopes:
            conn.execute(
                "INSERT INTO api_key_capabilities(api_key_id,capability) VALUES (%s,%s)",
                (row["id"], capability),
            )
    row["capabilities"] = scopes
    return {"key": key, "api_key": row}


@router.delete("/api/me/api/keys/{key_id}")
def revoke_key(key_id: int, request: Request):
    user = current_user(request)
    with db() as conn:
        row = conn.execute(
            """UPDATE api_keys SET revoked_at=now() WHERE id=%s AND user_id=%s AND revoked_at IS NULL
            RETURNING id""",
            (key_id, user["id"]),
        ).fetchone()
    if not row:
        raise HTTPException(404, "API Key 不存在或已撤销")
    return {"ok": True}


class KeyScopes(BaseModel):
    mode: str = Field(default="restricted", pattern="^(inherit|restricted)$")
    capabilities: list[str] = Field(default_factory=list, max_length=30)


@router.put("/api/me/api/keys/{key_id}/scopes")
def set_key_scopes(key_id: int, data: KeyScopes, request: Request):
    user = current_user(request)
    scopes = sorted(set(data.capabilities))
    with db() as conn:
        key = conn.execute(
            "SELECT id FROM api_keys WHERE id=%s AND user_id=%s AND revoked_at IS NULL",
            (key_id, user["id"]),
        ).fetchone()
        if not key:
            raise HTTPException(404, "API Key 不存在或已撤销")
        if data.mode == "restricted":
            known = conn.execute(
                "SELECT code FROM api_capabilities WHERE code=ANY(%s) AND active", (scopes,)
            ).fetchall()
            if {row["code"] for row in known} != set(scopes):
                raise HTTPException(422, "包含未知 API 能力")
        conn.execute("DELETE FROM api_key_capabilities WHERE api_key_id=%s", (key_id,))
        if data.mode == "restricted":
            for capability in scopes:
                conn.execute(
                    "INSERT INTO api_key_capabilities(api_key_id,capability) VALUES (%s,%s)",
                    (key_id, capability),
                )
        conn.execute("UPDATE api_keys SET scope_mode=%s WHERE id=%s", (data.mode, key_id))
    return {"scope_mode": data.mode, "capabilities": scopes if data.mode == "restricted" else []}


class SubscriptionCreate(BaseModel):
    account_id: int


@router.post("/api/me/api/subscriptions", status_code=201)
def add_subscription(data: SubscriptionCreate, request: Request):
    user = current_user(request)
    with db() as conn:
        # Serialize subscription changes for this user so several requests cannot consume one quota slot.
        conn.execute("SELECT id FROM users WHERE id=%s FOR UPDATE", (user["id"],))
        account = conn.execute(
            "SELECT id FROM official_accounts WHERE id=%s AND status='approved'", (data.account_id,)
        ).fetchone()
        if not account:
            raise HTTPException(404, "公众号未收录或未审核")
        exists = conn.execute(
            "SELECT 1 FROM api_subscriptions WHERE user_id=%s AND account_id=%s",
            (user["id"], data.account_id),
        ).fetchone()
        if exists:
            return {"ok": True, "already_subscribed": True}
        used = conn.execute(
            "SELECT count(*) AS count FROM api_subscriptions WHERE user_id=%s", (user["id"],)
        ).fetchone()["count"]
        if used >= subscription_limit(conn, user["id"]):
            raise HTTPException(409, "API 订阅额度已用完")
        conn.execute(
            "INSERT INTO api_subscriptions(user_id,account_id) VALUES (%s,%s)",
            (user["id"], data.account_id),
        )
    return {"ok": True}


@router.delete("/api/me/api/subscriptions/{account_id}")
def remove_subscription(account_id: int, request: Request):
    user = current_user(request)
    with db() as conn:
        row = conn.execute(
            "DELETE FROM api_subscriptions WHERE user_id=%s AND account_id=%s RETURNING account_id",
            (user["id"], account_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "API 订阅不存在")
    return {"ok": True}


def api_principal(request: Request, capability: str):
    scheme, _, key = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not key:
        raise HTTPException(401, "API Key 无效")
    with db() as conn:
        row = conn.execute(
            """SELECT id,user_id,scope_mode FROM api_keys WHERE token_hash=%s AND revoked_at IS NULL""",
            (hashlib.sha256(key.encode()).hexdigest(),),
        ).fetchone()
        if not row:
            raise HTTPException(401, "API Key 无效")
        conn.execute("SELECT id FROM users WHERE id=%s FOR UPDATE", (row["user_id"],))
        if row["scope_mode"] == "restricted" and not conn.execute(
            "SELECT 1 FROM api_key_capabilities WHERE api_key_id=%s AND capability=%s",
            (row["id"], capability),
        ).fetchone():
            raise HTTPException(403, "此 API Key 未获授权使用该能力")
        entitlement = capability_for_user(conn, row["user_id"], capability)
        if not entitlement or not entitlement["enabled"]:
            raise HTTPException(403, "当前套餐未开通该 API 能力")
        timing = conn.execute(
            "SELECT now() AS current_time,date_trunc('minute',now()) AS minute_start,date_trunc('day',now()) AS day_start"
        ).fetchone()
        counters = {}
        for period, start in (("minute", timing["minute_start"]), ("day", timing["day_start"])):
            counters[period] = conn.execute(
                """SELECT calls FROM api_usage_counters
                WHERE user_id=%s AND capability=%s AND period=%s AND period_start=%s""",
                (row["user_id"], capability, period, start),
            ).fetchone()
        minute_calls = counters["minute"]["calls"] if counters["minute"] else 0
        day_calls = counters["day"]["calls"] if counters["day"] else 0
        limits = {
            "minute": entitlement["requests_per_minute"],
            "day": entitlement["requests_per_day"],
        }
        calls = {"minute": minute_calls, "day": day_calls}
        for period in ("minute", "day"):
            if calls[period] >= limits[period]:
                reset = timing[period + "_start"] + (
                    timedelta(minutes=1) if period == "minute" else timedelta(days=1)
                )
                request.state.api_rate = {
                    "limit": limits["minute"],
                    "remaining": max(0, limits["minute"] - minute_calls),
                    "reset": reset,
                    "daily_limit": limits["day"],
                    "daily_remaining": max(0, limits["day"] - day_calls),
                }
                retry_after = max(1, int((reset - timing["current_time"]).total_seconds()))
                raise HTTPException(429, "API 调用额度已用完", headers={"Retry-After": str(retry_after)})
        for period, start in (("minute", timing["minute_start"]), ("day", timing["day_start"])):
            conn.execute(
                """INSERT INTO api_usage_counters(user_id,capability,period,period_start,calls)
                VALUES (%s,%s,%s,%s,1) ON CONFLICT(user_id,capability,period,period_start)
                DO UPDATE SET calls=api_usage_counters.calls+1""",
                (row["user_id"], capability, period, start),
            )
        conn.execute("UPDATE api_keys SET last_used_at=now() WHERE id=%s", (row["id"],))
        request.state.api_rate = {
            "limit": limits["minute"],
            "remaining": limits["minute"] - minute_calls - 1,
            "reset": timing["minute_start"] + timedelta(minutes=1),
            "daily_limit": limits["day"],
            "daily_remaining": limits["day"] - day_calls - 1,
        }
    return row


def encode_cursor(updated_at: datetime, article_id: int) -> str:
    raw = json.dumps([updated_at.isoformat(), article_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        timestamp, article_id = json.loads(raw)
        return datetime.fromisoformat(timestamp), int(article_id)
    except (BinasciiError, UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(422, "cursor 无效")


def public_account(row):
    return {"id": row["account_id"], "name": row["account_name"], "wechat_id": row["wechat_id"]}


@router.get("/api/v1/subscriptions")
def subscriptions(request: Request):
    principal = api_principal(request, "subscriptions.read")
    with db() as conn:
        snapshot = api_snapshot(conn, principal["user_id"])
    return {
        "subscription_limit": snapshot["subscription_limit"],
        "subscriptions_used": snapshot["subscriptions_used"],
        "subscriptions_remaining": snapshot["subscriptions_remaining"],
        "subscriptions": [
            {"id": row["id"], "name": row["name"], "wechat_id": row["wechat_id"]}
            for row in snapshot["subscriptions"]
            if row["status"] == "approved"
        ],
    }


@router.get("/api/v1/feed")
def feed(
    request: Request,
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    updated_since: datetime | None = None,
):
    principal = api_principal(request, "feed.read")
    clauses = [
        "s.user_id=%s",
        "a.status='approved'",
        "ar.status='ready'",
        "ar.content_text<>''",
    ]
    args: list[object] = [principal["user_id"]]
    if updated_since:
        clauses.append("ar.updated_at>%s")
        args.append(updated_since)
    if cursor:
        cursor_time, cursor_id = decode_cursor(cursor)
        clauses.append("(ar.updated_at<%s OR (ar.updated_at=%s AND ar.id<%s))")
        args.extend([cursor_time, cursor_time, cursor_id])
    with db() as conn:
        rows = conn.execute(
            """SELECT ar.id,ar.account_id,ar.title,ar.author,ar.source_url,ar.publish_time,ar.updated_at,
            ar.summary,ar.word_count,a.name AS account_name,a.wechat_id
            FROM api_subscriptions s JOIN official_accounts a ON a.id=s.account_id
            JOIN articles ar ON ar.account_id=a.id WHERE """
            + " AND ".join(clauses)
            + " ORDER BY ar.updated_at DESC,ar.id DESC LIMIT %s",
            args + [limit + 1],
        ).fetchall()
    has_more = len(rows) > limit
    items = rows[:limit]
    return {
        "items": [
            {
                "id": row["id"],
                "title": row["title"],
                "author": row["author"],
                "summary": row["summary"],
                "word_count": row["word_count"],
                "source_url": row["source_url"],
                "publish_time": row["publish_time"],
                "updated_at": row["updated_at"],
                "account": public_account(row),
                "article_path": f"/wechat/api/v1/articles/{row['id']}",
            }
            for row in items
        ],
        "next_cursor": encode_cursor(items[-1]["updated_at"], items[-1]["id"])
        if has_more and items
        else None,
    }


@router.get("/api/v1/articles/{article_id}")
def api_article(article_id: int, request: Request):
    principal = api_principal(request, "article.read")
    with db() as conn:
        row = conn.execute(
            """SELECT ar.id,ar.account_id,ar.title,ar.author,ar.source_url,ar.publish_time,ar.updated_at,
            ar.summary,ar.content_text,ar.word_count,a.name AS account_name,a.wechat_id,ai.data AS ai_summary
            FROM api_subscriptions s JOIN official_accounts a ON a.id=s.account_id
            JOIN articles ar ON ar.account_id=a.id LEFT JOIN ai_article_summaries ai ON ai.article_id=ar.id
            WHERE s.user_id=%s AND ar.id=%s AND a.status='approved' AND ar.status='ready' AND ar.content_text<>''""",
            (principal["user_id"], article_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "文章不存在")
    return {
        "id": row["id"],
        "title": row["title"],
        "author": row["author"],
        "summary": row["summary"],
        "ai_summary": row["ai_summary"],
        "content_text": row["content_text"],
        "word_count": row["word_count"],
        "source_url": row["source_url"],
        "publish_time": row["publish_time"],
        "updated_at": row["updated_at"],
        "account": public_account(row),
    }


def subscribed_account_profile(conn, user_id: int, account_id: int):
    return conn.execute(
        """SELECT a.id AS account_id,a.name AS account_name,a.wechat_id,a.description,a.account_type,
        coalesce((SELECT json_agg(t.name ORDER BY t.name) FROM official_account_tags account_tag
          JOIN tags t ON t.id=account_tag.tag_id WHERE account_tag.account_id=a.id),'[]'::json) AS tags,
        p.data AS profile,p.model_name,p.prompt_version,p.source_article_count,p.source_total_count,p.generated_at
        FROM api_subscriptions s JOIN official_accounts a ON a.id=s.account_id
        LEFT JOIN ai_account_profiles p ON p.account_id=a.id
        WHERE s.user_id=%s AND a.id=%s AND a.status='approved'""",
        (user_id, account_id),
    ).fetchone()


@router.get("/api/v1/accounts/{account_id}/insight")
def account_insight(account_id: int, request: Request):
    principal = api_principal(request, "account.insight")
    with db() as conn:
        row = subscribed_account_profile(conn, principal["user_id"], account_id)
    if not row:
        raise HTTPException(404, "公众号不存在")
    if not row["profile"]:
        raise HTTPException(404, "公众号 AI 画像尚未就绪")
    profile = {key: value for key, value in row["profile"].items() if key != "assessments"}
    return {
        "account": {
            **public_account(row),
            "description": row["description"],
            "account_type": row["account_type"],
            "tags": row["tags"],
        },
        "profile": profile,
        "analysis": {
            "model_name": row["model_name"],
            "prompt_version": row["prompt_version"],
            "source_article_count": row["source_article_count"],
            "source_total_count": row["source_total_count"],
            "generated_at": row["generated_at"],
        },
    }


@router.get("/api/v1/accounts/{account_id}/quality-evidence")
def account_quality_evidence(account_id: int, request: Request):
    principal = api_principal(request, "quality.evidence.read")
    with db() as conn:
        row = subscribed_account_profile(conn, principal["user_id"], account_id)
    if not row:
        raise HTTPException(404, "公众号不存在")
    if not row["profile"]:
        raise HTTPException(404, "公众号质量证据尚未就绪")
    profile = row["profile"]
    return {
        "account": public_account(row),
        "scoring_version": profile.get("scoring_version"),
        "overall_score": profile.get("overall_score"),
        "quality_scores": profile.get("quality_scores"),
        "assessments": profile.get("assessments", []),
        "sample_article_ids": profile.get("sample_article_ids", []),
        "sample_policy": profile.get("sample_policy"),
        "generated_at": row["generated_at"],
    }


@router.get("/api/v1/articles/{article_id}/insight")
def article_insight(article_id: int, request: Request):
    principal = api_principal(request, "article.insight")
    with db() as conn:
        row = conn.execute(
            """SELECT ar.id,ar.title,ar.publish_time,ar.updated_at,a.id AS account_id,
            a.name AS account_name,a.wechat_id,ai.data AS insight,ai.model_name,ai.prompt_version,ai.generated_at
            FROM api_subscriptions s JOIN official_accounts a ON a.id=s.account_id
            JOIN articles ar ON ar.account_id=a.id JOIN ai_article_summaries ai ON ai.article_id=ar.id
            WHERE s.user_id=%s AND ar.id=%s AND a.status='approved' AND ar.status='ready' AND ar.content_text<>''""",
            (principal["user_id"], article_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "文章 AI 洞察不存在")
    return {
        "id": row["id"],
        "title": row["title"],
        "publish_time": row["publish_time"],
        "updated_at": row["updated_at"],
        "account": public_account(row),
        "insight": row["insight"],
        "analysis": {
            "model_name": row["model_name"],
            "prompt_version": row["prompt_version"],
            "generated_at": row["generated_at"],
        },
    }


@router.get("/api/v1/tags")
def tags(request: Request, limit: int = Query(100, ge=1, le=200)):
    api_principal(request, "tags.read")
    with db() as conn:
        rows = conn.execute(
            """SELECT t.name,count(account_tag.account_id)::int AS account_count FROM tags t
            JOIN official_account_tags account_tag ON account_tag.tag_id=t.id
            JOIN official_accounts a ON a.id=account_tag.account_id AND a.status='approved'
            GROUP BY t.id,t.name ORDER BY account_count DESC,t.name LIMIT %s""",
            (limit,),
        ).fetchall()
    return {"items": rows}


@router.get("/api/v1/search")
def agent_search(
    request: Request,
    q: str = Query(..., min_length=2, max_length=100),
    kind: str = Query("articles"),
    mode: str = Query("keyword"),
    limit: int = Query(20, ge=1, le=50),
):
    if kind not in ("accounts", "articles") or mode not in ("keyword", "rerank"):
        raise HTTPException(422, "kind 仅支持 accounts/articles，mode 仅支持 keyword/rerank")
    principal = api_principal(request, "search." + mode)
    candidate_limit = min(limit * 5, 100) if mode == "rerank" else limit
    with db() as conn:
        if kind == "accounts":
            rows = conn.execute(
                """SELECT a.id AS account_id,a.name AS account_name,a.wechat_id,a.description,a.account_type,
                coalesce((SELECT json_agg(t.name ORDER BY t.name) FROM official_account_tags account_tag
                  JOIN tags t ON t.id=account_tag.tag_id WHERE account_tag.account_id=a.id),'[]'::json) AS tags,
                coalesce(ts_rank(d.document,plainto_tsquery('simple',%s)),0) AS relevance
                FROM api_subscriptions s JOIN official_accounts a ON a.id=s.account_id
                JOIN search_documents d ON d.kind='account' AND d.target_id=a.id
                WHERE s.user_id=%s AND a.status='approved' AND
                  (d.body ILIKE %s OR d.document @@ plainto_tsquery('simple',%s))
                ORDER BY relevance DESC,a.name,a.id LIMIT %s""",
                (q, principal["user_id"], "%" + q + "%", q, candidate_limit),
            ).fetchall()
            for row in rows:
                row["title"] = row["account_name"]
                row["summary"] = row["description"]
        else:
            rows = conn.execute(
                """SELECT ar.id,ar.title,ar.summary,ar.content_text,ar.publish_time,ar.updated_at,
                a.id AS account_id,a.name AS account_name,a.wechat_id,
                coalesce(ts_rank(d.document,plainto_tsquery('simple',%s)),0) AS relevance
                FROM api_subscriptions s JOIN official_accounts a ON a.id=s.account_id
                JOIN articles ar ON ar.account_id=a.id
                JOIN search_documents d ON d.kind='article' AND d.target_id=ar.id
                WHERE s.user_id=%s AND a.status='approved' AND ar.status='ready' AND ar.content_text<>'' AND
                  (d.body ILIKE %s OR d.document @@ plainto_tsquery('simple',%s))
                ORDER BY relevance DESC,ar.updated_at DESC,ar.id DESC LIMIT %s""",
                (q, principal["user_id"], "%" + q + "%", q, candidate_limit),
            ).fetchall()
    ranking = "database"
    if mode == "rerank":
        from .reranking import rerank

        try:
            rows, ranking = rerank(q, rows)
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            ranking = "database"
    items = []
    for row in rows[:limit]:
        if kind == "accounts":
            items.append(
                {
                    "account": public_account(row),
                    "description": row["description"],
                    "account_type": row["account_type"],
                    "tags": row["tags"],
                    "relevance_score": row.get("relevance_score", row["relevance"]),
                    "insight_path": f"/wechat/api/v1/accounts/{row['account_id']}/insight",
                }
            )
        else:
            items.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "summary": row["summary"],
                    "publish_time": row["publish_time"],
                    "updated_at": row["updated_at"],
                    "account": public_account(row),
                    "relevance_score": row.get("relevance_score", row["relevance"]),
                    "article_path": f"/wechat/api/v1/articles/{row['id']}",
                    "insight_path": f"/wechat/api/v1/articles/{row['id']}/insight",
                }
            )
    return {"items": items, "ranking": ranking}


@router.get("/api/v1/openapi.json")
def agent_openapi(request: Request):
    api_principal(request, "docs.read")
    shared_responses = {
        "401": {"description": "Missing, unknown, or revoked API key"},
        "403": {"description": "Key scope or plan capability is not enabled"},
        "429": {
            "description": "Per-user shared minute or daily allowance exhausted",
            "headers": {"Retry-After": {"schema": {"type": "integer"}}},
        },
    }

    def operation(summary: str, parameters=None, responses=None):
        return {
            "get": {
                "summary": summary,
                "security": [{"BearerAuth": []}],
                "parameters": parameters or [],
                "responses": {"200": {"description": "Success"}, **shared_responses, **(responses or {})},
            }
        }

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "WeChat Source Agent API",
            "version": "v1",
            "description": "All requests require a Bearer API Key. Limits are shared by every active key of one user.",
        },
        "servers": [{"url": "/wechat", "description": "Public path"}],
        "components": {
            "securitySchemes": {
                "BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "API Key"}
            },
            "headers": {
                "X-RateLimit-Limit": {"schema": {"type": "integer"}},
                "X-RateLimit-Remaining": {"schema": {"type": "integer"}},
                "X-RateLimit-Reset": {"schema": {"type": "integer"}},
                "X-Usage-Daily-Limit": {"schema": {"type": "integer"}},
                "X-Usage-Daily-Remaining": {"schema": {"type": "integer"}},
            }
        },
        "paths": {
            "/api/v1/subscriptions": operation("List API subscriptions and quota"),
            "/api/v1/feed": operation(
                "Read subscribed ready articles",
                [
                    {"name": "cursor", "in": "query", "schema": {"type": "string"}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "maximum": 100}},
                    {"name": "updated_since", "in": "query", "schema": {"type": "string", "format": "date-time"}},
                ],
            ),
            "/api/v1/articles/{article_id}": operation(
                "Read one subscribed article as plain text",
                [{"name": "article_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                {"404": {"description": "Article is unavailable or outside the subscription"}},
            ),
            "/api/v1/articles/{article_id}/insight": operation(
                "Read AI insight for one subscribed article",
                [{"name": "article_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                {"404": {"description": "Insight is unavailable or outside the subscription"}},
            ),
            "/api/v1/accounts/{account_id}/insight": operation(
                "Read AI profile for one subscribed account",
                [{"name": "account_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                {"404": {"description": "Profile is unavailable or outside the subscription"}},
            ),
            "/api/v1/accounts/{account_id}/quality-evidence": operation(
                "Read quality score evidence for one subscribed account",
                [{"name": "account_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                {"404": {"description": "Evidence is unavailable or outside the subscription"}},
            ),
            "/api/v1/tags": operation(
                "List approved-account tags and aggregate counts",
                [{"name": "limit", "in": "query", "schema": {"type": "integer", "maximum": 200}}],
            ),
            "/api/v1/search": operation(
                "Search subscribed accounts or articles by keyword or reranking",
                [
                    {"name": "q", "in": "query", "required": True, "schema": {"type": "string", "minLength": 2}},
                    {"name": "kind", "in": "query", "schema": {"type": "string", "enum": ["accounts", "articles"]}},
                    {"name": "mode", "in": "query", "schema": {"type": "string", "enum": ["keyword", "rerank"]}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "maximum": 50}},
                ],
            ),
        },
    }
