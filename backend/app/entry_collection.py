"""One-shot metadata collection. Only the authenticated desktop owns execution."""

import hashlib
import random
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from .auth import require_admin
from .content import article_key
from .db import db
from .repository import enqueue

admin_router = APIRouter(prefix="/api/admin/entry-collection", dependencies=[Depends(require_admin)])
router = APIRouter(prefix="/api/entry-collector")
ERRORS = {
    "empty": "上游明确返回空文章列表", "unknown": "wx_channel 尚未捕获该公众号凭据",
    "auth": "微信登录凭据失效", "verification": "微信要求人工验证",
    "rate_limit": "微信限制请求，请处理后复验", "network": "上游连接失败",
    "identity": "文章作者与目录标识不一致", "invalid": "上游响应不是有效文章数据",
}
BLOCKERS = {"auth", "verification", "rate_limit", "identity"}


def locked_run(conn):
    return conn.execute("SELECT * FROM entry_collection WHERE id=true FOR UPDATE").fetchone()


def require_collector(request: Request):
    authorization = request.headers.get("authorization", "")
    token = authorization.removeprefix("Bearer ")
    with db() as conn:
        expected = conn.execute("SELECT token_hash FROM entry_collection WHERE id=true").fetchone()["token_hash"]
    digest = hashlib.sha256(token.encode()).hexdigest()
    if not authorization.startswith("Bearer ") or not expected or not secrets.compare_digest(expected, digest):
        raise HTTPException(401, "采集端凭证无效或已撤销")
    return digest


def collector_run(conn, digest):
    run = locked_run(conn)
    if not run["token_hash"] or not secrets.compare_digest(run["token_hash"], digest):
        raise HTTPException(401, "采集端凭证已撤销")
    return run


router.dependencies.append(Depends(require_collector))


def phase_jobs(conn, phase):
    return conn.execute("""SELECT id,status,result,payload FROM jobs WHERE kind='account_entry'
        AND payload->>'run_id'=(SELECT run_id FROM entry_collection WHERE id=true)
        AND payload->>'phase'=%s ORDER BY id""", (phase,)).fetchall()


def phase_passed(conn, phase):
    jobs = phase_jobs(conn, phase)
    if len(jobs) != (20 if phase == "sample" else 50) or any(j["status"] != "done" for j in jobs):
        return False
    successes = [j for j in jobs if (j["result"] or {}).get("outcome") == "success"]
    if phase == "sample":
        successes = [j for j in successes if j["payload"]["group"] == "unknown"
                     and j["result"].get("pre_captured") is False]
    return len(successes) >= 10


@admin_router.get("")
def status(page: int = Query(1, ge=1)):
    with db() as conn:
        run = conn.execute("SELECT * FROM entry_collection WHERE id=true").fetchone()
        run.pop("token_hash")
        counts = conn.execute("""SELECT status,coalesce(result->>'outcome','pending') outcome,count(*) count
            FROM jobs WHERE kind='account_entry' AND payload->>'run_id'=%s GROUP BY 1,2""", (run["run_id"],)).fetchall()
        requests = conn.execute("SELECT coalesce(sum(requests),0) n FROM entry_request_budget WHERE day=(now() AT TIME ZONE 'Asia/Shanghai')::date").fetchone()["n"]
        samples = conn.execute("""SELECT j.id,a.name,a.source_id,j.status,j.error,j.result,j.payload->>'group' AS sample_group
            FROM jobs j JOIN official_accounts a ON a.id=(j.payload->>'target_id')::bigint
            WHERE j.kind='account_entry' AND j.payload->>'run_id'=%s AND j.payload->>'phase'='sample' ORDER BY j.id""", (run["run_id"],)).fetchall()
        failures = conn.execute("""SELECT error,count(*) count FROM jobs WHERE kind='account_entry'
            AND payload->>'run_id'=%s AND error IS NOT NULL GROUP BY error""", (run["run_id"],)).fetchall()
        current_jobs = conn.execute("""SELECT j.id,a.name,j.status,j.error,j.result,j.payload->>'group' AS sample_group
            FROM jobs j JOIN official_accounts a ON a.id=(j.payload->>'target_id')::bigint
            WHERE j.kind='account_entry' AND j.payload->>'run_id'=%s AND j.payload->>'phase'=%s
            ORDER BY j.id LIMIT 100 OFFSET %s""", (run["run_id"], run["phase"], (page-1)*100)).fetchall()
        return {**run, "counts": counts, "requests_today": requests, "daily_limit": 500,
                "sample_passed": phase_passed(conn, "sample"), "canary_passed": phase_passed(conn, "canary"),
                "samples": samples, "current_jobs": current_jobs, "page": page, "failures": failures}


