"""Draft list, detail, timeline selection and reload endpoints."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from aiohttp import web

from ..corpus import classify
from ._http import JSON, WEB_DIR, error_payload, offload, selector, session_of


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
    root = WEB_DIR.resolve()
    target = (root / rel).resolve()
    if not target.is_relative_to(root) or not target.is_file():
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


def _is_drafts_root(chosen: str) -> bool:
    """True when the picked folder is a *Drafts* container (children are drafts), not one draft.

    Picking the root is the natural mistake with a folder browser, and it used to fail as an
    unexplained "cannot open"; the page now says so instead.
    """
    folder = Path(chosen) if chosen else None
    if folder is None or not folder.is_dir() or (folder / "draft_content.json").is_file():
        return False
    try:
        children = list(folder.iterdir())
    except OSError:
        return False
    return sum(1 for child in children
               if child.is_dir() and (child / "draft_content.json").is_file()) >= 2


_TK_SNIPPET = (
    "import sys, tkinter, tkinter.filedialog as fd; "
    "root = tkinter.Tk(); root.withdraw(); root.attributes('-topmost', True); "
    "path = fd.askdirectory(title='选择剪映草稿文件夹', initialdir=sys.argv[1]) or ''; "
    "root.destroy(); sys.stdout.buffer.write(path.encode('utf-8'))"
)


def _tkinter_python() -> list[list[str]]:
    """Candidate interpreters that can show the dialog, best first.

    The dialog path is written back as UTF-8 bytes on purpose: this box's locale codec is GBK and
    a Chinese draft folder name coming from Explorer is not guaranteed to survive it, which is what
    blew up the reader thread of the first version of this helper.

    The server usually runs in the isolated MLT runtime, whose MSYS2 mingw Python has no tkinter
    at all, so the dialog is delegated to an interpreter that does. That restores the picker people
    had before the MLT runtime existed instead of dropping the feature.
    """
    candidates = [[sys.executable, "-c", _TK_SNIPPET]]
    if os.name == "nt":
        candidates.insert(0, ["py", "-3", "-c", _TK_SNIPPET])
    return [entry for entry in candidates if entry[0]]


def _pick_with_tkinter(initial: str) -> str:
    """Run the Tk folder dialog in a helper interpreter and return the chosen path ('' = cancel)."""
    last_error = "no usable interpreter"
    for command in _tkinter_python():
        try:
            result = subprocess.run(command + [initial], capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=600, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue
        if result.returncode == 0:
            return (result.stdout or "").strip()
        last_error = (result.stderr or "").strip()[-200:] or "dialog helper exited nonzero"
    raise RuntimeError(last_error)


async def pick_folder(request: web.Request) -> web.Response:
    """Open the OS folder picker and return what the user chose ("" if cancelled)."""
    session = session_of(request)
    initial = request.query.get("path") or str(session.config.drafts_root or Path.home())

    def dialog() -> str:
        return _pick_with_tkinter(initial)
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
    except (ImportError, RuntimeError) as exc:
        return error_payload("no_folder_dialog", f"no interpreter with tkinter is available: {exc}",
                             status=501)
    return JSON({"path": chosen, "cancelled": not chosen, "drafts_root_like": _is_drafts_root(chosen)})


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
