"""Probe one public account in an isolated, persistent local Chrome profile.

Run with .venv/Scripts/python.exe scripts/probe_weread_reader.py --account 9 --target 85.
Use --headed to complete any login/verification manually, then run again.
"""
import argparse
import hashlib
import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from playwright.sync_api import sync_playwright
from app.credentials import decrypt
from app.db import db
from app.source_admin import account_row, end_maintenance, save_verified
from app.sources.weread import WeReadAdapter


def reader_url(book):
    digest = hashlib.md5(book.encode()).hexdigest()
    encoded = book.encode().hex()
    value = digest[:3] + "42" + digest[-2:] + format(len(encoded), "02x") + encoded
    return "https://weread.qq.com/web/mp/reader/" + value + hashlib.md5(value.encode()).hexdigest()[:3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", type=int, required=True)
    parser.add_argument("--target", type=int, required=True)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    with db() as conn:
        sub = conn.execute("SELECT external_id FROM source_subscriptions WHERE account_id=%s AND source_id='weread'", (args.target,)).fetchone()
    if not sub:
        raise SystemExit("公众号尚未加入采集队列")
    row = account_row(args.account)
    stopped = threading.Event()
    def keep_reserved():
        while not stopped.wait(30):
            with db() as conn:
                conn.execute("UPDATE source_accounts SET maintenance_until=now()+interval '6 minutes' WHERE id=%s", (args.account,))
    reservation = threading.Thread(target=keep_reserved, daemon=True)
    reservation.start()
    try:
        credentials = decrypt(row["credentials"])
        profile = ROOT / "data/private/weread-browser" / str(args.account)
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(str(profile), channel="chrome", headless=not args.headed)
            try:
                existing = context.cookies("https://weread.qq.com")
                profile_vid = next((c["value"] for c in existing if c["name"] == "wr_vid"), None)
                if profile_vid and profile_vid != credentials["cookies"].get("wr_vid"):
                    raise RuntimeError("浏览器配置属于另一个账号，请检查配置目录")
                if not any(c["name"] == "wr_vid" for c in existing):
                    context.add_cookies([{"name": k, "value": v, "domain": ".weread.qq.com", "path": "/", "secure": True} for k,v in credentials["cookies"].items()])
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(reader_url(sub["external_id"]), wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(5000)
                if args.headed:
                    print("请在独立 Chrome 窗口中完成登录或验证，完成后在终端按回车。", flush=True)
                    input()
                visible = page.locator("body").inner_text()
                challenge = any(t in visible for t in ("安全验证", "完成验证", "拖动滑块", "验证码")) or any(frame.is_visible() for frame in page.locator("iframe[src*=captcha]").all())
                print(json.dumps({"reader_url": page.url, "title": page.title(), "verification": challenge, "visible_text": visible[:250]}, ensure_ascii=False), flush=True)
                page.screenshot(path=str(profile / "reader.png"), full_page=False)
                if challenge:
                    print("需要人工验证；未请求文章列表。", flush=True)
                    return
                result = page.evaluate("""async book => {
                    const r = await fetch('/web/mp/articles?bookId=' + encodeURIComponent(book) + '&offset=0', {credentials:'include'});
                    return {status:r.status, data:await r.json()};
                }""", sub["external_id"])
                data = result["data"]
                groups = data.get("reviews", [])
                print(json.dumps({"http_status": result["status"], "error_code": data.get("errCode"), "groups": len(groups), "articles": sum(len(g.get("subReviews", [])) for g in groups)}, ensure_ascii=False), flush=True)
                cookies = {c["name"]: c["value"] for c in context.cookies("https://weread.qq.com")}
                if cookies.get("wr_vid") != credentials["cookies"].get("wr_vid"):
                    raise RuntimeError("浏览器账号与选定账号不一致，未保存凭据")
                if isinstance(data.get("reviews"), list) and not data.get("errCode"):
                    adapter = WeReadAdapter({**credentials, "cookies": cookies})
                    try:
                        adapter.verify_or_renew()
                        save_verified(args.account, adapter)
                    finally:
                        adapter.close()
            finally:
                context.close()
    finally:
        stopped.set()
        reservation.join()
        end_maintenance(args.account)


if __name__ == "__main__":
    main()
