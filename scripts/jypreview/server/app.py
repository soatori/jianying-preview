"""Read-only aiohttp service: JSON APIs, ranged media, SSE reload."""

from __future__ import annotations

import asyncio
import json
import traceback
from pathlib import Path

from aiohttp import web

from ..config import Config
from ..decrypt.manager import DecryptError
from ..session import DraftNotFound, PreviewSession
from . import handlers_assets, handlers_backend, handlers_drafts, handlers_frame
from ._http import JSON, WEB_DIR, error_payload
from .events import EventHub
from .lifecycle import SessionLease
from ..shot.browser import BrowserSession
from .watcher import Watcher

MAX_JSON = 32 * 1024 * 1024


@web.middleware
async def json_errors(request: web.Request, handler) -> web.Response:
    try:
        return await handler(request)
    except DraftNotFound as exc:
        return error_payload(exc.code, str(exc), status=404, candidates=exc.candidates,
                             hint=exc.hint, selector=exc.selector)
    except (FileNotFoundError, PermissionError) as exc:
        return error_payload("io_error", f"{exc.__class__.__name__}: {exc}", status=500)
    except DecryptError as exc:
        return error_payload("decrypt_failed", str(exc), status=422)
    except ValueError as exc:
        return error_payload("invalid_input", str(exc), status=400)
    except web.HTTPNotFound:
        return error_payload("not_found", "no such route", status=404)
    except Exception as exc:
        detail = traceback.format_exc(limit=3)
        request.app["log"].append(f"{exc.__class__.__name__}: {exc}\n{detail}")
        return error_payload("error", f"{exc.__class__.__name__}: {exc}", status=500,
                             trace=detail.splitlines()[-1])


def create_app(config: Config, session: PreviewSession | None = None,
               lease: SessionLease | None = None) -> web.Application:
    app = web.Application(middlewares=[json_errors], client_max_size=MAX_JSON)
    app["config"] = config
    app["session"] = session or PreviewSession(config)
    app["lease"] = lease
    app["log"]: list[str] = []
    app["hub"] = EventHub()
    app["watcher"] = Watcher(config, app["hub"], app["session"])
    app["browser"] = BrowserSession(Path(config.user_state_dir) / "browser")
    app["native_backends"] = {}
    app["frames_built"] = 0

    async def revalidate_ui(request, response):
        # The UI is iterated on between runs; let the browser keep the file but always ask
        # whether it changed, so an edit never shows up as a stale stage.
        if request.path == "/" or request.path.startswith("/web/"):
            response.headers["Cache-Control"] = "no-cache"

    app.on_response_prepare.append(revalidate_ui)

    app.router.add_get("/", handlers_drafts.index)
    app.router.add_get("/api/drafts", handlers_drafts.list_drafts)
    app.router.add_get("/api/pick-folder", handlers_drafts.pick_folder)
    app.router.add_get("/api/draft", handlers_drafts.draft_detail)
    app.router.add_get("/api/timelines", handlers_drafts.timelines)
    app.router.add_post("/api/drafts/rescan", handlers_drafts.rescan)
    app.router.add_get("/api/reload", handlers_drafts.reload_draft)

    app.router.add_get("/api/frame", handlers_frame.frame)
    app.router.add_get("/api/frames", handlers_frame.frames)
    app.router.add_get("/api/what-at", handlers_frame.what_at)
    app.router.add_get("/api/trackmap", handlers_frame.trackmap)
    app.router.add_get("/api/ir-diff", handlers_frame.ir_diff)
    app.router.add_get("/api/fonts.css", handlers_frame.fonts_css)
    app.router.add_get("/api/preview-plan", handlers_frame.preview_plan)
    app.router.add_get("/api/state", handlers_frame.state)
    app.router.add_get("/api/health", health)
    app.router.add_post("/api/lease", touch_lease)
    app.router.add_post("/api/session/close", close_session)
    app.router.add_get("/api/catalog", handlers_frame.catalog)
    app.router.add_get("/api/events", handlers_frame.events)
    app.router.add_get("/api/shot", handlers_frame.shot)
    app.router.add_get("/api/backend/capabilities", handlers_backend.capabilities)
    app.router.add_post("/api/backend/open", handlers_backend.open_backend)
    app.router.add_get("/api/backend/render", handlers_backend.render)
    app.router.add_post("/api/backend/play", handlers_backend.play)
    app.router.add_post("/api/backend/pause", handlers_backend.pause)
    app.router.add_post("/api/backend/seek", handlers_backend.seek)
    app.router.add_get("/api/backend/stream", handlers_backend.stream)
    app.router.add_get("/api/backend/snapshot", handlers_backend.snapshot)
    app.router.add_post("/api/backend/close", handlers_backend.close_backend)

    app.router.add_get("/media", handlers_assets.media)
    app.router.add_get("/font", handlers_assets.font)
    app.router.add_get("/image", handlers_assets.image)
    app.router.add_get("/thumb", handlers_assets.thumb)
    app.router.add_get("/effect", handlers_assets.effect_file)
    app.router.add_get("/effectstyle", handlers_assets.effect_style)

    if WEB_DIR.is_dir():
        app.router.add_get("/web/{path:.*}", handlers_drafts.web_asset)
    return app


