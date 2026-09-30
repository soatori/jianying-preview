"""Runtime regression tests for the authoritative playback state machine."""

from __future__ import annotations

import json
import os
import time
import urllib.parse
from pathlib import Path

for _key in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(_key, None)


BASE = os.environ.get("JY_PREVIEW_TEST_BASE", "http://127.0.0.1:8765")
DRAFT = os.environ.get("JY_PREVIEW_TEST_DRAFT", "<草稿 id>")
TIMELINE = os.environ.get("JY_PREVIEW_TEST_TIMELINE", "timeline-primary")


def main() -> int:
    from ..shot.browser import BrowserSession
    from ..shot.cdp import CDP

    url = (f"{BASE}/?draft={urllib.parse.quote(DRAFT)}&timeline="
           f"{urllib.parse.quote(TIMELINE)}&t=0&chrome=1&backend=browser")
    browser = BrowserSession(Path.home() / ".jypreview" / "test-playback-state")
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
        first = client.evaluate("window.__state()")
        if first.get("phase") not in ("loading", "buffering", "playing"):
            raise AssertionError(f"invalid phase immediately after play: {first}")

        deadline = time.time() + 30
        samples = []
        while time.time() < deadline:
            state = client.evaluate("window.__state()")
            samples.append(state)
            if state.get("phase") == "playing" and state.get("tUs", 0) >= 200_000:
                break
            time.sleep(0.1)
        else:
            raise AssertionError(f"playback did not become playing: {samples[-1] if samples else None}")

        current = samples[-1]
        window = current.get("window")
        if not window or not (window[0] <= current["tUs"] < window[1]):
            raise AssertionError(f"playing state is outside its window: {current}")
        if not any(later["tUs"] > earlier["tUs"] for earlier, later in zip(samples, samples[1:])):
            raise AssertionError("playback phase was active but the timeline clock never advanced")

        client.evaluate("window.__play(false)")
        paused = client.evaluate("window.__state()")
        if paused.get("phase") != "paused":
            raise AssertionError(f"pause did not enter paused phase: {paused}")
        generation = paused.get("generation", 0)
        client.evaluate("window.__renderAt(10000000)", await_promise=True)
        after_seek = client.evaluate("window.__state()")
        if after_seek.get("generation", 0) <= generation:
            raise AssertionError(
                f"seek did not create a new request generation: before={generation} after={after_seek}"
            )
        client.evaluate("window.__renderAt(20000000)")
        client.evaluate("window.__renderAt(30000000)")
        deadline = time.time() + 30
        while time.time() < deadline:
            state = client.evaluate("window.__state()")
            if state.get("ready") and not state.get("pending") and state.get("tUs", 0) >= 30_000_000:
                break
            time.sleep(0.1)
        else:
            raise AssertionError(f"superseded point requests did not drain: {state}")
        print("ok: playback state machine gates clock advancement on a valid window")
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
