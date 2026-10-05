"""Use curl only (no JavaScript) to verify public HTML, metadata and crawler access."""
import argparse
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from bs4 import BeautifulSoup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://wechat.aim888888.xyz/wechat")
    parser.add_argument("--output", default="logs/public-html-verification")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    canonical_base = "https://wechat.aim888888.xyz/wechat"
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    curl = shutil.which("curl.exe") or shutil.which("curl")
    assert curl, "curl is required"

    def fetch(path, name):
        body = output / (name + ".body")
        headers = output / (name + ".headers")
        status = subprocess.check_output(
            [curl, "-sS", "--max-time", "120", "-D", str(headers), "-o", str(body),
             "-w", "%{http_code}", base + path], text=True,
        )
        raw_headers = headers.read_text(encoding="utf-8")
        fields = dict((key.lower(), value.strip()) for key, value in re.findall(r"^([^\s:]+):\s*(.*)$", raw_headers, re.M))
        return int(status), body.read_text(encoding="utf-8"), fields

    def api(path, name):
        status, body, _ = fetch("/api" + path, name)
        assert status == 200, (path, status)
        return json.loads(body)

    stats = api("/stats", "stats")
    categories = api("/categories", "category-data")
    category = next(item for item in categories if item["name"] == "人工智能" and item["account_count"])
    accounts = api(f'/accounts?category={category["id"]}&limit=1', "account-list")
    account = api(f'/accounts/{accounts["items"][0]["id"]}', "account-data")
    articles = api("/articles?limit=100", "article-list")
    article = api(f'/articles/{next(item for item in articles["items"] if item["status"] == "ready")["id"]}', "article-data")
    routes = [
        ("", "home", "WebSite", None),
        ("/categories", "categories", "ItemList", category["name"]),
        (f'/categories/{category["id"]}', "category", "ItemList", account["name"]),
        ("/discover", "discover", "ItemList", None),
        ("/rankings", "rankings", "ItemList", None),
        ("/search?q=" + str(account["name"]), "search", "ItemList", account["name"]),
        ("/search?tab=articles", "article-search", "ItemList", None),
        (f'/accounts/{account["id"]}', "account", "Organization", account["name"]),
        (f'/articles/{article["id"]}', "article", "Article", article["title"]),
    ]
    # curl URLs must percent-encode the Unicode query, just as a browser does.
    from urllib.parse import quote

    rows, titles, descriptions = [], [], []
    for path, name, schema, expected_text in routes:
        status, body, headers = fetch(quote(path, safe="/?=&"), name)
        assert status == 200, (path, status)
        soup = BeautifulSoup(body, "html.parser")
        title = soup.title.get_text()
        description = soup.select_one('meta[name="description"]')["content"]
        assert title and description
        canonical = soup.select_one('link[rel="canonical"]')["href"]
        assert canonical.startswith(canonical_base), canonical
        if "?" not in path:
            assert canonical == canonical_base + path, canonical
        for prop in ("title", "description", "url", "type", "image"):
            assert soup.select_one(f'meta[property="og:{prop}"]')["content"], (path, prop)
        assert soup.select_one('meta[property="og:url"]')["content"] == canonical
        assert soup.select_one('meta[name="twitter:card"]')["content"] == "summary_large_image"
        structured = [json.loads(script.string) for script in soup.select('script[type="application/ld+json"]')]
        if name == "account" and account["account_type"] == "个人IP":
            schema = "Person"
        data = next(item for item in structured if item["@type"] == schema)
        if schema == "WebSite":
            assert data["potentialAction"]["@type"] == "SearchAction"
        if schema == "Article":
            assert all(data.get(key) for key in ("headline", "datePublished", "author", "url"))
        if schema == "ItemList":
            assert data["itemListElement"], path
        for tag in soup.select("script, style, template"):
            tag.decompose()
        text = re.sub(r"\s+", "", soup.select_one("main").get_text())
        if expected_text:
            assert re.sub(r"\s+", "", expected_text) in text, (path, expected_text)
        links = soup.select('main a[href*="/accounts/"], main a[href*="/articles/"], main a[href*="/categories/"]')
        assert links, (path, "no detail links in rendered HTML")
        assert not soup.select('footer a[href*="/admin"], header a[href*="/admin"]')
        assert "ADMIN_TOKEN" not in body and ".env" not in body
        cache = headers.get("cache-control", "")
        assert "no-store" in cache and "31536000" not in cache, (path, cache)
        assert headers.get("cf-cache-status", "DYNAMIC") in ("DYNAMIC", "BYPASS", "MISS"), headers
        if name == "home":
            assert str(stats["accounts"]) in text and f'已收录{stats["articles"]}篇文章' in text
            assert "—个信息源" not in text and "暂无日期" not in text
        if name == "account" and account["description"]:
            assert re.sub(r"\s+", "", account["description"]) in text
        if name == "article":
            reading = soup.select_one(".reading-body")
            assert reading and len(reading.get_text(strip=True)) > 100, "Article body missing from HTML"
            assert soup.select_one(f'a[href="{article["source_url"]}"]')
        titles.append(title)
        descriptions.append(description)
        rows.append({"path": path, "status": status, "title": title, "text_characters": len(text), "detail_links": len(links), "schema": schema, "cache_control": cache, "cf_cache_status": headers.get("cf-cache-status")})
    assert len(set(titles)) == len(titles), "Titles must be unique"
    assert len(set(descriptions)) == len(descriptions), "Descriptions must be unique"
    status, robots, _ = fetch("/robots.txt", "robots")
    assert status == 200 and "Disallow: /wechat/admin" in robots and "Disallow: /wechat/api/admin" in robots
    status, sitemap, _ = fetch("/sitemap.xml", "sitemap")
    assert status == 200
    namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    entries = ET.fromstring(sitemap).findall("s:url", namespace)
    urls = {entry.find("s:loc", namespace).text for entry in entries}
    catalog = api("/public-sitemap", "sitemap-data")
    for kind in ("accounts", "articles"):
        assert all(f'{canonical_base}/{kind}/{entry["id"]}' in urls for entry in catalog[kind]), kind
    assert all(canonical_base + path in urls for path in ("", "/categories", "/discover", "/rankings"))
    assert all(f'{canonical_base}/categories/{item["id"]}' in urls for item in categories)
    assert all(entry.find("s:lastmod", namespace) is not None for entry in entries if "/accounts/" in entry.find("s:loc", namespace).text or "/articles/" in entry.find("s:loc", namespace).text)
    assert fetch("/llms.txt", "llms")[0] == 200
    status, admin, _ = fetch("/admin", "admin")
    assert status == 200 and "ADMIN_TOKEN" not in admin and ".env" not in admin
    assert BeautifulSoup(admin, "html.parser").select_one('meta[name="robots"]')["content"] == "noindex, nofollow"
    assert fetch("/api/admin/overview", "admin-denied")[0] in (403, 429)
    report = {"stats": stats, "account_id": account["id"], "article_id": article["id"], "routes": rows, "sitemap_urls": len(urls), "indexed_accounts": len(catalog["accounts"]), "indexed_articles": len(catalog["articles"])}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
