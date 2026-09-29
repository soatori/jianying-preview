"""Minimal Chrome DevTools Protocol client over websocket (no playwright dependency)."""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

import websocket


class CDP:
    def __init__(self, ws_url: str, timeout: float = 20.0):
        self.socket = websocket.create_connection(ws_url, timeout=timeout, max_size=None,
                                                  suppress_origin=True)
        self.next_id = 0
        self.timeout = timeout

    def close(self) -> None:
        try:
            self.socket.close()
        except Exception:
            pass

    def send(self, method: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
        self.next_id += 1
        message_id = self.next_id
        self.socket.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        deadline = time.time() + (timeout or self.timeout)
        while time.time() < deadline:
            raw = self.socket.recv()
            if not raw:
                continue
            data = json.loads(raw)
            if data.get("id") != message_id:
                continue
            if "error" in data:
                raise RuntimeError(f"{method}: {data['error'].get('message', data['error'])}")
            return data.get("result", {})
        raise TimeoutError(f"{method} timed out")

    def evaluate(self, expression: str, await_promise: bool = False) -> Any:
        result = self.send("Runtime.evaluate", {"expression": expression,
                                                "returnByValue": True,
                                                "awaitPromise": await_promise})
        if result.get("exceptionDetails"):
            raise RuntimeError(str(result["exceptionDetails"]))
        return (result.get("result") or {}).get("value")


def capture(browser, url: str, out_path: Path, width: int = 1080, height: int = 1920,
            wait_expr: str = "document.readyState === 'complete'",
            extra_wait_ms: int = 400, timeout: float = 30.0) -> dict[str, Any]:
    """Render ``url`` and write a PNG. Returns metadata about what was captured."""
    browser.start()
    page = browser.new_page("about:blank")
    ws_url = page.get("webSocketDebuggerUrl")
    if not ws_url:
        raise RuntimeError("devtools page has no webSocketDebuggerUrl")
    client = CDP(ws_url, timeout=timeout)
    try:
        client.send("Page.enable")
        client.send("Runtime.enable")
        client.send("Emulation.setDeviceMetricsOverride", {"width": width, "height": height,
                                                            "deviceScaleFactor": 1, "mobile": False})
        client.send("Page.navigate", {"url": url})
        deadline = time.time() + timeout
        ready = False
        while time.time() < deadline:
            try:
                if client.evaluate(f"!!({wait_expr})"):
                    ready = True
                    break
            except Exception:
                pass
            time.sleep(0.1)
        if not ready:
            raise TimeoutError(f"page never became ready: {wait_expr}")
        if extra_wait_ms:
            time.sleep(extra_wait_ms / 1000)
        shot = client.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
        blob = base64.b64decode(shot["data"])
    finally:
        client.close()
        try:
            browser._http(f"/json/close/{page['id']}")
        except Exception:
            pass
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(blob)
    import hashlib

    return {"path": str(out_path), "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest(),
            "size": [width, height], "url": url, "ready": ready}
