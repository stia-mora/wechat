"""Admin account pool and isolated, per-account QR sessions."""

import base64
import io
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import qrcode
from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException
from psycopg import Error as DatabaseError
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, Field

from .auth import require_admin
from .credentials import decrypt, encrypt
from .db import db
from .sources.weread import SourceError, WeReadAdapter, cookie_values

router = APIRouter(prefix="/api/admin/source-accounts", dependencies=[Depends(require_admin)])
sessions = {}
session_lock = threading.Lock()
executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="weread-login")


class AccountInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    max_tasks: int = Field(default=1, ge=1, le=4)
    max_subscriptions: int = Field(default=100, ge=1, le=1000)


class CookieInput(BaseModel):
    cookie: str = Field(min_length=10, max_length=16000)
    ticket: str = Field(default="", max_length=2000, pattern=r"^[^\r\n]*$")


@router.get("")
def accounts():
    with db() as conn:
        return conn.execute("""SELECT s.id,s.name,s.external_id,s.enabled,s.health,s.capability,
            s.max_tasks,s.max_subscriptions,s.consecutive_failures,s.total_failures,s.last_sync_at,
            s.last_failure_at,s.last_checked_at,s.cooldown_until,s.last_error,
            (SELECT count(*) FROM source_memberships m WHERE m.source_account_id=s.id) subscriptions,
            (SELECT count(*) FROM jobs j WHERE j.source_account_id=s.id AND j.lease_token IS NOT NULL AND j.status='running') current_tasks
            FROM source_accounts s ORDER BY s.id""").fetchall()


@router.post("")
def create(data: AccountInput):
    with db() as conn:
        return conn.execute(
            "INSERT INTO source_accounts(name,enabled,max_tasks,max_subscriptions) VALUES (%s,%s,%s,%s) RETURNING id",
            (data.name, data.enabled, data.max_tasks, data.max_subscriptions),
        ).fetchone()


@router.patch("/{account_id}")
def edit(account_id: int, data: AccountInput):
    with db() as conn:
        if not conn.execute(
            "UPDATE source_accounts SET name=%s,enabled=%s,max_tasks=%s,max_subscriptions=%s WHERE id=%s RETURNING id",
            (data.name, data.enabled, data.max_tasks, data.max_subscriptions, account_id),
        ).fetchone():
            raise HTTPException(404)
    return {"ok": True}


