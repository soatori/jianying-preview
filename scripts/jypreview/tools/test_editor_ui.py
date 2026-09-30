"""Browser acceptance for the read-only editor (plan Task 5).

Self-contained: it starts the real aiohttp app on a loopback port, drives an external
Chromium through CDP, and compares what the browser paints against what the Python IR
says is on screen -- while proving the draft's own bytes never moved.

Run:  python -X utf8 -m jypreview.tools.test_editor_ui [draft-name]
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path

for _key in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(_key, None)

HERE = Path(__file__).resolve().parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

DRAFTS = ("YASHIDA 9月24日", "6月7日 (全顺)", "9月28日")
CACHE_ROOTS = (".jypreview",)
SAMPLES = 5
PLAY_SECONDS = 5


class Acceptance:
    """One browser page against one in-process service, with the counters we assert on."""

    def __init__(self, draft: str) -> None:
        from aiohttp import web
        from aiohttp.test_utils import TestServer

        from ..config import Config
        from ..server.app import create_app
        from ..session import PreviewSession

        self.config = Config()
        self.session = PreviewSession(self.config)
        self.view = self.session.view(draft)
        self.timeline = self.view.resolve_timeline("active") if self.view.active_timeline_id \
            else self.view.timelines[0]
        self.tid = str(self.timeline["id"])
        self.app = create_app(self.config, session=self.session)
        self.loop = asyncio.new_event_loop()
        self.stopped = asyncio.Event()
        self.runner = None
        self.base = ""
        self.browser = None
        self.client = None

    def start(self) -> None:
        import threading

        threading.Thread(target=self._serve_forever, daemon=True).start()
        self._wait_for_server()
        self._open_browser()

    def _serve_forever(self) -> None:
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._serve())
        finally:
            self.loop.run_until_complete(self._shutdown())
            self.loop.close()

    async def _serve(self) -> None:
        from aiohttp import web

        loop = asyncio.get_running_loop()
        default = loop.get_exception_handler()

        def quiet(handler_loop, context):
            # A browser that navigates away resets its connections; that is not a service fault.
            if isinstance(context.get("exception"), (ConnectionResetError, BrokenPipeError)):
                return
            (default or (lambda *_a: None))(handler_loop, context)

        loop.set_exception_handler(quiet)
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        self.runner = runner
        port = site._server.sockets[0].getsockname()[1]  # noqa: SLF001
        self.base = f"http://127.0.0.1:{port}"
        await self.stopped.wait()

    async def _shutdown(self) -> None:
        if self.runner is not None:
            await self.runner.cleanup()

    def _wait_for_server(self, timeout: float = 60.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline and not self.base:
            time.sleep(0.1)
        if not self.base:
            raise AssertionError("the in-process service never bound a port")

    def _open_browser(self) -> None:
        from ..shot.browser import BrowserSession
        from ..shot.cdp import CDP

        self.browser = BrowserSession(Path(self.config.user_state_dir) / "acceptance-editor")
        self.browser.start()
        page = self.browser.new_page("about:blank")
        self.client = CDP(page["webSocketDebuggerUrl"], timeout=90)
        self.client.send("Page.enable")
        self.client.send("Runtime.enable")
        # Counted at the boundary the browser cannot lie about, instead of asking the app
        # to remember what it fetched.
        self.client.send("Page.addScriptToEvaluateOnNewDocument", {"source": """
            window.__requests = [];
            const original = window.fetch;
            window.fetch = (input, init) => {
              window.__requests.push(String(typeof input === 'string' ? input : input.url));
              return original(input, init);
            };
        """})

    def stop(self) -> None:
        if self.client:
            self.client.close()
        if self.browser:
            self.browser.stop()
        self.loop.call_soon_threadsafe(self.stopped.set)
        deadline = time.time() + 20
        while time.time() < deadline:
            time.sleep(0.05)

    def open_page(self) -> None:
        url = f"{self.base}/editor?" + urllib.parse.urlencode({"draft": self.view.did,
                                                               "timeline": self.tid, "t": "0"})
        self.client.send("Page.navigate", {"url": url})
        deadline = time.time() + 120
        while time.time() < deadline:
            try:
                if self.client.evaluate("!!document.querySelector('[data-testid=\"timeline-panel\"]')"):
                    return
            except Exception:
                time.sleep(0.5)
        detail = ""
        try:
            detail = str(self.evaluate("document.body.innerText.slice(0, 400)"))
        except Exception:
            detail = "unreadable"
        raise AssertionError(f"the editor never rendered at {url}: {detail}")

    def evaluate(self, expression: str):
        return self.client.evaluate(expression)

    def frames_built(self) -> int:
        return int(self.app["frames_built"])


HASH_LIMIT_BYTES = 4 << 20


def source_signature(root: Path) -> dict[str, dict[str, object]]:
    """Every file the draft owns, minus our own cache directory.

    Content-hashed up to a few megabytes; larger media is recorded by size and mtime,
    because reading gigabytes per run would make the check too slow to ever be run.
    """
    table: dict[str, dict[str, object]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or set(path.parts) & set(CACHE_ROOTS):
            continue
        stat = path.stat()
        entry: dict[str, object] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
        entry["sha256"] = _sha(path) if stat.st_size <= HASH_LIMIT_BYTES else "size+mtime"
        table[str(path)] = entry
    return table


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_source_is_untouched(state: dict) -> list[str]:
    state["before"] = source_signature(Path(state["acceptance"].view.root))
    assert state["before"], "the draft folder has no files to sign"
    return []


def check_editor_opens_with_read_only_document(state: dict) -> list[str]:
    acceptance = state["acceptance"]
    acceptance.open_page()
    snapshot = acceptance.evaluate("window.__editorSnapshot()")
    assert snapshot, "window.__editorSnapshot() is missing"
    assert snapshot["schema"] == "jypreview/editor-project@1", snapshot["schema"]
    assert snapshot["state"] == "stopped", snapshot
    assert snapshot["timeline"]["id"].upper() == acceptance.tid.upper(), snapshot["timeline"]
    assert snapshot["timeline"]["source_sha256"], "the document reports no source hash"
    assert int(snapshot["clips"]) > 0, snapshot
    state["snapshot"] = snapshot
    return [f"opened {acceptance.view.name} / {acceptance.timeline.get('name')}: "
            f"{snapshot['clips']} clips, {snapshot['tracks']} tracks"]


def check_scene_matches_python_ir(state: dict) -> list[str]:
    acceptance = state["acceptance"]
    duration = int(acceptance.evaluate("window.__editorSnapshot().duration_us"))
    assert duration > 0, duration
    mismatches = []
    for step in range(SAMPLES):
        stamp = int(duration * (step + 0.5) / SAMPLES)
        ir = acceptance.view.frame(acceptance.tid, stamp)
        expected = [layer["layer_id"] for layer in ir["layers"]]
        acceptance.evaluate(f"window.__editorSeek({stamp})")
        time.sleep(0.25)
        scene = acceptance.evaluate("window.__editorScene()")
        got = [item["clip_id"] for item in scene["clips"]]
        if got != expected:
            mismatches.append(f"t={stamp}us python={expected} browser={got}")
    assert not mismatches, "; ".join(mismatches)
    return [f"{SAMPLES} sampled times match the Python layer ids and order exactly"]


def check_boundaries_are_half_open(state: dict) -> list[str]:
    acceptance = state["acceptance"]
    seams = acceptance.evaluate("window.__editorSeams()")
    assert isinstance(seams, list) and seams, "no clip seams reported"
    checked = 0
    for seam in seams[:8]:
        end = int(seam["end_us"])
        acceptance.evaluate(f"window.__editorSeek({end - 1})")
        time.sleep(0.15)
        before = [item["clip_id"] for item in acceptance.evaluate("window.__editorScene()")["clips"]]
        acceptance.evaluate(f"window.__editorSeek({end})")
        time.sleep(0.15)
        after = [item["clip_id"] for item in acceptance.evaluate("window.__editorScene()")["clips"]]
        leaving, entering = str(seam["leaving"]), str(seam["entering"])
        if leaving and leaving not in before:
            raise AssertionError(f"t={end - 1}: {leaving} should still be on screen ({before})")
        if leaving and leaving in after:
            raise AssertionError(f"t={end}: {leaving} is still on screen; the span is not half-open")
        if entering and entering not in after:
            raise AssertionError(f"t={end}: {entering} should have appeared ({after})")
        checked += 1
    return [f"{checked} seams crossed without both clips overlapping"]


def check_playback_is_monotonic(state: dict) -> list[str]:
    acceptance = state["acceptance"]
    acceptance.evaluate("window.__editorSeek(0); window.__editorPlay()")
    marks = []
    started = time.time()
    while time.time() - started < PLAY_SECONDS:
        time.sleep(0.5)
        marks.append(int(acceptance.evaluate("window.__editorSnapshot().t_us")))
    acceptance.evaluate("window.__editorPause()")
    advanced = marks[-1] - marks[0]
    assert all(b >= a for a, b in zip(marks, marks[1:])), f"playhead went backwards: {marks}"
    assert 0.75 * PLAY_SECONDS * 1e6 <= advanced <= 1.35 * PLAY_SECONDS * 1e6, \
        f"playback covered {advanced / 1e6:.2f}s in {PLAY_SECONDS}s"
    return [f"playhead advanced {advanced / 1e6:.2f}s in {PLAY_SECONDS}s without reversing"]


def check_no_frame_request_storm(state: dict) -> list[str]:
    acceptance = state["acceptance"]
    before = acceptance.frames_built()
    acceptance.evaluate("window.__editorSeek(0); window.__editorPlay()")
    time.sleep(2.5)
    acceptance.evaluate("window.__editorPause()")
    requests = json.loads(acceptance.evaluate("JSON.stringify(window.__requests || [])"))
    per_frame = [item for item in requests if "/api/frame" in item]
    assert not per_frame, f"the editor asked for {len(per_frame)} per-frame payloads"
    assert acceptance.frames_built() == before, \
        f"the service built {acceptance.frames_built() - before} frames while playing"
    return [f"{len(requests)} network requests, none of them /api/frame"]


def check_warnings_are_visible(state: dict) -> list[str]:
    acceptance = state["acceptance"]
    acceptance.evaluate("window.__editorSeek(0)")
    time.sleep(0.2)
    panel = acceptance.evaluate("document.querySelector('[data-testid=\"warnings\"]')?.innerText || ''")
    snapshot = acceptance.evaluate("window.__editorSnapshot()")
    assert panel or not snapshot["warnings"], "the warnings panel is empty while the document warns"
    tiers = acceptance.evaluate("document.querySelector('[data-testid=\"tier-counts\"]')?.innerText || ''")
    assert snapshot["warnings"], "this draft produced no warnings; nothing to assert"
    return [f"warnings panel shows {len(snapshot['warnings'])} notes; tiers: {tiers.strip()[:60]}"]


def check_read_only_surface(state: dict) -> list[str]:
    acceptance = state["acceptance"]
    forbidden = ["保存", "导出", "剪切", "删除", "分割", "写入", "撤销", "重做"]
    labels = acceptance.evaluate(
        "JSON.stringify([...document.querySelectorAll('button')]"
        ".map(b => b.getAttribute('aria-label') || b.innerText))")
    names = json.loads(labels) if isinstance(labels, str) else labels
    hits = [name for name in names if any(word in str(name) for word in forbidden)]
    assert not hits, f"an edit command appeared: {hits}"
    controls = acceptance.evaluate("document.querySelectorAll('video[controls], audio[controls]').length")
    assert not controls, "native media controls would let the element drive time"
    return [f"{len(names)} controls, none of them an edit"]


def check_source_signature_survives(state: dict) -> list[str]:
    after = source_signature(Path(state["acceptance"].view.root))
    before = state["before"]
    changed = sorted(key for key, value in after.items() if before.get(key) != value)
    added = sorted(key for key in after if key not in before)
    removed = sorted(key for key in before if key not in after)
    assert not changed, f"files were rewritten: {changed[:3]}"
    assert not added, f"files were created outside the cache: {added[:3]}"
    assert not removed, f"files disappeared: {removed[:3]}"
    strays = [str(path) for path in Path(state["acceptance"].view.root).rglob("manifest.txt")
              if ".jypreview" not in path.parts]
    assert all(item["sha256"] == "size+mtime" or len(str(item["sha256"])) == 64
               for item in after.values()), "a signature entry has no digest"
    assert not strays, f"a cache manifest escaped the cache root: {strays[:2]}"
    return [f"{len(after)} draft files unchanged (sha256 + mtime + size)"]


def main(argv: list[str]) -> int:
    draft = argv[0] if argv else None
    from ..config import Config

    config = Config()
    if config.drafts_root is None or not Path(config.drafts_root).is_dir():
        print(json.dumps({"ok": True, "skipped": "no JianYing corpus on this machine"}))
        return 0
    from ..session import PreviewSession

    session = PreviewSession(config)
    if draft is None:
        for name in DRAFTS:
            try:
                draft = name if session.view(name).timelines else None
                if draft:
                    break
            except Exception:
                continue
    if draft is None:
        print(json.dumps({"ok": True, "skipped": "no readable draft found"}))
        return 0

    acceptance = Acceptance(draft)
    state = {"acceptance": acceptance}
    checks = (check_source_is_untouched, check_editor_opens_with_read_only_document,
              check_scene_matches_python_ir, check_boundaries_are_half_open,
              check_playback_is_monotonic, check_no_frame_request_storm,
              check_warnings_are_visible, check_read_only_surface,
              check_source_signature_survives)
    failures: list[str] = []

    def drive() -> None:
        acceptance.start()
        try:
            for check in checks:
                try:
                    for note in check(state) or []:
                        print(f"note {check.__name__}: {note}", flush=True)
                    print(f"ok   {check.__name__}", flush=True)
                except Exception as exc:
                    failures.append(f"{check.__name__}: {exc.__class__.__name__}: {exc}")
                    print(f"FAIL {check.__name__}: {exc.__class__.__name__}: {exc}", flush=True)
        finally:
            try:
                acceptance.evaluate("window.__editorClose && window.__editorClose()")
            except Exception:
                pass
            acceptance.stop()

    drive()
    print(json.dumps({"ok": not failures, "draft": draft, "checks": len(checks),
                      "failed": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