@admin_router.post("/token")
def rotate_token():
    token = "entry_" + secrets.token_urlsafe(32)
    with db() as conn:
        locked_run(conn)
        conn.execute("UPDATE entry_collection SET token_hash=%s,status='paused',reason='采集端令牌已轮换' WHERE id=true",
                     (hashlib.sha256(token.encode()).hexdigest(),))
        # Fence in-flight work as well as subsequent authentication.
        conn.execute("UPDATE jobs SET status='queued',execution_token=NULL WHERE kind='account_entry' AND status='running'")
    return {"token": token, "message": "仅此次显示；轮换会暂停队列并使旧令牌立即失效"}


@admin_router.delete("/token")
def revoke_token():
    with db() as conn:
        locked_run(conn)
        conn.execute("UPDATE entry_collection SET token_hash='',status='paused',reason='采集端令牌已撤销' WHERE id=true")
        conn.execute("UPDATE jobs SET status='queued',execution_token=NULL WHERE kind='account_entry' AND status='running'")
    return {"ok": True}


@admin_router.post("/prepare")
def prepare():
    with db() as conn:
        run = locked_run(conn)
        if run["run_id"]:
            raise HTTPException(409, "目标快照已创建，请继续原队列，不重复初始化")
        controls = conn.execute("""SELECT a.id FROM official_accounts a WHERE a.status='approved' AND a.platform='wechat'
            AND EXISTS(SELECT 1 FROM articles ar WHERE ar.account_id=a.id AND ar.status<>'hidden' AND ar.source_url<>'')
            ORDER BY a.id LIMIT 5""").fetchall()
        targets = conn.execute("""SELECT id FROM (SELECT a.id,a.primary_category_id,
            row_number() OVER(PARTITION BY a.primary_category_id ORDER BY a.id) r
            FROM official_accounts a WHERE a.status='approved' AND a.platform='wechat' AND NOT a.article_collection_enabled
            AND NOT EXISTS(SELECT 1 FROM articles ar WHERE ar.account_id=a.id AND ar.status<>'hidden' AND ar.source_url<>'')) t
            ORDER BY r,primary_category_id NULLS LAST,id""").fetchall()
        if len(controls) != 5 or len(targets) < 65:
            raise HTTPException(409, "需要 5 个对照账号及至少 65 个缺入口账号才能固定样本和灰度批次")
        run_id = secrets.token_hex(12)
        for index, row in enumerate(controls + targets):
            payload = {"target_id": row["id"], "run_id": run_id,
                       "phase": "sample" if index < 20 else "reserve",
                       "group": "control" if index < 5 else "unknown"}
            enqueue(conn, "account_entry", payload, "account-entry:" + str(row["id"]))
        conn.execute("UPDATE entry_collection SET run_id=%s,phase='sample',reason='样本已固定，等待启动验证' WHERE id=true", (run_id,))
    return {"targets": len(targets), "samples": 20}


class Action(BaseModel):
    action: str = Field(pattern="^(pause|resume|canary|full)$")


@admin_router.post("/control")
def control(data: Action):
    with db() as conn:
        run = locked_run(conn)
        if not run["run_id"] or not run["token_hash"]:
            raise HTTPException(409, "请先创建目标快照并配置采集端令牌")
        if data.action == "pause":
            conn.execute("UPDATE entry_collection SET status='paused',reason='管理员暂停' WHERE id=true")
        elif data.action == "resume":
            mode = "probe" if run["blocked"] else "active"
            if run["blocked"]:
                blocked = conn.execute("""SELECT id FROM jobs WHERE kind='account_entry' AND id=%s
                    AND status IN ('blocked','queued','failed','done') AND payload->>'run_id'=%s
                    AND payload->>'phase'=%s""", (run["probe_job_id"], run["run_id"], run["phase"])).fetchone()
                if not blocked:
                    raise HTTPException(409, "没有可复验任务，请先明确重试失败任务")
                conn.execute("UPDATE jobs SET status='queued',run_after=now() WHERE id=%s", (blocked["id"],))
            conn.execute("UPDATE entry_collection SET status=%s,reason='' WHERE id=true", (mode,))
        else:
            prerequisite = "sample" if data.action == "canary" else "canary"
            if run["blocked"] or not phase_passed(conn, prerequisite):
                raise HTTPException(409, "前一阶段未通过验收，不能启动后续批次")
            if run["phase"] != prerequisite:
                raise HTTPException(409, "不能跳过或重复推进阶段")
            limit = 50 if data.action == "canary" else 1000000
            conn.execute("""UPDATE jobs SET payload=jsonb_set(payload,'{phase}',to_jsonb(%s::text)) WHERE id IN
                (SELECT id FROM jobs WHERE kind='account_entry' AND payload->>'run_id'=%s AND payload->>'phase'='reserve' ORDER BY id LIMIT %s)""",
                         (data.action, run["run_id"], limit))
            conn.execute("UPDATE entry_collection SET phase=%s,status='active',reason='' WHERE id=true", (data.action,))
    return {"ok": True}


