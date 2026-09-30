"""Frame IR, agent assertion surfaces, catalog/state and SSE."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from aiohttp import web

from ..cli.dump_frame import parse_time
from ..model import paint
from ..model.fonts import css_block, resolve as resolve_font
from ._http import JSON, error_payload, offload, selector, session_of

MAX_BATCH = 60
MAX_WINDOW_US = 120_000_000


async def _view(request: web.Request, force: bool = False):
    session = session_of(request)
    return await offload(lambda: session.view(selector(request), force=force))


async def _tid(view, request: web.Request):
    return await offload(lambda: view.resolve_timeline(request.query.get("timeline") or "active")["id"])


def _ratio(request: web.Request) -> str | None:
    """Requested 画幅 (16:9, 9:16, …); absent means the draft's own canvas ratio."""
    return (request.query.get("ratio") or "").strip() or None


def _window(request: web.Request, t_us: int) -> tuple[int, int] | None:
    """Playback windows arrive in two shapes: ``window_us`` (a length measured from ``t_us``)
    and an explicit ``from_us``/``to_us`` pair. Both get clamped and normalised here."""
    low = _int(request.query.get("from_us"))
    high = _int(request.query.get("to_us"))
    if low is None and high is None:
        length = _int(request.query.get("window_us"))
        if not length or length <= 0:
            return None
        low, high = t_us, t_us + min(length, MAX_WINDOW_US)
    else:
        low = t_us if low is None else low
        high = low + min(max((high if high is not None else low + MAX_WINDOW_US) - low, 0), MAX_WINDOW_US)
    low, high = min(low, high), max(low, high)
    low = max(low, 0)
    return (low, low + min(high - low, MAX_WINDOW_US)) if high > low else None


async def frame(request: web.Request) -> web.Response:
    view = await _view(request)
    tid = await _tid(view, request)
    t_us = parse_time(request.query.get("t"), _int(request.query.get("t_us")))
    ratio = _ratio(request)
    window = _window(request, t_us)
    ir = await offload(lambda: view.frame(tid, t_us, ratio=ratio, window=window))
    request.app["watcher"].watch(view.did, view.root)
    request.app["frames_built"] += 1
    keep = request.query.get("layers")
    if keep:
        wanted = {item.strip() for item in keep.split(",")}
        ir = {**ir, "layers": [layer for layer in ir["layers"] if layer["kind"] in wanted
                              or ("text" in wanted and layer["kind"] == "text")]}
    return web.json_response({"ok": True, "code": "ok", "reason": "", "data": ir},
                             dumps=lambda value: json.dumps(value, ensure_ascii=False))


async def frames(request: web.Request) -> web.Response:
    view = await _view(request)
    tid = await _tid(view, request)
    stamps = request.query.get("times") or request.query.get("t_us") or "0"
    values = []
    for piece in str(stamps).split(","):
        piece = piece.strip()
        if piece:
            values.append(parse_time(None if piece.isdigit() else piece,
                                     int(piece) if piece.isdigit() else None))
    values = values[:MAX_BATCH]
    built = [await offload(lambda stamp=stamp: view.frame(tid, stamp, ratio=_ratio(request))) for stamp in values]
    compact = request.query.get("compact") in ("1", "true", "")
    if compact:
        from ..summary import who_at

        built = [{"t_us": item["time"]["t_us"], "who": who_at(item), "stats": item["stats"]}
                 for item in built]
    return JSON({"timeline": tid, "count": len(built), "frames": built})


async def what_at(request: web.Request) -> web.Response:
    from ..summary import who_at

    view = await _view(request)
    tid = await _tid(view, request)
    t_us = parse_time(request.query.get("t"), _int(request.query.get("t_us")))
    ir = await offload(lambda: view.frame(tid, t_us, ratio=_ratio(request)))
    return JSON({"t_us": ir["time"]["t_us"], "canvas": ir["canvas"], "duration_us": ir["duration_us"],
                 "timeline": ir["timeline"], "who": who_at(ir), "audio": ir["audio_labels"],
                 "stats": ir["stats"], "warnings": ir["warnings"]})


