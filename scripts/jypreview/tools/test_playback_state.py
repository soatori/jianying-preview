"""Runtime regression tests for the MLT-authoritative playback state machine."""

from __future__ import annotations

import contextlib
import json
import math
import os
import time
import urllib.parse
from pathlib import Path

for _key in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(_key, None)


BASE = os.environ.get("JY_PREVIEW_TEST_BASE", "http://127.0.0.1:8765")
DRAFT = os.environ.get("JY_PREVIEW_TEST_DRAFT", "<草稿 id>")
TIMELINE = os.environ.get("JY_PREVIEW_TEST_TIMELINE", "timeline-primary")


def canonical_frame(t_us: int, fps: float) -> int:
    """First project frame at or after t_us (Task 4's seek mapping)."""
    return math.ceil(t_us * fps / 1e6 - 1e-9)


def main() -> int:
    from ..shot.browser import BrowserSession
    from ..shot.cdp import CDP

    # The normal URL: MLT is the only playback path, no ?backend switch exists.
    url = (f"{BASE}/?draft={urllib.parse.quote(DRAFT)}&timeline="
           f"{urllib.parse.quote(TIMELINE)}&t=0&chrome=1")
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
            with contextlib.suppress(Exception):
                state = client.evaluate("window.__state()")
                if state and state.get("ready") and state.get("durationUs", 0) > 0:
                    break
            time.sleep(0.2)
        else:
            raise AssertionError("preview page did not become ready")

        # 1. The preview reports the MLT backend with a playback identity.
        state = client.evaluate("window.__state()")
        if state.get("backend") != "mlt":
            raise AssertionError(f"backend must be mlt: {state}")
        if not state.get("playbackId"):
            raise AssertionError(f"open did not report a playback id: {state}")
        fps = float(state.get("fps") or 30)
        frame_dur = math.ceil(1e6 / fps)
        duration = int(state["durationUs"])

        # 2. An exact seek reports the requested canonical frame and PTS.
        client.evaluate("window.__renderAt(10000000)", await_promise=True)
        exact = client.evaluate("window.__state()")
        if exact.get("frameIndex") != canonical_frame(10_000_000, fps):
            raise AssertionError(f"exact seek reported the wrong canonical frame: {exact}")
        if not 10_000_000 <= exact.get("tUs", -1) < 10_000_000 + frame_dur:
            raise AssertionError(f"exact seek reported a non-canonical PTS: {exact}")

        # 3. Rapid 10s/20s/30s seeks settle on the last issued request.
        base_request = int(exact.get("seekRequestId") or 0)
        for t_us in (10_000_000, 20_000_000, 30_000_000):
            client.evaluate(f"window.__renderAt({t_us})")
        deadline = time.time() + 30
        while time.time() < deadline:
            state = client.evaluate("window.__state()")
            if (state.get("seekRequestId") == base_request + 3
                    and state.get("tUs", 0) >= 30_000_000
                    and state.get("frameIndex") == canonical_frame(30_000_000, fps)):
                break
            time.sleep(0.1)
        else:
            raise AssertionError(f"rapid seeks did not settle on the last issued request: {state}")

        # Plan step 6, timestamp-aware frame drops: after the rapid seeks the
        # displayed frame may lag the backend clock by at most one frame, and
        # frameIndex must be the canonical frame of what is actually shown.
        deadline = time.time() + 15
        while time.time() < deadline:
            state = client.evaluate("window.__state()")
            shown = state.get("displayedPtsUs")
            if shown is not None and shown >= state.get("tUs", 0) - frame_dur:
                break
            time.sleep(0.1)
        else:
            raise AssertionError(f"displayed frame never caught up with the clock: {state}")
        shown = state["displayedPtsUs"]
        if state.get("frameIndex") != canonical_frame(shown, fps):
            raise AssertionError(f"frameIndex does not match the displayed PTS: {state}")

        # 4. Playback runs on the backend clock: timestamps advance and are
        #    monotonic within a generation.
        client.evaluate("window.__play(true)")
        started = client.evaluate("window.__state()")
        start_t = started.get("tUs", 0)
        deadline = time.time() + 30
        samples = []
        while time.time() < deadline:
            sample = client.evaluate("window.__state()")
            samples.append(sample)
            if sample.get("phase") == "playing" and sample.get("tUs", 0) >= start_t + 1_000_000:
                break
            time.sleep(0.1)
        else:
            raise AssertionError(f"playback did not advance while playing: "
                                 f"{samples[-1] if samples else started}")
        last_by_generation = {}
        for sample in samples:
            generation = sample.get("generation")
            t_us = sample.get("tUs", 0)
            previous = last_by_generation.get(generation)
            if previous is not None and t_us < previous:
                raise AssertionError(f"timestamps moved backwards within a generation: {sample}")
            last_by_generation[generation] = t_us

        # 5. Pause freezes the frame and the clock.
        client.evaluate("window.__play(false)")
        paused = client.evaluate("window.__state()")
        deadline = time.time() + 15
        while time.time() < deadline:
            paused = client.evaluate("window.__state()")
            if paused.get("phase") == "paused":
                break
            time.sleep(0.1)
        else:
            raise AssertionError(f"pause did not enter paused phase: {paused}")
        frozen = paused.get("tUs", -1)
        time.sleep(0.6)
        after_pause = client.evaluate("window.__state()")
        if after_pause.get("phase") != "paused" or after_pause.get("tUs") != frozen:
            raise AssertionError(f"pause did not freeze the clock: {after_pause}")

        # 6. Seeking to the end enters ended.
        client.evaluate(f"window.__renderAt({duration})", await_promise=True)
        ended = client.evaluate("window.__state()")
        deadline = time.time() + 10
        while time.time() < deadline:
            ended = client.evaluate("window.__state()")
            if ended.get("phase") == "ended":
                break
            time.sleep(0.1)
        else:
            raise AssertionError(f"end seek did not enter ended: {ended}")

        # 7. A backend failure surfaces the server message and never activates
        #    DOM media playback.
        client.evaluate("""
            (async () => {
              const id = window.__state().playbackId;
              await fetch(`/api/backend/close?playback_id=${encodeURIComponent(id)}`,
                          { method: "POST" });
              return true;
            })()
        """, await_promise=True)
        client.evaluate("window.__play(true)")
        failed = client.evaluate("window.__state()")
        deadline = time.time() + 15
        while time.time() < deadline:
            failed = client.evaluate("window.__state()")
            if failed.get("phase") == "error":
                break
            time.sleep(0.1)
        else:
            raise AssertionError(f"backend failure did not enter the error phase: {failed}")
        if not failed.get("error"):
            raise AssertionError(f"error phase is missing the server message: {failed}")
        active_media = client.evaluate(
            "[...document.querySelectorAll('video,audio')]"
            ".filter((el) => !el.paused && !el.ended).length")
        if active_media:
            raise AssertionError(f"backend failure activated DOM media playback: {active_media}")

        # 8. Reopening the same timeline rejects the old identity.
        old_playback = failed.get("playbackId")
        client.evaluate("""
            (() => {
              const select = document.getElementById('timelines');
              select.value = window.__state().tid;
              select.onchange({ target: select });
              return true;
            })()
        """)
        reopened = client.evaluate("window.__state()")
        deadline = time.time() + 60
        while time.time() < deadline:
            reopened = client.evaluate("window.__state()")
            if (reopened.get("ready") and reopened.get("playbackId")
                    and reopened.get("playbackId") != old_playback):
                break
            time.sleep(0.2)
        else:
            raise AssertionError(f"reopen did not produce a fresh playback id: {reopened}")
        stale_accepted = client.evaluate(
            f"window.__backend.accepts({{ playbackId: {json.dumps(old_playback)}, "
            "seekRequestId: 999, generation: 99 })")
        if stale_accepted is not False:
            raise AssertionError(f"old identity still updates the new selection: {stale_accepted}")

        print("ok: MLT playback state is authoritative end to end")
        return 0
    finally:
        with contextlib.suppress(Exception):
            client.evaluate("window.__close()", await_promise=True)
        client.close()
        with contextlib.suppress(Exception):
            browser._http(f"/json/close/{page['id']}")  # noqa: SLF001
        browser.stop()


if __name__ == "__main__":
    raise SystemExit(main())
