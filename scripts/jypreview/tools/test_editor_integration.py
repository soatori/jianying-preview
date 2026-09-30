"""Integration checks for the built editor served by the Python service (plan Task 4).

Runs the real aiohttp app in-process on a loopback port: no shared 8765 server, no
browser, and nothing outside the derived caches is written.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

for _key in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(_key, None)

HERE = Path(__file__).resolve().parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
DIST_DIR = WEB_DIR / "dist"


def _config():
    from ..config import Config

    return Config()


def _app(config=None):
    from ..server.app import create_app

    return create_app(config or _config())


async def _get(client, path: str) -> tuple[int, dict, bytes]:
    response = await client.request("GET", path)
    body = await response.read()
    content_type = response.headers.get("Content-Type", "")
    payload = {}
    if "json" in content_type and body:
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            payload = {}
    return response.status, payload, body


async def _client(app):
    from aiohttp.test_utils import TestClient, TestServer

    client = TestClient(TestServer(app))
    await client.start_server()
    return client


def check_built_editor_is_served() -> list[str]:
    """`/editor` is the built bundle, never a source file."""
    if not (DIST_DIR / "editor.html").is_file():
        return [f"skip: {DIST_DIR / 'editor.html'} missing — run npm run build first"]
    notes: list[str] = []

    async def run() -> None:
        client = await _client(_app())
        try:
            status, _, body = await _get(client, "/editor")
            assert status == 200, f"/editor returned {status}"
            text = body.decode("utf-8")
            assert 'data-testid="root"' in text or '<div id="root">' in text, text[:200]
            assert "/web/dist/assets/" in text, "the served html does not reference built assets by url"
            assert "src/app/main.tsx" not in text, "the served html still points at TypeScript source"

            asset = next(item for item in text.split('"') if item.startswith("/web/dist/assets/"))
            status, _, body = await _get(client, asset)
            assert status == 200, f"{asset} returned {status}"
            assert body, f"{asset} served an empty body"
            assert "immutable" in (await client.request("GET", asset)).headers.get(
                "Cache-Control", ""), "a hashed asset is not cached forever"
        finally:
            await client.close()

    asyncio.run(run())
    return notes


def check_source_is_not_served_when_built() -> list[str]:
    if not (DIST_DIR / "editor.html").is_file():
        return ["skip: no production bundle to compare against"]
    notes: list[str] = []

    async def run() -> None:
        client = await _client(_app())
        try:
            status, _, body = await _get(client, "/editor")
            assert status == 200, status
            assert b"createRoot" not in body, "the html inlined unbundled source"
            status, _, _ = await _get(client, "/web/src/app/main.tsx")
            assert status in (404, 403), f"source file served at /web/src: {status}"
        finally:
            await client.close()

    asyncio.run(run())
    return notes


def check_static_paths_cannot_escape() -> list[str]:
    attacks = ["/web/../../../../Windows/win.ini", "/web/%2e%2e%2f%2e%2e%2fwin.ini",
               "/web/dist/../../../../etc/passwd", "/web/dist/..%2f..%2fconfig.py",
               "/web/dist/%41%42%43", "/editor/../../scripts/preview.py"]

    async def run() -> None:
        client = await _client(_app())
        try:
            for path in attacks:
                status, _, body = await _get(client, path)
                assert status in (400, 403, 404), f"{path} -> {status}: {body[:80]!r}"
                assert b"[extensions]" not in body and b"python" not in body[:200].lower(), path
        finally:
            await client.close()

    asyncio.run(run())
    return []


def check_api_and_assets_reachable() -> list[str]:
    config = _config()
    if config.drafts_root is None or not Path(config.drafts_root).is_dir():
        return ["skip: no JianYing corpus on this machine"]
    notes: list[str] = []

    async def run() -> None:
        from ..session import PreviewSession

        session = PreviewSession(config)
        rows = [item for item in session.index()["rows"] if item.get("has_content")][:8]
        if not rows:
            notes.append("skip: corpus has no readable draft")
            return
        client = await _client(_app(config))
        try:
            served = None
            for row in rows:
                did = row["did"]
                status, payload, _ = await _get(client, f"/api/editor-project?draft={did}")
                if status == 409:
                    timelines = payload["data"]["available"]
                    status, payload, _ = await _get(
                        client, f"/api/editor-project?draft={did}&timeline={timelines[0]}")
                assert status == 200, f"editor-project {did}: {status} {payload.get('code')}"
                data = payload["data"]
                assert data["read_only"] is True
                assert data["schema"] == "jypreview/editor-project@1"
                status, _, body = await _get(client, f"/api/fonts.css?draft={did}")
                assert status == 200, f"fonts.css: {status}"
                texts = [clip for clip in data["clips"] if clip.get("text")]
                assert "@font-face" in body.decode("utf-8") or not texts,                     f"{did}: {len(texts)} text clips, no font served"
                served = next((clip["asset"]["path_served"] for clip in data["clips"]
                               if clip.get("asset") and clip["asset"].get("path_served")), None)
                if served:
                    break
            if served is None:
                notes.append("no draft in the first eight had locatable media; /media not exercised")
                return
            status, _, body = await _get(client, served)
            assert status in (200, 206), f"media {served}: {status}"
            assert body, "media served an empty body"
            ranged = await client.request("GET", served, headers={"Range": "bytes=0-1023"})
            assert ranged.status == 206, f"range request returned {ranged.status}"
            assert int(ranged.headers.get("Content-Length", 0)) <= 1024, "range ignored"
        finally:
            await client.close()

    asyncio.run(run())
    return notes


def check_sse_marks_the_editor_stale() -> list[str]:
    async def run() -> None:
        app = _app()
        client = await _client(app)
        try:
            response = await client.request("GET", "/api/events")
            assert response.status == 200, response.status
            assert "text/event-stream" in response.headers.get("Content-Type", "")
            await response.content.readuntil(b": connected\n\n")

            async def publish() -> None:
                await asyncio.sleep(0.15)
                app["hub"].publish("draft.changed", {"did": "abc", "path": "/tmp/x"})

            task = asyncio.ensure_future(publish())
            raw = await asyncio.wait_for(response.content.readuntil(b"\n\n"), timeout=5)
            await task
            text = raw.decode("utf-8")
            assert "event: draft.changed" in text, text
            assert '"did": "abc"' in text.replace("'", '"'), text
        finally:
            await client.close()

    asyncio.run(run())
    return []


def check_read_only_surface() -> list[str]:
    async def run() -> None:
        app = _app()
        client = await _client(app)
        try:
            for path in ("/api/editor-project", "/editor"):
                response = await client.request("POST", path)
                assert response.status in (404, 405), f"POST {path} -> {response.status}"
            methods = {route.method for route in app.router.routes()}
            assert "POST" in methods, "the lease/session routes are POST-only; check the router"
            for route in app.router.routes():
                if route.resource is None:
                    continue
                path = getattr(route.resource, "canonical", "")
                assert not (route.method == "POST" and path.startswith("/api/editor")), \
                    f"a write verb leaked onto the editor surface: {route.method} {path}"
        finally:
            await client.close()

    asyncio.run(run())
    return []


CHECKS = (
    ("built editor is served", check_built_editor_is_served),
    ("source is not served when built", check_source_is_not_served_when_built),
    ("static paths cannot escape", check_static_paths_cannot_escape),
    ("api and assets reachable", check_api_and_assets_reachable),
    ("sse marks the editor stale", check_sse_marks_the_editor_stale),
    ("read-only surface", check_read_only_surface),
)


def main() -> int:
    failures: list[str] = []
    for label, check in CHECKS:
        try:
            for note in check() or []:
                print(f"note {label}: {note}")
            print(f"ok   {label}")
        except Exception as exc:
            failures.append(f"{label}: {exc.__class__.__name__}: {exc}")
            print(f"FAIL {label}: {exc.__class__.__name__}: {exc}")
    print(json.dumps({"ok": not failures, "checks": len(CHECKS), "failed": failures},
                     ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
