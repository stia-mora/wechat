import base64
import secrets

import httpx
import pytest
from cryptography.fernet import Fernet
from test_core import client as client  # noqa: PLC0414

from app import account_pool as pool
from app import weread_crawler
from app.credentials import decrypt, encrypt
from app.repository import enqueue
from app.sources.weread import SourceError, WeReadAdapter, article_url, book_id


def target(conn):
    source = base64.b64encode(str(secrets.randbelow(10**14)).encode()).decode()
    return conn.execute(
        "INSERT INTO official_accounts(source_id,name,status) VALUES (%s,'隔离测试公众号','approved') RETURNING id",
        (source,),
    ).fetchone()["id"]


def source_account(conn, monkeypatch, max_tasks=1, max_subscriptions=2):
    monkeypatch.setenv("SOURCE_CREDENTIAL_KEY", Fernet.generate_key().decode())
    return conn.execute(
        """INSERT INTO source_accounts(name,health,credentials,max_tasks,max_subscriptions)
        VALUES ('隔离测试微信读书','healthy',%s,%s,%s) RETURNING id""",
        (encrypt({"cookies": {"wr_vid": "test", "wr_skey": "test"}}), max_tasks, max_subscriptions),
    ).fetchone()["id"]


def job(conn, account_id):
    jid = enqueue(conn, "sync", {"target_id": account_id})
    conn.execute("UPDATE jobs SET status='running',started_at=now(),attempts=1 WHERE id=%s", (jid,))
    return jid


def test_adapter_identity_and_group_pagination():
    assert book_id("MTIz") == "MP_WXS_123"
    assert article_url("MP_WXS_123_a_b~c", "MP_WXS_123").endswith("/a_b~c")
    with pytest.raises(SourceError):
        book_id("bad!")

    def remote(request):
        assert request.url.params["offset"] == "10"
        return httpx.Response(
            200,
            json={
                "reviews": [
                    {
                        "subReviews": [
                            {
                                "review": {
                                    "reviewId": "MP_WXS_123_a_b",
                                    "mpInfo": {"title": "A", "time": 1700000000},
                                }
                            },
                            {"review": {"reviewId": "MP_WXS_123_c", "mpInfo": {"title": "B"}}},
                        ]
                    }
                ]
            },
        )

    adapter = WeReadAdapter(transport=httpx.MockTransport(remote))
    data = adapter.articles("MP_WXS_123", 10)
    assert len(data["items"]) == 2 and data["next_offset"] == 11
    assert data["items"][1]["publish_time"] is None
    adapter.close()


@pytest.mark.parametrize("code,category", [(-2012, "auth"), (-2041, "ambiguous"), (-2010, "auth")])
def test_adapter_business_errors(code, category):
    adapter = WeReadAdapter(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"errCode": code, "errMsg": "sensitive response must not be copied"}
            )
        )
    )
    with pytest.raises(SourceError) as exc:
        adapter.shelf()
    assert exc.value.category == category and "sensitive" not in str(exc.value)
    adapter.close()


def test_pool_balances_reserves_capacity_and_migrates(client, monkeypatch):
    _, conn = client
    # Isolate from any real accounts already configured on this machine.
    conn.execute("UPDATE source_accounts SET enabled=false")
    s1 = source_account(conn, monkeypatch)
    s2 = source_account(conn, monkeypatch)
    a1, a2, a3 = [target(conn) for _ in range(3)]
    j1, j2, j3 = job(conn, a1), job(conn, a2), job(conn, a3)
    l1 = pool.acquire(j1, a1)
    l2 = pool.acquire(j2, a2)
    assert {l1["account"]["id"], l2["account"]["id"]} == {s1, s2}
    with pytest.raises(pool.PoolWaiting):
        pool.acquire(j3, a3)
    pool.release(l1, SourceError(-2012, "已失效", "auth"))
    conn.execute("UPDATE jobs SET status='queued' WHERE id=%s", (j1,))
    pool.release(l2)
    conn.execute("UPDATE jobs SET status='done' WHERE id=%s", (j2,))
    conn.execute("UPDATE jobs SET status='running' WHERE id=%s", (j1,))
    migrated = pool.acquire(j1, a1)
    assert migrated["account"]["id"] == l2["account"]["id"]
    assert (
        conn.execute(
            "SELECT health FROM source_accounts WHERE id=%s", (l1["account"]["id"],)
        ).fetchone()["health"]
        == "expired"
    )
    assert (
        conn.execute("SELECT count(*) n FROM crawl_attempts WHERE job_id=%s", (j1,)).fetchone()["n"]
        == 2
    )


