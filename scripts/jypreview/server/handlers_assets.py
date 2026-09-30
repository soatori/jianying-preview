"""Byte-range media, fonts, images and sandboxed effect-bundle reads."""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path

from aiohttp import web

from ..draft_id import inside, safe_rel
from ._http import JSON, error_payload, offload, selector, session_of

FONT_TYPES = {".ttf": "font/ttf", ".otf": "font/otf", ".ttc": "font/collection",
              ".woff2": "font/woff2", ".woff": "font/woff"}
EFFECT_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".ttf", ".otf", ".json", ".frag",
                   ".vert", ".material", ".xshader", ".mesh", ".scene", ".prefab", ".config"}


def _registry_response(request: web.Request, key: str, kind: str) -> web.Response:
    if not key:
        return error_payload("invalid_input", f"missing ?f= for {kind}")
    record = request.app["session"].registry.resolve(key)
    if not record or record.get("missing"):
        return error_payload("not_registered", f"no registered {kind} for key {key}", status=404)
    if kind == "media" and record.get("kind") == "font":
        kind = "font"
    path = Path(record["path"])
    if kind == "font":
        ctype = FONT_TYPES.get(path.suffix.lower(), "application/octet-stream")
    else:
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return web.FileResponse(path, headers={"Content-Type": ctype, "Accept-Ranges": "bytes",
                                           "Cache-Control": "public, max-age=31536000, immutable"})


async def media(request: web.Request) -> web.Response:
    return _registry_response(request, request.query.get("f", ""), "media")


async def font(request: web.Request) -> web.Response:
    return _registry_response(request, request.query.get("f", ""), "font")


async def image(request: web.Request) -> web.Response:
    return _registry_response(request, request.query.get("f", ""), "image")


async def thumb(request: web.Request) -> web.Response:
    session = session_of(request)

    def locate() -> Path | None:
        row = session.row(selector(request))
        root = Path(row["path"])
        tid = request.query.get("timeline")
        candidates = []
        if tid:
            candidates.append(root / "Timelines" / str(tid) / "draft_cover.jpg")
        candidates += [root / "draft_cover.jpg", root / "Resources" / "default_cover.jpg"]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    path = await offload(locate)
    if not path:
        return error_payload("cover_missing", "this draft has no draft_cover.jpg", status=404)
    return web.FileResponse(path, headers={"Content-Type": "image/jpeg"})


def _effect_dir(request: web.Request) -> Path | None:
    cache = session_of(request).config.effect_cache
    return Path(cache) if cache else None


async def effect_file(request: web.Request) -> web.Response:
    cache = _effect_dir(request)
    if not cache or not cache.is_dir():
        return error_payload("cache_missing", "no JianYing effect cache on this machine", status=404)
    effect_id = request.query.get("effect_id") or request.query.get("resource_id") or ""
    md5 = request.query.get("md5") or ""
    rel = request.query.get("rel") or "config.json"
    if not effect_id:
        return error_payload("invalid_input", "missing ?effect_id=")
    try:
        relative = safe_rel(rel)
    except ValueError as exc:
        return error_payload("invalid_input", str(exc))

    def find() -> Path | None:
        for bucket in ("effect", "artistEffect"):
            for ident in [value for value in (effect_id, md5) if value]:
                base = cache / bucket / ident
                if not base.is_dir():
                    continue
                exact = base / md5 / relative if md5 else base / relative
                if exact.is_file():
                    return exact
                matches = sorted(base.glob(f"*/{relative}"))
                if matches:
                    return matches[0]
        return None

    target = find()
    if target is None:
        return error_payload("bundle_missing", f"no local bundle for {effect_id}/{rel}", status=404)
    if not inside(cache, target):
        return error_payload("traversal_refused", "path escapes the effect cache", status=400)
    if target.suffix.lower() not in EFFECT_SUFFIXES:
        return error_payload("suffix_refused", f"refusing to serve {target.suffix}", status=400)
    ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return web.FileResponse(target, headers={"Content-Type": ctype})


async def effect_style(request: web.Request) -> web.Response:
    """Parsed 花字 recipe (``effectStyle.json``) for an artistEffect bundle."""
    cache = _effect_dir(request)
    rid = request.query.get("rid") or request.query.get("resource_id") or ""
    md5 = request.query.get("md5") or ""
    if not cache or not rid:
        return JSON({"render_class": "placeholder", "reason": "no resource id"})
    base = Path(cache) / "artistEffect" / rid
    candidate = (base / md5 / "effectStyle.json") if md5 else None
    if not (candidate and candidate.is_file()):
        matches = sorted(base.glob(f"*/effectStyle.json"))
        candidate = matches[0] if matches else None
    if candidate is None or not candidate.is_file():
        covers = sorted(base.glob("*/*"))
        return JSON({"render_class": "placeholder", "resource_id": rid,
                     "reason": "no local effectStyle.json",
                     "bundle_entries": [path.name for path in covers[:12]]})
    try:
        recipe = json.loads(candidate.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return error_payload("invalid_json", str(exc))
    return web.json_response({"ok": True, "code": "ok", "reason": "", "data": {
        "render_class": "exact", "resource_id": rid, "md5": md5 or candidate.parent.name,
        "bundle": str(candidate.parent), "recipe": recipe}},
        dumps=lambda value: json.dumps(value, ensure_ascii=False))
