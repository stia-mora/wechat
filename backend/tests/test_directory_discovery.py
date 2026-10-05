import json
import secrets

import pytest

from test_core import client as client, fixture_account
from app import bulk_discover, crawler, repair_featured_categories, worker, weread_crawler
from app.discovery_queries import queries
from app.sources.weread import SourceError
from app.repository import wechat_profile_url
from psycopg.types.json import Jsonb


def test_directory_search_deduplicates_and_does_not_enable_articles(client, monkeypatch):
    _, conn = client
    existing = fixture_account(conn)
    existing_source = conn.execute("SELECT source_id FROM official_accounts WHERE id=%s", (existing,)).fetchone()["source_id"]
    new_source = secrets.token_hex(16)
    source = crawler.SourceClient()
    monkeypatch.setattr(source, "bridge", lambda *args, **kwargs: {
        "list": [{"fakeid": new_source, "nickname": "目录测试账号"},
                 {"fakeid": existing_source, "nickname": "现有测试账号"},
                 {"nickname": "无真实标识不得入库"}],
        "has_more": True, "next_begin": 10,
    })
    before = conn.execute("SELECT count(*) n FROM articles").fetchone()["n"]
    payload = {"query": "目录测试", "begin": 5, "directory_only": True}
    first = source.discover(payload)
    second = source.discover(payload)
    assert first["next_begin"] == 10 and first["has_more"]
    assert first["accounts"] == second["accounts"]
    row = conn.execute("SELECT * FROM official_accounts WHERE source_id=%s", (new_source,)).fetchone()
    assert row["status"] == "approved" and not row["article_collection_enabled"]
    assert conn.execute("SELECT article_collection_enabled FROM official_accounts WHERE id=%s", (existing,)).fetchone()["article_collection_enabled"]
    assert not conn.execute("SELECT 1 FROM source_subscriptions WHERE account_id=%s", (row["id"],)).fetchone()
    assert conn.execute("SELECT count(*) n FROM articles").fetchone()["n"] == before
    worker.schedule()
    assert not conn.execute("SELECT 1 FROM jobs WHERE kind='sync' AND (payload->>'target_id')::bigint=%s", (row["id"],)).fetchone()
    with pytest.raises(SourceError, match="不可采集"):
        weread_crawler.collect({"_job_id": 0, "target_id": row["id"]})


def test_directory_discovery_preserves_existing_visibility_and_collection(client, monkeypatch):
    _, conn = client
    hidden = fixture_account(conn, status="hidden")
    pending = fixture_account(conn, status="pending")
    conn.execute("UPDATE official_accounts SET article_collection_enabled=false WHERE id=%s", (hidden,))
    rows = conn.execute("SELECT source_id FROM official_accounts WHERE id IN (%s,%s)", (hidden, pending)).fetchall()
    source = crawler.SourceClient()
    monkeypatch.setattr(source, "bridge", lambda *args, **kwargs: {
        "list": [{"fakeid": row["source_id"], "nickname": "现有账号"} for row in rows]
    })
    source.discover({"query": "现有账号", "directory_only": True})
    assert conn.execute("SELECT status,article_collection_enabled FROM official_accounts WHERE id=%s", (hidden,)).fetchone() == {
        "status": "hidden", "article_collection_enabled": False
    }
    assert conn.execute("SELECT status,article_collection_enabled FROM official_accounts WHERE id=%s", (pending,)).fetchone() == {
        "status": "pending", "article_collection_enabled": True
    }


def test_public_directory_is_browsable_and_has_wechat_links_without_articles(client):
    api, conn = client
    account = fixture_account(conn)
    hidden = fixture_account(conn, status="hidden")
    source_id = "MzA3MzI4MjgzMw=="
    conn.execute("UPDATE official_accounts SET source_id=%s,article_collection_enabled=false,created_at=now()+interval '1 day' WHERE id=%s", (source_id, account))
    conn.execute("UPDATE official_accounts SET created_at=now()+interval '2 days' WHERE id=%s", (hidden,))
    page = api.get("/api/accounts?sort=added&limit=1").json()
    assert page["items"][0]["id"] == account
    assert page["items"][0]["source_url"] == wechat_profile_url(source_id)
    detail = api.get(f"/api/accounts/{account}").json()
    assert detail["source_url"] == wechat_profile_url(source_id)
    assert detail["article_count"] == 0 and not detail["article_collection_enabled"]
    assert api.get(f"/api/accounts/{hidden}").status_code == 404


