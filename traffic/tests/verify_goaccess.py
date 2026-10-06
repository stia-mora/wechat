"""Run inside the local GoAccess build image; synthetic data never reaches production."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
import analyzer

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    stamp = analyzer.now().strftime('%d/%b/%Y:%H:%M:%S %z')
    agents = ['Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
              'Mozilla/5.0 (compatible; GPTBot/1.2; +https://openai.com/gptbot)',
              'Mozilla/5.0 (compatible; ChatGPT-User/1.0; +https://openai.com/bot)',
              'Googlebot/2.1 (+http://www.google.com/bot.html)', 'HeadlessChrome/120.0.0.0',
              'curl/8.9.1', 'unidentified-test-client']
    http = root / 'http.log'
    http.write_text(''.join(f'192.0.2.{i + 1} - - [{stamp}] "GET /wechat HTTP/1.1" 200 100 "-" "{agent}" '
                    '{"country":"CN","region":"Zhejiang","city":"Hangzhou"}\n' for i, agent in enumerate(agents)), encoding='utf-8')
    browser = root / 'browser.log'
    browser.write_text(''.join(f'2001:db8::{i + 1} - - [{stamp}] "GET /wechat/discover HTTP/1.1" 200 0 "https://{host}/" "{agents[0]}"\n' for i, host in enumerate(['www.google.com', 'chatgpt.com', 'www.google.com'])), encoding='utf-8')
    http_report = analyzer.analyze([http], root / 'http.json', root / 'http.html')
    browser_report = analyzer.analyze([browser], root / 'browser.json')
    summary = analyzer.summarize(http_report, browser_report)
    assert summary['http_requests'] == 7, summary
    geography = analyzer.location_summary([http], [browser])
    assert geography['countries'] == [{'country': '-', 'http_requests': 0, 'browser_pv': 3},
                                      {'country': 'CN', 'http_requests': 7, 'browser_pv': 0}]
    assert summary['types'] == {'AI 爬虫 / 助手': 2, '传统爬虫': 1, '自动化 / HTTP 工具': 2, '浏览器请求': 1, '其他 / 未知': 1}, summary
    assert summary['browser_pv'] == 3 and summary['browser_uv'] == 3, summary
    assert summary['sources'] == [{'host': 'www.google.com', 'kind': '搜索引擎', 'views': 2}, {'host': 'chatgpt.com', 'kind': 'AI 平台引荐', 'views': 1}], summary
    assert 'hosts' not in http_report and '192.0.2.' not in (root / 'http.html').read_text(), 'Private client addresses leaked into report'
    assert summary['daily'][0]['views'] == 3
    assert browser_report['referring_sites']['metadata']['hits']['total']['value'] == 3
    attack = root / 'attack.log'
    attack.write_text(f'192.0.2.10 - - [{stamp}] "GET /wechat/<script>alert(987654)</script> HTTP/1.1" 404 0 "-" "curl/8.9.1"\n')
    analyzer.analyze([attack], root / 'attack.json', root / 'attack.html')
    assert '<script>alert(987654)</script>' not in (root / 'attack.html').read_text(), 'Untrusted request injected a script tag'
    print(json.dumps(summary, ensure_ascii=False))
