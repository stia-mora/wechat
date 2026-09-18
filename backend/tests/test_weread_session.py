import json

import httpx
import pytest

from app.sources.weread import SourceError, WeReadAdapter


def test_mid_task_renewal_persists_and_deduplicates():
    calls = []
    saved = []

    def remote(request):
        calls.append(request.url.path)
        assert request.headers["cookie"].count("wr_skey=") == 1
        if request.url.path == "/web/login/renewal":
            assert json.loads(request.content)["ql"] is False
            return httpx.Response(200, json={"succ": 1}, headers={
                "set-cookie": "wr_skey=new; Domain=weread.qq.com; Path=/"})
        if len(calls) == 1:
            return httpx.Response(200, json={"errCode": -2012})
        assert "wr_skey=new" in request.headers["cookie"]
        return httpx.Response(200, json={"reviews": []})

    adapter = WeReadAdapter({"cookies": {"wr_skey": "old", "wr_rt": "refresh"}},
                            transport=httpx.MockTransport(remote))
    adapter.on_credentials_changed = saved.append
    try:
        assert adapter.articles("MP_WXS_1")["items"] == []
        assert len(calls) == 3
        assert saved[-1]["cookies"]["wr_skey"] == "new"
    finally:
        adapter.close()


@pytest.mark.parametrize("body", [{"succ": 0}, {"errCode": -2013}, {}])
def test_failed_renewal_preserves_credentials(body):
    adapter = WeReadAdapter({"cookies": {"wr_skey": "old", "wr_rt": "refresh"}},
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body,
            headers={"set-cookie": "wr_skey=bad; Domain=weread.qq.com; Path=/"})))
    saved = []
    adapter.on_credentials_changed = saved.append
    try:
        with pytest.raises(SourceError):
            adapter.renew()
        assert adapter.credentials()["cookies"]["wr_skey"] == "old"
        assert saved == []
    finally:
        adapter.close()


def test_list_restriction_does_not_renew():
    calls = []
    def remote(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"errCode": -2041})
    adapter = WeReadAdapter(transport=httpx.MockTransport(remote))
    try:
        with pytest.raises(SourceError) as error:
            adapter.articles("MP_WXS_1")
        assert error.value.code == "-2041"
        assert calls == ["/web/mp/articles"]
    finally:
        adapter.close()
