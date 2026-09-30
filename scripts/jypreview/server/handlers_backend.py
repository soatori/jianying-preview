"""Optional native playback backend endpoints.

The browser UI can probe this surface without making GStreamer a hard import
for the normal read-only server.  The endpoint returns PNG frames for exact
single-frame validation first; continuous transport is added only after the
full timeline profile passes the native audit.
"""

from __future__ import annotations

import io
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from aiohttp import web

from ..playback_backend import BackendUnavailable, GstGesBackend, clips_from_frame_ir
from ._http import JSON, error_payload, offload, selector, session_of


class NativeHandle:
    """Serialize all GES calls on the thread where GES was initialized."""

    def __init__(self, backend: GstGesBackend) -> None:
        self.backend = backend
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jypreview-ges")

    async def call(self, method: str, *args, **kwargs):
        loop = asyncio.get_running_loop()
        fn = getattr(self.backend, method)
        return await loop.run_in_executor(self.executor, lambda: fn(*args, **kwargs))

    async def close(self) -> None:
        try:
            await self.call("close")
        finally:
            self.executor.shutdown(wait=True, cancel_futures=True)


def _key(did: str, tid: str) -> str:
    return f"{did}:{tid}"


async def capabilities(request: web.Request) -> web.Response:
    available, reason = await offload(GstGesBackend.available)
    return JSON({"name": "gstreamer-ges", "available": available, "reason": reason,
                 "installed": available})


async def open_backend(request: web.Request) -> web.Response:
    session = session_of(request)
    view = await offload(lambda: session.view(selector(request)))
    tid = await offload(lambda: view.resolve_timeline(request.query.get("timeline") or "active")["id"])
    entry = await offload(lambda: view.resolve_timeline(tid))
    duration_us = int(entry.get("duration_us") or 0)
    if duration_us <= 0:
        return error_payload("native_empty_timeline", "timeline has no duration", status=422)
    handle = None
    try:
        ir = await offload(lambda: view.frame(tid, 0, window=(0, duration_us)))
        clips = clips_from_frame_ir(ir)
        handle = NativeHandle(GstGesBackend())
        await handle.call("open", view.did, tid, profile={
            "clips": clips, "realtime": request.query.get("realtime") in ("1", "true"),
            "audio_sink": request.query.get("audio_sink") or "fakesink",
        })
        if request.query.get("realtime") in ("1", "true"):
            await handle.call("render_at", 0)
    except BackendUnavailable as exc:
        if handle:
            await handle.close()
        return error_payload("native_backend_unavailable", str(exc), status=503)
    except (NotImplementedError, RuntimeError, ValueError) as exc:
        if handle:
            await handle.close()
        return error_payload("native_backend_open_failed", str(exc), status=422)
    backends = request.app["native_backends"]
    key = _key(view.did, tid)
    previous = backends.get(key)
    if previous:
        await previous.close()
    backends[key] = handle
    return JSON({"key": key, "timeline": tid, "clips": len(clips),
                 "capabilities": handle.backend.capabilities.__dict__,
                 "snapshot": await handle.call("snapshot")})


def _backend(request: web.Request):
    key = _key(request.query.get("draft") or "", request.query.get("timeline") or "")
    handle = request.app["native_backends"].get(key)
    if handle is None:
        raise web.HTTPNotFound(text="native backend is not open")
    return handle


async def render(request: web.Request) -> web.Response:
    handle = _backend(request)
    try:
        t_us = int(float(request.query.get("t_us") or 0))
        result = await handle.call("render_at", t_us)
    except (RuntimeError, ValueError) as exc:
        return error_payload("native_render_failed", str(exc), status=422)
    if not result.get("ok"):
        return web.json_response({"ok": False, "code": "native_buffering",
                                   "reason": result.get("reason", ""), "data": result},
                                  status=503, dumps=lambda value: json.dumps(value, default=str))
    try:
        from PIL import Image

        image = Image.frombytes("RGBA", (result["width"], result["height"]), result["buffer"])
        output = io.BytesIO()
        image.save(output, format="PNG")
    except Exception as exc:  # noqa: BLE001
        return error_payload("native_encode_failed", str(exc), status=500)
    return web.Response(body=output.getvalue(), content_type="image/png",
                        headers={"X-Backend": "gstreamer-ges",
                                 "X-Backend-PTS-US": str(result.get("pts_us"))})


async def play(request: web.Request) -> web.Response:
    handle = _backend(request)
    try:
        await handle.call("play", float(request.query.get("rate") or 1.0))
    except (RuntimeError, NotImplementedError) as exc:
        return error_payload("native_play_failed", str(exc), status=422)
    return JSON(await handle.call("snapshot"))


async def pause(request: web.Request) -> web.Response:
    handle = _backend(request)
    await handle.call("pause")
    return JSON(await handle.call("snapshot"))


async def seek(request: web.Request) -> web.Response:
    handle = _backend(request)
    try:
        await handle.call("seek", int(float(request.query.get("t_us") or 0)))
    except (RuntimeError, ValueError) as exc:
        return error_payload("native_seek_failed", str(exc), status=422)
    return JSON(await handle.call("snapshot"))


async def stream(request: web.Request) -> web.StreamResponse:
    handle = _backend(request)
    response = web.StreamResponse(headers={
        "Content-Type": "multipart/x-mixed-replace; boundary=frame",
        "Cache-Control": "no-store", "X-Backend": "gstreamer-ges"})
    await response.prepare(request)
    try:
        from PIL import Image
        while True:
            result = await handle.call("pull_frame", 250)
            if not result:
                await asyncio.sleep(0.01)
                continue
            image = Image.frombytes("RGBA", (result["width"], result["height"]), result["buffer"])
            output = io.BytesIO()
            image.save(output, format="PNG")
            payload = output.getvalue()
            await response.write(
                b"--frame\r\nContent-Type: image/png\r\n"
                + f"Content-Length: {len(payload)}\r\n".encode()
                + f"X-Backend-PTS-US: {result.get('pts_us')}\r\n\r\n".encode()
                + payload + b"\r\n")
    except ConnectionResetError:
        request.app["log"].append("native stream: client connection reset")
    except asyncio.CancelledError:
        request.app["log"].append("native stream: request cancelled")
        raise
    except Exception as exc:  # noqa: BLE001
        request.app["log"].append(f"native stream: {exc.__class__.__name__}: {exc}")
    finally:
        try:
            await response.write_eof()
        except Exception:
            pass
    return response


async def snapshot(request: web.Request) -> web.Response:
    return JSON(await _backend(request).call("snapshot"))


async def close_backend(request: web.Request) -> web.Response:
    key = _key(request.query.get("draft") or "", request.query.get("timeline") or "")
    handle = request.app["native_backends"].pop(key, None)
    if handle:
        await handle.close()
    return JSON({"closed": bool(handle), "key": key})
