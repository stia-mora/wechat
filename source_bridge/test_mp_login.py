import httpx
import pytest
from fastapi import HTTPException

from source_bridge.mp_login import MPLogin


class Manager:
    def __init__(self):
        self.saved = []

    def save_credentials(self, *args):
        self.saved.append(args)
        return True


def login_service(ret=0, search_ret=0):
    manager = Manager()
    def remote(request):
        action = request.url.params.get("action")
        if action == "getqrcode":
            return httpx.Response(200, content=b"\x89PNG\r\n\x1a\nfake-image", headers={"Set-Cookie": "scan=private-cookie; Path=/; Domain=mp.weixin.qq.com"})
        if action == "ask":
            return httpx.Response(200, json={"base_resp": {"ret": 0}, "status": 1, "private_field": "must-not-leak"})
        if action == "login":
            return httpx.Response(200, json={"base_resp": {"ret": 0}, "redirect_url": "/cgi-bin/home?token=123456789"})
        return httpx.Response(200, json={"base_resp": {"ret": search_ret if action == "search_biz" else ret, "err_msg": "secret-cookie"}})
    return MPLogin(manager, lambda: httpx.Client(base_url="https://mp.weixin.qq.com", transport=httpx.MockTransport(remote))), manager


def test_qr_login_keeps_cookies_server_side_and_requires_live_verification(capsys):
    login, manager = login_service()
    created = login.start()
    assert set(created) == {"session_id", "qr", "state", "expires_in"}
    completed = login.poll(created["session_id"])
    assert completed["state"] == "verified" and len(manager.saved) == 1
    assert manager.saved[0][0] == "123456789" and "private-cookie" in manager.saved[0][1]
    assert "private-cookie" not in str(completed) and "123456789" not in str(completed)
    assert "private-cookie" not in capsys.readouterr().out


def test_failed_start_is_not_reported_as_success():
    login, manager = login_service(ret=200003)
    with pytest.raises(HTTPException) as failure:
        login.start()
    assert failure.value.status_code == 409 and "secret-cookie" not in failure.value.detail
    assert not manager.saved and login.session is None


def test_failed_post_login_probe_does_not_save_credentials():
    login, manager = login_service(search_ret=200003)
    created = login.start()
    with pytest.raises(HTTPException):
        login.poll(created["session_id"])
    assert not manager.saved
    login.cancel()


def test_sessions_are_isolated_cancelled_and_expire():
    login, _ = login_service()
    created = login.start()
    with pytest.raises(HTTPException) as busy:
        login.start()
    assert busy.value.status_code == 409
    with pytest.raises(HTTPException) as unknown:
        login.poll("not-the-session")
    assert unknown.value.status_code == 404
    login.session["expires"] = 0
    with pytest.raises(HTTPException) as expired:
        login.poll(created["session_id"])
    assert expired.value.status_code == 410 and login.session is None
