"""Read-only production source probes; never print credentials or raw responses.

Run inside the api container with ``weread``, or source container with ``mp``.
No imports, subscription writes, login renewal or database updates are performed.
"""

import argparse
import json
import time


def emit(**data):
    print(json.dumps(data, ensure_ascii=False), flush=True)


def probe_weread():
    from app.credentials import decrypt
    from app.db import db
    from app.sources.weread import SourceError, WeReadAdapter, book_id

    with db() as conn:
        targets = conn.execute("""SELECT a.id,a.name,a.source_id FROM official_accounts a
            WHERE a.status='approved' AND NOT a.article_collection_enabled
            AND NOT EXISTS(SELECT 1 FROM articles r WHERE r.account_id=a.id
                AND r.status<>'hidden' AND r.source_url<>'') ORDER BY a.id LIMIT 2""").fetchall()
        accounts = conn.execute("""SELECT id,credentials FROM source_accounts
            WHERE source_id='weread' AND enabled AND credentials<>''
            ORDER BY last_checked_at DESC NULLS LAST LIMIT 2""").fetchall()
    for account in [None, *accounts]:
        adapter = WeReadAdapter(decrypt(account["credentials"]) if account else None)
        adapter.client.timeout = 15
        probes = [("/api/mp/cover", {"bookId": book_id(t["source_id"])}, t) for t in targets[:1 if account else 2]]
        if account:
            probes.insert(0, ("/web/shelf/sync", {"userVid": "", "synckey": 0, "lectureSynckey": 0}, {}))
        try:
            for path, params, target in probes:
                started = time.monotonic()
                try:
                    result = adapter._checked_request("GET", path, params=params)
                    emit(source="weread", login_account=account["id"] if account else None,
                         target=target.get("name"), path=path, seconds=round(time.monotonic()-started, 1),
                         has_article=bool(result.get("reviewId")), has_shelf=isinstance(result.get("books"), list))
                except SourceError as exc:
                    emit(source="weread", login_account=account["id"] if account else None,
                         target=target.get("name"), path=path, seconds=round(time.monotonic()-started, 1),
                         error_code=exc.code, category=exc.category)
                time.sleep(5)
        finally:
            adapter.close()


def probe_mp(fakeid):
    import httpx
    from utils.auth_manager import auth_manager

    creds = auth_manager.get_credentials() or {}
    emit(source="mp", has_credentials=bool(creds.get("token") and creds.get("cookie")),
         expired=bool(creds.get("expire_time") and time.time()*1000 > creds["expire_time"]))
    if not creds.get("token") or not creds.get("cookie"):
        return
    with httpx.Client(timeout=20, trust_env=False) as client:
        try:
            response = client.get("https://mp.weixin.qq.com/cgi-bin/appmsgpublish",
                params={"sub": "list", "search_field": "null", "query": "",
                        "begin": 0, "count": 1, "fakeid": fakeid, "type": "101_1",
                        "free_publish_type": 1, "sub_action": "list_ex", "token": creds["token"],
                        "lang": "zh_CN", "f": "json", "ajax": 1},
                headers={"Cookie": creds["cookie"], "Referer": "https://mp.weixin.qq.com/", "User-Agent": "Mozilla/5.0"})
        except httpx.HTTPError as exc:
            # Exception URLs can contain the login token; print the class only.
            emit(source="mp", error=type(exc).__name__)
            return
        try:
            data = response.json()
        except ValueError:
            emit(source="mp", http_status=response.status_code, error="non_json")
            return
        if not isinstance(data, dict):
            emit(source="mp", http_status=response.status_code, error="invalid_response")
            return
        page = data.get("publish_page") or {}
        try:
            if isinstance(page, str):
                page = json.loads(page)
        except ValueError:
            emit(source="mp", http_status=response.status_code, error="invalid_publish_page")
            return
        if not isinstance(page, dict):
            emit(source="mp", http_status=response.status_code, error="invalid_publish_page")
            return
        emit(source="mp", http_status=response.status_code,
             error_code=(data.get("base_resp") or {}).get("ret"),
             groups=len(page.get("publish_list") or []))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=["weread", "mp"])
    parser.add_argument("--fakeid", default="MzE5MTAxNTgzMw==")
    args = parser.parse_args()
    if args.source == "weread":
        probe_weread()
    else:
        probe_mp(args.fakeid)
