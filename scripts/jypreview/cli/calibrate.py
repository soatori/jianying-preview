"""Calibration against a real JianYing render.

``draft_cover.jpg`` is produced by JianYing itself, so it is a pixel oracle for the
compositor: we render our own stage at N times, find the frame that best matches the
cover, and report the residual. A high match validates the fit/transform model
(``fit_mode``, ``transform_y_basis``, ``y_sign``); the winning time is also printed so
the same instant can be re-shot for text comparison.

Text size is *not* provable this way (covers are usually picked from text-free
moments), so ``em_px = font_size * width / 100`` stays a documented assumption derived
from JianYing's own wrap rule -- see references/calibration-and-oracle.md.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

from ..cli.dump_frame import parse_time
from ..session import PreviewSession

CHANNELS = 3


def _load(path: Path, size: tuple[int, int]) -> list[float]:
    image = Image.open(path).convert("RGB").resize(size, Image.BILINEAR)
    return [value / 255.0 for value in image.tobytes()]


def _similarity(left: list[float], right: list[float]) -> float:
    total = 0.0
    for a, b in zip(left, right):
        total += (a - b) ** 2
    rmse = (total / max(len(left), 1)) ** 0.5
    return round(max(0.0, 1.0 - rmse), 4)


def sweep(config, draft: str, timeline: str = "active", samples: int = 12,
          out_dir: Path | None = None, base: str | None = None) -> dict:
    from ..cli.shot import _from_server, build_url  # reuse the server-owned browser

    session = PreviewSession(config)
    view = session.view(draft)
    tid = view.resolve_timeline(timeline)["id"]
    cover = Path(view.row["path"]) / "draft_cover.jpg"
    if not cover.is_file():
        return {"ok": False, "reason": "no draft_cover.jpg to compare against", "did": view.did}
    content, _meta = view.content(tid)
    duration = content.duration_us or 1
    width, height, _ratio = content.canvas
    base_url = base or f"http://{config.host}:{config.port}/"
    out_dir = Path(out_dir or (Path(config.user_state_dir) / "calibrate"))
    grid = (min(width, 360), min(height, 640))
    target = _load(cover, grid)
    rows = []
    for index in range(samples):
        stamp = int(duration * (index + 0.5) / samples)
        dest = out_dir / f"{view.did}-{stamp}.png"
        try:
            _from_server(base_url, view.did, tid, stamp, "stage", dest, grid[0] * 3, grid[1] * 3)
        except Exception as exc:
            rows.append({"t_us": stamp, "error": f"{exc.__class__.__name__}: {exc}"})
            continue
        try:
            score = _similarity(target, _load(dest, grid))
        except OSError as exc:
            rows.append({"t_us": stamp, "error": str(exc)})
            continue
        ir = view.frame(tid, stamp)
        rows.append({"t_us": stamp, "seconds": round(stamp / 1e6, 3), "similarity": score,
                     "layers": len(ir["layers"]),
                     "media_missing": ir["stats"]["media_missing"],
                     "shot": str(dest)})
    scored = [row for row in rows if "similarity" in row]
    best = max(scored, key=lambda row: row["similarity"]) if scored else None
    return {"ok": bool(scored), "did": view.did, "timeline": tid, "cover": str(cover),
            "grid": list(grid), "samples": len(scored), "best": best,
            "spread": [row["similarity"] for row in scored], "rows": rows,
            "url": build_url(base_url, view.did, tid, (best or {}).get("t_us", 0), "stage")
                  if best else None}


def run(config, draft: str, timeline: str = "active", samples: int = 12,
        out: str | None = None, base: str | None = None) -> int:
    data = sweep(config, draft, timeline, samples, Path(out) if out else None, base)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ok = bool(data.get("ok"))
    print(json.dumps({"ok": ok, "code": "ok" if ok else "no_oracle",
                      "reason": data.get("reason", ""), "data": data},
                     ensure_ascii=False, indent=2))
    return 0 if ok else 1
