import secrets
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app import auth, entry_collection as entry, main
from app.content import article_key
from app.db import db


@pytest.fixture
def client(monkeypatch):
    with db() as conn:
        class Rollback(Exception):
            pass
        try:
            with conn.transaction():
                @contextmanager
                def test_db():
                    with conn.transaction():
                        yield conn
                monkeypatch.setattr(entry, "db", test_db)
                monkeypatch.setenv("ADMIN_TOKEN", "entry-test-admin-token-long-enough")
                auth.admin_failures.clear()
                for n in range(70):
                    biz = "test" + secrets.token_hex(12)
                    row = conn.execute("""INSERT INTO official_accounts(source_id,name,status,article_collection_enabled)
                        VALUES (%s,%s,'approved',false) RETURNING id""", (biz, f"样本{n}")).fetchone()
                    if n < 5:
                        url = f"https://mp.weixin.qq.com/s?__biz={biz}&mid=100&idx=1&sn=abc"
                        conn.execute("INSERT INTO articles(account_id,source_key,title,source_url) VALUES (%s,%s,'对照文章',%s)", (row["id"], article_key(url), url))
                yield TestClient(main.app), conn
                raise Rollback()
        except Rollback:
            pass
        finally:
            auth.admin_failures.clear()


ADMIN = {"Authorization": "Bearer entry-test-admin-token-long-enough"}


def setup(client):
    api, conn = client
    reply = api.post("/api/admin/entry-collection/prepare", headers=ADMIN)
    assert reply.status_code == 200, reply.text
    token = api.post("/api/admin/entry-collection/token", headers=ADMIN).json()["token"]
    headers = {"Authorization": "Bearer " + token}
    assert api.post("/api/admin/entry-collection/control", headers=ADMIN, json={"action": "resume"}).status_code == 200
    return api, conn, headers


def claim(api, headers):
    return api.post("/api/entry-collector/claim", headers=headers).json()["job"]


def result(api, headers, job, outcome="success", **changes):
    payload = {"execution_token": job["execution_token"], "outcome": outcome,
               "pre_captured": False, "title": "真实文章", "link_verified": True,
               "publish_time": "2026-01-01T00:00:00+00:00",
               "verified_biz": job["source_id"],
               "url": f"https://mp.weixin.qq.com/s?__biz={job['source_id']}&mid=123&idx=1&sn=abc"}
    payload.update(changes)
    return api.post(f"/api/entry-collector/jobs/{job['id']}/result", headers=headers, json=payload)


def test_auth_rotation_revocation_and_no_hash_in_status(client):
    api, _, headers = setup(client)
    assert api.post("/api/entry-collector/claim").status_code == 401
    assert api.post("/api/entry-collector/claim", headers=ADMIN).status_code == 401
    job = claim(api, headers)
    state = api.get("/api/admin/entry-collection", headers=ADMIN)
    assert "token_hash" not in state.text and headers["Authorization"] not in state.text
    api.post("/api/admin/entry-collection/token", headers=ADMIN)
    assert result(api, headers, job).status_code == 401
    api.delete("/api/admin/entry-collection/token", headers=ADMIN)
    assert api.post("/api/entry-collector/claim", headers=headers).status_code == 401


def test_snapshot_dedup_single_concurrency_and_expired_lease(client):
    api, conn, headers = setup(client)
    assert api.post("/api/admin/entry-collection/prepare", headers=ADMIN).status_code == 409
    assert conn.execute("SELECT count(*) n FROM jobs WHERE kind='account_entry'").fetchone()["n"] == 70
    job = claim(api, headers)
    assert claim(api, headers) is None
    conn.execute("UPDATE jobs SET heartbeat_at=now()-interval '3 minutes' WHERE id=%s", (job["id"],))
    assert result(api, headers, job).status_code == 409
    replacement = claim(api, headers)
    assert replacement["id"] == job["id"] and replacement["execution_token"] != job["execution_token"]
    assert result(api, headers, job).status_code == 409


def test_metadata_only_idempotency_and_unchanged_directory_settings(client):
    api, conn, headers = setup(client)
    job = claim(api, headers)
    before = conn.execute("SELECT count(*) n FROM jobs WHERE kind<>'account_entry'").fetchone()["n"]
    assert result(api, headers, job, url=f"https://mp.weixin.qq.com/s?__biz={job['source_id']}&mid=123&idx=1&sn=abc&key=secret&pass_ticket=secret").status_code == 200
    assert result(api, headers, job).status_code == 409
    article = conn.execute("SELECT * FROM articles WHERE account_id=%s AND title='真实文章'", (job["payload"]["target_id"],)).fetchone()
    assert article["status"] == "metadata" and not article["content_text"] and not article["content_html"]
    assert "secret" not in article["source_url"] and article["publish_time"].year == 2026
    assert conn.execute("SELECT article_collection_enabled FROM official_accounts WHERE id=%s", (job["payload"]["target_id"],)).fetchone()["article_collection_enabled"] is False
    assert conn.execute("SELECT count(*) n FROM jobs WHERE kind<>'account_entry'").fetchone()["n"] == before


def test_missing_actual_publication_time_cannot_be_imported(client):
    api, conn, headers = setup(client)
    job = claim(api, headers)
    before = conn.execute("SELECT count(*) n FROM articles").fetchone()["n"]
    assert result(api, headers, job, publish_time=None).status_code == 422
    assert conn.execute("SELECT count(*) n FROM articles").fetchone()["n"] == before