@admin_router.post("/jobs/{job_id}/retry")
def retry(job_id: int):
    with db() as conn:
        run = locked_run(conn)
        updated = conn.execute("""UPDATE jobs SET status='queued',attempts=0,result=NULL,error=NULL,run_after=now(),execution_token=NULL
            WHERE id=%s AND kind='account_entry' AND payload->>'run_id'=%s AND payload->>'phase'=%s AND status IN ('blocked','failed','done') RETURNING id""",
                               (job_id, run["run_id"], run["phase"])).fetchone()
        if not updated:
            raise HTTPException(409, "任务不存在或不属于当前阶段可重试任务")
    return {"ok": True}


@router.post("/claim")
def claim(credential: str = Depends(require_collector)):
    with db() as conn:
        run = collector_run(conn, credential)
        conn.execute("UPDATE entry_collection SET last_heartbeat=now() WHERE id=true")
        conn.execute("""UPDATE jobs SET status='queued',execution_token=NULL WHERE kind='account_entry'
            AND status='running' AND heartbeat_at<now()-interval '2 minutes'""")
        if run["status"] not in ("active", "probe") or conn.execute("SELECT 1 FROM jobs WHERE kind='account_entry' AND status='running'").fetchone():
            return {"job": None}
        job = conn.execute("""SELECT j.id,j.payload,a.name,a.source_id FROM jobs j JOIN official_accounts a ON a.id=(j.payload->>'target_id')::bigint
            WHERE j.kind='account_entry' AND j.status='queued' AND j.run_after<=now()
            AND j.payload->>'run_id'=%s AND j.payload->>'phase'=%s
            AND (%s='active' OR j.id=%s)
            ORDER BY CASE WHEN j.error IS NOT NULL THEN 0 ELSE 1 END,j.id FOR UPDATE OF j SKIP LOCKED LIMIT 1""", (run["run_id"], run["phase"], run["status"], run["probe_job_id"])).fetchone()
        if not job:
            remaining = conn.execute("""SELECT 1 FROM jobs WHERE kind='account_entry' AND payload->>'run_id'=%s
                AND payload->>'phase'=%s AND status IN ('queued','running') LIMIT 1""", (run["run_id"], run["phase"])).fetchone()
            if not remaining:
                conn.execute("UPDATE entry_collection SET status='paused',reason='当前阶段完成，请检查验收结果' WHERE id=true")
            return {"job": None}
        job["execution_token"] = secrets.token_hex(24)
        conn.execute("UPDATE jobs SET status='running',execution_token=%s,heartbeat_at=now(),started_at=now(),attempts=attempts+1 WHERE id=%s", (job["execution_token"], job["id"]))
    return {"job": job}


class Lease(BaseModel):
    model_config = ConfigDict(extra="forbid")
    execution_token: str = Field(min_length=48, max_length=48)


def lease_job(conn, job_id, token):
    row = conn.execute("""SELECT * FROM jobs WHERE id=%s AND kind='account_entry' AND status='running'
        AND execution_token=%s AND heartbeat_at>=now()-interval '2 minutes' FOR UPDATE""", (job_id, token)).fetchone()
    if not row:
        raise HTTPException(409, "任务租约已过期或执行令牌不匹配")
    return row


@router.post("/jobs/{job_id}/heartbeat")
def heartbeat(job_id: int, data: Lease, credential: str = Depends(require_collector)):
    with db() as conn:
        collector_run(conn, credential)
        lease_job(conn, job_id, data.execution_token)
        conn.execute("UPDATE jobs SET heartbeat_at=now() WHERE id=%s", (job_id,))
        conn.execute("UPDATE entry_collection SET last_heartbeat=now() WHERE id=true")
    return {"ok": True}


@router.post("/jobs/{job_id}/request-permit")
def permit(job_id: int, data: Lease, credential: str = Depends(require_collector)):
    with db() as conn:
        run = collector_run(conn, credential)
        lease_job(conn, job_id, data.execution_token)
        if run["status"] not in ("active", "probe"):
            raise HTTPException(409, "队列已暂停")
        now = datetime.now(timezone.utc)
        if run["next_request_at"] and run["next_request_at"] > now:
            return {"allowed": False, "wait_seconds": max(1, (run["next_request_at"] - now).total_seconds())}
        day = now.astimezone(timezone(timedelta(hours=8))).date()
        conn.execute("INSERT INTO entry_request_budget(day) VALUES (%s) ON CONFLICT DO NOTHING", (day,))
        used = conn.execute("SELECT requests FROM entry_request_budget WHERE day=%s FOR UPDATE", (day,)).fetchone()["requests"]
        if used >= 500:
            return {"allowed": False, "wait_seconds": 60, "daily_exhausted": True}
        conn.execute("UPDATE entry_request_budget SET requests=requests+1 WHERE day=%s", (day,))
        conn.execute("UPDATE entry_collection SET next_request_at=%s WHERE id=true", (now + timedelta(seconds=random.uniform(20, 30)),))
    return {"allowed": True}


