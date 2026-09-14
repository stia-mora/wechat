import secrets
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient

from app import admin, ai, auth, crawler, main, pipeline
from app.content import article_key, clean_content
from app.db import db
from app.repository import enqueue, index_account, index_article


@pytest.fixture
def client(monkeypatch):
    # All fixture records and user actions roll back, never contributing to real collection counts.
    with db() as conn:

        class Rollback(Exception):
            pass

        try:
            with conn.transaction():

                @contextmanager
                def test_db():
                    with conn.transaction():
                        yield conn

                for module in (main, auth, admin, crawler, ai, pipeline):
                    monkeypatch.setattr(module, "db", test_db)
                monkeypatch.setenv("ADMIN_TOKEN", "test-only-admin-token-long-enough")
                auth.attempts.clear()
                yield TestClient(main.app), conn
                raise Rollback()
        except Rollback:
            pass


def fixture_account(conn, status="approved"):
    row = conn.execute(
        "INSERT INTO official_accounts(name,source_id,status) VALUES (%s,%s,%s) RETURNING id",
        ("测试人工智能信息源", secrets.token_hex(16), status),
    ).fetchone()
    index_account(conn, row["id"])
    return row["id"]


def test_article_identity_ignores_tracking():
    a = "https://mp.weixin.qq.com/s?__biz=one&mid=123&idx=1&sn=abc&scene=2"
    b = "https://mp.weixin.qq.com/s?idx=1&mid=123&__biz=one&scene=9"
    assert article_key(a) == article_key(b)
    assert article_key(a) != article_key(b.replace("idx=1", "idx=2"))
    with pytest.raises(ValueError):
        article_key("http://127.0.0.1/private")


def test_wechat_frequency_control_blocks_further_crawling():
    source = crawler.SourceClient()
    source.client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"success": False, "error": "ret=200013, msg=freq control"}
            )
        ),
        base_url="http://test-source",
    )
    with pytest.raises(crawler.SourceBlocked):
        source.request("GET", "/api/public/articles")


def test_reader_removes_active_content_and_untrusted_images():
    html, text = clean_content(
        '<script>alert(1)</script><p onclick="x()">正文</p><a href="javascript:alert(1)">链接</a><img src="http://127.0.0.1/a"><img data-src="https://mmbiz.qpic.cn/a" onerror="x()">'
    )
    assert (
        "<script" not in html
        and "onclick" not in html
        and "javascript:" not in html
        and "onerror" not in html
    )
    assert "127.0.0.1" not in html and "https://mmbiz.qpic.cn/a" in html and "正文" in text


def test_database_dedup_and_queue_idempotency(client):
    _, conn = client
    first = enqueue(conn, "sync", {"target_id": 987654321})
    second = enqueue(conn, "sync", {"target_id": 987654321})
    assert first and second is None
    account = fixture_account(conn)
    key = secrets.token_hex(16)
    for _ in range(2):
        conn.execute(
            "INSERT INTO articles(account_id,source_key,title,source_url) VALUES (%s,%s,%s,%s) ON CONFLICT(source_key) DO NOTHING",
            (account, key, "测试文章", "https://mp.weixin.qq.com/s/test"),
        )
    assert (
        conn.execute("SELECT count(*) AS n FROM articles WHERE source_key=%s", (key,)).fetchone()[
            "n"
        ]
        == 1
    )


def test_search_and_hidden_content_boundaries(client):
    api, conn = client
    visible = fixture_account(conn)
    hidden = fixture_account(conn, "hidden")
    response = api.get("/api/accounts", params={"q": "人工智能"})
    assert response.status_code == 200
    ids = [a["id"] for a in response.json()["items"]]
    assert visible in ids and hidden not in ids
    assert api.get("/api/accounts/" + str(hidden)).status_code == 404
    assert api.get("/api/categories").status_code == 200
    assert api.get("/api/admin/accounts").status_code == 403


def test_auth_collection_isolation_and_csrf(client):
    api, conn = client
    account = fixture_account(conn)
    email = secrets.token_hex(8) + "@example.invalid"
    response = api.post(
        "/api/auth/register", json={"email": email, "password": "test-password-unique"}
    )
    assert response.status_code == 200 and "HttpOnly" in response.headers["set-cookie"]
    assert (
        api.put(
            "/api/me/actions", json={"kind": "account", "target_id": account, "enabled": True}
        ).status_code
        == 200
    )
    assert len(api.get("/api/me/library?view=collections").json()["accounts"]) == 1
    assert (
        api.put(
            "/api/me/actions",
            headers={"Origin": "https://other.invalid"},
            json={"kind": "account", "target_id": account, "enabled": False},
        ).status_code
        == 403
    )
    api.delete("/api/auth/session")
    assert api.get("/api/me/library").status_code == 401
    api.post(
        "/api/auth/register", json={"email": "other-" + email, "password": "test-password-unique"}
    )
    assert api.get("/api/me/library?view=collections").json()["accounts"] == []


