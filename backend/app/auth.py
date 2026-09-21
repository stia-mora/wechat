import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request, Response
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, Field

from .db import db

router = APIRouter(prefix="/api/auth")
attempts = defaultdict(deque)


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ":" + digest


def current_user(request: Request, required=True):
    token = request.cookies.get("ws_session", "")
    with db() as conn:
        row = (
            conn.execute(
                "SELECT u.id,u.email,u.display_name FROM sessions s JOIN users u ON s.user_id=u.id WHERE s.token_hash=%s AND s.expires_at>now()",
                (hashlib.sha256(token.encode()).hexdigest(),),
            ).fetchone()
            if token
            else None
        )
    if required and not row:
        raise HTTPException(401, "请先登录")
    return row


def require_admin(request: Request):
    expected = os.getenv("ADMIN_TOKEN", "")
    provided = request.headers.get("authorization", "").removeprefix("Bearer ")
    if not expected or len(expected) < 24 or not hmac.compare_digest(expected, provided):
        raise HTTPException(403, "管理员密钥无效")


class Credentials(BaseModel):
    email: str = Field(min_length=5, max_length=200, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="读者", min_length=1, max_length=40)


@router.post("/{action}")
def authenticate(action: str, data: Credentials, request: Request, response: Response):
    if action not in ("login", "register"):
        raise HTTPException(404)
    key = request.client.host
    now = time.monotonic()
    bucket = attempts[key]
    while bucket and bucket[0] < now - 60:
        bucket.popleft()
    if len(bucket) >= 10:
        raise HTTPException(429, "尝试过于频繁，请一分钟后重试")
    bucket.append(now)
    with db() as conn:
        if action == "register":
            try:
                user = conn.execute(
                    "INSERT INTO users(email,display_name,password_hash) VALUES (%s,%s,%s) RETURNING id,email,display_name",
                    (data.email.lower(), data.display_name, hash_password(data.password)),
                ).fetchone()
                conn.execute("INSERT INTO user_api_access(user_id) VALUES (%s)", (user["id"],))
            except UniqueViolation:
                raise HTTPException(409, "该邮箱已注册")
        else:
            user = conn.execute(
                "SELECT * FROM users WHERE email=%s", (data.email.lower(),)
            ).fetchone()
            if not user or not hmac.compare_digest(
                user["password_hash"],
                hash_password(data.password, user["password_hash"].split(":")[0]),
            ):
                raise HTTPException(401, "邮箱或密码错误")
        token = secrets.token_urlsafe(32)
        conn.execute("DELETE FROM sessions WHERE expires_at<now()")
        conn.execute(
            "INSERT INTO sessions(token_hash,user_id) VALUES (%s,%s)",
            (hashlib.sha256(token.encode()).hexdigest(), user["id"]),
        )
    response.set_cookie(
        "ws_session",
        token,
        httponly=True,
        samesite="lax",
        secure=os.getenv("COOKIE_SECURE") == "true",
        max_age=2592000,
        path="/",
    )
    return {key: user[key] for key in ("id", "email", "display_name")}


@router.get("/me")
def me(request: Request):
    return current_user(request, False)


@router.delete("/session")
def logout(request: Request, response: Response):
    with db() as conn:
        conn.execute(
            "DELETE FROM sessions WHERE token_hash=%s",
            (hashlib.sha256(request.cookies.get("ws_session", "").encode()).hexdigest(),),
        )
    response.delete_cookie("ws_session", path="/")
    return {"ok": True}