async def health(request: web.Request) -> web.Response:
    lease = request.app.get("lease")
    return web.json_response({"ok": True, "code": "ok", "reason": "", "data": {
        "service": "jianying-preview", "lease": lease.describe() if lease else {"enabled": False}
    }}, dumps=lambda value: json.dumps(value, ensure_ascii=False))


def _request_token(request: web.Request) -> str | None:
    return request.headers.get("X-Preview-Token") or request.query.get("token")


async def touch_lease(request: web.Request) -> web.Response:
    lease = request.app.get("lease")
    if lease is None:
        return web.json_response({"ok": True, "code": "persistent", "reason": "", "data": {
            "persistent": True}}, dumps=lambda value: json.dumps(value, ensure_ascii=False))
    if not lease.touch(_request_token(request)):
        return error_payload("lease_invalid", "invalid or expired preview session", status=401)
    return web.json_response({"ok": True, "code": "ok", "reason": "", "data": {
        "persistent": False, "lease": lease.describe()}},
        dumps=lambda value: json.dumps(value, ensure_ascii=False))


async def close_session(request: web.Request) -> web.Response:
    lease = request.app.get("lease")
    if lease is None:
        return JSON({"closed": False, "persistent": True})
    if not lease.close(_request_token(request)):
        return error_payload("lease_invalid", "invalid preview session token", status=401)
    return JSON({"closed": True})


async def run(config: Config, open_browser: bool = True,
              lease: SessionLease | None = None) -> None:
    app = create_app(config, lease=lease)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, config.host, config.port)
    await site.start()
    actual_port = site._server.sockets[0].getsockname()[1]  # noqa: SLF001
    url = f"http://{config.host}:{actual_port}/"
    print(json.dumps({"ok": True, "code": "serving", "reason": "",
                      "data": {"url": url, "drafts_root": str(config.drafts_root),
                               "cache_location": config.cache_location,
                               "port": actual_port,
                               "lease": lease.describe() if lease else {"enabled": False},
                               "dll": app["session"].manager.dll_path}}, ensure_ascii=False),
          flush=True)
    await app["watcher"].start()
    if open_browser:
        import webbrowser

        try:
            webbrowser.open(url)
        except Exception:
            pass
    lease_task = asyncio.create_task(lease.watch()) if lease else None
    try:
        if lease is None:
            await asyncio.Event().wait()
        else:
            await lease.closed.wait()
    finally:
        if lease_task:
            lease_task.cancel()
            try:
                await lease_task
            except asyncio.CancelledError:
                pass
        await app["watcher"].stop()
        try:
            app["browser"].stop()
        except Exception:
            pass
        for backend in list(app["native_backends"].values()):
            try:
                await backend.close()
            except Exception:
                pass
        app["native_backends"].clear()
        await runner.cleanup()