@pytest.mark.parametrize("outcome", ["auth", "verification", "rate_limit", "identity"])
def test_source_blockers_pause_and_require_successful_probe(client, outcome):
    api, _, headers = setup(client)
    job = claim(api, headers)
    assert result(api, headers, job, outcome).json()["outcome"] == outcome
    assert claim(api, headers) is None
    assert api.post("/api/admin/entry-collection/control", headers=ADMIN, json={"action": "resume"}).status_code == 200
    probe = claim(api, headers)
    assert probe["id"] == job["id"] and claim(api, headers) is None
    result(api, headers, probe)
    assert claim(api, headers) is not None


@pytest.mark.parametrize("outcome", ["network", "invalid", "empty", "unknown"])
def test_failed_probe_can_be_retried_and_resumed_without_deadlock(client, outcome):
    api, _, headers = setup(client)
    job = claim(api, headers)
    result(api, headers, job, "auth")
    assert api.post(f"/api/admin/entry-collection/jobs/{job['id']}/retry", headers=ADMIN).status_code == 200
    assert api.post("/api/admin/entry-collection/control", headers=ADMIN, json={"action": "resume"}).status_code == 200
    probe = claim(api, headers)
    result(api, headers, probe, outcome)
    assert claim(api, headers) is None
    assert api.post("/api/admin/entry-collection/control", headers=ADMIN, json={"action": "resume"}).status_code == 200
    probe = claim(api, headers)
    assert probe["id"] == job["id"]
    result(api, headers, probe)
    assert claim(api, headers) is not None


def test_mismatched_author_and_conflicting_article_owner_are_not_imported(client):
    api, conn, headers = setup(client)
    job = claim(api, headers)
    before = conn.execute("SELECT count(*) n FROM articles").fetchone()["n"]
    assert result(api, headers, job, verified_biz="wrong-author").json()["outcome"] == "identity"
    assert conn.execute("SELECT count(*) n FROM articles").fetchone()["n"] == before
    api.post("/api/admin/entry-collection/control", headers=ADMIN, json={"action": "resume"})
    job = claim(api, headers)
    other = conn.execute("SELECT id FROM official_accounts WHERE id<>%s LIMIT 1", (job["payload"]["target_id"],)).fetchone()["id"]
    url = f"https://mp.weixin.qq.com/s?__biz={job['source_id']}&mid=123&idx=1&sn=abc"
    conn.execute("INSERT INTO articles(account_id,source_key,title,source_url) VALUES (%s,%s,'不允许覆盖',%s)", (other, article_key(url), url))
    assert result(api, headers, job).json()["outcome"] == "identity"
    assert conn.execute("SELECT account_id FROM articles WHERE source_key=%s", (article_key(url),)).fetchone()["account_id"] == other


def test_network_retry_three_attempts_with_backoff(client):
    api, conn, headers = setup(client)
    for n, expected in [(1, "queued"), (2, "queued"), (3, "failed")]:
        job = claim(api, headers)
        result(api, headers, job, "network")
        state = conn.execute("SELECT status,run_after>now() later FROM jobs WHERE id=%s", (job["id"],)).fetchone()
        assert state["status"] == expected and state["later"]
        conn.execute("UPDATE jobs SET run_after=now() WHERE id=%s", (job["id"],))


def test_request_budget_interval_and_persistent_daily_cap(client):
    api, conn, headers = setup(client)
    job = claim(api, headers)
    path = f"/api/entry-collector/jobs/{job['id']}/request-permit"
    lease = {"execution_token": job["execution_token"]}
    assert api.post(path, headers=headers, json=lease).json()["allowed"]
    wait = api.post(path, headers=headers, json=lease).json()
    assert not wait["allowed"] and 19 <= wait["wait_seconds"] <= 30
    conn.execute("UPDATE entry_collection SET next_request_at=NULL")
    conn.execute("UPDATE entry_request_budget SET requests=500")
    exhausted = api.post(path, headers=headers, json=lease).json()
    assert exhausted["daily_exhausted"] and not exhausted["allowed"]
    api.post("/api/admin/entry-collection/control", headers=ADMIN, json={"action": "pause"})
    assert api.post(path, headers=headers, json=lease).status_code == 409


def test_validation_gate_rejects_manual_capture_and_allows_only_ordered_canary(client):
    api, conn, headers = setup(client)
    for _ in range(20):
        job = claim(api, headers)
        assert result(api, headers, job, pre_captured=True).status_code == 200
    assert api.post("/api/admin/entry-collection/control", headers=ADMIN, json={"action": "canary"}).status_code == 409
    conn.execute("UPDATE jobs SET result=jsonb_set(result,'{pre_captured}','false') WHERE kind='account_entry' AND payload->>'group'='unknown' AND payload->>'phase'='sample'")
    assert api.post("/api/admin/entry-collection/control", headers=ADMIN, json={"action": "full"}).status_code == 409
    assert api.post("/api/admin/entry-collection/control", headers=ADMIN, json={"action": "canary"}).status_code == 200
    assert len(entry.phase_jobs(conn, "canary")) == 50
    assert api.post("/api/admin/entry-collection/control", headers=ADMIN, json={"action": "canary"}).status_code == 409
    assert api.post("/api/admin/entry-collection/control", headers=ADMIN, json={"action": "full"}).status_code == 409
