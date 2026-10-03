"""Playback controller phase, identity, and clock regression assertions."""

from __future__ import annotations

import asyncio
import contextlib
import struct
import threading
import time
import wave
from array import array
from pathlib import Path
from typing import cast

from jypreview.mlt_backend import PlaybackController, RenderedFrame, _stop_consumer
from jypreview.model.timeline import (
    Clip,
    FrameRate,
    MediaRef,
    TimelineModel,
    TimeRange,
    Track,
)

W, H = 300, 180
FPS = FrameRate(30)
ROOT = Path(__file__).resolve().parents[3] / "temp" / "mlt-controller"
LONG_US = 31_000_000
SNAPSHOT_KEYS = {"backend", "phase", "playback_id", "seek_request_id", "generation",
                 "frame_index", "t_us", "duration_us", "playing", "error", "open"}
FRAME_HEADERS = ("X-Playback-ID", "X-Playback-Generation", "X-Seek-Request-ID",
                 "X-Project-Frame", "X-Project-PTS-US")


def encoding_formats():
    import io
    from PIL import Image
    from jypreview.server.handlers_backend import _encode_jpeg, _encode_png
    rgba = bytes((255,0,0,255, 0,255,0,127, 0,0,255,0, 17,83,191,255))
    frame = RenderedFrame("p",1,2,3,100000,2,2,rgba)
    expected = io.BytesIO()
    Image.frombytes("RGBA",(2,2),rgba).convert("RGB").save(expected,format="JPEG",quality=85)
    assert _encode_jpeg(frame) == expected.getvalue(), "RGBX must keep exact q85 JPEG bytes"
    with Image.open(io.BytesIO(_encode_png(frame))) as image:
        assert image.format == "PNG" and image.tobytes() == rgba
    print("ok: stream JPEG q85 byte identity and point-frame PNG RGBA")


def frame_handoff():
    controller = PlaybackController()
    submit = controller._submit
    rgba = bytes((255,0,0,255))*4
    def ready():
        controller._open = True
        controller._phase = "ready"
        controller._playback_id = "handoff"
        controller._fps = FPS
        controller._width = controller._height = 2
        controller._stamp(237,rgba)
        controller._seek_frame = RenderedFrame("handoff",0,0,1,FPS.sample_us(1),2,2,rgba)
        return controller._frame_slot, controller._seek_frame
    selected, target = submit(ready)
    replaced = False
    def reply_then_callback(handler, *args):
        nonlocal replaced
        result = submit(handler, *args)
        if not replaced:
            replaced = True
            callback = threading.Thread(target=controller._stamp,args=(238,bytes(16)))
            callback.start(); callback.join(1)
            assert not callback.is_alive(), "selected frame must not block the callback"
        return result
    try:
        controller._submit = reply_then_callback
        assert controller.pull_frame(0) is selected, "handoff must return selected237, not replacement238"
        assert controller.pull_frame(0).frame_index == 238
        replaced = False
        assert controller.pull_frame(0,seek_target=True) is target
        controller._submit = submit
        def empty():
            controller._frame_slot = controller._seek_frame = None
        submit(empty)
        assert controller.pull_frame(0) is None and controller.pull_frame(0,seek_target=True) is None
        started = time.monotonic()
        assert controller.pull_frame(10) is None
        assert .01 <= time.monotonic()-started < .25
        submit(lambda: setattr(controller,"_phase","ended"))
        assert controller.pull_frame(0) is None
        submit(lambda: (setattr(controller,"_phase","error"),setattr(controller,"_error","dead sink")))
        try:
            controller.pull_frame(0)
        except RuntimeError as exc:
            assert str(exc) == "playback failed: dead sink"
        else:
            raise AssertionError("dead sink must remain a pull error")
    finally:
        controller._submit = submit
        controller.close()
    assert selected.rgba == rgba, "immutable selected bytes must survive shutdown"
    print("ok: atomic worker frame handoff, frozen seek target, empty/timeout/ended/error")


def native_frame_handoff(long_model):
    controller = PlaybackController()
    submit = controller._submit
    selected = []
    def reply_after_native_progress(handler, *args):
        result = submit(handler, *args)
        if handler == controller._h_prepare_pull and not selected:
            frame = result[2]
            assert frame is not None
            selected.append(frame)
            deadline = time.monotonic()+1
            while controller._frame_slot is frame and time.monotonic()<deadline:
                time.sleep(.002)
            assert controller._frame_slot.frame_index > frame.frame_index
        return result
    try:
        opened = controller.open(long_model)
        controller.play()
        deadline = time.monotonic()+5
        while time.monotonic()<deadline:
            if controller.snapshot()["phase"] == "playing":
                break
            time.sleep(.01)
        else:
            raise AssertionError("native handoff fixture did not start")
        controller._submit = reply_after_native_progress
        returned = controller.pull_frame(0)
        controller._submit = submit
        live = controller.pull_frame(0)
        assert returned is selected[0] and live.frame_index > returned.frame_index
        assert returned.playback_id == opened["playback_id"] and returned.generation == 0
        assert returned.pts_us == FPS.sample_us(returned.frame_index)
        assert len(returned.rgba) == W*H*4
        print(f"ok: native handoff kept frame {returned.frame_index} while live advanced to {live.frame_index}")
    finally:
        controller._submit = submit
        controller.close()


