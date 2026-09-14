import io
import json
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient

from source_bridge import service


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(service.rss_store, "DB_PATH", tmp_path / "rss.db")
    service.rss_store.init_db()
    service.app.dependency_overrides[service.authenticate] = lambda: None
    yield TestClient(service.app)
    service.app.dependency_overrides.clear()


def test_body_persist_export_and_cache_reuse(client, monkeypatch):
    calls = []

    async def article(*args):
        calls.append(1)
        return {
            "success": True,
            "data": {
                "content": "<p>正文样本</p>",
                "plain_content": "正文样本",
                "title": "解析后的标题",
                "author": "正文作者",
                "publish_time": 1700000000,
            },
        }

    monkeypatch.setattr(service, "get_article", article)
    record = client.post(
        "/api/bridge/articles",
        json={
            "fakeid": "isolated-test",
            "nickname": "测试公众号",
            "title": "标题样本",
            "link": "https://mp.weixin.qq.com/s/test",
        },
    ).json()["data"]
    assert client.get("/api/export/account/isolated-test.zip").status_code == 404
    for _ in range(2):
        response = client.post(f"/api/bridge/articles/{record['id']}/body")
        assert response.json()["data"]["plain_content"] == "正文样本"
        assert response.json()["data"]["title"] == "解析后的标题"
        assert response.json()["data"]["publish_time"] == 1700000000
    assert len(calls) == 1
    data = client.get("/api/bridge/articles?fakeid=isolated-test").json()["data"]
    assert data["articles"] == data["bodies"] == 1
    assert (
        data["items"][0]["title"] == "解析后的标题"
        and data["items"][0]["author"] == "正文作者"
    )
    exported = client.get("/api/export/account/isolated-test.zip")
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        assert any(
            "正文样本" in archive.read(n).decode("utf-8") for n in archive.namelist()
        )


def test_failed_body_is_not_exportable(client, monkeypatch):
    async def blocked(*args):
        return {"success": False, "error": "需要验证"}

    monkeypatch.setattr(service, "get_article", blocked)
    record = client.post(
        "/api/bridge/articles",
        json={
            "fakeid": "blocked",
            "nickname": "测试",
            "title": "测试",
            "link": "https://mp.weixin.qq.com/s/test",
        },
    ).json()["data"]
    assert not client.post(f"/api/bridge/articles/{record['id']}/body").json()[
        "success"
    ]
    assert client.get("/api/export/account/blocked.zip").status_code == 404
    assert (
        client.post(
            "/api/bridge/articles",
            json={
                "fakeid": "x",
                "nickname": "x",
                "title": "x",
                "link": "http://127.0.0.1/private",
            },
        ).status_code
        == 422
    )


def test_bridge_authentication():
    client = TestClient(service.app)
    assert client.get("/api/bridge/articles?fakeid=x").status_code == 403


def test_history_saves_every_article_and_uses_batch_cursor(client, monkeypatch):
    service.rss_store.add_subscription("history", "测试")
    monkeypatch.setattr(
        service.auth_manager,
        "get_credentials",
        lambda: {"token": "test", "cookie": "test"},
    )
    requests = []

    def remote(request):
        requests.append(request)
        articles = [
            {
                "title": f"文章{i}",
                "link": f"https://mp.weixin.qq.com/s/{i}",
                "update_time": 1700000000,
            }
            for i in range(11)
        ]
        return httpx.Response(
            200,
            json={
                "base_resp": {"ret": 0},
                "publish_page": json.dumps(
                    {
                        "publish_list": [
                            {"publish_info": json.dumps({"appmsgex": articles[:8]})},
                            {"publish_info": {"appmsgex": articles[8:]}},
                        ]
                    }
                ),
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        service.httpx,
        "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(remote)),
    )
    result = client.post(
        "/api/bridge/history", json={"fakeid": "history", "begin": 20}
    ).json()["data"]
    assert result == {"fetched": 11, "next_begin": 22, "has_more": False}
    assert requests[0].url.params["begin"] == "20"
    assert (
        client.get("/api/bridge/articles?fakeid=history").json()["data"]["articles"]
        == 11
    )
