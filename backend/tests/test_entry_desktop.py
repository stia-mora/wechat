import json
from pathlib import Path

import httpx
import pytest

from app.entry_desktop import CollectionError, DesktopCollector, classify, verify_page, message_articles
from app.entry_collection import public_article_url


def test_desktop_rejects_wrong_identity_captcha_and_nonarticle():
    page = b'<h1 id="activity-name">Title</h1><div id="js_content"></div><script>var biz="correct";</script>'
    verify_page(page, "correct")
    with pytest.raises(CollectionError, match="identity"):
        verify_page(page, "wrong")
    with pytest.raises(CollectionError, match="verification"):
        verify_page("环境异常，请完成验证".encode(), "correct")
    with pytest.raises(CollectionError, match="invalid"):
        verify_page(b'<h1>deleted</h1>', "correct")


@pytest.mark.parametrize("status,data,expected", [
    (404, "official account not found", "unknown"), (401, "rejected", "auth"),
    (502, "credential expired key=secret", "auth"), (429, {}, "rate_limit"),
    (502, "200013", "rate_limit"), (200, "需要验证", "verification"), (200, {}, "invalid"),
    (502, "upstream request failed: status 429", "rate_limit"),
    (502, "upstream request failed: status 401", "auth"),
    (502, "upstream request failed: status 403", "auth"),
    (502, "upstream connection reset key=secret", "network"),
    (200, {"ret": -3, "errmsg": "params rejected"}, "auth"),
])
def test_error_classification_never_exposes_raw_message(status, data, expected):
    category = classify(status, data)
    assert category == expected and "secret" not in str(CollectionError(category))


@pytest.mark.parametrize("url", ["http://mp.weixin.qq.com/s/a", "https://example.com/s/a", "https://mp.weixin.qq.com:443/s/a", "https://mp.weixin.qq.com/cgi-bin/home", "https://mp.weixin.qq.com/s?__biz=x"])
def test_only_public_article_links_are_accepted(url):
    with pytest.raises(Exception):
        public_article_url(url)


def collector_fixture(tmp_path, monkeypatch, upstream):
    collector = DesktopCollector.__new__(DesktopCollector)
    credentials = tmp_path / "mp.json"
    credentials.write_text(json.dumps({"known": {"key": "private-key", "uin": "private-uin", "cookie": "private-cookie"}}))
    collector.config = {"credentials_file": str(credentials)}
    def inventory(req):
        assert req.url.params["keyword"] in ("known", "uncaptured")
        return httpx.Response(200, json={"code": 0, "data": {"items": [{"biz": "known"}], "total_pages": 1}})
    collector.wx = httpx.Client(base_url="http://127.0.0.1:2026", transport=httpx.MockTransport(inventory))
    collector.public = httpx.Client(transport=httpx.MockTransport(upstream), follow_redirects=False)
    permits = []
    monkeypatch.setattr(collector, "reserve_request", lambda job, lease: permits.append(1))
    return collector, permits


def test_uncaptured_account_does_not_send_upstream_or_copy_credentials(tmp_path, monkeypatch):
    def forbidden(req):
        raise AssertionError("unknown biz must never reuse captured account's key")
    collector, permits = collector_fixture(tmp_path, monkeypatch, forbidden)
    outcome = collector.collect({"id": 1, "source_id": "uncaptured"}, {"execution_token": "x"})
    assert outcome["outcome"] == "unknown" and outcome["pre_captured"] is False
    assert not permits and outcome["request_count"] == 0
    collector.wx.close(); collector.public.close()


def test_each_list_and_identity_request_requires_a_permit(tmp_path, monkeypatch):
    calls = []
    def upstream(req):
        calls.append(req)
        if req.url.path == "/mp/profile_ext":
            assert req.url.params["offset"] == "0" and req.url.params["key"] == "private-key"
            return httpx.Response(200, json={"ret": 0, "general_msg_list": json.dumps({"list": [
                {"comm_msg_info": {"datetime": 1700000000}, "app_msg_ext_info": {"title": "Title", "content_url": "https://mp.weixin.qq.com/s?__biz=known&mid=1&idx=1&sn=abc"}}]})})
        return httpx.Response(200, content=b'<h1 id="activity-name">Title</h1><div id="js_content"></div><script>var biz="known";</script>')
    collector, permits = collector_fixture(tmp_path, monkeypatch, upstream)
    outcome = collector.collect({"id": 1, "source_id": "known"}, {"execution_token": "x"})
    assert outcome["outcome"] == "success" and outcome["pre_captured"] is True
    assert len(permits) == len(calls) == outcome["request_count"] == 2
    assert "private-key" not in json.dumps(outcome)
    collector.wx.close(); collector.public.close()


@pytest.mark.parametrize("response", [httpx.Response(429, content=b""), httpx.Response(401, content=b"<html>login</html>"), httpx.Response(403, content=b"denied"), httpx.Response(200, json={"ret": 200013}), httpx.Response(302, headers={"Location": "https://example.com"}), httpx.Response(200, text="环境异常，请完成验证")])
def test_upstream_limits_and_redirects_fail_closed(tmp_path, monkeypatch, response):
    collector, permits = collector_fixture(tmp_path, monkeypatch, lambda req: response)
    outcome = collector.collect({"id": 1, "source_id": "known"}, {"execution_token": "x"})
    assert outcome["outcome"] in ("rate_limit", "auth", "verification") and len(permits) == 1
    collector.wx.close(); collector.public.close()


@pytest.mark.parametrize("field,envelope", [("general_msg_list", "list"), ("home_page_list", "items"), ("home_page_list", "articles")])
def test_first_page_flat_formats_and_empty_general_fallback(field, envelope):
    data = {"general_msg_list": '{"list":[]}', field: json.dumps({envelope: [
        {"title": "真实文章", "source_url": "https://mp.weixin.qq.com/s/a", "create_time": 1700000000}]})}
    articles = message_articles(data)
    assert len(articles) == 1 and articles[0]["publish_time"] == 1700000000
    assert message_articles({"general_msg_list": '{"list":[]}'}) == []
    with pytest.raises(CollectionError, match="invalid"):
        message_articles({"ret": 0})
