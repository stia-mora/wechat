import argparse
import logging
import os
import time

from psycopg.types.json import Jsonb

from .crawler import SourceBlocked, SourceClient
from .db import db, initialize
from .repository import enqueue

log = logging.getLogger("worker")


def schedule():
    hours = max(1, int(os.getenv("SYNC_INTERVAL_HOURS", "24")))
    with db() as conn:
        rows = conn.execute(
            "SELECT a.id FROM official_accounts a WHERE a.status='approved' AND (a.last_crawled_at IS NULL OR a.last_crawled_at<now()-(%s * interval '1 hour')) AND coalesce((SELECT j.status FROM jobs j WHERE j.kind='sync' AND (j.payload->>'target_id')::bigint=a.id ORDER BY j.id DESC LIMIT 1),'done') NOT IN ('blocked','failed')",
            (hours,),
        ).fetchall()
        for row in rows:
            enqueue(conn, "sync", {"target_id": row["id"], "pages": 1, "parse_limit": 3})


def run(once=False, mode="all"):
    initialize()
    source = SourceClient()
    if mode != "ai":
        schedule()
    last_schedule = time.monotonic()
    while True:
        if time.monotonic() - last_schedule > 3600 and mode != "ai":
            schedule()
            last_schedule = time.monotonic()
        with db() as conn:
            conn.execute(
                "UPDATE jobs SET status='queued',error='Worker 中断，重新排队' WHERE status='running' AND started_at<now()-interval '3 hours'"
            )
            types = (
                ["article_ai", "account_ai"]
                if mode == "ai"
                else ["discover", "sync", "parse"]
                if mode == "crawler"
                else ["discover", "sync", "parse", "article_ai", "account_ai"]
            )
            job = conn.execute(
                "SELECT * FROM jobs WHERE status='queued' AND run_after<=now() AND kind=ANY(%s) ORDER BY CASE kind WHEN 'discover' THEN 0 WHEN 'sync' THEN 1 ELSE 2 END,id FOR UPDATE SKIP LOCKED LIMIT 1",
                (types,),
            ).fetchone()
            if job:
                conn.execute(
                    "UPDATE jobs SET status='running',attempts=attempts+1,started_at=now(),error=NULL WHERE id=%s",
                    (job["id"],),
                )
        if not job:
            if once:
                break
            time.sleep(2)
            continue
        try:
            if job["kind"].endswith("_ai"):
                from .ai import analyze

                result = analyze(job["kind"], job["payload"])
            else:
                payload = dict(job["payload"])
                if job["kind"] == "sync":
                    payload.update(
                        _job_id=job["id"], _progress=job["result"] or payload.get("_progress")
                    )
                result = getattr(source, job["kind"])(payload)
            with db() as conn:
                conn.execute(
                    "UPDATE jobs SET status='done',result=%s,finished_at=now() WHERE id=%s",
                    (Jsonb(result), job["id"]),
                )
            log.info("job %s %s done", job["id"], job["kind"])
        except SourceBlocked as exc:
            with db() as conn:
                conn.execute(
                    "UPDATE jobs SET status='blocked',error=%s,finished_at=now() WHERE id=%s",
                    (str(exc)[:1000], job["id"]),
                )
            log.warning("job %s blocked: %s", job["id"], exc)
            # Stop related queued source work after authentication/verification failures.
            if not job["kind"].endswith("_ai"):
                with db() as conn:
                    conn.execute(
                        "UPDATE jobs SET status='blocked',error=%s,finished_at=now() WHERE status='queued' AND kind IN ('discover','sync','parse') AND coalesce((payload->>'cache_only')::boolean,false)=false",
                        (str(exc)[:1000],),
                    )
        except Exception as exc:
            terminal = job["attempts"] + 1 >= job["max_attempts"]
            with db() as conn:
                conn.execute(
                    "UPDATE jobs SET status=%s,error=%s,run_after=now()+interval '60 seconds',finished_at=CASE WHEN %s THEN now() ELSE NULL END WHERE id=%s",
                    ("failed" if terminal else "queued", str(exc)[:1000], terminal, job["id"]),
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
