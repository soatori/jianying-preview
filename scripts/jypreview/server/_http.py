"""Shared HTTP helpers (kept out of app.py to avoid a circular import)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from aiohttp import web


def json_dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def JSON(payload) -> web.Response:
    return web.json_response({"ok": True, "code": "ok", "reason": "", "data": payload},
                             dumps=json_dumps)


def error_payload(code: str, reason: str, status: int = 400, **data) -> web.Response:
    return web.json_response({"ok": False, "code": code, "reason": reason, "data": data},
                             status=status, dumps=json_dumps)


async def offload(fn, *args, **kwargs):
    """Run blocking work (subprocess decrypt, ffprobe, disk IO) off the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))


def session_of(request: web.Request):
    return request.app["session"]


def selector(request: web.Request) -> str:
    value = request.query.get("draft") or request.query.get("did") or ""
    if not value:
        raise ValueError("missing ?draft=<did|name|path>")
    return value


WEB_DIR = Path(__file__).resolve().parent.parent / "web"
