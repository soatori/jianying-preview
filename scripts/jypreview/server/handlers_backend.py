"""Native MLT playback backend endpoints.

The browser UI probes this surface without making MLT a hard import for the
normal read-only server.  PNG frames validate exact seeks first; the multipart
stream carries continuous playback with per-frame identity headers stamped at
production time so a client can discard frames its own requests superseded.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
from concurrent.futures import ThreadPoolExecutor

from aiohttp import web  # type: ignore[import-not-found]  # present in the runtime env, not the analyzer's

from ..mlt_backend import BackendUnavailable, MltCompiler, PlaybackController
from ._http import JSON, error_payload, offload, selector, session_of


class PlaybackHandle:
    """Serialize handle calls on one thread; PlaybackController owns its worker."""

    def __init__(self) -> None:
        self.controller = PlaybackController()
        self.playback_id = ""
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jypreview-playback")

    async def call(self, method: str, *args, **kwargs):
        loop = asyncio.get_running_loop()
        fn = getattr(self.controller, method)
        return await loop.run_in_executor(self.executor, lambda: fn(*args, **kwargs))

    async def close(self) -> None:
        try:
            await self.call("close")
        finally:
            self.executor.shutdown(wait=True, cancel_futures=True)


def _key(did: str, tid: str) -> str:
    return f"{did}:{tid}"


def _int_param(value: str | None, name: str, minimum: int | None = None) -> int:
    try:
        parsed = int(value or "")
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer") from None
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return parsed


def _frame_headers(frame) -> dict[str, str]:
    # Frame envelope comes from the RenderedFrame stamped at production, never
    # from a current snapshot: a delayed encode must keep the old identity.
    return {"X-Backend": "mlt",
            "X-Playback-ID": frame.playback_id,
            "X-Playback-Generation": str(frame.generation),
            "X-Seek-Request-ID": str(frame.seek_request_id),
            "X-Project-Frame": str(frame.frame_index),
            "X-Project-PTS-US": str(frame.pts_us)}


def _encode_png(frame) -> bytes:
    from PIL import Image

    image = Image.frombytes("RGBA", (frame.width, frame.height), frame.rgba)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


async def capabilities(request: web.Request) -> web.Response:
    available, reason = await offload(MltCompiler.available)
    return JSON({"name": "mlt", "available": available, "reason": reason,
                 "installed": available})


async def open_backend(request: web.Request) -> web.Response:
    session = session_of(request)
    view = await offload(lambda: session.view(selector(request)))
    tid = await offload(lambda: view.resolve_timeline(request.query.get("timeline") or "active")["id"])
    model = await offload(lambda: view.timeline_model(tid))
    handle = PlaybackHandle()
    try:
        state = await handle.call("open", model)
    except BackendUnavailable as exc:
        await handle.close()
        return error_payload("mlt_backend_unavailable", str(exc), status=503)
    except (NotImplementedError, RuntimeError, ValueError, TypeError) as exc:
        await handle.close()
        return error_payload("mlt_backend_open_failed", str(exc), status=422)
    except Exception as exc:  # noqa: BLE001
        await handle.close()
        return error_payload("mlt_backend_open_failed", str(exc), status=500)
    handle.playback_id = state["playback_id"]
    backends = request.app["playback_backends"]
    key = _key(view.did, tid)
    previous = backends.get(key)
    if previous:
        await previous.close()
    backends[key] = handle
    return JSON({"key": key, "timeline": tid, "snapshot": state})


async def _open_handle(request: web.Request) -> web.Response | PlaybackHandle:
    """Resolve the handle, or the structured error rejecting this caller."""
    key = _key(request.query.get("draft") or "", request.query.get("timeline") or "")
    handle = request.app["playback_backends"].get(key)
    if handle is None:
        raise web.HTTPNotFound(text="playback backend is not open")
    playback_id = request.query.get("playback_id") or ""
    if not playback_id:
        return error_payload("invalid_playback_id", "missing ?playback_id", status=400)
    if playback_id != handle.playback_id:
        # Do not echo the current credential back to an excluded caller.
        return error_payload("stale_playback_id", "playback_id does not match the open session",
                             status=409)
    return handle


async def render(request: web.Request) -> web.Response:
    handle = await _open_handle(request)
    if isinstance(handle, web.Response):
        return handle
    try:
        request_id = _int_param(request.query.get("request_id", "0"), "request_id", minimum=0)
    except ValueError as exc:
        return error_payload("invalid_request_id", str(exc), status=400)
    # The snapshot settles the accepted seek so its frame lands in the slot;
    # render never issues a seek of its own.
    state = await handle.call("snapshot")
    if state["phase"] == "ended":
        return JSON({"ended": True, "snapshot": state})
    if state["error"]:
        return error_payload("mlt_render_failed", state["error"], status=500)
    try:
        frame = await handle.call("pull_frame", 500)
    except RuntimeError as exc:
        # A dying sink raises here; surface it as the render failure it is.
        return error_payload("mlt_render_failed", str(exc), status=500)
    if frame is None:
        return error_payload("mlt_frame_unavailable", "no frame is available", status=503)
    if frame.playback_id != handle.playback_id or frame.seek_request_id != request_id:
        return error_payload("frame_superseded", "frame identity does not match request_id",
                             status=409, frame_playback_id=frame.playback_id,
                             frame_request_id=frame.seek_request_id,
                             frame_generation=frame.generation)
    payload = await offload(_encode_png, frame)
    return web.Response(body=payload, content_type="image/png", headers=_frame_headers(frame))


async def play(request: web.Request) -> web.Response:
    handle = await _open_handle(request)
    if isinstance(handle, web.Response):
        return handle
    try:
        return JSON(await handle.call("play"))
    except (RuntimeError, NotImplementedError, ValueError) as exc:
        return error_payload("mlt_play_failed", str(exc), status=422)


async def pause(request: web.Request) -> web.Response:
    handle = await _open_handle(request)
    if isinstance(handle, web.Response):
        return handle
    try:
        return JSON(await handle.call("pause"))
    except (RuntimeError, NotImplementedError, ValueError) as exc:
        return error_payload("mlt_pause_failed", str(exc), status=422)


async def seek(request: web.Request) -> web.Response:
    handle = await _open_handle(request)
    if isinstance(handle, web.Response):
        return handle
    try:
        t_us = _int_param(request.query.get("t_us"), "t_us")
        request_id = _int_param(request.query.get("request_id"), "request_id", minimum=1)
    except ValueError as exc:
        return error_payload("invalid_seek_params", str(exc), status=400)
    try:
        result = await handle.call("seek", t_us,
                                   playback_id=handle.playback_id, request_id=request_id)
    except (RuntimeError, ValueError) as exc:
        return error_payload("mlt_seek_failed", str(exc), status=422)
    return JSON(result)


async def stream(request: web.Request) -> web.StreamResponse:
    handle = await _open_handle(request)
    if isinstance(handle, web.Response):
        return handle
    response = web.StreamResponse(headers={
        "Content-Type": "multipart/x-mixed-replace; boundary=frame",
        "Cache-Control": "no-store", "X-Backend": "mlt"})
    await response.prepare(request)
    last = None
    try:
        while True:
            transport = request.transport
            if transport is None or transport.is_closing():
                request.app["log"].append("mlt stream: client disconnected")
                break
            frame = await handle.call("pull_frame", 100)
            if frame is None:
                await asyncio.sleep(0.02)
                continue
            stamp = (frame.playback_id, frame.generation, frame.seek_request_id,
                     frame.frame_index, frame.pts_us)
            if stamp == last:
                # Re-sending the identical frame would spin; wait for progress.
                await asyncio.sleep(0.02)
                continue
            last = stamp
            payload = await offload(_encode_png, frame)
            headers = "".join(f"{name}: {value}\r\n" for name, value in _frame_headers(frame).items())
            await response.write(
                b"--frame\r\nContent-Type: image/png\r\n"
                + f"Content-Length: {len(payload)}\r\n".encode()
                + headers.encode() + b"\r\n" + payload + b"\r\n")
    except ConnectionResetError:
        request.app["log"].append("mlt stream: client connection reset")
    except asyncio.CancelledError:
        request.app["log"].append("mlt stream: request cancelled")
        raise
    except Exception as exc:  # noqa: BLE001
        request.app["log"].append(f"mlt stream: {exc.__class__.__name__}: {exc}")
    finally:
        with contextlib.suppress(Exception):
            await response.write_eof()
    return response


async def snapshot(request: web.Request) -> web.Response:
    handle = await _open_handle(request)
    if isinstance(handle, web.Response):
        return handle
    return JSON(await handle.call("snapshot"))


async def close_backend(request: web.Request) -> web.Response:
    handle = await _open_handle(request)
    if isinstance(handle, web.Response):
        return handle
    key = _key(request.query.get("draft") or "", request.query.get("timeline") or "")
    popped = request.app["playback_backends"].pop(key, None)
    if popped:
        await popped.close()
    return JSON({"closed": popped is not None, "key": key})
