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
DIST_DIR = WEB_DIR / "dist"

STATIC_TYPES = {
    ".js": ("text/javascript", True),
    ".mjs": ("text/javascript", True),
    ".css": ("text/css", True),
    ".html": ("text/html", True),
    ".json": ("application/json", False),
    ".map": ("application/json", False),
    ".svg": ("image/svg+xml", False),
    ".png": ("image/png", False),
    ".jpg": ("image/jpeg", False),
    ".woff2": ("font/woff2", False),
    ".woff": ("font/woff", False),
    ".ttf": ("font/ttf", False),
}


def static_file(rel: str, root: Path = WEB_DIR) -> Path | None:
    """Resolve a UI asset inside ``root``; anything that escapes it is not served.

    Vite emits hashed filenames under ``dist/assets``, so those are the only paths
    allowed to be cached forever.
    """
    cleaned = str(rel or "").replace("\\", "/").lstrip("/")
    if not cleaned or "\x00" in cleaned or ":" in cleaned:
        return None
    target = (root / cleaned).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        return None
    return target


def static_response(target: Path, root: Path = WEB_DIR) -> web.Response:
    kind, textual = STATIC_TYPES.get(target.suffix.lower(), (None, False))
    headers = {"Cache-Control": "public, max-age=31536000, immutable"
               if _is_hashed(target, root) else "no-cache"}
    if kind is None:
        return web.Response(body=target.read_bytes(), headers=headers)
    if textual:
        return web.Response(text=target.read_text(encoding="utf-8"), content_type=kind,
                            charset="utf-8", headers=headers)
    return web.Response(body=target.read_bytes(), content_type=kind, headers=headers)


def _is_hashed(target: Path, root: Path) -> bool:
    parts = target.relative_to(root).parts
    return "assets" in parts and any("-" in name and "." in name for name in parts[-1:])
