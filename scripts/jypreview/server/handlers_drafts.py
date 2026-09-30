"""Draft list, detail, timeline selection and reload endpoints."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from aiohttp import web

from ..corpus import classify
from ._http import (DIST_DIR, JSON, WEB_DIR, error_payload, offload, selector,
                    session_of, static_file, static_response)


def _ui_build() -> str:
    """Token that changes whenever any UI asset changes, so an edit is never hidden by cache."""
    newest = 0
    try:
        for entry in WEB_DIR.rglob("*"):
            if entry.is_file():
                newest = max(newest, int(entry.stat().st_mtime))
    except OSError:
        pass
    return format(newest, "x")


IMPORT_RE = re.compile(r"""(?P<head>from\s+|import\s+)(?P<q>["'])(?P<spec>\./[^"']+)(?P=q)""")


async def web_asset(request: web.Request) -> web.Response:
    """Serve a UI file, stamping every relative import with the build token.

    Browsers cache ES modules by URL, so a token on app.js alone leaves ./render.js pinned to a
    stale copy; rewriting the specifiers invalidates the whole graph in one go.
    """
    rel = (request.match_info.get("path") or "").replace("\\", "/").lstrip("/")
    if _bundle_ready() and rel.startswith("src/"):
        return error_payload("editor_source_not_served",
                             "the built bundle is served from /web/dist; the TypeScript "
                             "sources are not the application", status=404)
    target = static_file(rel, WEB_DIR)
    if target is None:
        return error_payload("not_found", f"no such ui file: {rel}", status=404)
    suffix = target.suffix.lower()
    if suffix in (".js", ".css", ".html"):
        token = _ui_build()
        text = IMPORT_RE.sub(lambda m: f"{m.group('head')}{m.group('q')}{m.group('spec')}"
                                      f"?v={token}{m.group('q')}", target.read_text(encoding="utf-8"))
        kind = {"js": "text/javascript", "css": "text/css", "html": "text/html"}[suffix.lstrip(".")]
        return web.Response(text=text, content_type=kind, charset="utf-8",
                            headers={"Cache-Control": "no-cache"})
    return web.Response(body=target.read_bytes(), headers={"Cache-Control": "no-cache"})


def _bundle_ready() -> bool:
    return (DIST_DIR / "editor.html").is_file()


async def editor_index(request: web.Request) -> web.Response:
    """The built editor. Never a fallback to source: an unbuilt bundle is a build step away."""
    target = static_file("editor.html", DIST_DIR)
    if target is None:
        return error_payload("editor_not_built",
                             f"no built editor at {DIST_DIR / 'editor.html'}; run npm run build",
                             status=500, dist=str(DIST_DIR))
    return web.Response(text=target.read_text(encoding="utf-8"), content_type="text/html",
                        charset="utf-8", headers={"Cache-Control": "no-cache"})


async def editor_asset(request: web.Request) -> web.Response:
    rel = (request.match_info.get("path") or "").replace("\\", "/").lstrip("/")
    target = static_file(rel, DIST_DIR)
    if target is None:
        return error_payload("not_found", f"no such asset: {rel}", status=404)
    return static_response(target, DIST_DIR)


async def index(request: web.Request) -> web.Response:
    path = WEB_DIR / "index.html"
    if not path.is_file():
        return error_payload("ui_missing", f"{path} not found", status=500)
    token = _ui_build()
    html = path.read_text(encoding="utf-8").replace('/web/app.js"', f'/web/app.js?v={token}"') \
        .replace('/web/stage.css"', f'/web/stage.css?v={token}"')
    return web.Response(text=html, content_type="text/html", charset="utf-8")


async def list_drafts(request: web.Request) -> web.Response:
    session = session_of(request)
    index_data = await offload(session.index)
    rows = index_data.get("rows", [])
    query = (request.query.get("q") or "").strip().lower()
    layout = request.query.get("layout")
    encoding = request.query.get("encoding")
    if query:
        rows = [row for row in rows if query in row["name"].lower() or query == row["did"]
                or query in str(row.get("path", "")).lower()]
    if layout:
        rows = [row for row in rows if row.get("layout") == layout]
    if encoding:
        rows = [row for row in rows if row.get("encoding") == encoding]
    sort = request.query.get("sort") or "mtime"
    rows = sorted(rows, key=lambda row: (row.get("mtime_iso") or "") if sort == "mtime" else row["name"],
                  reverse=sort == "mtime")
    total = len(rows)
    offset = int(request.query.get("offset") or 0)
    limit = min(int(request.query.get("limit") or 100), 500)
    items = []
    for row in rows[offset:offset + limit]:
        items.append({
            "did": row["did"], "name": row["name"], "layout": row.get("layout"),
            "encoding": row.get("encoding"), "has_content": row.get("has_content", True),
            "mtime": row.get("mtime_iso"), "cover": f"/thumb?draft={row['did']}" if row.get("cover") else None,
            "timeline_count": row.get("timeline_count", 0),
            "active_timeline_id": row.get("active_timeline_id"), "note": row.get("note"),
            "timelines": [{"tid": item["id"], "name": item.get("name"), "deleted": item.get("deleted"),
                           "active": item.get("active"), "duration_us": item.get("duration_us"),
                           "encoding": item.get("encoding")} for item in row.get("timelines", [])],
        })
    return JSON({"drafts_root": index_data.get("drafts_root"), "built_at": index_data.get("built_at"),
                 "total": total, "offset": offset, "count": len(items), "items": items})


async def pick_folder(request: web.Request) -> web.Response:
    """Open the OS folder picker and return what the user chose ("" if cancelled)."""
    session = session_of(request)
    initial = request.query.get("path") or str(session.config.drafts_root or Path.home())

    def dialog() -> str:
        import tkinter
        from tkinter import filedialog

        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            return str(filedialog.askdirectory(parent=root, initialdir=initial,
                                               title="选择剪映草稿文件夹") or "")
        finally:
            root.destroy()

    try:
        chosen = await offload(dialog)
    except ImportError as exc:
        return error_payload("no_folder_dialog", f"tkinter unavailable: {exc}", status=501)
    return JSON({"path": chosen, "cancelled": not chosen})


async def rescan(request: web.Request) -> web.Response:
    session = session_of(request)
    from ..corpus import scan, write_index

    data = await offload(lambda: write_index(session.config.corpus_index_path,
                                             session.config.drafts_root,
                                             scan(session.config.drafts_root)))
    return JSON(data)


async def draft_detail(request: web.Request) -> web.Response:
    session = session_of(request)
    view = await offload(session.view, selector(request))
    payload = view.describe()
    payload["path"] = str(view.root)
    return JSON(payload)


async def timelines(request: web.Request) -> web.Response:
    session = session_of(request)
    view = await offload(session.view, selector(request))
    rows = []
    for entry in view.describe()["timelines"]:
        ratio = await offload(lambda: _media_hit(view, entry["id"])) if entry["content_exists"] else None
        rows.append({**entry, "media_hit_ratio": ratio})
    return JSON({
        "did": view.did, "name": view.name, "layout": view.layout,
        "path": str(view.root), "active_timeline_id": view.active_timeline_id,
        "active_evidence": view.probe.get("active_evidence", []),
        "mirror_drift": view.mirror, "cache": view.cache.describe(),
        "timelines": rows})


def _media_hit(view, tid: str) -> dict:
    try:
        content, _meta = view.content(tid)
    except Exception as exc:
        return {"error": str(exc)}
    total = ok = 0
    for _track, segment, _position in content.segments():
        material = content.material(segment.get("material_id"))
        if not material or material[0] not in ("videos", "audios", "stickers"):
            continue
        total += 1
        path = str(material[1].get("path") or "")
        if path and Path(path.replace("\\", "/")).is_file():
            ok += 1
    return {"total": total, "present": ok, "ratio": round(ok / total, 3) if total else None}


async def reload_draft(request: web.Request) -> web.Response:
    session = session_of(request)
    view = await offload(lambda: session.view(selector(request), force=True))
    tid = request.query.get("timeline")
    if tid:
        await offload(lambda: view.content(view.resolve_timeline(tid)["id"]))
    request.app["hub"].publish("draft.changed", {"did": view.did, "source_sha256":
                                                 (view.timelines[0].get("replicas") or [{}])[0].get("sha256")})
    return JSON({"did": view.did, "timelines": len(view.timelines),
                 "cache": view.cache.describe(), "mirror_drift": view.mirror})