def test_pool_capacity_and_crash_lease_recovery(client, monkeypatch):
    _, conn = client
    conn.execute("UPDATE source_accounts SET enabled=false")
    sid = source_account(conn, monkeypatch, max_subscriptions=1)
    a1, a2 = target(conn), target(conn)
    conn.execute(
        "INSERT INTO source_memberships(source_account_id,account_id) VALUES (%s,%s)", (sid, a1)
    )
    j2 = job(conn, a2)
    with pytest.raises(pool.PoolWaiting):
        pool.acquire(j2, a2)
    j1 = job(conn, a1)
    lease = pool.acquire(j1, a1)
    conn.execute("UPDATE jobs SET heartbeat_at=now()-interval '6 minutes' WHERE id=%s", (j1,))
    pool.recover(conn)
    assert conn.execute("SELECT status,lease_token FROM jobs WHERE id=%s", (j1,)).fetchone() == {
        "status": "queued",
        "lease_token": None,
    }
    with pytest.raises(pool.PoolWaiting):
        pool.heartbeat(lease)
    assert (
        conn.execute("SELECT status FROM crawl_attempts WHERE job_id=%s", (j1,)).fetchone()[
            "status"
        ]
        == "interrupted"
    )


def test_crawl_resumes_after_expiry_and_repairs_missing_body(client, monkeypatch):
    _, conn = client
    conn.execute("UPDATE source_accounts SET enabled=false")
    source_account(conn, monkeypatch)
    source_account(conn, monkeypatch)
    account = target(conn)
    jid = job(conn, account)
    calls = []
    fail = [True]

    class Adapter:
        def __init__(self, *a, **kw):
            pass

        def verify_or_renew(self):
            return []

        def ensure_subscription(self, book):
            pass

        def articles(self, book, offset):
            calls.append(offset)
            return {
                "items": [
                    {
                        "external_id": book + "_one",
                        "title": "测试正文",
                        "link": "https://mp.weixin.qq.com/s/" + str(account),
                        "publish_time": 1780272000,
                    }
                ]
                if offset == 0
                else [],
                "next_offset": offset + 1,
                "exhausted": offset > 0,
            }

        def content(self, rid):
            if fail[0]:
                fail[0] = False
                raise SourceError(-2012, "过期", "auth")
            return {"content": "<p>微信读书完整正文</p>"}

        def credentials(self):
            return {"cookies": {"wr_vid": "test", "wr_skey": "test"}}

        def close(self):
            pass

    monkeypatch.setattr(weread_crawler, "WeReadAdapter", Adapter)
    # Credential correctness is covered separately; this test isolates task behavior.
    monkeypatch.setattr(pool, "credentials", lambda lease: {})
    payload = {"target_id": account, "_job_id": jid, "pages": 1, "parse_limit": 3, "backfill": True}
    with pytest.raises(SourceError):
        weread_crawler.collect(payload)
    assert (
        conn.execute(
            "SELECT history_offset FROM source_subscriptions WHERE account_id=%s", (account,)
        ).fetchone()["history_offset"]
        == 1
    )
    # Verified/renewed credentials survive a later body failure.
    saved = conn.execute(
        "SELECT credentials FROM source_accounts WHERE id=(SELECT source_account_id FROM jobs WHERE id=%s)",
        (jid,),
    ).fetchone()
    assert decrypt(saved["credentials"])["cookies"]["wr_skey"] == "test"
    result = weread_crawler.collect(payload)
    assert result["readable_articles"] == 1 and result["history_complete"]
    assert calls == [0, 0, 1]
    assert (
        conn.execute("SELECT count(*) n FROM articles WHERE account_id=%s", (account,)).fetchone()[
            "n"
        ]
        == 1
    )
    assert (
        conn.execute(
            "SELECT count(*) n FROM jobs WHERE kind='embedding' AND (payload->>'target_id')::bigint IN(SELECT id FROM articles WHERE account_id=%s)",
            (account,),
        ).fetchone()["n"]
        == 1
    )