def stream_readiness():
    controller = PlaybackController()
    submit = controller._submit
    rgba = bytes(16)
    def ready(position=237):
        controller._open = True
        controller._phase = "paused"
        controller._playback_id = "readiness"
        controller._fps = FPS
        controller._width = controller._height = 2
        controller._stamp(position,rgba)
        frame = controller._frame_slot
        return (frame.playback_id,frame.generation,frame.seek_request_id,frame.frame_index,frame.pts_us)
    def wait_call(after, timeout=500):
        result = []
        def call():
            try: result.append(controller._pull_stream_frame(timeout,after_identity=after))
            except Exception as exc: result.append(exc)
        thread = threading.Thread(target=call)
        thread.start()
        return thread,result
    try:
        after = submit(ready)
        assert hasattr(controller,"_pull_stream_frame"), "bounded frame-ready stream wait is missing"
        def brief_frame():
            time.sleep(.003); controller._stamp(238,rgba)
            time.sleep(.003); controller._stamp(239,rgba)
        producer = threading.Thread(target=brief_frame)
        producer.start()
        frame = controller._pull_stream_frame(100,after_identity=after)
        producer.join()
        assert frame.frame_index == 238, "3ms-lived frame must wake the stream between checks"
        # An update after selection but before reply must leave a ready signal.
        after = submit(ready)
        fired = False
        def selection_then_update(handler,*args):
            nonlocal fired
            result = submit(handler,*args)
            if not fired:
                fired = True
                controller._stamp(238,rgba)
            return result
        controller._submit = selection_then_update
        assert controller._pull_stream_frame(100,after_identity=after).frame_index == 238
        controller._submit = submit
        # Same identity notifications never extend the absolute deadline or emit repeats.
        after = submit(lambda: ready(238))
        stop = threading.Event()
        def repeat():
            while not stop.wait(.002): controller._stamp(238,rgba)
        producer = threading.Thread(target=repeat)
        producer.start(); started=time.monotonic()
        assert controller._pull_stream_frame(40,after_identity=after) is None
        elapsed=time.monotonic()-started; stop.set(); producer.join()
        assert .035 <= elapsed < .15, elapsed
        thread,result = wait_call(after)
        time.sleep(.01); submit(controller._end_of_stream)
        thread.join(.2)
        assert not thread.is_alive() and result == [None], result
        after = submit(ready)
        thread,result = wait_call(after)
        time.sleep(.01); submit(controller._fail,RuntimeError("readiness sink failed"))
        thread.join(.2)
        assert not thread.is_alive() and isinstance(result[0],RuntimeError), result
        after = submit(ready)
        thread,result = wait_call(after)
        time.sleep(.01); controller.close(); thread.join(.2)
        assert not thread.is_alive() and isinstance(result[0],ValueError), result
    finally:
        controller._submit = submit
        controller.close()
    print("ok: stream readiness catches3ms frame, preserves deadline, wakes end/error/close")


def native_stream_readiness(long_model):
    controller = PlaybackController()
    result = []
    try:
        opened = controller.open(long_model)
        frame = controller.pull_frame(0)
        after = (frame.playback_id,frame.generation,frame.seek_request_id,frame.frame_index,frame.pts_us)
        def waiting():
            result.append(controller._pull_stream_frame(500,after_identity=after))
        waiter = threading.Thread(target=waiting)
        waiter.start(); time.sleep(.01)
        controller.seek(500000,playback_id=opened["playback_id"],request_id=1)
        waiter.join(1)
        assert not waiter.is_alive() and result[0].frame_index == 15, result
        assert result[0].generation == 1 and result[0].seek_request_id == 1
        assert controller.pull_frame(0,seek_target=True) is result[0]
        print("ok: native seek wakes stream waiter with exact frame 15 and frozen identity")
    finally:
        controller.close()


def still(name, rgb):
    """One flat BMP still; content only needs to be a decodable visual clip."""
    path = ROOT / f"{name}.bmp"
    row = bytes((rgb[2], rgb[1], rgb[0])) * W
    data = row * H
    path.write_bytes(b"BM" + struct.pack("<IHHI", 54 + len(data), 0, 0, 54)
                     + struct.pack("<IiiHHIIiiII", 40, W, H, 1, 24, 0, len(data), 0, 0, 0, 0)
                     + data)
    return MediaRef(name, str(path), True, width=W, height=H, has_audio=False)


def tone(name, seconds):
    """Quiet 48 kHz stereo tone so the local audio sink has a real clock source."""
    path = ROOT / f"{name}.wav"
    with wave.open(str(path), "wb") as out:
        out.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
        out.writeframes(array("h", [500] * (2 * 48000 * seconds)).tobytes())
    return MediaRef(name, str(path), True, TimeRange(0, seconds * 1_000_000),
                    seconds * 1_000_000, has_audio=True)


def build_model(duration_us, visual, audio):
    picture = Clip("bg", "image", TimeRange(0, duration_us), TimeRange(0, duration_us), visual)
    return TimelineModel("controller", duration_us, FPS, (W, H), (
        Track("video", "video", (picture,)),
        Track("audio", "audio", (Clip("tone", "audio", TimeRange(0, duration_us),
                                      TimeRange(0, duration_us), audio),)),
    ))


