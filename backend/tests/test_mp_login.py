import httpx
from fastapi.testclient import TestClient

from app import auth, main, mp_login


def test_login_proxy_is_admin_only_and_never_forwards_credentials(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "qr-test-admin-token-long-enough")
    monkeypatch.setenv("SOURCE_API_URL", "http://source:5500")
    auth.admin_failures.clear()
    calls = []

    def source(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json={"state": "verified", "token": "private-token",
                                        "cookie": "private-cookie", "redirect_url": "private-url"},
                              headers={"Set-Cookie": "private-cookie"})

    monkeypatch.setattr(mp_login.httpx, "post", source)
    client = TestClient(main.app)
    assert client.post("/api/admin/mp-login/start").status_code == 403
    response = client.post("/api/admin/mp-login/start", headers={"Authorization": "Bearer qr-test-admin-token-long-enough"})
    assert response.status_code == 200 and response.json() == {"state": "verified"}
    assert "private" not in response.text and "set-cookie" not in response.headers
    assert len(calls) == 1 and calls[0][0].endswith("/api/bridge/mp-login/start")
    auth.admin_failures.clear()
