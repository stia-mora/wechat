import hashlib
import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[1]))
import analyzer
import app as monitor


@pytest.fixture
def client(tmp_path, monkeypatch):
    salt = bytes.fromhex('ab' * 16)
    digest = hashlib.pbkdf2_hmac('sha256', b'local-test-password', salt, 180000).hex()
    monkeypatch.setenv('TRAFFIC_PASSWORD_HASH', salt.hex() + ':' + digest)
    monkeypatch.setenv('TRAFFIC_SESSION_KEY', 'c' * 64)
    monkeypatch.setenv('TRAFFIC_ORIGIN', 'https://testserver')
    monkeypatch.setattr(analyzer, 'DATA', tmp_path)
    monkeypatch.setattr(analyzer, 'run', lambda stop: stop.wait())
    monitor.failures.clear()
    with TestClient(monitor.app, base_url='https://testserver') as test_client:
        yield test_client


def sign_in(client):
    return client.post('/traffic/login', json={'username': 'admin', 'password': 'local-test-password'})


def test_private_reports_require_valid_unexpired_cookie(client):
    assert client.get('/traffic/api/summary').status_code == 401
    assert client.get('/traffic/report').status_code == 401
    assert 'login-form' in client.get('/traffic').text
    response = sign_in(client)
    assert response.status_code == 200
    assert all(flag in response.headers['set-cookie'] for flag in ('Secure', 'HttpOnly', 'SameSite=strict', 'Path=/traffic'))
    assert '浏览器上报访问' in client.get('/traffic').text
    assert client.get('/traffic/api/summary').status_code == 503
    expiry = str(int(time.time()) - 1)
    client.cookies.set(monitor.COOKIE, expiry + '.' + monitor.signature(expiry), domain='testserver.local', path='/traffic')
    assert client.get('/traffic/report').status_code == 401
    client.cookies.set(monitor.COOKIE, str(int(time.time()) + 999) + '.forged', domain='testserver.local', path='/traffic')
    assert client.get('/traffic/report').status_code == 401


def test_login_failure_limit_and_cross_site_rejection(client):
    response = client.post('/traffic/login', headers={'Origin': 'https://evil.example'}, json={'username': 'admin', 'password': 'local-test-password'})
    assert response.status_code == 403
    assert response.headers['Cache-Control'] == 'private, no-store'
    for _ in range(10):
        assert client.post('/traffic/login', json={'username': 'admin', 'password': 'wrong'}).status_code == 403
    assert sign_in(client).status_code == 429


def test_events_cannot_record_private_urls_or_queries_or_raw_ips(client):
    assert client.post('/traffic/events', json={'path': '/wechat/admin'}).status_code == 422
    assert client.post('/traffic/events', json={'path': '/wechat/search?q=secret'}).status_code == 422
    response = client.post('/traffic/events', headers={'X-Real-IP': '192.0.2.99', 'User-Agent': 'Browser"\nInjected'}, json={'path': '/wechat/discover', 'referrer': 'https://www.google.com/search?q=private-search-term'})
    assert response.status_code == 204
    text = next((analyzer.DATA / 'browser').glob('*.log')).read_text(encoding='utf-8')
    assert '192.0.2.99' not in text and 'private-search-term' not in text
    assert 'https://www.google.com/' in text and text.count('\n') == 1
    assert client.get('/traffic/../app.py').status_code == 404


def test_period_filter_logout_and_safe_report_headers(client):
    sign_in(client)
    assert client.get('/traffic/api/summary?days=100').status_code == 422
    reports = analyzer.DATA / 'reports'
    reports.mkdir()
    (reports / 'summary-1.json').write_text(json.dumps({'http_requests': 5}))
    response = client.get('/traffic/api/summary')
    assert response.json() == {'http_requests': 5}
    assert response.headers['X-Robots-Tag'] == 'noindex, nofollow'
    assert response.headers['Cloudflare-CDN-Cache-Control'] == 'no-store'
    assert client.post('/traffic/logout').status_code == 200
    assert client.get('/traffic/api/summary').status_code == 401


@pytest.mark.parametrize(('url', 'kind'), [('https://www.google.co.uk/search?q=a', '搜索引擎'), ('https://www.baidu.com/s?wd=a', '搜索引擎'), ('https://gemini.google.com/app/a', 'AI 平台引荐'), ('https://chatgpt.com/c/a', 'AI 平台引荐'), ('https://wechat.aim888888.xyz/wechat', '站内'), ('https://chatgpt.com.evil.example/', '外部引荐')])
def test_search_and_ai_referrers_are_separate(url, kind):
    assert analyzer.source_kind(analyzer.source_host(url)) == kind


def test_untrusted_referrers_cannot_inject_log_lines():
    for value in ('https://foo"bar.example/', 'https://foo\\bar.example/', 'javascript:alert(1)', 'https://[invalid'):
        assert analyzer.source_host(value) == ''


def test_truncated_referrers_do_not_become_direct_visits():
    browser = {'general': {'valid_requests': 10}, 'referring_sites': {
        'metadata': {'hits': {'total': {'value': 8}}},
        'data': [{'data': 'www.google.com', 'hits': {'count': 5}}]}}
    sources = analyzer.summarize({}, browser)['sources']
    assert sources == [{'host': 'www.google.com', 'kind': '搜索引擎', 'views': 5},
                       {'host': '其他未列出的引荐域名', 'kind': '其他来源', 'views': 3},
                       {'host': '无引荐信息', 'kind': '直接 / 未知', 'views': 2}]