def must_raise(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ValueError:
        return
    raise AssertionError(f"{fn} accepted {args} {kwargs}")


def phase_machine(long_model):
    controller = PlaybackController()
    idle = controller.snapshot()
    assert set(idle) == SNAPSHOT_KEYS and idle["backend"] == "mlt"
    assert idle["phase"] == "idle" and not idle["open"] and idle["error"] is None
    assert idle["duration_us"] == 0 and idle["playing"] is False

    ready = controller.open(long_model)
    assert set(ready) == SNAPSHOT_KEYS and ready["phase"] == "ready" and ready["open"]
    assert ready["generation"] == 0 and ready["seek_request_id"] == 0
    assert ready["frame_index"] == 0 and ready["t_us"] == 0 and ready["playing"] is False
    assert ready["duration_us"] == LONG_US and ready["error"] is None
    playback_id = ready["playback_id"]
    assert playback_id and len(playback_id) >= 16

    # Request 0 is valid immediately after open: the selected frame 0 is retrievable.
    first = controller.pull_frame(500)
    assert first is not None and first.frame_index == 0 and first.pts_us == 0
    assert first.seek_request_id == 0 and first.generation == 0
    assert first.playback_id == playback_id and len(first.rgba) == W * H * 4

    # Seek quantization: 50 ms at 30 FPS is frame 1, canonical sample 33_334 us.
    seeking = controller.seek(50_000, playback_id=playback_id, request_id=1)
    assert seeking["phase"] == "seeking" and seeking["generation"] == 1
    assert seeking["seek_request_id"] == 1 and seeking["playing"] is False
    frame = controller.pull_frame(2_000)
    assert frame is not None and frame.frame_index == 1 and frame.pts_us == 33_334
    assert frame.seek_request_id == 1 and frame.generation == 1
    settled = controller.snapshot()
    assert settled["phase"] == "ready" and settled["frame_index"] == 1
    assert settled["t_us"] == 33_334 and settled["playing"] is False

    # Explicit backward seek starts a new generation and may lower project time.
    backward = controller.seek(0, playback_id=playback_id, request_id=2)
    assert backward["generation"] == 2 and backward["phase"] == "seeking"
    frame = controller.pull_frame(2_000)
    assert frame is not None and frame.frame_index == 0 and frame.generation == 2
    assert controller.snapshot()["t_us"] == 0
    return controller, playback_id


def arrival_order(controller, playback_id):
    """Requests arrive 3, 1, 2: only ID 3 may seek or increment generation."""
    third = controller.seek(30_000_000, playback_id=playback_id, request_id=3)
    assert third["phase"] == "seeking" and third["generation"] == 3
    assert third["seek_request_id"] == 3 and third["frame_index"] == 0
    first = controller.seek(10_000_000, playback_id=playback_id, request_id=1)
    second = controller.seek(20_000_000, playback_id=playback_id, request_id=2)
    assert first == third and second == third, (first, second, third)
    replay = controller.seek(30_000_000, playback_id=playback_id, request_id=3)
    assert replay == third, "repeating ID 3 must be idempotent"

    frame = controller.pull_frame(2_000)
    assert frame is not None and frame.seek_request_id == 3 and frame.generation == 3
    assert frame.frame_index == 900 and frame.pts_us == FPS.sample_us(900)
    settled = controller.snapshot()
    assert settled["phase"] == "ready" and settled["frame_index"] == 900
    assert settled["seek_request_id"] == 3 and settled["generation"] == 3

    before = controller.snapshot()
    for invalid in (0, -1, "abc", None):
        must_raise(controller.seek, 1_000_000, playback_id=playback_id, request_id=invalid)
    must_raise(controller.seek, 1_000_000, playback_id="stale", request_id=99)
    assert controller.snapshot() == before, "rejected seeks must not mutate the snapshot"


def end_and_cleanup(controller, playback_id):
    ended = controller.seek(LONG_US, playback_id=playback_id, request_id=4)
    assert ended["phase"] == "ended" and ended["generation"] == 4
    assert ended["seek_request_id"] == 4 and ended["playing"] is False
    assert ended["t_us"] >= LONG_US, ended
    assert controller.pull_frame(150) is None, "seek at the timeline end must not pull a frame"

    resumed = controller.seek(1_000_000, playback_id=playback_id, request_id=5)
    assert resumed["phase"] == "seeking" and resumed["generation"] == 5
    settled = controller.snapshot()  # completes the accepted seek
    assert settled["phase"] == "ready" and settled["frame_index"] == 30
    assert settled["t_us"] == 1_000_000 and settled["error"] is None
    return settled


def transport_and_clock(controller, playback_id):
    buffering = controller.play()
    assert buffering["phase"] == "buffering" and buffering["playing"] is False
    frame = controller.pull_frame(3_000)
    assert frame is not None and frame.generation == 5
    assert controller.snapshot()["phase"] == "playing"

    # Snapshot time follows the consumer clock and stays monotonic in a generation.
    previous, samples = -1, 0
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        snap = controller.snapshot()
        assert snap["phase"] == "playing", snap
        assert snap["generation"] == 5 and snap["t_us"] >= previous, (previous, snap)
        previous, samples = snap["t_us"], samples + 1
        time.sleep(0.03)
    assert samples > 20 and previous >= 900_000, (samples, previous)

    paused = controller.pause()
    assert paused["phase"] == "paused" and paused["playing"] is False
    frozen = controller.snapshot()["t_us"]
    time.sleep(0.1)
    assert controller.snapshot()["t_us"] == frozen, "pause must freeze the project clock"

    # Resume after seek: playing stops, the accepted frame arrives, playback continues.
    assert controller.play()["phase"] == "buffering"
    assert controller.pull_frame(3_000) is not None
    assert controller.snapshot()["phase"] == "playing"
    seek = controller.seek(5_000_000, playback_id=playback_id, request_id=6)
    assert seek["phase"] == "seeking" and seek["generation"] == 6
    resumed = controller.snapshot()
    assert resumed["phase"] == "buffering" and resumed["frame_index"] == 150
    assert resumed["t_us"] == 5_000_000
    frame = controller.pull_frame(3_000)
    assert frame is not None and frame.frame_index == 150
    assert frame.generation == 6 and frame.seek_request_id == 6
    assert controller.snapshot()["phase"] == "playing"

    # A delayed frame keeps the identity captured when it was produced.
    delayed = controller.pull_frame(500)
    assert delayed is not None and delayed.generation == 6
    assert delayed.seek_request_id == 6 and delayed.playback_id == playback_id
    newer = controller.seek(6_000_000, playback_id=playback_id, request_id=7)
    assert newer["generation"] == 7
    assert delayed.generation == 6 and delayed.seek_request_id == 6
    assert delayed.playback_id == playback_id, "transport must not re-label a delayed frame"
    fresh = controller.pull_frame(3_000)
    assert fresh is not None and fresh.generation == 7 and fresh.seek_request_id == 7

    later = controller.snapshot()
    time.sleep(0.2)
    advanced = controller.snapshot()
    assert advanced["t_us"] >= later["t_us"] and advanced["generation"] == 7
    return controller


def consumer_failure_and_reopen(long_model, playback_id):
    controller = PlaybackController()
    controller.open(long_model)
    controller.play()
    controller.pull_frame(3_000)
    assert controller.snapshot()["phase"] == "playing"
    if controller._consumer is not None:
        _stop_consumer(controller._consumer)  # simulate a consumer dying mid-playback
    failed = controller.snapshot()
    assert failed["phase"] == "error" and failed["error"], failed
    assert failed["playing"] is False
    must_raise(controller.play)
    must_raise(controller.seek, 0, playback_id=playback_id, request_id=9)

    controller.close()
    closed = controller.snapshot()
    assert closed["phase"] == "idle" and not closed["open"]
    for call in (lambda: controller.play(),
                 lambda: controller.pull_frame(50),
                 lambda: controller.seek(0, playback_id=playback_id, request_id=10)):
        must_raise(call)

    # Reopening invalidates the previous opaque playback identity.
    reopened = controller.open(long_model)
    fresh_id = reopened["playback_id"]
    assert fresh_id != playback_id and reopened["generation"] == 0
    must_raise(controller.seek, 0, playback_id=playback_id, request_id=11)
    assert controller.snapshot()["seek_request_id"] == 0
    assert controller.pull_frame(500) is not None
    controller.close()


def playing_backward_seek(long_model):
    """A rewind cannot reuse the sink's last position, including near EOS."""
    controller = PlaybackController()
    try:
        playback_id = controller.open(long_model)["playback_id"]
        for request_id, old_us in ((1, 8_000_000), (3, LONG_US - 500_000)):
            controller.seek(old_us, playback_id=playback_id, request_id=request_id)
            controller.snapshot()
            controller.play()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                before = controller.snapshot()
                if before["phase"] == "playing" and before["t_us"] > old_us:
                    break
                assert before["phase"] not in ("error", "ended"), before
                time.sleep(0.01)
            else:
                raise AssertionError(f"playback did not advance: {before}")
            controller.seek(50_000, playback_id=playback_id, request_id=request_id + 1)
            target = controller.snapshot()
            assert target["t_us"] == 33_334 and target["frame_index"] == 1, target
            frame = controller.pull_frame(500, seek_target=True)
            assert frame is not None and frame.frame_index == 1, frame
            assert frame.seek_request_id == request_id + 1
            immediate = controller.snapshot()
            assert immediate["t_us"] < 500_000, (before, target, immediate)
            assert immediate["phase"] in ("buffering", "playing"), immediate
            time.sleep(0.5)
            advanced = controller.snapshot()
            assert 33_334 < advanced["t_us"] < 1_000_000, advanced
            assert advanced["phase"] == "playing", advanced
            live = controller.pull_frame(0)
            assert live is not None and live.frame_index > 1, live
            for _ in range(2):
                frozen = controller.pull_frame(0, seek_target=True)
                assert frozen is not None and frozen.frame_index == 1 and frozen.pts_us == 33_334, frozen
                assert frozen.seek_request_id == request_id + 1
            print(f"ok: playing rewind {before['t_us']} -> {target['t_us']} -> "
                  f"{immediate['t_us']} -> {advanced['t_us']}")
            controller.pause()
    finally:
        controller.close()


def end_of_stream(short_model):
    controller = PlaybackController()
    playback_id = controller.open(short_model)["playback_id"]
    controller.play()
    deadline = time.monotonic() + 10
    snap = {}
    while time.monotonic() < deadline:
        controller.pull_frame(50)
        snap = controller.snapshot()
        if snap["phase"] == "ended":
            break
        time.sleep(0.05)
    else:
        raise AssertionError(f"playback never reached the timeline end: {snap}")
    assert snap["error"] is None and snap["playing"] is False
    rewind = controller.seek(0, playback_id=playback_id, request_id=1)
    assert rewind["phase"] == "seeking"
    settled = controller.snapshot()
    assert settled["phase"] == "ready" and settled["frame_index"] == 0
    assert settled["t_us"] == 0 and settled["error"] is None
    controller.close()


def missing_consumer_output(long_model):
    """Manual captures and retained consumer.position cannot impersonate output."""
    class SilentController(PlaybackController):
        def _on_frame_show(self, _properties, _data, event_data):
            pass  # Simulate a sink that never delivers its output event.

    controller = SilentController()
    try:
        playback_id = controller.open(long_model)["playback_id"]
        controller.seek(50_000, playback_id=playback_id, request_id=1)
        controller.snapshot()
        started = controller.play()
        returned_at = time.monotonic()
        assert started["phase"] == "buffering" and started["t_us"] == 33_334, started
        deadline = returned_at + 2.5
        while time.monotonic() < deadline:
            snap = controller.snapshot()
            if snap["phase"] == "error":
                break
            assert snap["phase"] == "buffering" and snap["t_us"] == 33_334, snap
            time.sleep(0.02)
        elapsed = time.monotonic() - returned_at
        assert snap["phase"] == "error" and "no frame" in snap["error"], snap
        assert 1.45 <= elapsed < 2.5, elapsed
        print(f"ok: missing output kept target/buffering then failed after {elapsed:.3f}s")
    finally:
        controller.close()


def worker_lifecycle(short_model):
    """close() must retire the worker; open/close cycles must not leak threads."""
    baseline = threading.active_count()
    for _ in range(5):
        controller = PlaybackController()
        controller.open(short_model)
        controller.close()
        controller.close()  # idempotent second close is a no-op
    # A failed open still owns a live worker; close must retire it too.
    failing = PlaybackController()
    must_raise(failing.open, "not a timeline")
    failing.close()
    deadline = time.monotonic() + 5
    while threading.active_count() > baseline and time.monotonic() < deadline:
        time.sleep(0.02)
    leftover = [t for t in threading.enumerate() if t.name == "jypreview-playback"]
    assert not leftover, f"worker threads leaked: {leftover}"
    assert threading.active_count() <= baseline + 1, (baseline, threading.active_count())
    print(f"ok: {5 + 1} open/close cycles retired all workers; "
          f"active_count {baseline} -> {threading.active_count()}")


async def _read_until(stream, marker: bytes) -> bytes:
    buffer = b""
    while marker not in buffer:
        chunk = await stream.read(1)
        if not chunk:
            raise AssertionError(f"stream ended before {marker!r}: {buffer!r}")
        buffer += chunk
    return buffer


async def endpoint_acceptance(model):
    """Drive all nine HTTP routes against a fake view exposing timeline_model."""
    import aiohttp
    from aiohttp.test_utils import TestClient, TestServer

    from jypreview.config import Config
    from jypreview.server import handlers_backend
    from jypreview.server.app import create_app
    from jypreview.session import PreviewSession

    class FakeView:
        did = "fake-draft"

        def resolve_timeline(self, selector):
            return {"id": "timeline-acceptance", "duration_us": model.duration_us}

        def timeline_model(self, tid):
            return model

    class FakeSession:
        def view(self, selector, force=False):
            return FakeView()

    config = Config(drafts_root=ROOT, jianying_root=ROOT, install_root=ROOT,
                    user_state_dir=ROOT / "state")
    app = create_app(config, session=cast(PreviewSession, FakeSession()))
    client = TestClient(TestServer(app), timeout=aiohttp.ClientTimeout(total=60))
    await client.start_server()
    base = {"draft": "fake-draft", "timeline": "timeline-acceptance"}
    try:
        caps = await client.get("/api/backend/capabilities")
        caps_body = await caps.json()
        assert caps.status == 200 and caps_body["ok"], (caps.status, caps_body)
        assert caps_body["data"]["name"] == "mlt", caps_body
        assert caps_body["data"]["available"] is True, caps_body

        opened = await client.post("/api/backend/open", params=dict(base))
        opened_body = await opened.json()
        assert opened.status == 200 and opened_body["ok"], (opened.status, opened_body)
        snap = opened_body["data"]["snapshot"]
        assert set(snap) == SNAPSHOT_KEYS and snap["backend"] == "mlt", snap
        assert snap["phase"] == "ready" and snap["open"] and snap["error"] is None, snap
        assert snap["generation"] == 0 and snap["seek_request_id"] == 0, snap
        playback_id = snap["playback_id"]
        assert len(playback_id) == 32, playback_id
        q = dict(base, playback_id=playback_id)

        # Request 0 is valid immediately after open; render retrieves without seeking.
        first = await client.get("/api/backend/render", params=dict(q, request_id="0"))
        assert first.status == 200 and first.content_type == "image/png", (first.status, first.content_type)
        for header in FRAME_HEADERS:
            assert header in first.headers, (header, dict(first.headers))
        assert first.headers["X-Backend"] == "mlt"
        assert first.headers["X-Playback-ID"] == playback_id
        assert first.headers["X-Playback-Generation"] == "0"
        assert first.headers["X-Seek-Request-ID"] == "0"
        assert first.headers["X-Project-Frame"] == "0"
        assert first.headers["X-Project-PTS-US"] == "0"
        assert (await first.read())[:8] == b"\x89PNG\r\n\x1a\n"

        # Arrival order 3/1/2: only 3 seeks; 1 and 2 replay its accepted snapshot.
        third = await client.post("/api/backend/seek", params=dict(q, t_us="30000000", request_id="3"))
        s3 = (await third.json())["data"]
        assert third.status == 200 and s3["phase"] == "seeking", (third.status, s3)
        assert s3["generation"] == 1 and s3["seek_request_id"] == 3, s3
        first_id = await client.post("/api/backend/seek", params=dict(q, t_us="10000000", request_id="1"))
        second_id = await client.post("/api/backend/seek", params=dict(q, t_us="20000000", request_id="2"))
        s1, s2 = (await first_id.json())["data"], (await second_id.json())["data"]
        assert first_id.status == 200 and second_id.status == 200
        assert s1 == s3 and s2 == s3, (s1, s2, s3)

        for params in ({"t_us": "1000000", "request_id": "0"},
                       {"t_us": "1000000", "request_id": "abc"},
                       {"request_id": "5"},
                       {"t_us": "1.5", "request_id": "5"}):
            resp = await client.post("/api/backend/seek", params=dict(q, **params))
            body = await resp.json()
            assert resp.status == 400 and body["ok"] is False, (params, resp.status, body)
        missing = await client.post("/api/backend/seek", params=dict(base, t_us="1000000", request_id="9"))
        missing_body = await missing.json()
        assert missing.status == 400 and missing_body["code"] == "invalid_playback_id", (missing.status, missing_body)
        wrong = await client.post("/api/backend/seek", params=dict(base, playback_id="0" * 32,
                                                                    t_us="1000000", request_id="9"))
        wrong_body = await wrong.json()
        assert wrong.status == 409 and wrong_body["code"] == "stale_playback_id", (wrong.status, wrong_body)
        assert "expected" not in wrong_body["data"], "stale id must not echo the current credential"

        rendered = await client.get("/api/backend/render", params=dict(q, request_id="3"))
        assert rendered.status == 200 and rendered.content_type == "image/png", rendered.status
        assert rendered.headers["X-Playback-ID"] == playback_id
        assert rendered.headers["X-Playback-Generation"] == "1"
        assert rendered.headers["X-Seek-Request-ID"] == "3"
        assert rendered.headers["X-Project-Frame"] == "900"
        assert rendered.headers["X-Project-PTS-US"] == str(FPS.sample_us(900))
        await rendered.read()

        for stale_id in ("1", "99"):
            resp = await client.get("/api/backend/render", params=dict(q, request_id=stale_id))
            body = await resp.json()
            assert resp.status == 409 and body["code"] == "frame_superseded", (stale_id, resp.status, body)

        state_resp = await client.get("/api/backend/snapshot", params=q)
        state = (await state_resp.json())["data"]
        assert state_resp.status == 200 and set(state) == SNAPSHOT_KEYS, state
        assert state["phase"] == "ready" and state["frame_index"] == 900, state
        assert state["seek_request_id"] == 3 and state["generation"] == 1, state
        assert state["t_us"] == FPS.sample_us(900), state

        # Delayed encoding across a newer seek keeps the old frame identity.
        original_encode = handlers_backend._encode_png
        entered, release = threading.Event(), threading.Event()

        def delayed_encode(frame):
            entered.set()
            release.wait(10)
            return original_encode(frame)

        handlers_backend._encode_png = delayed_encode
        try:
            async def slow_render():
                return await client.get("/api/backend/render", params=dict(q, request_id="3"))

            task = asyncio.create_task(slow_render())
            deadline = time.monotonic() + 10
            while not entered.is_set() and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            assert entered.is_set(), "render never reached the encoder"
            newer = await client.post("/api/backend/seek", params=dict(q, t_us="10000000", request_id="4"))
            s4 = (await newer.json())["data"]
            assert newer.status == 200 and s4["generation"] == 2 and s4["seek_request_id"] == 4, s4
            release.set()
            resp = await task
            assert resp.status == 200 and resp.content_type == "image/png", (resp.status, resp.content_type)
            assert resp.headers["X-Playback-ID"] == playback_id
            assert resp.headers["X-Playback-Generation"] == "1"
            assert resp.headers["X-Seek-Request-ID"] == "3"
            assert resp.headers["X-Project-Frame"] == "900"
            await resp.read()
        finally:
            handlers_backend._encode_png = original_encode
            release.set()

        ended = await client.post("/api/backend/seek", params=dict(q, t_us=str(LONG_US), request_id="5"))
        e5 = (await ended.json())["data"]
        assert ended.status == 200 and e5["phase"] == "ended", (ended.status, e5)
        assert e5["generation"] == 3 and e5["seek_request_id"] == 5, e5
        end_render = await client.get("/api/backend/render", params=dict(q, request_id="5"))
        end_body = await end_render.json()
        assert end_render.status == 200 and end_render.content_type == "application/json", (end_render.status, end_render.content_type)
        assert end_body["ok"] and end_body["data"]["ended"] is True, end_body

        reopened = await client.post("/api/backend/open", params=dict(base))
        snap2 = (await reopened.json())["data"]["snapshot"]
        assert reopened.status == 200 and snap2["generation"] == 0, (reopened.status, snap2)
        playback2 = snap2["playback_id"]
        assert playback2 != playback_id and len(playback2) == 32, (playback_id, playback2)
        q2 = dict(base, playback_id=playback2)

        stream_resp = await client.get("/api/backend/stream", params=q2)
        assert stream_resp.status == 200, stream_resp.status
        ctype = stream_resp.headers["Content-Type"]
        assert ctype.startswith("multipart/x-mixed-replace"), ctype
        assert stream_resp.headers["X-Backend"] == "mlt"
        head = await _read_until(stream_resp.content, b"\r\n\r\n")
        assert head.startswith(b"--frame\r\n"), head
        part = {}
        for line in head.split(b"\r\n")[1:]:
            if not line:
                continue  # the head includes its terminating blank line
            name, sep, value = line.partition(b": ")
            assert sep, line
            part[name.decode()] = value.decode()
        for header in FRAME_HEADERS:
            assert header in part, (header, part)
        assert part["Content-Type"] == "image/jpeg", part
        assert part["X-Playback-ID"] == playback2, part
        assert part["X-Playback-Generation"] == "0" and part["X-Seek-Request-ID"] == "0", part
        body = await stream_resp.content.readexactly(int(part["Content-Length"]))
        assert body[:2] == b"\xff\xd8" and body[-2:] == b"\xff\xd9", len(body)
        from PIL import Image
        import io
        with Image.open(io.BytesIO(body)) as image:
            assert image.format == "JPEG" and image.size == (W, H), (image.format,image.size)
        stream_resp.close()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not any("stream" in line for line in app["log"]):
            await asyncio.sleep(0.05)
        assert any("stream" in line for line in app["log"]), app["log"]

        playing = await client.post("/api/backend/play", params=q2)
        p1 = (await playing.json())["data"]
        assert playing.status == 200 and p1["phase"] in ("buffering", "playing"), (playing.status, p1)
        paused = await client.post("/api/backend/pause", params=q2)
        p2 = (await paused.json())["data"]
        assert paused.status == 200 and p2["phase"] == "paused", (paused.status, p2)
        assert p2["playing"] is False, p2

        # Live stream: while playing the multipart source emits continuous parts
        # whose X-Project-Frame advances (bounded read with a timeout guard).
        playing2 = await client.post("/api/backend/play", params=q2)
        assert playing2.status == 200, playing2.status
        live_state = {}
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            live_state = (await (await client.get("/api/backend/snapshot", params=q2)).json())["data"]
            if live_state["phase"] == "playing":
                break
            await asyncio.sleep(0.02)
        assert live_state["phase"] == "playing", live_state

        # Snapshot polling can settle/restart a seek before /render arrives.
        rewind = await client.post("/api/backend/seek", params=dict(q2, t_us="0", request_id="1"))
        assert rewind.status == 200, rewind.status
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            live_state = (await (await client.get("/api/backend/snapshot", params=q2)).json())["data"]
            if live_state["t_us"] > 100_000:
                break
            await asyncio.sleep(0.02)
        assert live_state["phase"] == "playing" and live_state["t_us"] > 100_000, live_state
        frozen = await client.get("/api/backend/render", params=dict(q2, request_id="1"))
        assert frozen.status == 200 and frozen.headers["X-Project-PTS-US"] == "0", dict(frozen.headers)
        assert frozen.headers["X-Project-Frame"] == "0" and frozen.headers["X-Seek-Request-ID"] == "1"
        await frozen.read()
        print(f"ok: render kept frame0 after concurrent snapshots advanced to {live_state['t_us']}")

        live = await client.get("/api/backend/stream", params=q2)
        assert live.status == 200, live.status
        assert live.headers["Content-Type"].startswith("multipart/x-mixed-replace"), live.headers["Content-Type"]
        live_frames = []
        read_deadline = time.monotonic() + 1.0
        while time.monotonic() < read_deadline and len(live_frames) < 10:
            try:
                head = await asyncio.wait_for(_read_until(live.content, b"\r\n\r\n"), timeout=3)
            except asyncio.TimeoutError:
                break
            part = {}
            for line in head.split(b"\r\n"):
                if not line or line.startswith(b"--"):
                    continue  # boundary marker / blank separator
                name, sep, value = line.partition(b": ")
                assert sep, line
                part[name.decode()] = value.decode()
            assert part["Content-Type"] == "image/jpeg", part
            live_frames.append(int(part["X-Project-Frame"]))
            await asyncio.wait_for(live.content.readexactly(int(part["Content-Length"])), timeout=3)
        assert len(set(live_frames)) >= 2, f"stream starved during play: {live_frames}"
        assert live_frames == sorted(live_frames), f"frame index regressed: {live_frames}"
        assert live_frames[-1] > live_frames[0], live_frames
        print(f"ok: live stream {len(set(live_frames))} distinct advancing frames "
              f"{live_frames[0]}..{live_frames[-1]}")

        # Killing the sink while the stream is open must terminate it with a
        # logged error instead of idling forever on pull_frame() -> None.
        handle = app["playback_backends"]["fake-draft:timeline-acceptance"]
        _stop_consumer(handle.controller._consumer)
        tail = None
        with contextlib.suppress(asyncio.TimeoutError):
            tail = await asyncio.wait_for(live.content.read(), timeout=5)
        live.close()
        assert tail is not None, "stream never terminated after consumer failure"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not any(
                "mlt stream" in line and "playback failed" in line for line in app["log"]):
            await asyncio.sleep(0.05)
        assert any("mlt stream" in line and "playback failed" in line
                   for line in app["log"]), app["log"]

        # A late client from the first session cannot touch or close its replacement.
        for method, path, extra in (("get", "/api/backend/snapshot", {}),
                                    ("post", "/api/backend/seek", {"t_us": "1000000", "request_id": "7"}),
                                    ("get", "/api/backend/render", {"request_id": "0"}),
                                    ("post", "/api/backend/close", {})):
            resp = await client.request(method, path,
                                        params=dict(base, playback_id=playback_id, **extra))
            body = await resp.json()
            assert resp.status == 409 and body["code"] == "stale_playback_id", (path, resp.status, body)
        alive = await client.get("/api/backend/snapshot", params=q2)
        assert alive.status == 200, "stale close must not close the replacement session"
        closed = await client.post("/api/backend/close", params=q2)
        close_body = await closed.json()
        assert closed.status == 200 and close_body["data"]["closed"] is True, close_body
        gone = await client.get("/api/backend/snapshot", params=q2)
        assert gone.status == 404, gone.status
    finally:
        for leftover in list(app["playback_backends"].values()):
            await leftover.close()
        app["playback_backends"].clear()
        await client.close()


_capture_pin = {"stamps_while_running": 0, "stamps_while_stopped": 0}
_capture_pin_local = threading.local()
_orig_capture = PlaybackController._capture
_orig_stamp = PlaybackController._stamp


def _pin_capture(self, mlt_frame):
    """Run the real _capture with this thread marked as on the capture path."""
    _capture_pin_local.in_capture = True
    try:
        return _orig_capture(self, mlt_frame)
    finally:
        _capture_pin_local.in_capture = False


def _pin_stamp(self, position, rgba):
    """Count capture-path stamps by consumer state; listener stamps pass through."""
    if getattr(_capture_pin_local, "in_capture", False):
        if self._consumer is not None and not self._consumer.is_stopped():
            _capture_pin["stamps_while_running"] += 1
        else:
            _capture_pin["stamps_while_stopped"] += 1
    return _orig_stamp(self, position, rgba)


def main():
    encoding_formats()
    frame_handoff()
    stream_readiness()
    ROOT.mkdir(parents=True, exist_ok=True)
    long_model = build_model(LONG_US, still("red", (255, 0, 0)), tone("tone-long", 31))
    short_model = build_model(500_000, still("blue", (0, 0, 255)), tone("tone-short", 1))
    native_frame_handoff(long_model)
    native_stream_readiness(long_model)
    playing_backward_seek(long_model)
    missing_consumer_output(long_model)

    # Capture-guard pin (design: temp/teardown/verify.md): pin the e562d7f
    # invariant that no capture-path _stamp ever lands while the consumer runs.
    # The thread-local marks capture-path _stamp calls only, so concurrent
    # frame-show-listener stamps are not counted.
    PlaybackController._capture = _pin_capture
    PlaybackController._stamp = _pin_stamp

    controller, playback_id = phase_machine(long_model)
    arrival_order(controller, playback_id)
    end_and_cleanup(controller, playback_id)
    transport_and_clock(controller, playback_id)
    # Non-vacuous pin: the stopped path really stamped, and no capture-path stamp
    # ever landed while the consumer was running. Today _capture runs only on
    # worker settle pulls (consumer stopped); a seam regression that routes a
    # running-consumer pull through it trips the first assert.
    assert _capture_pin["stamps_while_running"] == 0, _capture_pin
    assert _capture_pin["stamps_while_stopped"] >= 1, _capture_pin
    controller.close()
    consumer_failure_and_reopen(long_model, playback_id)
    end_of_stream(short_model)
    worker_lifecycle(short_model)
    print("ok: playback controller phase, identity, and clock regressions")
    asyncio.run(endpoint_acceptance(long_model))
    print("ok: MLT playback endpoint acceptance")


if __name__ == "__main__":
    main()
