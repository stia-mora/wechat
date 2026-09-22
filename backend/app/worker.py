import argparse
import logging
import os
import secrets
import time

from psycopg.types.json import Jsonb

from .account_pool import PoolWaiting, recover
from .crawler import SourceBlocked, SourceClient
from .db import db, initialize
from .repository import enqueue
from .sources.weread import SourceError

log = logging.getLogger("worker")


def schedule():
    from .account_pool import subscribe
    from .sources.weread import SourceError

    with db() as conn:
        for row in conn.execute(
            "SELECT id FROM official_accounts WHERE status IN ('approved','pending')"
        ).fetchall():
            try:
                subscribe(conn, row["id"])
            except SourceError:
                continue
        rows = conn.execute("""SELECT s.account_id AS id,s.history_complete FROM source_subscriptions s
            JOIN official_accounts a ON a.id=s.account_id WHERE s.enabled
            AND a.status IN ('approved','pending') AND s.next_sync_at<=now()
            ORDER BY CASE a.status WHEN 'approved' THEN 0 ELSE 1 END,s.last_sync_at NULLS FIRST,s.account_id""").fetchall()
        for row in rows:
            enqueue(
                conn,
                "sync",
                {
                    "target_id": row["id"],
                    "pages": 3,
                    "parse_limit": 20,
                    "backfill": not row["history_complete"],
                },
            )
            conn.execute(
                "UPDATE source_subscriptions SET next_sync_at=now()+(%s*interval '1 hour') WHERE account_id=%s AND source_id='weread'",
                (max(1, int(os.getenv("SYNC_INTERVAL_HOURS", "3"))), row["id"]),
            )
        conn.execute("""UPDATE jobs SET status='queued',run_after=now(),error=NULL
            WHERE kind='sync' AND status='blocked' AND error LIKE '没有健康%%'
            AND id=(SELECT max(w.id) FROM jobs w WHERE w.dedupe_key=jobs.dedupe_key AND w.status='blocked')
            AND NOT EXISTS(SELECT 1 FROM jobs active WHERE active.dedupe_key=jobs.dedupe_key AND active.status IN ('queued','running'))
            AND EXISTS(SELECT 1 FROM source_accounts WHERE enabled AND
              (health='healthy' OR (health='cooldown' AND cooldown_until<=now())))""")


