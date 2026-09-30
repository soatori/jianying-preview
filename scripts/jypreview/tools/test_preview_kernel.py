"""Runtime regression tests for the browser playback kernel."""

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
ANIMATED_TEXT = "timeline-animated-text"


def main() -> int:
    from ..shot.browser import BrowserSession
    from ..shot.cdp import CDP

    url = (f"{BASE}/?draft={urllib.parse.quote(DRAFT)}&timeline="
           f"{urllib.parse.quote(TIMELINE)}&t=0&chrome=1")
    browser = BrowserSession(Path.home() / ".jypreview" / "test-preview-kernel")
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

        def text_state(t_us: int):
            client.evaluate(f"window.__renderAt({t_us})", await_promise=True)
            expression = (
                "JSON.stringify(window.__stage.flat.filter((entry) => "
                "entry.layer.layer_id === " + json.dumps(ANIMATED_TEXT) + ").map((entry) => ({"
                "visible: entry.visible, animation: entry.layer.animation, "
                "transform: entry.root.getAttribute('transform'), "
                "styleTransform: entry.root.style.transform, "
                "opacity: entry.root.getAttribute('opacity')})))"
            )
            return json.loads(client.evaluate(expression))

        before = text_state(0)
        during = text_state(250_000)
        if not before or not during:
            raise AssertionError("animated text layer was not present at test times")
        before_dom = [(row["transform"], row["styleTransform"], row["opacity"]) for row in before]
        during_dom = [(row["transform"], row["styleTransform"], row["opacity"]) for row in during]
        if before_dom == during_dom or not any(value for row in during_dom for value in row[:2]):
            raise AssertionError(
                "animated text DOM state did not change between animation frames: "
                f"before={before_dom} during={during_dom}"
            )
        print("ok: text animation changes the rendered DOM state")
        client.evaluate("window.__close()")
        closed = client.evaluate("window.__state()")
        backend_closed = client.evaluate("window.__backend.snapshot().closed")
        if not backend_closed or closed.get("pool", 0) != 0:
            raise AssertionError(f"close left rendered layers behind: {closed}")
        print("ok: close clears the playback pool")
        return 0
    finally:
        client.close()
        try:
            browser._http(f"/json/close/{page['id']}")  # noqa: SLF001
        except Exception:  # noqa: BLE001
            pass
        browser.stop()


if __name__ == "__main__":
    raise SystemExit(main())