def test_article_search_and_detail(client):
    api, conn = client
    account = fixture_account(conn)
    row = conn.execute(
        "INSERT INTO articles(account_id,source_key,title,source_url,content_html,content_text,status) VALUES (%s,%s,'数据聚合文章','https://mp.weixin.qq.com/s/test','<p>正文</p>','正文','ready') RETURNING id",
        (account, secrets.token_hex(16)),
    ).fetchone()
    index_article(conn, row["id"])
    assert api.get("/api/articles?q=数据聚合").json()["total"] >= 1
    assert api.get("/api/articles/" + str(row["id"])).json()["content_text"] == "正文"


def test_admin_ranking_validation(client):
    api, _ = client
    headers = {"Authorization": "Bearer test-only-admin-token-long-enough"}
    assert (
        api.put(
            "/api/admin/ranking",
            headers=headers,
            json={"quality": 1, "activity": 1, "completeness": 1, "following": 1},
        ).status_code
        == 422
    )
    assert (
        api.put(
            "/api/admin/ranking",
            headers=headers,
            json={"quality": 0.25, "activity": 0.25, "completeness": 0.25, "following": 0.25},
        ).status_code
        == 200
    )


def test_ai_profile_is_structured_and_preserves_manual_review(client, monkeypatch):
    _, conn = client
    account = fixture_account(conn)
    for i in range(3):
        conn.execute(
            "INSERT INTO articles(account_id,source_key,title,source_url,content_text,status) VALUES (%s,%s,%s,'https://mp.weixin.qq.com/s/test','用于隔离测试的正文','ready')",
            (account, secrets.token_hex(16), f"test {i}"),
        )
    profile = {
        "profile_summary": "测试画像",
        "account_type": "媒体",
        "target_audience": ["研究人员"],
        "content_style": ["资讯型"],
        "expertise_level": "专业",
        "topic_distribution": [{"name": "人工智能", "percentage": 100}],
        "strengths": ["资料清晰"],
        "weaknesses": ["样本较少"],
        "recommendation_reason": "用于隔离测试",
        "not_recommended_for": [],
        "quality_scores": {"专业度": 4},
    }
    monkeypatch.setattr(
        ai,
        "generate",
        lambda schema, source: (schema.model_validate(profile).model_dump(), "test-model"),
    )
    ai.analyze("account_ai", {"target_id": account})
    row = conn.execute(
        "SELECT * FROM ai_account_profiles WHERE account_id=%s", (account,)
    ).fetchone()
    assert row["source_article_count"] == 3 and row["source_total_count"] == 3
    assert row["model_name"] == "test-model" and row["prompt_version"] == ai.PROMPT_VERSION
    conn.execute("UPDATE ai_account_profiles SET reviewed=true WHERE account_id=%s", (account,))
    with pytest.raises(crawler.SourceBlocked):
        ai.analyze("account_ai", {"target_id": account})


def test_pipeline_resumes_bodies_without_refetching_history(client, monkeypatch):
    _, conn = client
    account = fixture_account(conn)
    job_id = enqueue(conn, "sync", {"target_id": account})
    marker = secrets.token_hex(8)
    cached, calls = [], []
    fail = True

    def bridge(method, path, **kw):
        nonlocal fail
        calls.append(path)
        if path == "/history":
            cached.extend(
                {
                    "id": i,
                    "title": f"article {i}",
                    "publish_time": 1700000000,
                    "link": f"https://mp.weixin.qq.com/s?__biz={marker}&mid={i}&idx=1",
                }
                for i in range(1, 4)
            )
            return {"next_begin": 10, "has_more": True}
        if path == "/articles":
            return {
                "items": [dict(i) for i in cached if i["id"] > kw["params"]["after"]],
                "next_after": 3,
            }
        item = next(i for i in cached if i["id"] == int(path.split("/")[2]))
        if item["id"] == 2 and fail:
            fail = False
            raise crawler.SourceBlocked("ret=200013")
        item.update(content="<p>真实链路的隔离测试正文</p>")
        return dict(item)

    source = crawler.SourceClient()
    monkeypatch.setattr(source, "bridge", bridge)
    monkeypatch.setattr(source, "request", lambda *a, **kw: {"success": True})
    payload = {"target_id": account, "pages": 1, "parse_limit": 3, "_job_id": job_id}
    with pytest.raises(crawler.SourceBlocked):
        source.sync(payload)
    assert (
        conn.execute(
            "SELECT count(*) n FROM articles WHERE account_id=%s AND status='ready'", (account,)
        ).fetchone()["n"]
        == 1
    )
    progress = conn.execute("SELECT result FROM jobs WHERE id=%s", (job_id,)).fetchone()["result"]
    assert progress["pages_done"] == 1
    result = source.sync({**payload, "_progress": progress})
    assert result["readable_articles"] == 3 and result["export_available"]
    assert calls.count("/history") == 1 and calls.count("/articles/3/body") == 1
    assert (
        marker
        in conn.execute(
            "SELECT source_url FROM official_accounts WHERE id=%s", (account,)
        ).fetchone()["source_url"]
    )


