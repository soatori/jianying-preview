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
from . import handlers_assets, handlers_drafts, handlers_frame
from ._http import WEB_DIR, error_payload
from .events import EventHub
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


def create_app(config: Config, session: PreviewSession | None = None) -> web.Application:
    app = web.Application(middlewares=[json_errors], client_max_size=MAX_JSON)
    app["config"] = config
    app["session"] = session or PreviewSession(config)
    app["log"]: list[str] = []
    app["hub"] = EventHub()
    app["watcher"] = Watcher(config, app["hub"], app["session"])
    app["browser"] = BrowserSession(Path(config.user_state_dir) / "browser")
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
    app.router.add_get("/api/catalog", handlers_frame.catalog)
    app.router.add_get("/api/events", handlers_frame.events)
    app.router.add_get("/api/shot", handlers_frame.shot)

    app.router.add_get("/media", handlers_assets.media)
    app.router.add_get("/font", handlers_assets.font)
    app.router.add_get("/image", handlers_assets.image)
    app.router.add_get("/thumb", handlers_assets.thumb)
    app.router.add_get("/effect", handlers_assets.effect_file)
    app.router.add_get("/effectstyle", handlers_assets.effect_style)

    if WEB_DIR.is_dir():
        app.router.add_get("/web/{path:.*}", handlers_drafts.web_asset)
    return app


async def run(config: Config, open_browser: bool = True) -> None:
    app = create_app(config)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, config.host, config.port)
    await site.start()
    url = f"http://{config.host}:{config.port}/"
    print(json.dumps({"ok": True, "code": "serving", "reason": "",
                      "data": {"url": url, "drafts_root": str(config.drafts_root),
                               "cache_location": config.cache_location,
                               "dll": app["session"].manager.dll_path}}, ensure_ascii=False),
          flush=True)
    await app["watcher"].start()
    if open_browser:
        import webbrowser

        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        await asyncio.Event().wait()
    finally:
        await app["watcher"].stop()
        try:
            app["browser"].stop()
        except Exception:
            pass
        await runner.cleanup()