def test_wechat_profile_links_use_only_real_numeric_identities():
    assert wechat_profile_url("MzA3MzI4MjgzMw==") == (
        "https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz=MzA3MzI4MjgzMw%3D%3D#wechat_redirect"
    )
    for source_id in ("", "test-account", "YWJj", "javascript:alert(1)"):
        assert wechat_profile_url(source_id) == ""


def test_featured_accounts_use_curated_identities_and_preserve_hidden_status(client):
    api, conn = client
    first = fixture_account(conn)
    second = fixture_account(conn)
    hidden = fixture_account(conn, status="hidden")
    uncategorized = fixture_account(conn)
    conn.execute("UPDATE official_accounts SET primary_category_id=(SELECT id FROM categories WHERE slug='科技') WHERE id=ANY(%s)", ([first,second,hidden],))
    rows = conn.execute("SELECT id,source_id FROM official_accounts WHERE id=ANY(%s)", ([first,second,hidden,uncategorized],)).fetchall()
    identities = {row['id']: row['source_id'] for row in rows}
    other_platform = fixture_account(conn)
    conn.execute("UPDATE official_accounts SET platform='other',source_id=%s WHERE id=%s", (identities[second],other_platform))
    conn.execute("INSERT INTO settings(key,value) VALUES ('homepage_accounts',%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", (Jsonb([identities[second],identities[hidden],identities[uncategorized],identities[first]]),))
    page = api.get('/api/accounts?sort=featured&limit=1').json()
    assert page['total'] == 2 and [row['id'] for row in page['items']] == [second]
    assert api.get('/api/accounts?sort=featured&page=2&limit=1').json()['items'][0]['id'] == first
    assert api.get('/api/accounts').json()['total'] > page['total']


def test_featured_category_repair_preserves_existing_categories_and_is_idempotent(client, monkeypatch):
    _, conn = client
    missing, categorized, unlisted = [fixture_account(conn) for _ in range(3)]
    existing = conn.execute("SELECT id FROM categories WHERE slug='科技'").fetchone()['id']
    conn.execute("UPDATE official_accounts SET primary_category_id=%s WHERE id=%s", (existing,categorized))
    rows = conn.execute("SELECT id,source_id FROM official_accounts WHERE id=ANY(%s)", ([missing,categorized,unlisted],)).fetchall()
    identities = {row['id']: row['source_id'] for row in rows}
    monkeypatch.setattr(repair_featured_categories, 'FEATURED_CATEGORIES', {source_id: '媒体与时政' for source_id in identities.values()})
    conn.execute("INSERT INTO settings(key,value) VALUES ('homepage_accounts',%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", (Jsonb([identities[missing],identities[categorized]]),))
    changed = repair_featured_categories.repair_featured_categories(conn)
    assert [row['id'] for row in changed] == [missing]
    assert changed[0]['category'] == '媒体与时政'
    assert '媒体与时政' in conn.execute("SELECT body FROM search_documents WHERE kind='account' AND target_id=%s", (missing,)).fetchone()['body']
    assert conn.execute("SELECT primary_category_id FROM official_accounts WHERE id=%s", (categorized,)).fetchone()['primary_category_id'] == existing
    assert conn.execute("SELECT primary_category_id FROM official_accounts WHERE id=%s", (unlisted,)).fetchone()['primary_category_id'] is None
    assert repair_featured_categories.repair_featured_categories(conn) == []