def test_cache_import_updates_old_body_keeps_hidden_and_needs_no_login(client, monkeypatch):
    _, conn = client
    account = fixture_account(conn)
    marker = secrets.token_hex(8)
    items = [
        {
            "id": i,
            "title": f"cached {i}",
            "publish_time": 1700000000,
            "link": f"https://mp.weixin.qq.com/s?__biz={marker}&mid={i}&idx=1",
        }
        for i in range(1, 104)
    ]
    source = crawler.SourceClient()

    def bridge(method, path, **kw):
        assert method == "GET" and path == "/articles"
        batch = [dict(i) for i in items if i["id"] > kw["params"]["after"]][:100]
        return {"items": batch, "next_after": batch[-1]["id"] if batch else 103}

    monkeypatch.setattr(source, "bridge", bridge)
    monkeypatch.setattr(
        source, "request", lambda *a, **kw: pytest.fail("cache import contacted WeChat")
    )
    source.sync({"target_id": account, "cache_only": True})
    conn.execute(
        "UPDATE articles SET status='hidden' WHERE account_id=%s AND title='cached 1'", (account,)
    )
    items[0]["content"] = "<p>补全的正文</p>"
    items[0].update(author="补全作者", publish_time=1800000000, digest="补全摘要")
    source.sync({"target_id": account, "cache_only": True})
    rows = conn.execute("SELECT * FROM articles WHERE account_id=%s", (account,)).fetchall()
    assert len(rows) == 103
    hidden = next(r for r in rows if r["title"] == "cached 1")
    assert hidden["status"] == "hidden" and hidden["content_text"] == "补全的正文"
    assert hidden["author"] == "补全作者" and hidden["publish_time"].timestamp() == 1800000000
    assert hidden["summary"] == "补全摘要"


def test_admin_export_requires_auth_and_proxies_file(client, monkeypatch):
    api, conn = client
    account = fixture_account(conn)
    url = f"/api/admin/accounts/{account}/export/zip"
    assert api.get(url).status_code == 403
    monkeypatch.setattr(
        admin.httpx,
        "get",
        lambda *a, **kw: httpx.Response(
            200,
            content=b"PK-test-export",
            headers={"Content-Type": "application/zip"},
            request=httpx.Request("GET", "http://source/export"),
        ),
    )
    headers = {"Authorization": "Bearer test-only-admin-token-long-enough"}
    response = api.get(url, headers=headers)
    assert (
        response.content == b"PK-test-export"
        and "attachment" in response.headers["content-disposition"]
    )
    assert api.get(url.replace("/zip", "/exe"), headers=headers).status_code == 422


def test_source_message_errors_are_preserved():
    source = crawler.SourceClient()
    source.client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"success": False, "message": "微信API错误: ret=200013"}
            )
        ),
        base_url="http://source",
    )
    with pytest.raises(crawler.SourceBlocked, match="200013"):
        source.request("POST", "/api/admin/history/fetch", remote=False)


def test_manual_links_queue_parse_and_save_real_metadata(client, monkeypatch):
    api, conn = client
    account = fixture_account(conn)
    headers = {"Authorization": "Bearer test-only-admin-token-long-enough"}
    url = f"https://mp.weixin.qq.com/s?__biz={secrets.token_hex(8)}&mid=1&idx=1"
    endpoint = f"/api/admin/accounts/{account}/links"
    assert (
        api.post(endpoint, headers=headers, json={"urls": ["http://127.0.0.1/"]}).status_code == 422
    )
    result = api.post(endpoint, headers=headers, json={"urls": [url, url]}).json()
    assert len(result["ids"]) == 1
    job = conn.execute("SELECT payload FROM jobs WHERE id=%s", (result["ids"][0],)).fetchone()
    calls = []

    def bridge(method, path, **kw):
        calls.append(path)
        if path == "/articles":
            return {"id": 99, "content": ""}
        return {
            "title": "解析到的标题",
            "author": "作者",
            "publish_time": 1700000000,
            "content": "<p>解析正文</p>",
        }

    source = crawler.SourceClient()
    monkeypatch.setattr(source, "bridge", bridge)
    source.parse(job["payload"])
    article = conn.execute(
        "SELECT * FROM articles WHERE id=%s", (job["payload"]["target_id"],)
    ).fetchone()
    assert article["status"] == "ready" and article["title"] == "解析到的标题"
    assert article["author"] == "作者" and article["publish_time"].timestamp() == 1700000000
    assert calls == ["/articles", "/articles/99/body"]
