# SPDX-License-Identifier: AGPL-3.0-only
"""Local extension of wechat-download-api; upstream checkout stays unchanged.

History request/decoding adapted from upstream routes/admin.py (tmwgsicp, 2026).
"""

import json
import secrets
import sys
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import dotenv_values
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ref" / "wechat-download-api"))

from app import app
from routes.article import ArticleRequest, get_article
from utils import rss_store
from utils.auth_manager import auth_manager


def authenticate(authorization: str = Header(default="")):
    token = dotenv_values(ROOT / ".env").get("ADMIN_TOKEN") or ""
    if not token or not secrets.compare_digest(authorization, "Bearer " + token):
        raise HTTPException(403, "需要采集桥接密钥")


router = APIRouter(prefix="/api/bridge", dependencies=[Depends(authenticate)])


@router.get("/articles")
def cached_articles(
    fakeid: str, after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100)
):
    # ID pagination retains articles sharing one publication timestamp. Rescan on each
    # import so filling an old row's body cannot fall behind an incremental cursor.
    with closing(rss_store._get_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM articles WHERE fakeid=? AND id>? ORDER BY id LIMIT ?",
            (fakeid, after, limit),
        ).fetchall()
        counts = conn.execute(
            "SELECT count(*) AS articles, sum(CASE WHEN content<>'' THEN 1 ELSE 0 END) AS bodies FROM articles WHERE fakeid=?",
            (fakeid,),
        ).fetchone()
    return {
        "success": True,
        "data": {
            "items": [dict(r) for r in rows],
            "next_after": rows[-1]["id"] if rows else after,
            "articles": counts["articles"],
            "bodies": counts["bodies"] or 0,
        },
    }


class HistoryPage(BaseModel):
    fakeid: str
    begin: int = Field(0, ge=0, le=10000)


class SeedArticle(BaseModel):
    fakeid: str
    nickname: str
    title: str
    link: str
    publish_time: int = 0
    author: str = ""
    cover: str = ""
    digest: str = ""


@router.post("/articles")
def seed_article(data: SeedArticle):
    parsed = urlparse(data.link)
    if parsed.scheme not in ("http", "https") or parsed.hostname != "mp.weixin.qq.com":
        raise HTTPException(422, "只允许微信文章链接")
    rss_store.add_subscription(data.fakeid, data.nickname)
    rss_store.save_articles(data.fakeid, [data.model_dump()])
    with closing(rss_store._get_conn()) as conn:
        row = conn.execute(
            "SELECT * FROM articles WHERE fakeid=? AND link=?", (data.fakeid, data.link)
        ).fetchone()
    return {"success": True, "data": dict(row)}


@router.post("/history")
async def history_page(data: HistoryPage):
    creds = auth_manager.get_credentials()
    if not creds or not creds.get("token") or not creds.get("cookie"):
        return {"success": False, "error": "未登录，请先扫码登录"}
    if not rss_store.get_subscription(data.fakeid):
        raise HTTPException(409, "请先订阅公众号")
    params = {
        "begin": data.begin,
        "count": 10,
        "fakeid": data.fakeid,
        "type": "101_1",
        "free_publish_type": 1,
        "sub_action": "list_ex",
        "token": creds["token"],
        "lang": "zh_CN",
        "f": "json",
        "ajax": 1,
    }
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        response = await client.get(
            "https://mp.weixin.qq.com/cgi-bin/appmsgpublish",
            params=params,
            headers={
                "Cookie": creds["cookie"],
                "Referer": "https://mp.weixin.qq.com/",
                "User-Agent": "Mozilla/5.0",
            },
        )
        if response.status_code in (401, 403, 429):
            raise HTTPException(
                response.status_code, "微信历史接口需要认证或限制了请求"
            )
        if response.is_error:
            raise HTTPException(502, "微信历史接口暂不可用")
        result = response.json()
    ret = result.get("base_resp", {}).get("ret", -1)
    if ret != 0:
        return {
            "success": False,
            "error": f"微信历史接口 ret={ret}，可能需要重新登录、验证或等待限流恢复",
        }
    page = result.get("publish_page", {})
    if isinstance(page, str):
        page = json.loads(page)
    batches = page.get("publish_list", [])
    articles = []
    for batch in batches:
        info = batch.get("publish_info", {})
        if isinstance(info, str):
            info = json.loads(info)
        for item in info.get("appmsgex", []):
            if item.get("link"):
                articles.append({**item, "publish_time": item.get("update_time", 0)})
    rss_store.save_articles(data.fakeid, articles, source="deep_fetch")
    return {
        "success": True,
        "data": {
            "fetched": len(articles),
            "next_begin": data.begin + len(batches),
            "has_more": len(batches) == 10,
        },
    }


@router.post("/articles/{article_id}/body")
async def persist_body(article_id: int, request: Request):
    article = rss_store.get_article_by_id(article_id)
    if not article:
        raise HTTPException(404, "缓存文章不存在")
    if article.get("content"):
        return {"success": True, "data": article}
    parsed = urlparse(article["link"])
    if parsed.scheme not in ("http", "https") or parsed.hostname != "mp.weixin.qq.com":
        raise HTTPException(422, "只允许微信文章链接")
    result = await get_article(ArticleRequest(url=article["link"]), request)
    if not result.get("success"):
        return result
    body = result.get("data") or {}
    if not body.get("content") or not body.get("plain_content", "").strip():
        return {"success": False, "error": "未返回可读正文，未写入导出库"}
    # Upstream's conflict update omits title/time. Commit body and metadata together
    # so interruption cannot leave a readable cache row with placeholder metadata.
    with closing(rss_store._get_conn()) as conn:
        conn.execute(
            "UPDATE articles SET title=?,publish_time=?,author=?,content=?,plain_content=? WHERE id=?",
            (
                body.get("title") or article["title"],
                body.get("publish_time") or article["publish_time"],
                body.get("author") or article["author"],
                body["content"],
                body["plain_content"],
                article_id,
            ),
        )
        conn.commit()
    return {"success": True, "data": rss_store.get_article_by_id(article_id)}


app.include_router(router)
