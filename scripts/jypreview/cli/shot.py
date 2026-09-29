"""``preview.py shot`` -- render one instant to a PNG without opening JianYing.

The running server owns the headless browser (one instance, reused), so this CLI
prefers ``GET /api/shot`` and only launches its own browser when no server is up.
"""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ..cli.dump_frame import parse_time
from ..session import PreviewSession


def build_url(base: str, draft: str, tid: str, t_us: int, view: str, ratio: str | None = None) -> str:
    separator = "&" if "?" in base else "?"
    extra = f"&ratio={urllib.parse.quote(str(ratio))}" if ratio else ""
    return (f"{base}{separator}draft={urllib.parse.quote(str(draft))}"
            f"&timeline={urllib.parse.quote(str(tid))}&t={t_us / 1_000_000:.6f}"
            f"&chrome={0 if view == 'stage' else 1}{extra}")


def _out_path(config, did: str, tid: str, t_us: int, out: str | None) -> Path:
    if out:
        return Path(out)
    return Path(config.user_state_dir) / "shots" / f"{did}-{tid[:8]}-{int(t_us)}.png"


def _from_server(base: str, draft: str, tid: str, t_us: int, view: str, dest: Path,
                 width: int | None, height: int | None, timeout: float = 90.0,
                 ratio: str | None = None) -> dict:
    query = {"draft": draft, "timeline": tid, "t_us": int(t_us), "view": view}
    if ratio:
        query["ratio"] = ratio
    if width:
        query["w"] = width
    if height:
        query["h"] = height
    url = f"{base.rstrip('/')}/api/shot?" + urllib.parse.urlencode(query)
    with urllib.request.urlopen(url, timeout=timeout) as response:
        blob = response.read()
        headers = {key.lower(): value for key, value in response.getheaders()}
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(blob)
    return {"path": str(dest), "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest(),
            "server_sha256": headers.get("x-shot-sha256"), "server_path": headers.get("x-shot-path"),
            "via": "server"}


def _local(config, view_obj, tid: str, t_us: int, view: str, dest: Path,
           width: int | None, height: int | None, ratio: str | None = None) -> dict:
    from ..shot.browser import BrowserSession
    from ..shot.cdp import capture

    ir = view_obj.frame(tid, t_us, ratio=ratio)
    width = width or int(ir["canvas"]["width"])
    height = height or int(ir["canvas"]["height"])
    browser = BrowserSession(Path(config.user_state_dir) / "browser-cli")
    try:
        result = capture(browser, build_url(f"http://{config.host}:{config.port}/", view_obj.did,
                                            tid, ir["time"]["t_us"], view, ratio=ratio), dest,
                         width=width, height=height, wait_expr="window.__ready === true && (!window.__settle || window.__settle())",
                         extra_wait_ms=900)
    finally:
        browser.stop()
    result["t_us"] = ir["time"]["t_us"]
    result["layers"] = len(ir["layers"])
    result["via"] = "local"
    return result


def run(config, draft: str, timeline: str = "active", t_us: int | None = None, t: str | None = None,
        out: str | None = None, view: str = "stage", width: int | None = None,
        height: int | None = None, base: str | None = None, force_local: bool = False,
        ratio: str | None = None) -> int:
    session = PreviewSession(config)
    view_obj = session.view(draft)
    tid = view_obj.resolve_timeline(timeline)["id"]
    stamp = parse_time(t, t_us)
    ir = view_obj.frame(tid, stamp, ratio=ratio)
    dest = _out_path(config, view_obj.did, tid, ir["time"]["t_us"], out)
    base_url = base or f"http://{config.host}:{config.port}/"
    result = None
    if not force_local:
        try:
            result = _from_server(base_url, view_obj.did, tid, ir["time"]["t_us"], view, dest,
                                  width, height, ratio=ratio)
        except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
            result = _local(config, view_obj, tid, ir["time"]["t_us"], view, dest, width, height,
                              ratio=ratio)
            result["server_error"] = f"{exc.__class__.__name__}: {exc}"
    if result is None:
        result = _local(config, view_obj, tid, ir["time"]["t_us"], view, dest, width, height,
                          ratio=ratio)
    result.update({"timeline": tid, "t_us": ir["time"]["t_us"], "layers": len(ir["layers"]),
                   "canvas": ir["canvas"], "url": build_url(base_url, view_obj.did, tid,
                                                            ir["time"]["t_us"], view, ratio=ratio)})
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps({"ok": True, "code": "ok", "reason": "", "data": result},
                     ensure_ascii=False, indent=2))
    return 0