async def trackmap(request: web.Request) -> web.Response:
    view = await _view(request)
    tid = await _tid(view, request)

    def build() -> dict:
        from ..model.content import DEFAULT_RI

        content, _meta = view.content(tid)
        tracks = []
        for index, track in enumerate(content.tracks):
            rows = []
            ri_values = []
            for segment in track.get("segments") or []:
                if not isinstance(segment, dict):
                    continue
                material = content.material(segment.get("material_id"))
                name = None
                if material:
                    name = material[1].get("material_name") or material[1].get("name")
                    if material[0] == "texts":
                        text, _styles = paint.parse_content(material[1])
                        name = text
                target = segment.get("target_timerange") or {}
                source = segment.get("source_timerange") or {}
                ri = segment.get("render_index")
                if ri is None:
                    ri = track.get("render_index")
                if ri is not None:
                    ri_values.append(int(ri))
                rows.append({
                    "segment_id": segment.get("id"), "material_id": segment.get("material_id"),
                    "name": name, "start_us": int(target.get("start", 0) or 0),
                    "duration_us": int(target.get("duration", 0) or 0),
                    "source_start_us": int(source.get("start", 0) or 0),
                    "render_index": segment.get("render_index"),
                    "volume": segment.get("volume"), "speed": segment.get("speed"),
                    "refs": len(segment.get("extra_material_refs") or []),
                })
            track_type = str(track.get("type") or "")
            z_ri = (max(ri_values) if ri_values
                    else int(track.get("render_index") if track.get("render_index") is not None
                             else DEFAULT_RI.get(track_type, 0)))
            rows.sort(key=lambda row: row["start_us"])
            tracks.append({"id": track.get("id"), "index": index, "type": track_type,
                           "name": track.get("name"),
                           "group": "audio" if track_type == "audio" else "visual",
                           "z_ri": z_ri, "min_z_ri": min(ri_values) if ri_values else z_ri,
                           "segment_count": len(rows), "segments": rows,
                           "end_us": max((row["start_us"] + row["duration_us"] for row in rows),
                                         default=0)})
        lanes = sorted([t for t in tracks if t["group"] == "visual"],
                       key=lambda t: -t["z_ri"]) + \
            sorted([t for t in tracks if t["group"] == "audio"], key=lambda t: t["index"])
        for order, lane in enumerate(lanes):
            lane["lane"] = order
        content_value = content.value
        return {"timeline": tid, "duration_us": content.duration_us,
                "declared_duration_us": int(content_value.get("duration", 0) or 0),
                "fps": content.fps or None, "canvas": content_value.get("canvas_config"),
                "render_index_track_mode_on": content.render_index_track_mode,
                "tracks": lanes, "material_counts": content.counts()}

    return JSON(await offload(build))


async def ir_diff(request: web.Request) -> web.Response:
    view = await _view(request)
    tid = await _tid(view, request)
    snapshots = Path(session_of(request).config.user_state_dir) / "snapshots"

    async def load_side(name: str) -> dict:
        target = snapshots / f"{name}.json"
        if target.is_file():
            return json.loads(target.read_text(encoding="utf-8"))
        stamp = parse_time(request.query.get(name), _int(request.query.get(f"{name}_us")))
        return await offload(lambda: view.frame(tid, stamp, ratio=_ratio(request)))

    left = await load_side("a")
    right = await load_side("b")
    from ..ir_diff import diff

    return JSON({"timeline": tid, "a": {"t_us": left["time"]["t_us"]}, "b": {"t_us": right["time"]["t_us"]},
                 **diff(left, right)})


async def fonts_css(request: web.Request) -> web.Response:
    view = await _view(request)
    tid = await _tid(view, request)
    session = session_of(request)

    def build() -> str:
        content, _meta = view.content(tid)
        refs = []
        seen = set()
        for material in content.bucket("texts").values():
            _text, styles = paint.parse_content(material)
            style_font = styles[0].get("font", {}) if styles else {}
            ref = resolve_font(material, style_font, session.font_index, session.config.effect_cache,
                               session.config.install_fonts, session.registry)
            if ref.family not in seen:
                seen.add(ref.family)
                refs.append(ref)
        return css_block(refs)

    return web.Response(text=await offload(build), content_type="text/css", charset="utf-8")


