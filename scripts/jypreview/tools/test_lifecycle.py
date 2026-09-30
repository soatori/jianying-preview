"""Smoke test for the launcher/session lifecycle API."""

from __future__ import annotations

import json
import os
import urllib.request


BASE = os.environ.get("JY_PREVIEW_TEST_BASE", "http://127.0.0.1:8765")


def main() -> int:
    with urllib.request.urlopen(BASE + "/api/health", timeout=10) as response:
        payload = json.load(response)
    if not payload.get("ok"):
        raise AssertionError(payload)
    data = payload.get("data") or {}
    if data.get("service") != "jianying-preview":
        raise AssertionError(f"unexpected health payload: {payload}")
    print("ok: lifecycle health endpoint is available")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