def run(once=False, mode="all"):
    initialize()
    source = SourceClient()
    if mode != "ai":
        schedule()
    last_schedule = time.monotonic()
    while True:
        if time.monotonic() - last_schedule > 60 and mode != "ai":
            schedule()
            last_schedule = time.monotonic()
        with db() as conn:
            recover(conn)
            conn.execute(
                "UPDATE jobs SET status='queued',execution_token=NULL,error='Worker 中断，重新排队' WHERE status='running' AND lease_token IS NULL AND started_at<now()-interval '3 hours'"
            )
            types = (
                ["article_ai", "account_ai", "embedding"]
                if mode == "ai"
                else ["discover", "sync", "parse"]
                if mode == "crawler"
                else ["discover", "sync", "parse", "article_ai", "account_ai", "embedding"]
            )
            job = conn.execute(
                """SELECT j.* FROM jobs j LEFT JOIN official_accounts a ON j.kind='sync'
                AND a.id=(j.payload->>'target_id')::bigint WHERE j.status='queued'
                AND j.run_after<=now() AND j.kind=ANY(%s)
                ORDER BY CASE j.kind WHEN 'discover' THEN 0 WHEN 'sync' THEN 1 ELSE 2 END,
                CASE WHEN j.kind='sync' AND a.status='approved' THEN 0 ELSE 1 END,j.id
                FOR UPDATE OF j SKIP LOCKED LIMIT 1""",
                (types,),
            ).fetchone()
            if job:
                job["execution_token"] = secrets.token_hex(24)
                conn.execute(
                    "UPDATE jobs SET status='running',attempts=attempts+1,started_at=now(),error=NULL,execution_token=%s WHERE id=%s",
                    (job["execution_token"], job["id"]),
                )
        if not job:
            if once:
                break
            time.sleep(2)
            continue
        try:
            if job["kind"] in ("embedding", "account_embedding"):
                from .embeddings import generate, refresh_account

                result = (
                    generate(job["payload"])
                    if job["kind"] == "embedding"
                    else refresh_account(job["payload"])
                )
            elif job["kind"].endswith("_ai"):
                from .ai import analyze

                result = analyze(job["kind"], job["payload"])
            else:
                payload = dict(job["payload"])
                if job["kind"] == "sync":
                    payload.update(
                        _job_id=job["id"],
                        _execution_token=job["execution_token"],
                        _progress=job["result"] or payload.get("_progress"),
                    )
                result = getattr(source, job["kind"])(payload)
            with db() as conn:
                conn.execute(
                    "UPDATE jobs SET status='done',result=%s,finished_at=now() WHERE id=%s AND execution_token=%s",
                    (Jsonb(result), job["id"], job["execution_token"]),
                )
            log.info("job %s %s done", job["id"], job["kind"])
        except PoolWaiting as exc:
            with db() as conn:
                conn.execute(
                    "UPDATE jobs SET status='blocked',attempts=greatest(attempts-1,0),error=%s,lease_token=NULL,finished_at=now() WHERE id=%s AND execution_token=%s",
                    (str(exc), job["id"], job["execution_token"]),
                )
        except SourceError as exc:
            terminal = (
                exc.category in ("target", "verification")
                or job["attempts"] + 1 >= job["max_attempts"]
            )
            with db() as conn:
                conn.execute(
                    """UPDATE jobs SET status=%s,error=%s,lease_token=NULL,
                    run_after=now()+interval '60 seconds',finished_at=CASE WHEN %s THEN now() ELSE NULL END WHERE id=%s AND execution_token=%s""",
                    (
                        "blocked"
                        if exc.category == "verification"
                        else "failed"
                        if terminal
                        else "queued",
                        str(exc),
                        terminal,
                        job["id"],
                        job["execution_token"],
                    ),
                )
                if terminal:
                    conn.execute(
                        "UPDATE source_subscriptions SET next_sync_at=now()+(%s*interval '1 hour') WHERE account_id=%s AND source_id='weread'",
                        (
                            max(1, int(os.getenv("SYNC_INTERVAL_HOURS", "3"))),
                            job["payload"].get("target_id"),
                        ),
                    )
            log.warning("job %s source error %s", job["id"], exc.code)
        except SourceBlocked as exc:
            with db() as conn:
                conn.execute(
                    "UPDATE jobs SET status='blocked',error=%s,finished_at=now() WHERE id=%s AND execution_token=%s",
                    (str(exc)[:1000], job["id"], job["execution_token"]),
                )
            log.warning("job %s blocked: %s", job["id"], exc)
            # Stop related queued source work after authentication/verification failures.
            if job["kind"] in ("discover", "parse") and "仅采集" not in str(exc):
                with db() as conn:
                    conn.execute(
                        "UPDATE jobs SET status='blocked',error=%s,finished_at=now() WHERE status='queued' AND kind=%s",
                        (str(exc)[:1000], job["kind"]),
                    )
        except Exception as exc:
            terminal = job["attempts"] + 1 >= job["max_attempts"]
            with db() as conn:
                conn.execute(
                    "UPDATE jobs SET status=%s,error=%s,run_after=now()+interval '60 seconds',finished_at=CASE WHEN %s THEN now() ELSE NULL END WHERE id=%s AND execution_token=%s",
                    (
                        "failed" if terminal else "queued",
                        str(exc)[:1000],
                        terminal,
                        job["id"],
                        job["execution_token"],
                    ),
                )
            log.exception("job %s failed", job["id"])
        if once:
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--mode", choices=["all", "crawler", "ai"], default="all")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(args.once, args.mode)
