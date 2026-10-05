"""GoAccess remains the parsing and aggregation engine; this adds site-specific views."""
import json
import logging
import os
import re
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('Asia/Shanghai')
LOGS = Path(os.getenv('TRAFFIC_LOGS', '/logs'))
DATA = Path(os.getenv('TRAFFIC_DATA', '/data'))
STATIC = Path(__file__).parent / 'static'
SEARCH_DOMAINS = ('bing.com', 'baidu.com', 'sogou.com', 'so.com', 'yahoo.com', 'yandex.ru', 'duckduckgo.com')
AI_DOMAINS = ('chatgpt.com', 'openai.com', 'perplexity.ai', 'claude.ai', 'gemini.google.com',
              'copilot.microsoft.com', 'doubao.com', 'yuanbao.tencent.com', 'kimi.com', 'moonshot.cn', 'deepseek.com')


def now():
    return datetime.now(ZONE)


def source_host(value):
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        return host.lower() if parsed.scheme in ('http', 'https') and host and len(host) <= 253 and re.fullmatch(r'[a-zA-Z0-9.-]+', host) else ''
    except ValueError:
        return ''


def source_kind(host):
    def matches(domains):
        return any(host == domain or host.endswith('.' + domain) for domain in domains)
    if host == 'wechat.aim888888.xyz':
        return '站内'
    if matches(AI_DOMAINS):
        return 'AI 平台引荐'
    if matches(SEARCH_DOMAINS) or re.search(r'(^|\.)google\.(com|[a-z]{2}|com\.[a-z]{2}|co\.[a-z]{2})$', host):
        return '搜索引擎'
    return '外部引荐'


def hits(row):
    return row.get('hits', {}).get('count', 0)


def panel(report, name):
    return report.get(name, {}).get('data', [])


def summarize(http, browser):
    kinds = {'AI 爬虫 / 助手': 0, '传统爬虫': 0, '自动化 / HTTP 工具': 0, '浏览器请求': 0, '其他 / 未知': 0}
    ai = []
    for group in panel(http, 'browsers'):
        name = group['data']
        if name == 'AI Crawlers':
            kind = 'AI 爬虫 / 助手'
            ai.extend({'name': row['data'], 'requests': hits(row)} for row in group.get('items', []))
        elif name in ('Crawlers', 'Feeds', 'Fediverse', 'Uptime'):
            kind = '传统爬虫'
        elif name in ('Automation', 'HTTP Library'):
            kind = '自动化 / HTTP 工具'
        elif name in ('Chrome', 'Firefox', 'Safari', 'Edge', 'Opera', 'MSIE', 'Vivaldi', 'Brave', 'Android Browser'):
            kind = '浏览器请求'
        else:
            kind = '其他 / 未知'
        if name == 'Others':
            tools = sum(hits(row) for row in group.get('items', [])
                        if re.search(r'curl|wget|python|httpclient|node-fetch|libwww', row['data'], re.I))
            kinds['自动化 / HTTP 工具'] += tools
            kinds[kind] += hits(group) - tools
        else:
            kinds[kind] += hits(group)
    sources = [{'host': row['data'], 'kind': source_kind(row['data']), 'views': hits(row)}
               for row in panel(browser, 'referring_sites')]
    total = browser.get('general', {}).get('valid_requests', 0)
    listed = sum(row['views'] for row in sources)
    referred = browser.get('referring_sites', {}).get('metadata', {}).get('hits', {}).get('total', {}).get('value', listed)
    omitted = max(0, referred - listed)
    if omitted:
        sources.append({'host': '其他未列出的引荐域名', 'kind': '其他来源', 'views': omitted})
    missing = max(0, total - referred)
    if missing:
        sources.append({'host': '无引荐信息', 'kind': '直接 / 未知', 'views': missing})
    return {'http_requests': http.get('general', {}).get('valid_requests', 0),
            'browser_pv': total, 'browser_uv': browser.get('general', {}).get('unique_visitors', 0),
            'types': kinds, 'ai': ai, 'sources': sorted(sources, key=lambda row: -row['views']),
            'pages': [{'path': row['data'], 'views': hits(row)} for row in panel(browser, 'requests')],
            'daily': [{'date': row['data'], 'views': hits(row)} for row in panel(browser, 'visitors')],
            'status_codes': [{'status': row['data'], 'requests': hits(row)} for row in panel(http, 'status_codes')]}


def log_files(channel, days):
    root = LOGS if channel == 'http' else DATA / 'browser'
    prefix = 'access' if channel == 'http' else 'browser'
    today = now().date()
    return [root / f'{prefix}-{today - timedelta(days=offset)}.log'
            for offset in reversed(range(days))
            if (root / f'{prefix}-{today - timedelta(days=offset)}.log').exists()]


def analyze(files, output, html=None):
    if not files or not any(path.stat().st_size for path in files):
        output.unlink(missing_ok=True)
        if html:
            html.unlink(missing_ok=True)
        return {}
    temporary = output.with_name(output.stem + '.tmp.json')
    args = ['goaccess', *map(str, files), '--log-format=COMBINED', '--no-progress',
            '--no-query-string', '--ignore-panel=HOSTS',
            '--max-items=500', '--browsers-file=' + str(Path(__file__).parent / 'browsers.list'),
            '--output=' + str(temporary)]
    if html:
        args.extend(['--output=' + str(html.with_suffix('.tmp.html')), '--html-report-title=WeChat Source Traffic'])
    subprocess.run(args, check=True, timeout=45, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    report = json.loads(temporary.read_text())
    temporary.replace(output)
    if html:
        html.with_suffix('.tmp.html').replace(html)
    return report


def refresh():
    reports = DATA / 'reports'
    reports.mkdir(parents=True, exist_ok=True)
    for days in (1, 7, 30):
        http = analyze(log_files('http', days), reports / f'http-{days}.json', reports / 'goaccess.html' if days == 30 else None)
        browser = analyze(log_files('browser', days), reports / f'browser-{days}.json')
        result = summarize(http, browser)
        result.update(updated_at=now().isoformat(), days=days, engine='GoAccess 1.12',
                      collection_started_at=(DATA / 'started.txt').read_text(encoding='ascii').strip())
        target = reports / f'summary-{days}.json'
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        temporary.replace(target)


def run(stop: threading.Event):
    while not stop.is_set():
        try:
            refresh()
            cutoff = now().date() - timedelta(days=30)
            for root, prefix in ((LOGS, 'access'), (DATA / 'browser', 'browser')):
                for path in root.glob(prefix + '-*.log'):
                    match = re.fullmatch(prefix + r'-(\d{4}-\d{2}-\d{2})\.log', path.name)
                    if match and datetime.strptime(match[1], '%Y-%m-%d').date() <= cutoff:
                        path.unlink()
        except (OSError, ValueError, subprocess.SubprocessError):
            logging.exception('Traffic report refresh failed; previous reports retained')
        stop.wait(60)
