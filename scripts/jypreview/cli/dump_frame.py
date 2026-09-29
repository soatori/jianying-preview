"""``preview.py frame`` -- dump the FrameDescriptor for one instant."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from .. import summary
from ..model import timing


def parse_time(value: str | None, t_us: int | None) -> int:
    if t_us is not None:
        return int(t_us)
    if not value:
        return 0
    text = str(value).strip().lower()
    if text.endswith("us"):
        return int(float(text[:-2]))
    if text.endswith("ms"):
        return int(float(text[:-2]) * 1000)
    if text.endswith("s"):
        return int(float(text[:-1]) * 1_000_000)
    if ":" in text:
        minutes, _, seconds = text.partition(":")
        return int((int(minutes) * 60 + float(seconds)) * 1_000_000)
    if "frame" in text:
        return 0
    return int(float(text) * 1_000_000)


def run(config, draft: str, timeline: str = "active", t_us: int | None = None, t: str | None = None,
        compact: bool = False, out: str | None = None, times: str | None = None,
        ratio: str | None = None, window: float | None = None, to: float | None = None) -> int:
    from jypreview.session import PreviewSession

    session = PreviewSession(config)
    view = session.view(draft)
    entry = view.resolve_timeline(timeline)
    started = time.perf_counter()
    start_us = parse_time(t, t_us)
    span = None
    if window is not None or to is not None:
        end_us = int(round(to * 1e6)) if to is not None else start_us + int(round(window * 1e6))
        span = (min(start_us, end_us), max(start_us, end_us))

    if times:
        stamps = [parse_time(piece.strip(), None) for piece in str(times).split(",") if piece.strip()][:60]
        frames = [view.frame(entry["id"], stamp, ratio=ratio) for stamp in stamps]
        payload = {"timeline": entry["id"], "count": len(frames),
                   "frames": [summary.compact_frame(frame) for frame in frames] if compact else frames}
        if out:
            Path(out).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            payload = {"out": out, "count": len(frames)}
        print(json.dumps({"ok": True, "code": "ok", "reason": "",
                          "data": {"elapsed_ms": int((time.perf_counter() - started) * 1000),
                                   "timeline": entry["id"], "descriptor": payload}},
                         ensure_ascii=False, indent=1))
        return 0

    requested = start_us
    ir = view.frame(entry["id"], requested, ratio=ratio, window=span)
    if out:
        Path(out).write_text(json.dumps(ir, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps({"ok": True, "code": "ok", "reason": "",
                          "data": {"out": out, "timeline": entry["id"], "requested_t_us": requested,
                                   "layers": len(ir.get("layers", [])),
                                   "elapsed_ms": int((time.perf_counter() - started) * 1000)}},
                         ensure_ascii=False, indent=1))
        return 0
    if compact:
        print(json.dumps(summary.compact_frame(ir), ensure_ascii=False, indent=2))
        return 0
    print(json.dumps({"ok": True, "code": "ok", "reason": "",
                      "data": {"elapsed_ms": int((time.perf_counter() - started) * 1000),
                               "timeline": entry["id"], "requested_t_us": requested,
                               "descriptor": ir}}, ensure_ascii=False, indent=1))
    return 0
