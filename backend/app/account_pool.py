"""PostgreSQL task leases, capacity reservations, health and migration."""

import os
import secrets
import time

from cryptography.fernet import InvalidToken

from .credentials import decrypt, encrypt
from .db import db
from .sources.weread import SourceError, book_id


class PoolWaiting(Exception):
    pass


def subscribe(conn, account_id):
    account = conn.execute(
        "SELECT source_id FROM official_accounts WHERE id=%s", (account_id,)
    ).fetchone()
    if not account:
        raise SourceError("account", "公众号不存在", "target")
    external = book_id(account["source_id"])
    return conn.execute(
        """INSERT INTO source_subscriptions(account_id,external_id) VALUES (%s,%s)
        ON CONFLICT(account_id,source_id) DO UPDATE SET enabled=true RETURNING *""",
        (account_id, external),
    ).fetchone()


def acquire(job_id, account_id, execution_token=None):
    token = secrets.token_hex(24)
    with db() as conn:
        # Per-account row lock prevents capacity overbooking across multiple workers.
        account = conn.execute(
            """SELECT s.* FROM source_accounts s
          WHERE s.source_id='weread' AND s.enabled AND s.credentials<>''
          AND (s.maintenance_until IS NULL OR s.maintenance_until<=now())
          AND EXISTS(SELECT 1 FROM data_sources d WHERE d.id=s.source_id AND d.enabled)
          AND (s.health='healthy' OR (s.health='cooldown' AND s.cooldown_until<=now()))
          AND (s.cooldown_until IS NULL OR s.cooldown_until<=now())
          AND (SELECT count(*) FROM jobs j WHERE j.source_account_id=s.id AND j.status='running' AND j.lease_token IS NOT NULL)<s.max_tasks
          AND (EXISTS(SELECT 1 FROM source_memberships m WHERE m.source_account_id=s.id AND m.account_id=%s)
            OR (SELECT count(*) FROM source_memberships m WHERE m.source_account_id=s.id)
             +(SELECT count(*) FROM jobs j WHERE j.source_account_id=s.id AND j.status='running' AND j.lease_token IS NOT NULL)<s.max_subscriptions)
          ORDER BY (SELECT count(*)::float FROM jobs j WHERE j.source_account_id=s.id AND j.status='running' AND j.lease_token IS NOT NULL)/s.max_tasks,
            (SELECT count(*)::float FROM source_memberships m WHERE m.source_account_id=s.id)/s.max_subscriptions,
            s.consecutive_failures,s.last_assigned_at NULLS FIRST,s.id
          FOR UPDATE OF s SKIP LOCKED LIMIT 1""",
            (account_id,),
        ).fetchone()
        if not account:
            raise PoolWaiting("没有健康且有空余负载的微信读书账号，等待登录、冷却或释放容量")
        updated = conn.execute(
            """UPDATE jobs SET source_account_id=%s,lease_token=%s,heartbeat_at=now()
            WHERE id=%s AND status='running' AND lease_token IS NULL
            AND execution_token IS NOT DISTINCT FROM %s RETURNING id""",
            (account["id"], token, job_id, execution_token),
        ).fetchone()
        if not updated:
            raise PoolWaiting("任务已被其他执行器接管")
        conn.execute(
            "UPDATE source_accounts SET last_assigned_at=now() WHERE id=%s", (account["id"],)
        )
        conn.execute(
            "INSERT INTO crawl_attempts(job_id,source_account_id,lease_token) VALUES (%s,%s,%s)",
            (job_id, account["id"], token),
        )
    return {"account": account, "token": token, "job_id": job_id}


def heartbeat(lease):
    with db() as conn:
        row = conn.execute(
            "UPDATE jobs SET heartbeat_at=now() WHERE id=%s AND lease_token=%s AND status='running' RETURNING id",
            (lease["job_id"], lease["token"]),
        ).fetchone()
    if not row:
        raise PoolWaiting("采集租约已过期，停止当前执行")


def save_credentials(lease, credentials):
    with db() as conn:
        conn.execute(
            """UPDATE source_accounts SET credentials=%s,last_checked_at=now()
            WHERE id=%s AND EXISTS(SELECT 1 FROM jobs WHERE id=%s AND lease_token=%s AND status='running')""",
            (encrypt(credentials), lease["account"]["id"], lease["job_id"], lease["token"]),
        )


