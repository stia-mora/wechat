"""Verify query canonicalization, deferred WeChat dialogs and classified featured accounts with curl."""
import argparse
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

from bs4 import BeautifulSoup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='https://wechat.aim888888.xyz/wechat')
    parser.add_argument('--output', default='logs/list-variants-verification')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    canonical_base = 'https://wechat.aim888888.xyz/wechat'
    curl = shutil.which('curl.exe') or shutil.which('curl')
    assert curl, 'curl is required'

    def fetch(path, name):
        body = output / (name + '.body')
        status = subprocess.check_output(
            [curl, '-fsS', '--max-time', '120', '-D', str(output / (name + '.headers')),
             '-o', str(body), '-w', '%{http_code}', args.base_url.rstrip('/') + quote(path, safe='/?=&')],
            text=True,
        )
        assert status == '200', (path, status)
        return body.read_text(encoding='utf-8')

    rows = []
    for path, suffix in [
        ('/discover', '?page=1'), ('/discover', '?page=2'),
        ('/discover', '?sort=featured'), ('/discover', '?category=2'),
        ('/discover', '?account_type=媒体'), ('/discover', '?frequency=high'),
        ('/rankings', '?page=2&sort=active'), ('/categories', '?page=2'),
        ('/categories/2', '?page=2'), ('/categories/2', '?sort=featured'),
        ('/search', '?q=人民日报'), ('/search', '?q='),
        ('/search', '?tab=articles&page=2'),
    ]:
        raw = fetch(path + suffix, 'variant-' + str(len(rows)))
        soup = BeautifulSoup(raw, 'html.parser')
        canonical = soup.select_one('link[rel="canonical"]')['href']
        robots = soup.select_one('meta[name="robots"]')['content']
        assert canonical == canonical_base + path, (path, canonical)
        assert set(robots.replace(' ', '').split(',')) >= {'noindex', 'follow'}, robots
        assert soup.select_one('meta[property="og:url"]')['content'] == canonical
        assert '用微信扫一扫' not in raw and not soup.select('dialog')
        rows.append({'url': path + suffix, 'canonical': canonical, 'robots': robots})

    home = fetch('', 'home')
    soup = BeautifulSoup(home, 'html.parser')
    assert home.count('用微信扫一扫') == 0 and not soup.select('dialog')
    assert '待分类' not in home
    featured = next(section for section in soup.select('main section')
                    if section.find('h2') and section.find('h2').get_text() == '权威公众号精选')
    accounts = json.loads(fetch('/api/accounts?sort=featured&limit=100', 'featured-data'))['items']
    assert accounts and all(account['category'] and account['primary_category_id'] for account in accounts)
    assert {'人民日报', '央视新闻', '新华社'} <= {account['name'] for account in accounts}
    for account in accounts[:12]:
        card = featured.select_one(f'a[href="/wechat/accounts/{account["id"]}"]').find_parent('article')
        assert account['category'] in card.get_text(), account['name']
    for account_id in (accounts[0]['id'], 21):
        detail = fetch(f'/accounts/{account_id}', 'account-' + str(account_id))
        assert '用微信扫一扫' not in detail and not BeautifulSoup(detail, 'html.parser').select('dialog')
    for path in ('/discover', '/rankings', '/categories', '/categories/2', '/search'):
        clean = BeautifulSoup(fetch(path, 'clean-' + path.replace('/', '-')), 'html.parser')
        assert clean.select_one('link[rel="canonical"]')['href'] == canonical_base + path
        robots = clean.select_one('meta[name="robots"]')
        assert robots is None or 'noindex' not in robots['content']
    sitemap = ET.fromstring(fetch('/sitemap.xml', 'sitemap'))
    urls = [element.text for element in sitemap.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
    assert urls and all('?' not in url for url in urls)
    report = {'variants': rows, 'homepage_scan_phrase_count': home.count('用微信扫一扫'),
              'homepage_unclassified_phrase_count': home.count('待分类'),
              'featured_categories': {account['name']: account['category'] for account in accounts},
              'sitemap_urls': len(urls), 'sitemap_query_urls': 0}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
