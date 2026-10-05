import hashlib
import hmac
import ipaddress
import json
import os
import re
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

import analyzer

COOKIE = 'traffic_session'
failures = deque()
failure_lock = threading.Lock()
log_lock = threading.Lock()
PUBLIC_PATH = re.compile(r'^/wechat/?$|^/wechat/(discover|rankings|search|categories)(/\d+)?/?$|^/wechat/(accounts|articles)/\d+/?$')


@asynccontextmanager
async def lifespan(app):
    if len(os.environ.get('TRAFFIC_SESSION_KEY', '')) < 32 or not os.environ.get('TRAFFIC_PASSWORD_HASH'):
        raise RuntimeError('Traffic credentials must be configured before startup')
    (analyzer.DATA / 'browser').mkdir(parents=True, exist_ok=True)
    started = analyzer.DATA / 'started.txt'
    if not started.exists():
        started.write_text(analyzer.now().isoformat(), encoding='ascii')
    stop = threading.Event()
    thread = threading.Thread(target=analyzer.run, args=(stop,), daemon=True)
    thread.start()
    yield
    stop.set()
    thread.join(timeout=3)


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware('http')
async def security(request: Request, call_next):
    origin = request.headers.get('origin')
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and origin and origin != os.environ['TRAFFIC_ORIGIN']:
        response = JSONResponse({'detail': '不允许跨站请求'}, status_code=403)
    else:
        response = await call_next(request)
    response.headers.update({'Cache-Control': 'private, no-store', 'CDN-Cache-Control': 'no-store',
                             'Cloudflare-CDN-Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex, nofollow',
                             'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'SAMEORIGIN',
                             'Referrer-Policy': 'same-origin'})
    scripts = "'self' 'unsafe-inline'" if request.url.path == '/traffic/report' else "'self'"
    response.headers['Content-Security-Policy'] = ("default-src 'self'; script-src " + scripts +
        "; style-src 'self' 'unsafe-inline'; img-src 'self' data:; base-uri 'none'; form-action 'self'; frame-ancestors 'self'")
    return response


def signature(value):
    return hmac.new(os.environ['TRAFFIC_SESSION_KEY'].encode(), value.encode(), hashlib.sha256).hexdigest()


def authenticated(request: Request):
    value = request.cookies.get(COOKIE, '')
    try:
        expiry, digest = value.split('.')
        return int(expiry) > time.time() and hmac.compare_digest(digest.encode(), signature(expiry).encode())
    except (ValueError, OverflowError):
        return False


def require_admin(request: Request):
    if not authenticated(request):
        raise HTTPException(401, '请先登录监控后台')


class Login(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(min_length=1, max_length=256)


@app.post('/traffic/login')
def login(data: Login, response: Response):
    with failure_lock:
        current = time.monotonic()
        while failures and failures[0] <= current - 60:
            failures.popleft()
        if len(failures) >= 10:
            raise HTTPException(429, '尝试过于频繁，请稍后重试', headers={'Retry-After': '60'})
        salt, expected = os.environ['TRAFFIC_PASSWORD_HASH'].split(':')
        actual = hashlib.pbkdf2_hmac('sha256', data.password.encode(), bytes.fromhex(salt), 180000).hex()
        if data.username != 'admin' or not hmac.compare_digest(actual, expected):
            failures.append(current)
            raise HTTPException(403, '用户名或密码不正确')
    expiry = str(int(time.time()) + 12 * 3600)
    response.set_cookie(COOKIE, expiry + '.' + signature(expiry), max_age=12 * 3600,
                        httponly=True, secure=True, samesite='strict', path='/traffic')
    return {'ok': True}


@app.post('/traffic/logout')
def logout(response: Response):
    response.delete_cookie(COOKIE, path='/traffic')
    return {'ok': True}


@app.get('/traffic', response_class=HTMLResponse)
@app.get('/traffic/', response_class=HTMLResponse)
def dashboard(request: Request):
    return (analyzer.STATIC / ('dashboard.html' if authenticated(request) else 'login.html')).read_text(encoding='utf-8')


@app.get('/traffic/api/summary', dependencies=[Depends(require_admin)])
def summary(days: int = 1):
    if days not in (1, 7, 30):
        raise HTTPException(422, '请选择今天、7天或30天')
    path = analyzer.DATA / 'reports' / f'summary-{days}.json'
    if not path.exists():
        raise HTTPException(503, '监控已启动，正在生成第一份报表')
    return json.loads(path.read_text(encoding='utf-8'))


@app.get('/traffic/report', dependencies=[Depends(require_admin)])
def report():
    path = analyzer.DATA / 'reports' / 'goaccess.html'
    if not path.exists():
        return HTMLResponse('<meta charset="utf-8"><p>尚无公开请求日志，访问网站后一分钟内生成报告。</p>')
    return FileResponse(path, media_type='text/html')


@app.get('/traffic/health')
def health():
    return {'status': 'ok'}


@app.get('/traffic/{asset}')
def asset(asset: str):
    if asset not in ('style.css', 'tokens.css', 'dashboard.js', 'login.js', 'collect.js'):
        raise HTTPException(404)
    return FileResponse(analyzer.STATIC / asset)


class PageEvent(BaseModel):
    path: str = Field(max_length=256)
    referrer: str = Field(default='', max_length=2048)


@app.post('/traffic/events', status_code=204)
def event(data: PageEvent, request: Request):
    if not PUBLIC_PATH.fullmatch(data.path):
        raise HTTPException(422, '非公开内容页')
    # Only the gateway can reach this service; it overwrites X-Real-IP.
    client = request.headers.get('x-real-ip', request.client.host)
    try:
        ipaddress.ip_address(client)
    except ValueError:
        raise HTTPException(422, '无效请求')
    current = analyzer.now()
    visitor = hmac.new(os.environ['TRAFFIC_SESSION_KEY'].encode(),
                       (str(current.date()) + client).encode(), hashlib.sha256).digest()[:16]
    address = str(ipaddress.IPv6Address(visitor))
    host = analyzer.source_host(data.referrer)
    referrer = 'https://' + host + '/' if host else '-'
    agent = request.headers.get('user-agent', '-')[:1024]
    agent = re.sub(r'["\\\r\n\t]', '_', agent)
    stamp = current.strftime('%d/%b/%Y:%H:%M:%S %z')
    line = f'{address} - - [{stamp}] "GET {data.path} HTTP/1.1" 200 0 "{referrer}" "{agent}"\n'
    folder = analyzer.DATA / 'browser'
    folder.mkdir(parents=True, exist_ok=True)
    with log_lock, (folder / f'browser-{current.date()}.log').open('a', encoding='utf-8') as stream:
        stream.write(line)
    return Response(status_code=204)