def account_row(account_id):
    with db() as conn:
        row = conn.execute(
            "SELECT *,maintenance_until>now() AS maintaining FROM source_accounts WHERE id=%s FOR UPDATE",
            (account_id,),
        ).fetchone()
        active = conn.execute(
            "SELECT 1 FROM jobs WHERE source_account_id=%s AND lease_token IS NOT NULL AND status='running'",
            (account_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "账号不存在")
        if active or row["maintaining"]:
            raise HTTPException(409, "账号正在采集或登录检查，请等待当前操作结束")
        conn.execute(
            "UPDATE source_accounts SET maintenance_until=now()+interval '6 minutes' WHERE id=%s",
            (account_id,),
        )
    return row


def end_maintenance(account_id):
    with db() as conn:
        conn.execute("UPDATE source_accounts SET maintenance_until=NULL WHERE id=%s", (account_id,))


def save_verified(account_id, adapter):
    credentials = adapter.credentials()
    vid = credentials["cookies"].get("wr_vid")
    if not vid:
        raise SourceError("vid", "登录响应缺少微信读书用户标识", "auth")
    try:
        with db() as conn:
            row = conn.execute(
                "SELECT external_id FROM source_accounts WHERE id=%s FOR UPDATE", (account_id,)
            ).fetchone()
            if row["external_id"] and row["external_id"] != vid:
                raise SourceError(
                    "identity", "此记录属于另一个微信读书用户，请新增账号记录", "target"
                )
            conn.execute(
                """UPDATE source_accounts SET credentials=%s,external_id=%s,health='healthy',
                consecutive_failures=0,last_error=NULL,cooldown_until=NULL,last_checked_at=now() WHERE id=%s""",
                (encrypt(credentials), vid, account_id),
            )
            conn.execute(
                """UPDATE jobs SET status='queued',run_after=now(),error=NULL WHERE kind='sync' AND status='blocked' AND error LIKE '没有健康%%'
            AND id=(SELECT max(w.id) FROM jobs w WHERE w.dedupe_key=jobs.dedupe_key AND w.status='blocked')
            AND NOT EXISTS(SELECT 1 FROM jobs active WHERE active.dedupe_key=jobs.dedupe_key AND active.status IN ('queued','running'))"""
            )
    except UniqueViolation:
        raise SourceError(
            "duplicate", "这个微信读书用户已经在账号池中，不能重复计为两个账号", "target"
        )


def record_error(account_id, exc):
    health = (
        "expired"
        if exc.category == "auth"
        else "cooldown"
        if exc.category in ("cooldown", "ambiguous")
        else "error"
    )
    with db() as conn:
        conn.execute(
            """UPDATE source_accounts SET health=%s,last_error=%s,last_failure_at=now(),
            total_failures=total_failures+1,consecutive_failures=consecutive_failures+1,
            cooldown_until=CASE WHEN %s='cooldown' THEN now()+interval '30 minutes' ELSE NULL END WHERE id=%s""",
            (health, str(exc), health, account_id),
        )


@router.post("/{account_id}/cookie")
def set_cookie(account_id: int, data: CookieInput):
    account_row(account_id)
    adapter = None
    try:
        adapter = WeReadAdapter({"cookies": cookie_values(data.cookie), "ticket": data.ticket})
        adapter.verify_or_renew()
        save_verified(account_id, adapter)
        return {"ok": True, "message": "凭据已验证并加密保存"}
    except SourceError as exc:
        raise HTTPException(422, str(exc))
    finally:
        if adapter:
            adapter.close()
        end_maintenance(account_id)


@router.post("/{account_id}/check")
def check(account_id: int):
    row = account_row(account_id)
    if not row["credentials"]:
        end_maintenance(account_id)
        raise HTTPException(409, "请先扫码或导入 Cookie")
    adapter = None
    try:
        try:
            adapter = WeReadAdapter(decrypt(row["credentials"]))
        except (InvalidToken, ValueError, OSError):
            raise SourceError("credentials", "无法解密凭据，请恢复密钥或重新登录", "auth")
        books = adapter.verify_or_renew()
        save_verified(account_id, adapter)
        return {"ok": True, "shelf_count": len(books)}
    except SourceError as exc:
        record_error(account_id, exc)
        raise HTTPException(422, str(exc))
    finally:
        if adapter:
            adapter.close()
        end_maintenance(account_id)


def poll_login(account_id, session):
    try:
        while time.time() < session["expires"]:
            try:
                status = session["adapter"].login_poll(session["uid"])
            except SourceError as exc:
                if exc.code == "timeout":
                    continue
                raise
            if status["status"] == "done":
                save_verified(account_id, session["adapter"])
                session.update(status="done", message="扫码登录成功，账号已进入健康池")
                return
            time.sleep(2)
        session.update(status="expired", message="二维码已过期，请重新获取")
    except SourceError as exc:
        session.update(status="failed", message=str(exc))
    except (DatabaseError, ValueError, OSError):
        session.update(status="failed", message="扫码登录处理失败，请重新获取二维码或导入 Cookie")
    finally:
        session["adapter"].close()
        end_maintenance(account_id)


@router.post("/{account_id}/qr")
def qr(account_id: int):
    with session_lock:
        old = sessions.get(account_id)
        if old and old["status"] == "waiting" and old["expires"] > time.time():
            return {k: old[k] for k in ("status", "message", "image")}
        if sum(s["status"] == "waiting" for s in sessions.values()) >= 4:
            raise HTTPException(429, "最多同时打开四个扫码会话")
        account_row(account_id)
        adapter = WeReadAdapter()
        try:
            uid = adapter.login_start()
        except SourceError as exc:
            adapter.close()
            end_maintenance(account_id)
            raise HTTPException(502, str(exc))
        buffer = io.BytesIO()
        qrcode.make("https://weread.qq.com/web/confirm?uid=" + uid).save(buffer, format="PNG")
        session = {
            "uid": uid,
            "adapter": adapter,
            "expires": time.time() + 300,
            "status": "waiting",
            "message": "请用微信读书对应微信扫码确认",
            "image": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode(),
        }
        sessions[account_id] = session
        executor.submit(poll_login, account_id, session)
    return {k: session[k] for k in ("status", "message", "image")}


@router.get("/{account_id}/qr")
def qr_status(account_id: int):
    session = sessions.get(account_id)
    return (
        {k: session[k] for k in ("status", "message", "image")}
        if session
        else {"status": "none", "message": "请获取二维码"}
    )


@router.get("/attempts/recent")
def attempts():
    with db() as conn:
        return conn.execute("""SELECT c.*,s.name,j.payload,j.result FROM crawl_attempts c
            JOIN source_accounts s ON s.id=c.source_account_id JOIN jobs j ON j.id=c.job_id
            ORDER BY c.id DESC LIMIT 100""").fetchall()
