import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app import auth, main


@pytest.fixture
def admin_client(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-only-admin-token-long-enough")
    auth.admin_failures.clear()
    app = FastAPI()

    @app.get("/admin", dependencies=[Depends(auth.require_admin)])
    def protected():
        return {"ok": True}

    yield TestClient(app)
    auth.admin_failures.clear()


def test_admin_failures_stop_all_credential_checks_after_budget_is_exhausted(admin_client):
    valid_headers = {"Authorization": "Bearer test-only-admin-token-long-enough"}
    assert admin_client.get("/admin", headers=valid_headers).status_code == 200
    for _ in range(10):
        assert admin_client.get("/admin").status_code == 403
    denied = admin_client.get("/admin", headers={"Authorization": "Bearer wrong"})
    assert denied.status_code == 429
    assert 1 <= int(denied.headers["Retry-After"]) <= 61
    assert denied.headers["Cache-Control"] == "private, no-store"
    assert admin_client.get("/admin", headers=valid_headers).status_code == 429


def test_admin_failure_budget_expires(admin_client, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(auth.time, "monotonic", lambda: now[0])
    for _ in range(10):
        assert admin_client.get("/admin").status_code == 403
    assert admin_client.get("/admin").status_code == 429
    now[0] += 61
    assert admin_client.get("/admin", headers={"Authorization": "Bearer test-only-admin-token-long-enough"}).status_code == 200


@pytest.mark.parametrize("authorization", ["test-only-admin-token-long-enough", "Basic test-only-admin-token-long-enough", "Bearer 错误凭证", "Bearer "])
def test_admin_requires_bearer_token(admin_client, authorization):
    # ASGI headers use latin-1; pass UTF-8 bytes to exercise arbitrary untrusted input.
    assert admin_client.get("/admin", headers={b"authorization": authorization.encode()}).status_code == 403


def test_every_management_route_is_protected(admin_client):
    client = TestClient(main.app)
    routes = []
    for included in main.app.routes:
        candidates = included.original_router.routes if hasattr(included, "original_router") else [included]
        routes.extend(route for route in candidates if getattr(route, "path", "").startswith("/api/admin"))
    assert routes
    for route in routes:
        assert any(dependency.call is auth.require_admin for dependency in route.dependant.dependencies), route.path
        if "GET" in route.methods:
            path = route.path
            for name in route.param_convertors:
                path = path.replace("{" + name + "}", "1")
            assert client.get(path).status_code in (403, 429), path