def test_cover_is_explicit_degradation_not_history_success(client, monkeypatch):
    _, conn = client
    conn.execute("UPDATE source_accounts SET enabled=false")
    source_account(conn, monkeypatch)
    account = target(conn)
    jid = job(conn, account)

    class Adapter:
        def __init__(self, *a, **kw):
            pass

        def verify_or_renew(self):
            return []

        def ensure_subscription(self, book):
            pass

        def shelf(self):
            return []

        def articles(self, *a):
            raise SourceError(-2041, "列表不支持", "ambiguous")

        def latest(self, book):
            return {
                "external_id": book + "_latest",
                "title": "最新一篇",
                "link": "https://mp.weixin.qq.com/s/" + str(account),
                "publish_time": None,
            }

        def content(self, rid):
            pytest.fail('Unknown publication date must not fetch a body')

        def credentials(self):
            return {"cookies": {}}

        def close(self):
            pass

    monkeypatch.setattr(weread_crawler, "WeReadAdapter", Adapter)
    monkeypatch.setattr(pool, "credentials", lambda lease: {})
    result = weread_crawler.collect(
        {"target_id": account, "_job_id": jid, "backfill": True, "pages": 2}
    )
    assert result["capability"] == "latest_only" and not result["history_complete"]
    row = conn.execute(
        "SELECT publish_time FROM articles WHERE account_id=%s", (account,)
    ).fetchone()
    assert row["publish_time"] is None
    assert (
        conn.execute(
            "SELECT history_offset FROM source_subscriptions WHERE account_id=%s", (account,)
        ).fetchone()["history_offset"]
        == 0
    )


def test_pool_admin_never_returns_credentials(client, monkeypatch):
    api, conn = client
    sid = source_account(conn, monkeypatch)
    assert api.get("/api/admin/source-accounts").status_code == 403
    response = api.get(
        "/api/admin/source-accounts",
        headers={"Authorization": "Bearer test-only-admin-token-long-enough"},
    )
    assert response.status_code == 200 and all("credentials" not in row for row in response.json())
    stored = conn.execute("SELECT credentials FROM source_accounts WHERE id=%s", (sid,)).fetchone()[
        "credentials"
    ]
    assert "wr_skey" not in stored and stored not in response.text


def test_discovery_uses_local_database_without_external_search(client, monkeypatch):
    api, conn = client
    target(conn)
    monkeypatch.setattr("app.main.current_user", lambda request: {"id": 1})
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: pytest.fail("must not scrape during search"))
    response = api.post("/api/discovery-requests", json={"query": "隔离测试公众号"})
    assert response.json()["status"] == "existing"
    query = "找不到的隔离查询" + secrets.token_hex(4)
    first = api.post("/api/discovery-requests", json={"query": query}).json()
    second = api.post("/api/discovery-requests", json={"query": query}).json()
    assert first["job_id"] == second["job_id"] and first["status"] == "queued"


def test_stale_execution_and_login_maintenance_cannot_acquire(client, monkeypatch):
    _, conn = client
    conn.execute("UPDATE source_accounts SET enabled=false")
    sid = source_account(conn, monkeypatch)
    account = target(conn)
    jid = job(conn, account)
    conn.execute("UPDATE jobs SET execution_token='new-worker' WHERE id=%s", (jid,))
    with pytest.raises(pool.PoolWaiting):
        pool.acquire(jid, account, "old-worker")
    from app.source_admin import account_row, end_maintenance

    account_row(sid)
    with pytest.raises(pool.PoolWaiting):
        pool.acquire(jid, account, "new-worker")
    end_maintenance(sid)
    assert pool.acquire(jid, account, "new-worker")["account"]["id"] == sid


def test_stable_origin_and_all_postgres_exports(client, monkeypatch):
    import io
    import json
    import zipfile

    from app.exports import export_account
    from app.normalizer import save_article

    _, conn = client
    account = target(conn)
    item = {
        "external_id": f"unique_{account}",
        "title": "隔离导出",
        "link": f"https://mp.weixin.qq.com/s/first{account}",
        "content": "<p>测试正文</p>",
    }
    first = save_article(account, "MP_WXS_test", item)
    assert (
        save_article(
            account, "MP_WXS_test", {**item, "link": f"https://mp.weixin.qq.com/s/changed{account}"}
        )
        == first
    )
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: pytest.fail("exports must stay local"))
    for format in ("zip", "html", "json", "xlsx", "docx", "pdf", "epub"):
        body = export_account(account, format).body
        assert len(body) > 20
        if format in ("zip", "xlsx", "docx", "epub"):
            assert zipfile.ZipFile(io.BytesIO(body)).testzip() is None
        elif format == "json":
            assert json.loads(body)[0]["title"] == item["title"]
        elif format == "pdf":
            assert body.startswith(b"%PDF")
        else:
            assert "测试正文" in body.decode()
