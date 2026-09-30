"""Regression test for repeated compound-clip children in the playback pool.

The <草稿> 成片 timeline contains several instances of the same compound clip.
Those instances reuse the child segment IDs, but each instance has a different
outer time range and must remain a separate DOM-pool entry during windowed
playback.

Run with the read-only preview server already listening on 127.0.0.1:8765::

    python -m jypreview.tools.test_playback_pool
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

for _key in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(_key, None)


BASE = "http://127.0.0.1:8765"
DRAFT = "<草稿 id>"
TIMELINE = "timeline-primary"


def get(path: str, **query):
    url = BASE + path + "?" + urllib.parse.urlencode(query)
    with urllib.request.urlopen(url, timeout=300) as response:
        payload = json.load(response)
    if not payload.get("ok"):
        raise RuntimeError(payload)
    return payload["data"]


def flatten(layers):
    result = []
    for layer in layers:
        nested = (layer.get("nest") or {}).get("layers") or []
        result.extend(flatten(nested) if nested else [layer])
    return result


def nested_video_ids(layers, parents=()):
    result = []
    for layer in layers:
        media = layer.get("media") or {}
        if media.get("family") == "video" and parents:
            result.append(layer["layer_id"])
        nested = (layer.get("nest") or {}).get("layers") or []
        if nested:
            result.extend(nested_video_ids(nested, parents + (layer["layer_id"],)))
    return result


def video_layers(layers, parents=()):
    result = []
    for layer in layers:
        if (layer.get("media") or {}).get("family") == "video":
            result.append((layer, parents))
        nested = (layer.get("nest") or {}).get("layers") or []
        if nested:
            result.extend(video_layers(nested, parents + (layer["layer_id"],)))
    return result


def main() -> int:
    from ..shot.browser import BrowserSession
    from ..shot.cdp import CDP

    window_ir = get("/api/frame", draft=DRAFT, timeline=TIMELINE,
                    t_us=0, window_us=20_000_000)
    counts = Counter(layer["layer_id"] for layer in flatten(window_ir["layers"]))
    duplicate_id, expected = next((item for item in counts.items() if item[1] > 1), (None, 0))
    if not duplicate_id:
        raise AssertionError("fixture no longer contains a repeated compound-clip child")
    later_ir = get("/api/frame", draft=DRAFT, timeline=TIMELINE, t_us=30_600_000)
    later_nested_id = next(iter(nested_video_ids(later_ir["layers"])), None)
    if not later_nested_id:
        raise AssertionError("fixture no longer contains a later nested video")
    mid_ir = get("/api/frame", draft=DRAFT, timeline=TIMELINE, t_us=14_000_000)
    mid_direct = next(
        (layer for layer, parents in video_layers(mid_ir["layers"]) if not parents),
        None,
    )
    if not mid_direct:
        raise AssertionError("fixture no longer contains a direct video at 14s")
    mid_direct_id = mid_direct["layer_id"]

    url = (f"{BASE}/?draft={urllib.parse.quote(DRAFT)}&timeline={urllib.parse.quote(TIMELINE)}"
           "&t=0&chrome=1&backend=browser")
    browser = BrowserSession(Path.home() / ".jypreview" / "test-playback-pool")
    browser.start()
    page = browser.new_page("about:blank")
    client = CDP(page["webSocketDebuggerUrl"], timeout=60)
    try:
        client.send("Page.enable")
        client.send("Runtime.enable")
        client.send("Page.navigate", {"url": url})
        deadline = time.time() + 90
        while time.time() < deadline:
            try:
                state = client.evaluate("window.__state()")
                if state and state.get("ready") and state.get("durationUs", 0) > 0:
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.2)
        else:
            raise AssertionError("preview page did not become ready")

        client.evaluate("window.__play(true)")
        deadline = time.time() + 30
        while time.time() < deadline:
            state = client.evaluate("window.__state()")
            if (state.get("window") and not state.get("buffering")
                    and state.get("tUs", 0) >= 200_000):
                break
            time.sleep(0.1)
        else:
            raise AssertionError("windowed playback did not leave its initial buffer")

        expression = (
            "window.__stage.flat.filter((entry) => "
            f"entry.layer.layer_id === {json.dumps(duplicate_id)}).length"
        )
        actual = client.evaluate(expression)
        if actual != expected:
            raise AssertionError(
                f"repeated child {duplicate_id} collapsed in pool: expected {expected}, got {actual}"
            )

        deadline = time.time() + 30
        while time.time() < deadline:
            state = client.evaluate("window.__state()")
            if (state.get("window") and not state.get("buffering")
                    and state.get("tUs", 0) >= 14_800_000):
                break
            time.sleep(0.1)
        else:
            raise AssertionError("natural playback did not reach the 14s overlay window")
        if state.get("armed", 0) > 8:
            raise AssertionError(f"stale media sources were retained: {state.get('armed')} armed entries")
        snapshot = client.evaluate("window.__snapshot()")
        mid_entry = next((item for item in snapshot["layers"] if item["id"] == mid_direct_id), None)
        if not mid_entry or mid_entry["paused"]:
            raise AssertionError(
                f"direct video {mid_direct_id} was not started in natural playback: {mid_entry}"
            )

        client.evaluate("window.__play(false)")
        client.evaluate("window.__renderAt(30600000)", await_promise=True)
        deadline = time.time() + 30
        while time.time() < deadline:
            state = client.evaluate("window.__state()")
            if (state.get("ready") and not state.get("playing")
                    and state.get("tUs", 0) >= 30_600_000):
                break
            time.sleep(0.1)
        else:
            raise AssertionError("point render at 30.6s did not become ready")
        expression = (
            "window.__stage.flat.some((entry) => entry.visible && entry.armed && "
            f"entry.layer.layer_id === {json.dumps(later_nested_id)})"
        )
        if not client.evaluate(expression):
            raise AssertionError(f"later nested video {later_nested_id} was not armed at its outer time")

        print(f"ok: repeated child {duplicate_id} has {actual} independent pool entries")
        print(f"ok: later nested video {later_nested_id} is armed at 30.6s")
        print(f"ok: direct video {mid_direct_id} was started and stale sources were released")
        return 0
    finally:
        try:
            client.evaluate("window.__play(false)")
        except Exception:  # noqa: BLE001
            pass
        client.close()
        try:
            browser._http(f"/json/close/{page['id']}")  # noqa: SLF001
        except Exception:  # noqa: BLE001
            pass
        browser.stop()


if __name__ == "__main__":
    raise SystemExit(main())