class Result(Lease):
    outcome: str = Field(pattern="^(success|empty|unknown|auth|verification|rate_limit|network|identity|invalid)$")
    pre_captured: bool
    title: str = Field(default="", max_length=500)
    url: str = Field(default="", max_length=2000)
    verified_biz: str = Field(default="", max_length=200)
    link_verified: bool = False
    publish_time: datetime | None = None
    request_count: int = Field(default=0, ge=0, le=500)


def public_article_url(raw):
    parsed = urlparse(raw)
    if parsed.scheme != "https" or parsed.netloc != "mp.weixin.qq.com" or not (parsed.path == "/s" or parsed.path.startswith("/s/")):
        raise HTTPException(422, "只接受公开 HTTPS 微信文章链接")
    query = parse_qs(parsed.query)
    keep = {key: query[key][0] for key in ("__biz", "mid", "idx", "sn") if query.get(key)}
    if parsed.path == "/s" and not all(keep.get(k) for k in ("__biz", "mid", "idx", "sn")):
        raise HTTPException(422, "长文章链接缺少必要身份参数")
    return urlunparse(("https", "mp.weixin.qq.com", parsed.path, "", urlencode(keep), ""))


@router.post("/jobs/{job_id}/result")
def result(job_id: int, data: Result, credential: str = Depends(require_collector)):
    with db() as conn:
        run = collector_run(conn, credential)
        job = lease_job(conn, job_id, data.execution_token)
        outcome, article_id = data.outcome, None
        account = conn.execute("SELECT * FROM official_accounts WHERE id=%s FOR UPDATE", (job["payload"]["target_id"],)).fetchone()
        if account["status"] != "approved":
            outcome = "invalid"
        if outcome == "success":
            url = public_article_url(data.url)
            biz = parse_qs(urlparse(url).query).get("__biz", [data.verified_biz])[0]
            if biz != account["source_id"] or data.verified_biz != account["source_id"] or not data.link_verified:
                outcome = "identity"
            elif not data.title.strip() or not data.publish_time or data.publish_time.tzinfo is None or data.publish_time > datetime.now(timezone.utc) + timedelta(minutes=5):
                raise HTTPException(422, "文章标题或发布时间无效")
            else:
                key = article_key(url)
                existing = conn.execute("SELECT id,account_id,status FROM articles WHERE source_key=%s", (key,)).fetchone()
                if existing and (existing["account_id"] != account["id"] or existing["status"] == "hidden"):
                    outcome = "identity"
                else:
                    row = conn.execute("""INSERT INTO articles(account_id,source_key,title,source_url,publish_time,author)
                        VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(source_key) DO NOTHING RETURNING id""",
                                       (account["id"], key, data.title.strip(), url, data.publish_time, account["name"])).fetchone()
                    if row:
                        article_id = row["id"]
                    else:
                        existing = conn.execute("SELECT id,account_id,status FROM articles WHERE source_key=%s", (key,)).fetchone()
                        if existing["account_id"] != account["id"] or existing["status"] == "hidden":
                            outcome = "identity"
                        else:
                            article_id = existing["id"]
        stored = {"outcome": outcome, "article_id": article_id, "pre_captured": data.pre_captured,
                  "request_count": data.request_count, "source": "wx_channel_v5.7.11"}
        state, delay = "done", 0
        if outcome in BLOCKERS:
            state = "blocked"
            conn.execute("UPDATE entry_collection SET status='paused',blocked=true,reason=%s,probe_job_id=%s WHERE id=true", (ERRORS[outcome], job_id))
        elif outcome in ("network", "invalid"):
            state = "queued" if outcome == "network" and job["attempts"] < 3 else "failed"
            delay = 300 if job["attempts"] == 1 else 1800
        if run["status"] == "probe" and outcome not in BLOCKERS:
            if outcome != "success":
                state = "blocked"
            conn.execute("UPDATE entry_collection SET status=%s,blocked=%s,reason=%s WHERE id=true",
                         ("active" if outcome == "success" else "paused", outcome != "success", "" if outcome == "success" else "复验未取得有效文章"))
        conn.execute("""UPDATE jobs SET status=%s,result=%s,error=%s,execution_token=NULL,
            run_after=now()+(%s*interval '1 second'),finished_at=now() WHERE id=%s""",
                     (state, Jsonb(stored), ERRORS.get(outcome), delay, job_id))
    return {"ok": True, "outcome": outcome}
