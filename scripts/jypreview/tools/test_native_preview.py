"""End-to-end native default preview check on the local GStreamer backend."""

from __future__ import annotations

import json
import os
import time
import urllib.parse
from pathlib import Path

for _key in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(_key, None)


BASE = "http://127.0.0.1:8765"
DRAFT = "<草稿 id>"
TIMELINE = "timeline-primary"


def main() -> int:
    from ..shot.browser import BrowserSession
    from ..shot.cdp import CDP

    url = (f"{BASE}/?draft={urllib.parse.quote(DRAFT)}&timeline="
           f"{urllib.parse.quote(TIMELINE)}&t=0&chrome=1")
    browser = BrowserSession(Path.home() / ".jypreview" / "test-native-preview")
    browser.start()
    page = browser.new_page("about:blank")
    client = CDP(page["webSocketDebuggerUrl"], timeout=60)
    try:
        client.send("Page.enable")
        client.send("Runtime.enable")
        client.send("Page.navigate", {"url": url})
        deadline = time.time() + 120
        last = None
        while time.time() < deadline:
            try:
                last = client.evaluate("window.__state()")
                if (last and last.get("ready") and last.get("backend") == "gstreamer-ges"
                        and last.get("loading", {}).get("kind") == "idle"):
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.5)
        else:
            raise AssertionError(f"native preview did not become ready: {last}")
        client.evaluate("window.__play(true)")
        playing = None
        deadline = time.time() + 10
        while time.time() < deadline:
            time.sleep(0.5)
            playing = client.evaluate("window.__state()")
            if playing.get("tUs", 0) > 0 and playing.get("playing"):
                break
        if playing.get("backend") != "gstreamer-ges" or playing.get("tUs", 0) <= 0:
            raise AssertionError(f"native clock did not advance: {playing}")
        client.evaluate("window.__play(false)")
        time.sleep(0.4)
        paused = client.evaluate("window.__state()")
        if paused.get("playing"):
            raise AssertionError(f"native pause did not settle: {paused}")
        print("ok: native GStreamer preview opens, advances, and pauses")
        return 0
    finally:
        try:
            client.evaluate("window.__close()")
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