async def preview_plan(request: web.Request) -> web.Response:
    view = await _view(request)
    tid = await _tid(view, request)
    ir = await offload(lambda: view.frame(tid, 0, ratio=_ratio(request)))
    return JSON({"timeline": tid, "describe": view.describe(),
                 "layer_kinds": {layer["kind"]: 0 for layer in ir["layers"]},
                 "stats": ir["stats"], "warnings": ir["warnings"]})


async def shot(request: web.Request) -> web.Response:
    from ..cli.shot import build_url
    from ..shot.cdp import capture

    view = await _view(request)
    tid = await _tid(view, request)
    t_us = parse_time(request.query.get("t"), _int(request.query.get("t_us")))
    ratio = _ratio(request)
    ir = await offload(lambda: view.frame(tid, t_us, ratio=ratio))
    width = _int(request.query.get("w")) or int(ir["canvas"]["width"])
    height = _int(request.query.get("h")) or int(ir["canvas"]["height"])
    view_mode = request.query.get("view") or "stage"
    browser = request.app["browser"]
    base = f"http://{request.app['config'].host}:{request.app['config'].port}/"
    url = build_url(base, view.did, tid, ir["time"]["t_us"], view_mode, ratio=ratio)
    out = Path(request.app["config"].user_state_dir) / "shots" / (
        f"{view.did}-{tid[:8]}-{ir['time']['t_us']}-{'st' if view_mode == 'stage' else 'ui'}.png")
    try:
        result = await offload(lambda: capture(browser, url, out, width=width, height=height,
                                               wait_expr="window.__ready === true && (!window.__settle || window.__settle())", extra_wait_ms=900))
    except Exception as exc:
        return error_payload("shot_failed", f"{exc.__class__.__name__}: {exc}", status=503,
                             browser=browser.info())
    headers = {"X-Shot-Sha256": result["sha256"], "X-Shot-Path": str(out),
               "Cache-Control": "no-store"}
    if request.query.get("out"):
        Path(request.query.get("out")).parent.mkdir(parents=True, exist_ok=True)
        Path(request.query.get("out")).write_bytes(out.read_bytes())
    return web.Response(body=out.read_bytes(), content_type="image/png", headers=headers)


async def catalog(request: web.Request) -> web.Response:
    session = session_of(request)
    if session.catalog is None:
        return error_payload("catalog_missing", "run: python scripts/preview.py catalog",
                             status=404, path=str(session.catalog_path))
    query = request.query
    items = await offload(lambda: session.catalog.search(query.get("q", ""), query.get("kind", ""),
                                                          query.get("render_class", ""),
                                                          min(int(query.get("limit") or 50), 500)))
    return JSON({"describe": session.catalog.describe(), "count": len(items), "items": items})


async def state(request: web.Request) -> web.Response:
    session = session_of(request)
    watcher = request.app["watcher"]
    payload = await offload(session.state)
    payload["server"] = {"frames_built": request.app["frames_built"],
                         "subscribers": request.app["hub"].count(),
                         "recent_events": json.loads(request.app["hub"].dump())[-5:],
                         "log": request.app.get("log", [])[-20:]}
    payload["watcher"] = {"watching": {did: str(path) for did, path in watcher.watching.items()},
                          "poll_ms": watcher.poll_ms, "polls": watcher.polls}
    return JSON(payload)


async def events(request: web.Request) -> web.Response:
    hub = request.app["hub"]
    queue = hub.subscribe()
    response = web.StreamResponse(status=200, headers={"Content-Type": "text/event-stream",
                                                       "Cache-Control": "no-cache",
                                                       "X-Accel-Buffering": "no"})
    await response.prepare(request)
    try:
        await response.write(b": connected\n\n")
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=25)
            except asyncio.TimeoutError:
                await response.write(b"event: heartbeat\ndata: {}\n\n")
                continue
            await response.write(f"event: {event['name']}\ndata: "
                                 f"{json.dumps(event['data'], ensure_ascii=False)}\n\n".encode("utf-8"))
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        hub.unsubscribe(queue)
    return response


def _int(value) -> int | None:
    try:
        return None if value is None else int(float(value))
    except (TypeError, ValueError):
        return None
