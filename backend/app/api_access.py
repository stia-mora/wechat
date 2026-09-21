import base64
import hashlib
import json
import secrets
from binascii import Error as BinasciiError
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .auth import current_user
from .db import db

router = APIRouter()
DEFAULT_SUBSCRIPTION_LIMIT = 3


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
        """SELECT id,name,key_prefix,created_at,last_used_at,revoked_at FROM api_keys
        WHERE user_id=%s ORDER BY created_at DESC,id DESC""",
        (user_id,),
    ).fetchall()
    return {
        "subscription_limit": limit,
        "subscriptions_used": len(subscriptions),
        "subscriptions_remaining": max(0, limit - len(subscriptions)),
        "subscriptions": subscriptions,
        "keys": keys,
    }


class KeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


@router.get("/api/me/api")
def my_api_access(request: Request):
    user = current_user(request)
    with db() as conn:
        return api_snapshot(conn, user["id"])


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
    key = "ws_live_" + secrets.token_urlsafe(32)
    with db() as conn:
        row = conn.execute(
            """INSERT INTO api_keys(user_id,name,key_prefix,token_hash) VALUES (%s,%s,%s,%s)
            RETURNING id,name,key_prefix,created_at,last_used_at,revoked_at""",
            (
                user["id"],
                name,
                key[:16],
                hashlib.sha256(key.encode()).hexdigest(),
            ),
        ).fetchone()
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


def api_principal(request: Request):
    scheme, _, key = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not key:
        raise HTTPException(401, "API Key 无效")
    with db() as conn:
        row = conn.execute(
            """SELECT id,user_id FROM api_keys WHERE token_hash=%s AND revoked_at IS NULL""",
            (hashlib.sha256(key.encode()).hexdigest(),),
        ).fetchone()
        if not row:
            raise HTTPException(401, "API Key 无效")
        conn.execute("UPDATE api_keys SET last_used_at=now() WHERE id=%s", (row["id"],))
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
    principal = api_principal(request)
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
    principal = api_principal(request)
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
    principal = api_principal(request)
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


@router.get("/api/v1/openapi.json")
def agent_openapi(request: Request):
    api_principal(request)
    return {
        "openapi": "3.1.0",
        "info": {"title": "WeChat Source Agent API", "version": "v1"},
        "servers": [{"url": "/wechat", "description": "Public path"}],
        "components": {
            "securitySchemes": {
                "BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "API Key"}
            }
        },
        "paths": {
            "/api/v1/subscriptions": {
                "get": {
                    "summary": "List API subscriptions and quota",
                    "security": [{"BearerAuth": []}],
                    "responses": {"200": {"description": "Subscription list"}},
                }
            },
            "/api/v1/feed": {
                "get": {
                    "summary": "Read subscribed ready articles",
                    "security": [{"BearerAuth": []}],
                    "parameters": [
                        {"name": "cursor", "in": "query", "schema": {"type": "string"}},
                        {"name": "limit", "in": "query", "schema": {"type": "integer", "maximum": 100}},
                        {
                            "name": "updated_since",
                            "in": "query",
                            "schema": {"type": "string", "format": "date-time"},
                        },
                    ],
                    "responses": {"200": {"description": "Stable cursor page"}},
                }
            },
            "/api/v1/articles/{id}": {
                "get": {
                    "summary": "Read one subscribed article as plain text",
                    "security": [{"BearerAuth": []}],
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}
                    ],
                    "responses": {"200": {"description": "Article detail"}, "404": {"description": "Not available"}},
                }
            },
        },
    }
