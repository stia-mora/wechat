"""Authenticated, same-origin proxy; no MP cookies are set in the user's browser."""

import os

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .auth import require_admin

router = APIRouter(prefix="/api/admin/mp-login", dependencies=[Depends(require_admin)])


def bridge(action, payload=None):
    try:
        response = httpx.post(os.environ["SOURCE_API_URL"] + "/api/bridge/mp-login/" + action,
                              headers={"Authorization": "Bearer " + os.environ["ADMIN_TOKEN"]},
                              json=payload or {}, timeout=85, trust_env=False)
        if response.status_code != 200:
            raise HTTPException(response.status_code if response.status_code in (409, 410, 429) else 502,
                                "扫码会话无效、繁忙或来源暂不可连接，请稍后重试")
        data = response.json()
        # Never forward raw upstream structures, cookies, redirects or credentials.
        return {k: data[k] for k in ("session_id", "qr", "state", "expires_in", "message", "ok") if k in data}
    except (httpx.HTTPError, ValueError, KeyError):
        raise HTTPException(502, "公众平台扫码服务暂不可连接") from None


class Session(BaseModel):
    session_id: str = Field(min_length=20, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")


@router.post("/start")
def start():
    return bridge("start")


@router.post("/poll")
def poll(data: Session):
    return bridge("poll", data.model_dump())


@router.post("/cancel")
def cancel():
    return bridge("cancel")
