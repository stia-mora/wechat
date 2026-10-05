"""Verify gateway, independent login and reports using curl; never echo credentials."""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url', required=True)
parser.add_argument('--credentials-file', type=Path)
parser.add_argument('--local-test', action='store_true')
args = parser.parse_args()
if args.local_test:
    password = 'local-test-password'
else:
    if not args.credentials_file:
        parser.error('--credentials-file required for production')
    password = next(line.removeprefix('Password: ') for line in args.credentials_file.read_text(encoding='utf-8').splitlines() if line.startswith('Password: '))

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    cookies = root / 'cookies'
    def curl(path, method='GET', data=None, auth=False, extra=None):
        output, headers = root / 'body', root / 'headers'
        command = ['curl.exe', '-sS', '--max-time', '45', '-A', 'traffic-verify/1.0', '-o', str(output), '-D', str(headers), '-w', '%{http_code}', args.url.rstrip('/') + path]
        if method != 'GET':
            command.extend(['-X', method])
        if auth:
            command.extend(['-b', str(cookies), '-c', str(cookies)])
        if data is not None:
            payload = root / 'payload'
            payload.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            command.extend(['-H', 'Content-Type: application/json', '--data-binary', '@' + str(payload)])
        if path == '/traffic/login' and not extra:
            command.extend(['-c', str(cookies)])
        command.extend(extra or [])
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        return int(result.stdout), output.read_text(encoding='utf-8'), headers.read_text(encoding='utf-8')

    status, body, headers = curl('/traffic')
    assert status == 200 and 'login-form' in body
    assert 'no-store' in headers and 'noindex' in headers
    print('PASS /traffic: 200, independent login, no-store, noindex')
    for path in ('/traffic/api/summary', '/traffic/report'):
        assert curl(path)[0] == 401
        print('PASS ' + path + ': unauthenticated 401')
    assert curl('/traffic/login', 'POST', {'username': 'admin', 'password': password})[0] == 200
    status, body, _ = curl('/traffic', auth=True)
    assert status == 200 and '浏览器上报访问' in body
    for days in (1, 7, 30):
        status, body, _ = curl('/traffic/api/summary?days=' + str(days), auth=True)
        assert status == 200
        summary = json.loads(body)
        assert summary['days'] == days and summary['engine'] == 'GoAccess 1.12'
        print(f'PASS authenticated summary days={days}: HTTP={summary["http_requests"]}, browserPV={summary["browser_pv"]}, AI={summary["types"]["AI 爬虫 / 助手"]}')
    assert curl('/traffic/events', 'POST', {'path': '/wechat/admin'})[0] == 422
    assert curl('/traffic/events', 'POST', {'path': '/wechat/search?q=private'})[0] == 422
    assert curl('/traffic/login', 'POST', {'username': 'admin', 'password': password}, extra=['-H', 'Origin: https://evil.example'])[0] == 403
    status, _, _ = curl('/wechat/api/admin/accounts/1', 'PATCH', {'description': '测' * 3000})
    assert status in (401, 403), status
    print('PASS >4KiB existing API body forwarded; upstream denies unauthorized request, gateway did not return413')
    status, body, _ = curl('/wechat')
    assert status == 200 and '权威公众号精选' in body and '/traffic/collect.js' in body
    assert '用微信扫一扫' not in body and '待分类' not in body
    print('PASS site HTML: SSR content and collector present, prior GEO text cleanup preserved')
    assert curl('/traffic/logout', 'POST', auth=True)[0] == 200
    assert curl('/traffic/api/summary', auth=True)[0] == 401
    print('PASS logout invalidates browser cookie')
