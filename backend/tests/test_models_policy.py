import json
from datetime import datetime

import httpx
import pytest
from test_core import client as client  # noqa: PLC0414

from app.collection_policy import eligible
from app.reranking import rerank


def test_ai_accepts_markdown_fenced_json(client, monkeypatch):
    from app.ai import Summary, generate

    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "gemini-test")
    monkeypatch.delenv("LLM_FALLBACK_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_FALLBACK_API_KEY", raising=False)
    monkeypatch.delenv("LLM_FALLBACK_MODEL", raising=False)
    response_data = {
        "summary": "summary",
        "key_points": ["point"],
        "keywords": ["keyword"],
        "target_audience": ["reader"],
        "article_type": "analysis",
        "sentiment": "neutral",
        "quality_score": 80,
    }

    def post(self, url, **kwargs):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "```json\n" + json.dumps(response_data) + "\n```"
                        }
                    }
                ]
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.Client, "post", post)
    data, model = generate(Summary, {"title": "test", "content": "body"})
    assert model == "gemini-test" and data["summary"] == "summary"


def test_embedding_mixed_numeric_types_persist(client, monkeypatch):
    import secrets

    from app.embeddings import generate

    _, conn = client
    aid = conn.execute(
        "INSERT INTO official_accounts(source_id,name) VALUES (%s,'模型测试') RETURNING id",
        (secrets.token_hex(16),),
    ).fetchone()["id"]
    article = conn.execute(
        "INSERT INTO articles(account_id,source_key,title,source_url,content_text,status) VALUES (%s,%s,'测试','https://mp.weixin.qq.com/s/test','正文','ready') RETURNING id",
        (aid, secrets.token_hex(16)),
    ).fetchone()["id"]
    monkeypatch.setenv("EMBEDDING_API_KEY", "test")
    monkeypatch.setenv("EMBEDDING_MODEL", "Qwen/Qwen3-VL-Embedding-8B")

    def post(self, url, **kwargs):
        return httpx.Response(
            200, json={"data": [{"embedding": [0, 0.25, -0.5]}]}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx.Client, "post", post)
    assert generate({"target_id": article})["dimensions"] == 3
    assert conn.execute(
        "SELECT embedding FROM article_embeddings WHERE article_id=%s", (article,)
    ).fetchone()["embedding"] == [0.0, 0.25, -0.5]
    account_embedding = conn.execute(
        "SELECT source_embedding_count,embedding FROM account_embeddings WHERE account_id=%s", (aid,)
    ).fetchone()
    assert account_embedding == {"source_embedding_count": 1, "embedding": [0.0, 0.25, -0.5]}


def test_body_cutoff_shanghai_boundary(monkeypatch):
    monkeypatch.setenv("BODY_SINCE", "2026-06-01")
    assert not eligible(None)
    assert not eligible(datetime.fromisoformat("2026-05-31T15:59:59+00:00"))
    assert eligible(datetime.fromisoformat("2026-05-31T16:00:00+00:00"))


@pytest.mark.parametrize("unreadable", [False, True])
@pytest.mark.parametrize("undated", [False, True])
def test_corrected_old_body_date_is_not_refetched(client, monkeypatch, unreadable, undated):
    from types import SimpleNamespace

    from test_weread import job, source_account, target

    from app import weread_crawler

    _, conn = client
    conn.execute("UPDATE source_accounts SET enabled=false")
    source_account(conn, monkeypatch)
    aid = target(conn)
    jid = job(conn, aid)
    calls = []

    def content(rid):
        calls.append(rid)
        if unreadable and rid.endswith("_old"):
            from app.sources.weread import SourceError

            raise SourceError("invalid_content", "正文缺失", "content")
        return {
            "content": "<p>正文</p>",
            "publish_time": 1700000000 if rid.endswith("_old") else 1780272000,
        }

    def articles(book, offset):
        return {
            "items": [
                {
                    "external_id": book + "_" + name,
                    "title": name,
                    "link": f"https://mp.weixin.qq.com/s/{aid}{name}",
                    "publish_time": None if undated else 1780272000,
                }
                for name in ("old", "new")
            ],
            "next_offset": 2,
            "exhausted": False,
        }

    adapter = SimpleNamespace(
        verify_or_renew=list,
        credentials=lambda: {"cookies": {}},
        ensure_subscription=lambda b: None,
        articles=articles,
        content=content,
        close=lambda: None,
    )
    monkeypatch.setattr(weread_crawler, "WeReadAdapter", lambda *a, **k: adapter)
    payload = {"_job_id": jid, "target_id": aid, "pages": 1, "parse_limit": 20}
    weread_crawler.collect(payload)
    weread_crawler.collect(payload)
    assert len(calls) == 2
    rows = conn.execute(
        "SELECT title,publish_time,content_text FROM articles WHERE account_id=%s", (aid,)
    ).fetchall()
    old = next(r for r in rows if r["title"] == "old")
    assert not old["content_text"]
    if not unreadable:
        assert old["publish_time"].timestamp() == 1700000000
    assert next(r for r in rows if r["title"] == "new")["content_text"] == "正文"


def test_rerank_maps_original_rows_and_rejects_bad_indices(monkeypatch):
    monkeypatch.setenv("RERANK_API_KEY", "test")
    monkeypatch.setenv("RERANK_MODEL", "Qwen/Qwen3-VL-Reranker-8B")
    monkeypatch.setenv("RERANK_BASE_URL", "https://api.siliconflow.cn/v1")
    results = [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.1}]

    def post(self, url, **kwargs):
        assert kwargs["json"]["model"] == "Qwen/Qwen3-VL-Reranker-8B"
        assert kwargs["json"]["documents"] == ["A\n\n", "B\n\n"]
        return httpx.Response(200, json={"results": results}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", post)
    rows = [{"id": 1, "title": "A"}, {"id": 2, "title": "B"}]
    assert [r["id"] for r in rerank("问题", rows)[0]] == [2, 1]
    results[0]["index"] = 0
    with pytest.raises(ValueError):
        rerank("问题", rows)


def test_unknown_date_is_probed_once_then_deferred(client, monkeypatch):
    from types import SimpleNamespace
    from test_weread import job, source_account, target
    from app import weread_crawler
    _, conn = client
    conn.execute("UPDATE source_accounts SET enabled=false")
    source_account(conn, monkeypatch)
    aid = target(conn)
    jid = job(conn, aid)
    calls = []
    def content(rid):
        calls.append(rid)
        return {"content": "<p>没有日期的正文</p>", "publish_time": None}
    adapter = SimpleNamespace(
        verify_or_renew=list, credentials=lambda: {"cookies": {}},
        ensure_subscription=lambda b: None, close=lambda: None, content=content,
        articles=lambda book, offset: {"items": [{"external_id": book + "_undated",
            "title": "未知日期", "link": f"https://mp.weixin.qq.com/s/{aid}undated",
            "publish_time": None}], "next_offset": 1, "exhausted": True})
    monkeypatch.setattr(weread_crawler, "WeReadAdapter", lambda *a, **k: adapter)
    payload = {"_job_id": jid, "target_id": aid, "pages": 1}
    weread_crawler.collect(payload)
    weread_crawler.collect(payload)
    row = conn.execute("SELECT content_text,body_error,body_retry_after FROM articles WHERE account_id=%s", (aid,)).fetchone()
    assert len(calls) == 1
    assert row["content_text"] == ""
    assert row["body_retry_after"] is not None
    assert "发布时间" in row["body_error"]
