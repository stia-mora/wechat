import json
import secrets

import pytest

from test_core import client as client, fixture_account
from app import bulk_discover, crawler, worker, weread_crawler
from app.discovery_queries import queries
from app.sources.weread import SourceError


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
    assert row["status"] == "pending" and not row["article_collection_enabled"]
    assert conn.execute("SELECT article_collection_enabled FROM official_accounts WHERE id=%s", (existing,)).fetchone()["article_collection_enabled"]
    assert not conn.execute("SELECT 1 FROM source_subscriptions WHERE account_id=%s", (row["id"],)).fetchone()
    assert conn.execute("SELECT count(*) n FROM articles").fetchone()["n"] == before
    worker.schedule()
    assert not conn.execute("SELECT 1 FROM jobs WHERE kind='sync' AND (payload->>'target_id')::bigint=%s", (row["id"],)).fetchone()
    with pytest.raises(SourceError, match="不可采集"):
        weread_crawler.collect({"_job_id": 0, "target_id": row["id"]})


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