def test_wechat_qr_is_available_only_for_public_wechat_identities(client):
    api, conn = client
    account = fixture_account(conn)
    conn.execute("UPDATE official_accounts SET source_id='MzA3MzI4MjgzMw==',article_collection_enabled=false WHERE id=%s", (account,))
    response = api.get(f'/api/accounts/{account}/wechat-qr')
    assert response.status_code == 200
    assert response.headers['content-type'] == 'image/png'
    assert response.content.startswith(b'\x89PNG\r\n\x1a\n')
    conn.execute("UPDATE official_accounts SET status='hidden' WHERE id=%s", (account,))
    assert api.get(f'/api/accounts/{account}/wechat-qr').status_code == 404
    conn.execute("UPDATE official_accounts SET status='approved',source_id='not-a-wechat-biz' WHERE id=%s", (account,))
    assert api.get(f'/api/accounts/{account}/wechat-qr').status_code == 404
    assert api.get('/api/accounts/987654321/wechat-qr').status_code == 404


def test_directory_only_account_blocks_manual_body_requests(client, monkeypatch):
    _, conn = client
    account = fixture_account(conn)
    conn.execute("UPDATE official_accounts SET article_collection_enabled=false WHERE id=%s", (account,))
    article = conn.execute(
        "INSERT INTO articles(account_id,source_key,title,source_url,publish_time) "
        "VALUES (%s,%s,'目录文章测试','https://mp.weixin.qq.com/s/test',now()) RETURNING id",
        (account, secrets.token_hex(16)),
    ).fetchone()["id"]
    source = crawler.SourceClient()
    monkeypatch.setattr(source, "bridge", lambda *args, **kwargs: pytest.fail("目录账号请求了文章"))
    with pytest.raises(crawler.SourceBlocked, match="未启用文章采集"):
        source.parse({"target_id": article})


def test_discovery_terms_are_unique_and_cover_geographic_topics():
    terms = queries()
    assert len(terms) == len(set(terms)) and len(terms) > 10000
    assert "人工智能" in terms and "杭州科技" in terms and "南宁教育" in terms


def test_bulk_target_counts_real_rows_and_resumes_from_saved_progress(client, monkeypatch, tmp_path):
    _, conn = client
    target = conn.execute("SELECT count(*) n FROM official_accounts WHERE platform='wechat'").fetchone()["n"] + 1
    source = crawler.SourceClient()
    calls = []

    def search(*args, **kwargs):
        calls.append(kwargs)
        return {"list": [{"fakeid": secrets.token_hex(16), "nickname": "续跑测试账号"}],
                "next_begin": 1, "has_more": False}

    monkeypatch.setattr(source, "bridge", search)
    monkeypatch.setattr(bulk_discover, "initialize", lambda: None)
    monkeypatch.setattr(bulk_discover, "db", crawler.db)
    monkeypatch.setattr(bulk_discover, "SourceClient", lambda: source)
    monkeypatch.setattr(bulk_discover, "wait_for_login", lambda source: True)
    path = tmp_path / "progress.json"
    first = bulk_discover.collect(target, path)
    second = bulk_discover.collect(target, path)
    assert first["status"] == second["status"] == "complete"
    assert len(calls) == 1 and first["pages"] == 1
    assert json.loads(path.read_text(encoding="utf-8"))["total"] == target


def test_expired_login_saves_blocked_progress_without_searching(client, monkeypatch, tmp_path):
    _, conn = client
    target = conn.execute("SELECT count(*) n FROM official_accounts WHERE platform='wechat'").fetchone()["n"] + 1
    monkeypatch.setattr(bulk_discover, "initialize", lambda: None)
    monkeypatch.setattr(bulk_discover, "db", crawler.db)
    monkeypatch.setattr(bulk_discover, "wait_for_login", lambda source: False)
    path = tmp_path / "progress.json"
    with pytest.raises(crawler.SourceBlocked, match="登录已过期"):
        bulk_discover.collect(target, path)
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["status"] == "waiting_login" and state["pages"] == 0
    assert state["total"] == target - 1
