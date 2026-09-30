"""Resumable directory-only discovery from authenticated, live WeChat searches."""

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from psycopg.types.json import Jsonb

from .crawler import SourceBlocked, SourceClient
from .db import db, initialize
from .discovery_queries import queries


def save_state(path, state):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def wait_for_login(source):
    response = source.client.get("/api/admin/status", timeout=10)
    response.raise_for_status()
    status = response.json()
    return bool(status.get("loggedIn") and not status.get("isExpired"))


def collect(target, state_path, wait_login=False):
    initialize()
    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "query_index": 0, "begin": 0, "pages": 0, "previous_ids": [],
    }
    source = SourceClient()
    terms = queries()
    # Session lock survives page commits, preventing concurrent bulk collectors.
    with db() as lock:
        with lock.transaction():
            if not lock.execute("SELECT pg_try_advisory_lock(1911760658) locked").fetchone()["locked"]:
                raise RuntimeError("另一个公众号目录采集器正在运行")
        while True:
            with db() as conn:
                total = conn.execute("SELECT count(*) n FROM official_accounts WHERE platform='wechat'").fetchone()["n"]
            state.update(total=total, target=target, updated_at=datetime.now(UTC).isoformat())
            if total >= target or state["query_index"] >= len(terms):
                state["status"] = "complete" if total >= target else "queries_exhausted"
                save_state(path, state)
                print(json.dumps(state, ensure_ascii=False), flush=True)
                if total < target:
                    raise RuntimeError(f"查询词已用完，真实公众号只有 {total} 个，未达到目标 {target}")
                return state
            query = terms[state["query_index"]]
            payload = {"query": query, "begin": state["begin"], "directory_only": True}
            job_id = None
            try:
                if not wait_for_login(source):
                    raise SourceBlocked("微信发现登录已过期，请重新扫码登录")
                with db() as conn:
                    job_id = conn.execute(
                        "INSERT INTO jobs(kind,payload,dedupe_key,status,attempts,started_at) "
                        "VALUES ('discover',%s,%s,'running',1,now()) RETURNING id",
                        (Jsonb(payload), f"bulk-discover:{query}:{state['begin']}:{os.getpid()}:{time.time_ns()}"),
                    ).fetchone()["id"]
                result = source.discover(payload)
                ids = [row["source_id"] for row in result["accounts"]]
                with db() as conn:
                    conn.execute("UPDATE jobs SET status='done',result=%s,finished_at=now() WHERE id=%s",
                                 (Jsonb(result), job_id))
                # Some sources repeat their first page; never loop forever on it.
                if (result["has_more"] and result["next_begin"] > state["begin"]
                        and (not ids or ids != state["previous_ids"]) and result["next_begin"] < 100):
                    state.update(begin=result["next_begin"], previous_ids=ids)
                else:
                    state.update(query_index=state["query_index"] + 1, begin=0, previous_ids=[])
                state.update(pages=state["pages"] + 1, status="running", error=None,
                             last_query=query, last_result_count=len(ids))
                save_state(path, state)
                print(f"{query}: {len(ids)} returned; directory >= {total}; pages={state['pages']}", flush=True)
            except (SourceBlocked, httpx.HTTPError, RuntimeError) as exc:
                state.update(status=("waiting_login" if "登录" in str(exc) else "waiting_source")
                             if isinstance(exc, SourceBlocked) else "retrying",
                             error=str(exc)[:500])
                save_state(path, state)
                if job_id:
                    with db() as conn:
                        conn.execute("UPDATE jobs SET status=%s,error=%s,finished_at=now() WHERE id=%s",
                                     ("blocked" if isinstance(exc, SourceBlocked) else "failed", state["error"], job_id))
                print(f"{state['status']}: {state['error']}", flush=True)
                if not wait_login:
                    raise
                # Authentication and rate limits resume the same page, without account rotation.
                time.sleep(300 if state["status"] == "waiting_source" else 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=10000)
    parser.add_argument("--state", default="/data/private/directory-discovery.json")
    parser.add_argument("--wait-login", action="store_true")
    args = parser.parse_args()
    collect(args.target, args.state, args.wait_login)