def throttle(lease):
    heartbeat(lease)
    interval = max(3, float(os.getenv("WEREAD_REQUEST_INTERVAL", "5")))
    with db() as conn:
        row = conn.execute(
            """SELECT enabled,health,cooldown_until>now() AS cooling,coalesce(extract(epoch FROM (next_request_at-now())),0) AS delay
            FROM source_accounts WHERE id=%s FOR UPDATE""",
            (lease["account"]["id"],),
        ).fetchone()
        if not row["enabled"] or row["health"] in ("expired", "error", "unconfigured"):
            raise SourceError("disabled", "采集账号已禁用或失效", "auth")
        if row["cooling"]:
            raise SourceError("cooldown", "账号正在冷却，暂停当前任务", "cooldown")
        delay = max(0, float(row["delay"]))
        conn.execute(
            "UPDATE source_accounts SET next_request_at=greatest(coalesce(next_request_at,now()),now())+(%s*interval '1 second') WHERE id=%s",
            (interval, lease["account"]["id"]),
        )
    while delay > 0:
        wait = min(delay, 30)
        time.sleep(wait)
        delay -= wait
        heartbeat(lease)
    heartbeat(lease)


def release(lease, error=None, capability=None):
    with db() as conn:
        row = conn.execute(
            "UPDATE jobs SET lease_token=NULL,heartbeat_at=now() WHERE id=%s AND lease_token=%s RETURNING id",
            (lease["job_id"], lease["token"]),
        ).fetchone()
        if not row:
            return
        conn.execute(
            "UPDATE crawl_attempts SET status=%s,error_code=%s,error=%s,finished_at=now() WHERE lease_token=%s",
            (
                "failed" if error else "done",
                getattr(error, "code", None),
                str(error)[:500] if error else None,
                lease["token"],
            ),
        )
        sid = lease["account"]["id"]
        if error:
            category = getattr(error, "category", "transient")
            # A bad target/body is not evidence that the login itself is unhealthy.
            health = (
                "expired"
                if category == "auth"
                else "cooldown"
                if category in ("cooldown", "ambiguous", "transient")
                else None
            )
            cooldown = 1800 if category in ("cooldown", "ambiguous") else 60
            conn.execute(
                """UPDATE source_accounts SET health=coalesce(%s,health),
                cooldown_until=CASE WHEN %s='cooldown' THEN now()+(%s*interval '1 second') ELSE cooldown_until END,
                consecutive_failures=consecutive_failures+1,total_failures=total_failures+1,last_failure_at=now(),last_error=%s WHERE id=%s""",
                (health, health, cooldown, str(error)[:500], sid),
            )
        else:
            conn.execute(
                """UPDATE source_accounts SET last_sync_at=now(),capability=coalesce(%s,capability) WHERE id=%s""",
                (capability, sid),
            )
            # A concurrent success must not erase a newer authentication failure.
            conn.execute(
                """UPDATE source_accounts SET health='healthy',cooldown_until=NULL,
                consecutive_failures=0,last_error=NULL WHERE id=%s AND
                (last_failure_at IS NULL OR last_failure_at<(SELECT started_at FROM crawl_attempts WHERE lease_token=%s))""",
                (sid, lease["token"]),
            )


def recover(conn):
    stale = conn.execute("""UPDATE jobs SET status='queued',lease_token=NULL,source_account_id=NULL,execution_token=NULL,
        error='执行器中断，租约回收后重新调度',run_after=now()
        WHERE status='running' AND lease_token IS NOT NULL AND heartbeat_at<now()-interval '5 minutes' RETURNING id""").fetchall()
    for row in stale:
        conn.execute(
            "UPDATE crawl_attempts SET status='interrupted',finished_at=now(),error='租约超时' WHERE job_id=%s AND status='running'",
            (row["id"],),
        )


def credentials(lease):
    try:
        return decrypt(lease["account"]["credentials"])
    except (InvalidToken, ValueError, OSError):
        raise SourceError("credentials", "无法解密账号凭据，请检查本机密钥或重新登录", "auth")
