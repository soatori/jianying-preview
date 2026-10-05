"""Task 6 acceptance: model/composition/internal-A/V assertions, the read-only
check, and the synchronized-capture evidence gate (plan Task 6 Steps 1-2).

Sections run first and report individually; the process exits nonzero when any
section fails or when ``--av-evidence`` is missing, inconclusive, failed, or
labeled synthetic. ``ok:`` prints only when sections AND the evidence gate pass.

capture-calibration: owned by capture lane (integrates here) — the 30-second
marker/pulse timeline, screen+audio capture pipeline, and generation of
``temp/mlt-av-evidence.json`` belong to the parallel capture lane; this script
only validates their output against the plan schema.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import struct
import time
from typing import Any
from unittest.mock import patch

from jypreview.cli.selfcheck import mtime_snapshot
from jypreview.mlt_backend import MltCompiler, PlaybackController
from jypreview.model import framedesc
from jypreview.model.content import TimelineContent
from jypreview.model.draft_adapter import DraftAdapter
from jypreview.model.timeline import (
    AudioSpec, Clip, FrameRate, MediaRef, TextPayload, TimelineModel, TimeMapping,
    TimeRange, Track, Transition, evaluate,
)
from jypreview.tools.test_mlt_compiler import color, model as compiled_model, picture, pixels
from jypreview.tools.test_mlt_runtime import (
    loaded_audio_api, marker_av_delta, pcm, write_audio_markers,
)
from jypreview.tools.test_timeline_model import (
    LOCATED as FIXTURE_LOCATED, PROBE as FIXTURE_PROBE, build as build_fixture_model,
    fixture as model_fixture,
)

ROOT = Path(__file__).resolve().parents[3]
TEMP = ROOT / "temp"
HERE = TEMP / "mlt-acceptance"
FPS = FrameRate(30)
W, H = 300, 180
DURATION_US = 1_000_000

# Per-run measurements shared with the written acceptance evidence.
MEASURED: dict[str, object] = {}


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set; source temp/mlt-runtime/process-env.ps1 first")
    return value


def _mlt() -> Any:
    """mlt7 exists only inside the isolated runtime; import lazily as Any."""
    import importlib
    return importlib.import_module("mlt7")


def _still(name: str, rgb: tuple[int, int, int]) -> MediaRef:
    """One flat BMP still under temp/; content only needs to be decodable visual media."""
    path = HERE / "media" / f"{name}.bmp"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = bytes((rgb[2], rgb[1], rgb[0])) * W
    data = row * H
    path.write_bytes(b"BM" + struct.pack("<IHHI", 54 + len(data), 0, 0, 54)
                     + struct.pack("<IiiHHIIiiII", 40, W, H, 1, 24, 0, len(data),
                                   0, 0, 0, 0) + data)
    return MediaRef(name, str(path), True, width=W, height=H, has_audio=False)


def _tree_files(root: Path) -> set[str]:
    return {str(p) for p in Path(root).rglob("*") if p.is_file()}


# -- Step 1: pure model/composition/internal-A/V assertions -----------------

def evaluate_determinism() -> str:
    red, green = _still("red", (255, 0, 0)), _still("green", (0, 255, 0))
    tone = MediaRef("tone", str(HERE / "media" / "missing.wav"), False, has_audio=True)
    left = picture("left", red, duration=500_000)
    right = picture("right", green, start=500_000, duration=500_000, z=1)
    title = Clip("title", "text", TimeRange(0, 700_000),
                 text_payload=TextPayload("Acceptance"))
    voice = Clip("voice", "audio", TimeRange(0, DURATION_US), TimeRange(0, DURATION_US), tone,
                 audio=AudioSpec(volume=1.5))
    hush = Clip("hush", "audio", TimeRange(0, DURATION_US), TimeRange(0, DURATION_US), tone)
    disabled = Clip("ghost", "image", TimeRange(0, DURATION_US), media_ref=red)
    model = TimelineModel(
        "rich", DURATION_US, FPS, (W, H),
        (Track("A", "video", (left, right)),
         Track("T", "text", (title,)),
         Track("voice", "audio", (voice,)),
         Track("quiet", "audio", (hush,), muted=True),
         Track("off", "video", (disabled,), enabled=False)),
        (Transition("fade", "fade", TimeRange(0, 300_000), None, "left"),
         Transition("cross", "crossfade", TimeRange(400_000, 200_000), "left", "right")),
    )
    times = [0, 1, 33_333, 33_334, 33_335, 100_000, 299_999, 300_000, 399_999,
             400_000, 500_000, 599_999, 600_000, 700_000, 750_000, 999_999,
             DURATION_US, DURATION_US + 5_000_000]
    baseline = {t: evaluate(model, t) for t in times}
    for t in times:
        assert evaluate(model, t) == baseline[t], f"repeated evaluate differs at {t}"
    shuffled = list(times)
    import random
    random.Random(6).shuffle(shuffled)
    for t in shuffled:
        assert evaluate(model, t) == baseline[t], f"shuffled evaluate differs at {t}"
    ended = baseline[DURATION_US]
    assert ended.state == "ended" and ended.video == () and ended.audio == ()
    return f"{len(times)} instants x 3 orders identical"


def framedesc_parity() -> str:
    """Task 2's explicit compatible subset: valid, enabled, visible, unnested,
    forward 1x/2x clips without transitions or source clamping."""
    config, value = model_fixture()
    a = dict(value["tracks"][0]["segments"][0], id="a", reverse=False, render_index=7,
             target_timerange={"start": 0, "duration": 600_000},
             source_timerange={"start": 2_000_000, "duration": 1_200_000})
    b = dict(a, id="b", speed=1, target_timerange={"start": 600_000, "duration": 1_000_000},
             source_timerange={"start": 4_000_000, "duration": 1_000_000})
    c = dict(a, id="c", speed=1, target_timerange={"start": 0, "duration": 2_000_000},
             source_timerange={"start": 6_000_000, "duration": 2_000_000})
    value["tracks"] = [{"id": "A", "type": "video", "segments": [a, b]},
                       {"id": "B", "type": "video", "segments": [c]}]
    checked = 0
    with patch("jypreview.media.resolve", return_value=FIXTURE_LOCATED), \
            patch("jypreview.media.probe", return_value=FIXTURE_PROBE):
        content = TimelineContent.build(value)
        model = build_fixture_model(value, config)
        for requested, expected_ids in ((0, ["a", "c"]), (333_335, ["a", "c"]),
                                        (600_000, ["b", "c"]), (1_000_000, ["b", "c"]),
                                        (1_900_000, ["c"])):
            scene = evaluate(model, requested)
            legacy = framedesc.build_frame(content, scene.sample_us, config,
                                           draft_root=TEMP, did="draft")
            assert [i.clip_id for i in scene.video] == expected_ids, \
                (requested, [i.clip_id for i in scene.video])
            assert [(i.clip_id, i.track_id, i.render_index) for i in scene.video] == \
                [(layer["layer_id"], layer["track"]["id"], layer["z"]["global"])
                 for layer in legacy["layers"]], requested
            assert [i.source_us for i in scene.video] == \
                [layer["time"]["source_time_us"] for layer in legacy["layers"]], requested
            checked += 1
        legacy = framedesc.build_frame(content, 0, config, draft_root=TEMP, did="draft")
        assert (legacy["canvas"]["width"], legacy["canvas"]["height"]) == model.canvas
        assert legacy["fps"] == 30.0 and legacy["duration_us"] == model.duration_us
    # The pinned known difference stays outside legacy parity (Task 2 rule).
    assert TimeMapping(2, direction="reverse").source_us(
        250_000, TimeRange(2_000_000, 1_000_000)) == 2_499_999
    return f"{checked} instants parity (ids, tracks, z, source times, canvas)"


def three_layer_geometry() -> str:
    red, green, blue = (_still(n, c) for n, c in (
        ("red", (255, 0, 0)), ("green", (0, 255, 0)), ("blue", (0, 0, 255))))
    compiler = MltCompiler()
    # Adjacent z=0/z=2 clips on track A crossing a continuous z=1 clip on track B.
    layered = compiled_model(
        Track("A", "video", (picture("a0", red, duration=500_000, z=0),
                             picture("a2", red, start=500_000, duration=500_000, z=2))),
        Track("B", "video", (picture("b", green, z=1),)))
    before, after = evaluate(layered, 250_000), evaluate(layered, 750_000)
    assert [i.clip_id for i in before.video] == ["a0", "b"]
    assert [i.render_index for i in before.video] == [0, 1]
    assert [i.clip_id for i in after.video] == ["b", "a2"]
    assert [i.render_index for i in after.video] == [1, 2]
    graph = compiler.compile(layered)
    color(graph, 14, (0, 255, 0))
    color(graph, 15, (255, 0, 0))
    graph.close()
    # Opacity: model value and rendered blend agree.
    alpha = compiler.compile(compiled_model(
        Track("t", "video", (picture("r", red), picture("b", blue, opacity=.5)))))
    scene = evaluate(alpha.model, 0)
    assert [round(i.opacity, 3) for i in scene.video] == [1.0, 0.5]
    color(alpha, 0, (127, 0, 128))
    alpha.close()
    # Position and per-axis size (scale) through actual RGBA geometry.
    bands = compiler.compile(compiled_model(Track("bands", "video", tuple(
        picture(str(i), media, transform=__import__("jypreview.model.timeline",
                                                    fromlist=["Transform"]).Transform(
                                                        50 + 100 * i, 90, 100, 180))
        for i, media in enumerate((red, green, blue))))))
    for x, expected in ((50, (255, 0, 0)), (150, (0, 255, 0)), (250, (0, 0, 255))):
        color(bands, 0, expected, x)
    # Verify width as well as center; center-only probes miss undersized affine layers.
    for x, expected in ((90, (255, 0, 0)), (190, (0, 255, 0)), (290, (0, 0, 255))):
        color(bands, 0, expected, x)
    bands.close()
    scaled = compiler.compile(compiled_model(Track("s", "video", (
        picture("r", red, transform=_transform(150, 90, 150, 90, scale_x=0.5, scale_y=0.5)),))))
    color(scaled, 0, (0, 0, 0), 100, 90)
    color(scaled, 0, (255, 0, 0), 150, 90)
    color(scaled, 0, (0, 0, 0), 150, 130)
    scaled.close()
    rotated = compiler.compile(compiled_model(Track("r", "video", (
        picture("r", red, transform=_transform(150, 90, 120, 30, rotation=90)),))))
    color(rotated, 0, (255, 0, 0), 150, 45)
    color(rotated, 0, (0, 0, 0), 100, 90)
    rotated.close()
    cropped = compiler.compile(compiled_model(
        Track("c", "image", (picture("r", red, crop=(.25, 0, .75, 1)),))))
    color(cropped, 0, (0, 0, 0), 25)
    color(cropped, 0, (255, 0, 0), 150)
    color(cropped, 0, (0, 0, 0), 275)
    cropped.close()
    # Canvas ratio: a 360x180 model renders a 2:1 RGBA frame.
    wide = TimelineModel("wide", DURATION_US, FPS, (360, 180),
                         (Track("v", "video", (picture("r", red),)),))
    graph = compiler.compile(wide)
    mlt = _mlt()
    tractor: Any = graph.tractor
    assert tractor.seek(0) == 0
    frame = tractor.get_frame()
    data = bytes(frame.get_image(mlt.mlt_image_rgba, 360, 180))
    assert len(data) == 360 * 180 * 4 and any(data[3::4]), "2:1 canvas produced empty RGBA"
    graph.close()
    return "order/z seam, opacity, position, scale, rotation, crop, 2:1 canvas"


def _transform(x, y, width, height, **kw):
    from jypreview.model.timeline import Transform
    return Transform(x, y, width, height, **kw)


def interval_counts() -> str:
    rate30 = FrameRate(30)
    assert rate30.frame_count(0) == 0
    assert rate30.frame_count(33_334) == 1
    assert rate30.frame_count(33_335) == 2
    ntsc = FrameRate(30_000, 1_001)
    assert ntsc.quantize(1_000_000) == (29, 967_634)
    assert ntsc.frame_count(967_634) == 29 and ntsc.frame_count(967_635) == 30
    for rate in (rate30, ntsc, FrameRate(24), FrameRate(60, 1),
                 FrameRate(24_000, 1_001), FrameRate(60_000, 1_001)):
        for frame in (0, 1, 29, 30):
            sample = rate.sample_us(frame)
            assert rate.quantize(sample) == (frame, sample), (rate, frame)
    red, blue = _still("red", (255, 0, 0)), _still("blue", (0, 0, 255))
    # Still, text, and sticker occupy exactly their half-open intervals.
    still_clip = picture("s", red, duration=500_000)
    title = Clip("title", "text", TimeRange(200_000, 100_000),
                 text_payload=TextPayload("T", font_size=20))
    sticker = Clip("dot", "sticker", TimeRange(0, DURATION_US), media_ref=blue)
    spans = TimelineModel("spans", DURATION_US, FPS, (W, H), (
        Track("v", "video", (still_clip,)),
        Track("text", "text", (title,)),
        Track("sticker", "sticker", (sticker,))))
    # z order: still=0, sticker=12000, text=14000 — order is (z, track, segment).
    assert [i.clip_id for i in evaluate(spans, 199_999).video] == ["s", "dot"]
    assert [i.clip_id for i in evaluate(spans, 200_000).video] == ["s", "dot", "title"]
    assert [i.clip_id for i in evaluate(spans, 299_999).video] == ["s", "dot", "title"]
    assert [i.clip_id for i in evaluate(spans, 300_000).video] == ["s", "dot"]
    assert [i.clip_id for i in evaluate(spans, 499_999).video] == ["s", "dot"]
    assert [i.clip_id for i in evaluate(spans, 500_000).video] == ["dot"]
    assert evaluate(spans, 250_000).video[1].render_index == 12000  # sticker default z
    # Fade and crossfade use the same half-open window with linear weights.
    left = picture("left", red, duration=500_000)
    right = picture("right", blue, start=500_000, duration=500_000, z=1)
    fading = picture("fadein", red)
    crossfade = TimelineModel("cross", DURATION_US, FPS, (W, H),
                              (Track("t", "video", (left, right)),),
                              (Transition("x", "crossfade", TimeRange(400_000, 200_000),
                                          "left", "right"),))
    mid = evaluate(crossfade, 500_000)
    assert [i.clip_id for i in mid.video] == ["left", "right"]
    assert [round(i.opacity, 6) for i in mid.video] == [0.5, 0.5]
    after = evaluate(crossfade, 600_000)  # window end is exclusive; right still spans
    assert [i.clip_id for i in after.video] == ["right"]
    assert [round(i.opacity, 6) for i in after.video] == [1.0]
    fade = TimelineModel("fade", DURATION_US, FPS, (W, H),
                         (Track("t", "video", (fading,)),),
                         (Transition("f", "fade", TimeRange(0, DURATION_US), None, "fadein"),))
    assert round(evaluate(fade, 500_000).video[0].opacity, 6) == 0.5
    # Canonical boundary counts compiled through MLT.
    compiler = MltCompiler()
    for rate, duration, count in ((FPS, 33_334, 1), (FPS, 33_335, 2),
                                  (FrameRate(30_000, 1_001), 967_634, 29),
                                  (FrameRate(30_000, 1_001), 967_635, 30)):
        graph = compiler.compile(compiled_model(
            Track("t", "image", (picture("r", red, start=33_334, duration=1),)),
            duration=duration, rate=rate))
        assert graph.duration_frames == count, (rate, duration, graph.duration_frames)
        graph.close()
    graph = compiler.compile(compiled_model(duration=0))
    assert graph.duration_frames == 0 and graph.tractor is None
    graph.close()
    return "canonical counts at 30/NTSC + still/text/sticker/fade/crossfade spans"


def missing_handle_clamps() -> str:
    # evaluate side: Task 2's missing-handle case through the adapter fixture.
    config, value = model_fixture()
    transition = deepcopy(value)
    transition["materials"]["transitions"] = [
        {"id": "xf", "type": "transition", "name": "叠化", "duration": 400_000}]
    out = transition["tracks"][0]["segments"][0]
    out.update(extra_material_refs=["xf"], speed=1, reverse=False,
               source_timerange={"start": 2_000_000, "duration": 1_000_000})
    transition["tracks"][0]["segments"].append(dict(
        out, id="next", extra_material_refs=[],
        target_timerange={"start": 1_000_000, "duration": 1_000_000},
        source_timerange={"start": 5_000_000, "duration": 1_000_000}))
    with patch("jypreview.media.resolve", return_value=FIXTURE_LOCATED), \
            patch("jypreview.media.probe", return_value=FIXTURE_PROBE):
        transitioned = build_fixture_model(transition, config)
        handles = evaluate(transitioned, 900_000)
        assert [i.source_us for i in handles.video] == [2_900_000, 4_900_000]
        assert "transition_handle_clamped" not in handles.warnings
        transition["materials"]["videos"][0]["available_range"] = {
            "start": 2_000_000, "duration": 1_000_000}
        missing = evaluate(build_fixture_model(transition, config), 1_000_000)
        assert missing.video[0].source_us == 2_999_999
        assert "transition_handle_clamped" in missing.warnings
    # compiler side: same shapes through the real graph, real media handles.
    video = MediaRef("video", _require_env("JY_PREVIEW_TEST_VIDEO"), True,
                     TimeRange(0, 4_000_000), 4_000_000, FrameRate(30), True, W, H)
    cross = Transition("cross", "crossfade", TimeRange(400_000, 200_000), "left", "right")
    left = Clip("left", "video", TimeRange(0, 500_000), TimeRange(500_000, 500_000),
                video, audio=AudioSpec(False))
    right = Clip("right", "video", TimeRange(500_000, 500_000), TimeRange(0, 500_000),
                 video, render_index=1, audio=AudioSpec(False))
    compiler = MltCompiler()
    graph = compiler.compile(compiled_model(Track("t", "video", (left, right)),
                                            transitions=(cross,)))
    assert "transition_handle_clamped" in graph.warnings, graph.warnings
    pixels(graph, 12)
    pixels(graph, 15)
    graph.close()
    generous = Clip("right", "video", TimeRange(500_000, 500_000),
                    TimeRange(1_000_000, 500_000), video, render_index=1,
                    audio=AudioSpec(False))
    graph = compiler.compile(compiled_model(Track("t", "video", (left, generous)),
                                            transitions=(cross,)))
    assert "transition_handle_clamped" not in graph.warnings, graph.warnings
    pixels(graph, 15)
    graph.close()
    return "evaluate clamps+warns; compiler warns on missing, silent on sufficient handles"


def mixed_audio() -> str:
    markers = HERE / "media" / "markers.wav"
    write_audio_markers(markers)
    marker_ref = MediaRef("markers", str(markers), True, TimeRange(0, 4_000_000),
                          4_000_000, has_audio=True)
    constant = HERE / "media" / "constant.wav"
    if not constant.is_file():
        import wave
        constant.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(constant), "wb") as out:
            out.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
            out.writeframes(struct.pack("<h", 2000) * (2 * 48000 * 2))
    const_ref = MediaRef("const", str(constant), True, TimeRange(0, 2_000_000),
                         2_000_000, has_audio=True)
    trim = Clip("trim", "audio", TimeRange(0, 500_000), TimeRange(500_000, 500_000),
                marker_ref)
    offset = Clip("offset", "audio", TimeRange(500_000, 500_000),
                  TimeRange(0, 500_000), marker_ref)
    gain = Clip("gain", "audio", TimeRange(0, DURATION_US), TimeRange(0, 500_000),
                const_ref, audio=AudioSpec(volume=1.5))
    hush = Clip("hush", "audio", TimeRange(0, 500_000), TimeRange(0, 500_000), const_ref)
    silent = Clip("silent", "audio", TimeRange(0, 500_000), TimeRange(0, 500_000),
                  const_ref, audio=AudioSpec(False))
    model = TimelineModel("audio", DURATION_US, FPS, (W, H), (
        Track("base", "audio", (trim, silent)),
        Track("delay", "audio", (offset,)),
        Track("gain", "audio", (gain,)),
        Track("quiet", "audio", (hush,), muted=True)))
    at_zero = evaluate(model, 0)
    assert [i.clip_id for i in at_zero.audio] == ["trim", "gain"]
    assert [i.source_us for i in at_zero.audio] == [500_000, 0]
    assert [i.volume for i in at_zero.audio] == [1.0, 1.5]
    at_offset = evaluate(model, 750_000)
    assert [i.clip_id for i in at_offset.audio] == ["offset", "gain"]
    # evaluate quantizes first: 750_000 lands on sample 733_334 → local 233_334.
    assert at_offset.audio[0].source_us == FPS.quantize(750_000)[1] - 500_000
    assert at_zero.video == ()  # audio tracks contribute no video items
    # Compiled PCM: trimmed marker lane + 1.5x constant lane; muted/disabled silent.
    graph = MltCompiler().compile(compiled_model(
        Track("base", "audio", (trim, silent)),
        Track("gain", "audio", (gain,)),
        Track("quiet", "audio", (hush,), muted=True),
        duration=500_000))
    mlt = _mlt()
    library, get_audio, _ = loaded_audio_api()
    tractor: Any = graph.tractor
    for position, marker_value in ((0, 2500), (3, 2800)):
        assert tractor.seek(position) == 0
        values = pcm(tractor.get_frame(), get_audio, mlt)
        average = sum(values) / len(values)
        assert abs(average - (marker_value + 3000)) <= 110, (position, average)
    graph.close()
    return "trim/offset source times, mute/track-mute exclusion, 1.5x gain in evaluate+PCM"


def replace_id(clip: Clip, ident: str) -> Clip:
    from dataclasses import replace
    return replace(clip, id=ident)


def internal_av_pts() -> str:
    markers = HERE / "media" / "markers.wav"
    write_audio_markers(markers)
    red = _still("red", (255, 0, 0))
    marker_ref = MediaRef("markers", str(markers), True, TimeRange(0, 4_000_000),
                          4_000_000, has_audio=True)
    marker_clip = Clip("m", "audio", TimeRange(0, 4_000_000),
                       TimeRange(0, 4_000_000), marker_ref)
    # marker_av_delta decodes a TWO-lane summed marker amplitude (runtime-gate contract).
    graph = MltCompiler().compile(compiled_model(
        Track("v", "video", (picture("bg", red),)),
        Track("a1", "audio", (marker_clip,)),
        Track("a2", "audio", (replace_id(marker_clip, "m2"),)),
        duration=4_000_000))
    mlt = _mlt()
    library, get_audio, _ = loaded_audio_api()
    tractor: Any = graph.tractor
    max_delta = 0
    deltas = {}
    for position in (0, 1, 3, 7, 12, 23, 31, 47, 63, 90, 111):
        assert tractor.seek(position) == 0
        frame = tractor.get_frame()
        assert frame.get_position() == position, (position, frame.get_position())
        audio_position, error, delta = marker_av_delta(position, pcm(frame, get_audio, mlt))
        deltas[position] = delta
        max_delta = max(max_delta, delta)
    graph.close()
    assert max_delta <= 1, f"internal A/V offset {max_delta} frames at {deltas}"
    MEASURED["max_internal_av_delta_frames"] = max_delta
    return f"max_internal_av_delta_frames={max_delta} over {len(deltas)} marker positions"


def readonly_non_mutation() -> str:
    """Step 2: open/seek/play/close must not touch source draft/Timelines metadata,
    and every created file must stay under the preview cache or root temp/."""
    import wave
    drafts_root = HERE / "drafts"
    draft_dir = drafts_root / "acc-src"
    assets = draft_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    bmp = assets / "still.bmp"
    if not bmp.is_file():
        row = bytes((0, 0, 255)) * W
        data = row * H
        bmp.write_bytes(b"BM" + struct.pack("<IHHI", 54 + len(data), 0, 0, 54)
                        + struct.pack("<IiiHHIIiiII", 40, W, H, 1, 24, 0, len(data),
                                      0, 0, 0, 0) + data)
    tone = assets / "tone.wav"
    if not tone.is_file():
        with wave.open(str(tone), "wb") as out:
            out.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
            out.writeframes(struct.pack("<h", 500) * (2 * 48000 * 2))
    draft = {
        "id": "acc-src", "fps": 30, "duration": 2_000_000,
        "canvas_config": {"width": W, "height": H, "ratio": "5:3"},
        "materials": {
            "images": [{"id": "img", "type": "photo", "path": "assets/still.bmp",
                        "width": W, "height": H, "duration": 1_000_000}],
            "audios": [{"id": "tone", "type": "audio", "path": "assets/tone.wav",
                        "duration": 2_000_000, "has_audio": True, "sample_rate": 48000}]},
        "tracks": [
            {"id": "video", "type": "video", "render_index": 0, "segments": [
                {"id": "s0", "material_id": "img",
                 "target_timerange": {"start": 0, "duration": 1_000_000}},
                {"id": "s1", "material_id": "img",
                 "target_timerange": {"start": 1_000_000, "duration": 1_000_000}}]},
            {"id": "audio", "type": "audio", "render_index": 1, "segments": [
                {"id": "a0", "material_id": "tone",
                 "target_timerange": {"start": 0, "duration": 2_000_000},
                 "source_timerange": {"start": 0, "duration": 2_000_000}}]},
        ],
    }
    (draft_dir / "draft_content.json").write_text(
        json.dumps(draft, ensure_ascii=False, indent=1), encoding="utf-8")
    # Plaintext read through the production adapter (no decrypt worker/skill needed).
    value = json.loads((draft_dir / "draft_content.json").read_text(encoding="utf-8-sig"))
    adapter_config, _ = model_fixture()
    model = DraftAdapter(adapter_config, None, None, None, None).build(
        TimelineContent.build(value), draft_root=draft_dir, did="acc-src", timeline_info={})
    real = [clip for track in model.tracks for clip in track.clips if not clip.placeholder]
    assert len(real) >= 3, \
        f"source draft model incomplete: {[(c.id, c.warnings) for c in model.tracks[0].clips]}"
    before = mtime_snapshot(drafts_root)
    watched_before = _tree_files(drafts_root)
    state_before = _tree_files(HERE / "state")
    controller = PlaybackController()
    pulled = 0
    try:
        opened = controller.open(model)
        assert opened["phase"] == "ready" and opened["open"], opened
        playback_id = opened["playback_id"]
        controller.seek(500_000, playback_id=playback_id, request_id=1)
        settled = controller.snapshot()
        assert settled["frame_index"] == FPS.quantize(500_000)[0], settled
        controller.play()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if controller.pull_frame(50) is not None:
                pulled += 1
        assert pulled >= 1, "no frame produced during playback"
        controller.pause()
        controller.seek(0, playback_id=playback_id, request_id=2)
        assert controller.snapshot()["frame_index"] == 0
    finally:
        controller.close()
    after = mtime_snapshot(drafts_root)
    changed = {key for key in set(before) | set(after) if before.get(key) != after.get(key)}
    assert not changed, f"source draft metadata mutated: {sorted(changed)}"
    created = (_tree_files(drafts_root) - watched_before) | \
        (_tree_files(HERE / "state") - state_before)
    stray = [path for path in created
             if ".jypreview" not in Path(path).parts
             and not Path(path).is_relative_to(TEMP)]
    assert not stray, f"files created outside preview cache/temp: {stray}"
    MEASURED["readonly"] = {"mutated": 0, "frames_pulled": pulled,
                            "source_files": len(before)}
    return f"mtime_snapshot identical over {len(before)} source files, {pulled} frames pulled"


# -- Evidence validator (plan Step 1 schema) --------------------------------

EVENT_KEYS = {"project_frame", "video_capture_us", "audio_capture_us"}
MODES = ("normal", "dropped_video")
FAIL_STATUSES = {"failed", "inconclusive", "unverified", "missing", "error"}


def validate_av_evidence(data: dict) -> dict:
    """Validate one capture-evidence document; never mutates it."""
    reasons: list[str] = []
    synthetic = data.get("synthetic") is True or \
        "synthetic" in str(data.get("capture_method", "")).lower()
    for key in ("frame_rate", "runtime", "capture_method", "raw_capture",
                "uncertainty_us", "runs"):
        if key not in data:
            reasons.append(f"missing top-level key {key!r}")
    rate = data.get("frame_rate")
    num = den = 0
    if "frame_rate" in data:
        if not isinstance(rate, dict) or type(rate.get("num")) is not int \
                or type(rate.get("den")) is not int or rate["num"] <= 0 or rate["den"] <= 0:
            reasons.append("frame_rate must be {num, den} positive integers")
        else:
            num, den = rate["num"], rate["den"]
    for key in ("runtime", "capture_method", "raw_capture"):
        value = data.get(key)
        if value is None or (isinstance(value, str) and not value.strip()) \
                or (isinstance(value, dict) and not value) or (isinstance(value, list) and not value):
            reasons.append(f"{key} must record a nonempty observation")
    uncertainty = data.get("uncertainty_us")
    if "uncertainty_us" in data:
        if type(uncertainty) is not int or uncertainty < 0:
            reasons.append("uncertainty_us must be a nonnegative integer")
        elif num and uncertainty * 4 * num > 1_000_000 * den:
            reasons.append(f"uncertainty_us {uncertainty} exceeds one quarter of a project frame")
    expected_frames: list[int] | None = None
    if num:
        try:
            rate_obj = FrameRate(num, den)
            expected_frames = [rate_obj.first_frame_at_or_after(k * 1_000_000)
                               for k in range(1, 30)]
        except ValueError:
            reasons.append(f"frame_rate {{{num}/{den}}} is not a valid project rate")
    runs = data.get("runs")
    if not isinstance(runs, list) or not runs:
        reasons.append("runs must be a nonempty list")
        runs = []
    seen_modes: list[str] = []
    for index, run in enumerate(runs):
        where = f"runs[{index}]"
        if not isinstance(run, dict):
            reasons.append(f"{where} must be an object")
            continue
        mode = str(run.get("mode"))
        seen_modes.append(mode)
        if mode not in MODES:
            reasons.append(f"{where}.mode {mode!r} is not one of {MODES}")
            continue
        where = f"run {mode!r}"
        duration = run.get("duration_us")
        if type(duration) is not int or duration < 30_000_000:
            reasons.append(f"{where} must run at least 30 seconds (duration_us={duration!r})")
        dropped = run.get("dropped_frames")
        if type(dropped) is not int or dropped < 0:
            reasons.append(f"{where} dropped_frames must be a nonnegative integer")
        events = run.get("events")
        if not isinstance(events, list):
            reasons.append(f"{where} events must be a list")
            continue
        if expected_frames is not None:
            if len(events) != 29:
                reasons.append(f"{where} has {len(events)} events, expected exactly 29 marker/pulse pairs")
            frames = [event.get("project_frame") for event in events if isinstance(event, dict)]
            if sorted(frame for frame in frames if type(frame) is int) != sorted(expected_frames):
                reasons.append(f"{where} project_frame set does not match the 29 expected marker frames")
        for event in events:
            if not isinstance(event, dict) or set(event) != EVENT_KEYS:
                reasons.append(f"{where} events must carry exactly {sorted(EVENT_KEYS)} "
                               "(UI diagnostics stay separate, never inside observations)")
                break
            if any(type(event[key]) is not int for key in EVENT_KEYS):
                reasons.append(f"{where} event fields must be integer microseconds/frames")
                break
            if num and type(uncertainty) is int and (
                    abs(event["video_capture_us"] - event["audio_capture_us"])
                    + uncertainty) * num > 1_000_000 * den:
                reasons.append(
                    f"{where} pair at frame {event['project_frame']} exceeds one project frame "
                    "including uncertainty")
                break
        if mode == "dropped_video":
            if type(dropped) is not int or dropped < 1:
                reasons.append("dropped_video run records no actual dropped frames")
            drops = run.get("drops")
            if not isinstance(drops, list) or not drops:
                reasons.append("dropped_video run must record drop positions (drops: [project_frame, ...])")
            else:
                positions = [entry if type(entry) is int else
                             (entry or {}).get("project_frame") if isinstance(entry, dict) else None
                             for entry in drops]
                positions = [p for p in positions if type(p) is int]
                if expected_frames is not None and not any(
                        abs(p - marker) <= 1 for p in positions for marker in expected_frames):
                    reasons.append("no recorded drop lies within one frame of a marker")
    for mode in MODES:
        if mode not in seen_modes:
            reasons.append(f"missing required run mode {mode!r}")
    return {"schema_ok": not reasons, "schema_reasons": reasons, "synthetic": synthetic}


def evidence_gate(verdict: dict, data: dict | None) -> list[str]:
    """Gate rules beyond schema: never accept synthetic or failed evidence."""
    reasons = [] if verdict.get("schema_ok") else ["schema invalid"]
    if verdict.get("synthetic"):
        reasons.append("file is labeled synthetic (validator self-test artifact, not captured evidence)")
    if data:
        if data.get("ok") is False:
            reasons.append("capture reported ok:false")
        status = str(data.get("status", "")).lower()
        if status in FAIL_STATUSES:
            reasons.append(f"capture status {status!r} does not verify A/V sync")
    return reasons


def synthetic_evidence() -> dict:
    """Labeled synthetic validator fixture: schema-valid, never acceptance evidence."""
    rate = FrameRate(30)
    events = []
    for k in range(1, 30):
        frame = rate.first_frame_at_or_after(k * 1_000_000)
        stamp = k * 1_000_000
        events.append({"project_frame": frame,
                       "video_capture_us": stamp + 5_000,
                       "audio_capture_us": stamp + 5_000 - (k % 3) * 1_000})
    return {
        "synthetic": True,
        "note": ("SYNTHETIC validator self-test artifact written by "
                 "test_mlt_acceptance --write-synthetic; NOT captured evidence."),
        "frame_rate": {"num": 30, "den": 1},
        "runtime": {"kind": "synthetic", "note": "not a real runtime"},
        "capture_method": "synthetic-validator-fixture",
        "raw_capture": {"synthetic": True, "path": None},
        "uncertainty_us": 4_000,
        "runs": [
            {"mode": "normal", "duration_us": 30_005_000, "dropped_frames": 0,
             "events": [dict(e) for e in events]},
            {"mode": "dropped_video", "duration_us": 30_005_000, "dropped_frames": 7,
             "drops": [61, 841, 871, 1234],
             "events": [dict(e) for e in events]},
        ],
    }


def evidence_validator_selftest() -> str:
    base = synthetic_evidence()
    verdict = validate_av_evidence(base)
    assert verdict["schema_ok"], verdict["schema_reasons"]
    assert verdict["synthetic"], "synthetic fixture must self-identify"
    assert evidence_gate(verdict, base), "synthetic evidence must never pass the gate"
    assert evidence_gate({"schema_ok": True, "synthetic": False},
                         dict(base, status="inconclusive"))
    assert not evidence_gate({"schema_ok": True, "synthetic": False},
                             {"ok": True, "status": "passed"})

    checked = 0

    def mutant(name, mutate):
        nonlocal checked
        data = json.loads(json.dumps(base))
        mutate(data)
        result = validate_av_evidence(data)
        assert result["schema_ok"] is False, f"{name}: validator accepted {result}"
        checked += 1

    mutant("missing runs", lambda d: d.pop("runs"))
    mutant("short normal run", lambda d: d["runs"][0].update(duration_us=29_000_000))
    mutant("missing marker pair", lambda d: d["runs"][0]["events"].pop())
    mutant("wrong marker frame",
           lambda d: d["runs"][1]["events"][0].update(project_frame=31))
    mutant("negative uncertainty", lambda d: d.update(uncertainty_us=-1))
    mutant("uncertainty beyond quarter frame", lambda d: d.update(uncertainty_us=8_334))
    def break_sync(data):
        data["runs"][0]["events"][0] = {
            "project_frame": 30, "video_capture_us": 1_005_000,
            "audio_capture_us": 965_000}

    mutant("sync violation", break_sync)
    mutant("dropped_video without drops",
           lambda d: (d["runs"][1].update(dropped_frames=0), d["runs"][1].pop("drops")))
    mutant("drops never near a marker", lambda d: d["runs"][1].update(drops=[1234]))
    mutant("missing dropped_video mode", lambda d: d.update(runs=d["runs"][:1]))
    mutant("unknown mode", lambda d: d["runs"][1].update(mode="calibration"))
    mutant("extra event field",
           lambda d: d["runs"][0]["events"][0].update(ui_pixel=1))
    mutant("invalid frame_rate", lambda d: d.update(frame_rate={"num": 0, "den": 1}))
    return f"schema-valid synthetic accepted; {checked} mutants rejected; gate blocks synthetic/status"


# -- Runner -----------------------------------------------------------------

def _read_evidence(path: Path) -> dict:
    verdict = {"path": str(path), "schema_ok": False, "schema_reasons": [],
               "synthetic": False, "gate_reasons": ["not evaluated"], "gate_ok": False}
    if not path.is_file():
        verdict["schema_reasons"] = [f"capture evidence missing: {path}"]
        verdict["gate_reasons"] = [f"capture evidence missing: {path}"]
        return verdict
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        verdict["schema_reasons"] = [f"capture evidence unreadable: {exc}"]
        verdict["gate_reasons"] = [f"capture evidence unreadable: {exc}"]
        return verdict
    if not isinstance(data, dict):
        verdict["schema_reasons"] = ["capture evidence must be a JSON object"]
        verdict["gate_reasons"] = ["capture evidence must be a JSON object"]
        return verdict
    verdict.update(validate_av_evidence(data))
    verdict["gate_reasons"] = evidence_gate(verdict, data)
    verdict["gate_ok"] = not verdict["gate_reasons"]
    return verdict


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--av-evidence", default="temp/mlt-av-evidence.json",
                        help="capture evidence JSON from the capture lane "
                             "(default: temp/mlt-av-evidence.json)")
    parser.add_argument("--write-synthetic", metavar="PATH",
                        help="write the labeled synthetic validator fixture under temp/ and exit")
    args = parser.parse_args(argv)

    if args.write_synthetic:
        target = Path(args.write_synthetic)
        target = target if target.is_absolute() else ROOT / target
        if not target.is_relative_to(TEMP):
            parser.error("--write-synthetic must stay inside this repository's temp/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(synthetic_evidence(), indent=1,
                                     ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote labeled synthetic validator fixture: {target}")
        return 0

    HERE.mkdir(parents=True, exist_ok=True)
    sections = [
        ("evaluate determinism (repeated and shuffled)", evaluate_determinism),
        ("FrameDescriptor parity (Task 2 compatible subset)", framedesc_parity),
        ("three-layer geometry (order/z/opacity/position/scale/rotation/canvas)",
         three_layer_geometry),
        ("still/text/sticker/fade/crossfade intervals + canonical frame counts",
         interval_counts),
        ("missing transition handles clamp and warn", missing_handle_clamps),
        ("mixed audio trim/offset/mute/gain", mixed_audio),
        ("internal A/V PTS (graph PCM vs video PTS)", internal_av_pts),
        ("read-only non-mutation around open/seek/play/close", readonly_non_mutation),
        ("capture-evidence validator self-test", evidence_validator_selftest),
    ]
    report_sections = []
    failures = 0
    for name, run in sections:
        started = time.perf_counter()
        try:
            detail = run()
            detail = detail or ""
            ms = round((time.perf_counter() - started) * 1000)
            print(f"PASS: {name}" + (f" — {detail}" if detail else "") + f" ({ms} ms)")
            report_sections.append({"name": name, "ok": True, "detail": detail, "ms": ms})
        except Exception as exc:
            failures += 1
            detail = f"{type(exc).__name__}: {exc}"
            print(f"FAIL: {name} — {detail}")
            report_sections.append({"name": name, "ok": False, "detail": detail})

    # capture-calibration: owned by capture lane (integrates here) —
    # marker/pulse timeline construction, screen+audio capture on one clock, and
    # temp/mlt-av-evidence.json generation are delivered by the parallel lane and
    # consumed only by the gate below.

    evidence_path = Path(args.av_evidence)
    evidence_path = evidence_path if evidence_path.is_absolute() else ROOT / evidence_path
    verdict = _read_evidence(evidence_path)
    if verdict["schema_ok"]:
        print(f"PASS: av-evidence schema — {evidence_path} "
              "(both modes >=30 s, 29 marker/pulse pairs each, sync within one frame)")
    else:
        for reason in verdict["schema_reasons"]:
            print(f"FAIL: av-evidence schema — {reason}")
    if verdict["gate_ok"]:
        print("PASS: av-evidence gate — capture evidence accepted")
    else:
        for reason in verdict["gate_reasons"]:
            print(f"FAIL: av-evidence gate — {reason}")
    ok = failures == 0 and verdict["gate_ok"]
    exit_code = 0 if ok else (1 if failures else 2)
    report = {
        "schema": "jypreview/mlt-acceptance@1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "sections": report_sections,
        "measured": MEASURED,
        "av_evidence": verdict,
        "ok": ok,
        "exit_code": exit_code,
    }
    output = HERE / "acceptance-report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print(output)
    if failures:
        print(f"FAIL: {failures} acceptance section(s) failed")
        return 1
    if not verdict["gate_ok"]:
        print("FAIL: acceptance gate — capture evidence is missing, unverified, or "
              "labeled synthetic; cutover needs the capture lane's real evidence")
        return 2
    print("ok: MLT acceptance — model/composition/internal A/V, read-only check, "
          "and synchronized capture evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
