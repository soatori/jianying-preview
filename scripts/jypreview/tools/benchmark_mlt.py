"""Observed-performance benchmark for the compiled MLT preview (plan Task 6 Step 3).

Measures cold open, random seek latency, 30 seconds of continuous output, output
FPS, dropped frames, monotonicity, and a presented-vs-clock A/V diagnostic on
a 64-second/105-clip sample, and writes raw samples plus hardware/runtime/
plugin provenance to ``--json`` (default ``temp/mlt-benchmark.json``).

The plan's real 64-second/105-clip sample is absent from this environment: the
draft library was sanitized from the repository at b3d3353 (placeholder names,
original machine's paths removed) and no drafts root exists on this machine.
By coordinator ruling the default target is therefore a clearly-labeled
SYNTHETIC fixture with the same shape (64 s, exactly 105 clips, mixed
stills/text/transitions/audio lanes) that references the runtime's REAL
representative media so decode/seek/output measurements exercise actual
decoding.  ``fixture: "synthetic"`` plus a note are recorded in the JSON and
printed.  Pass ``--draft <selector>`` to benchmark a real draft instead; an
unresolvable selector exits nonzero with a clear reason.

Observed values only (plan Step 3: these measurements cannot replace the
browser/captured-audio acceptance): no threshold is invented here.  The
plan-stated correctness bounds this tool checks are exact seek targets and
zero timestamp regressions; a run that executes and records exits 0.  The
plan's max A/V delta <= 1 project frame is the GRAPH PCM/video PTS metric,
measured by test_mlt_acceptance and the runtime gate — not this benchmark;
the live presented-vs-clock numbers here are ungated diagnostics (see the
report's ``notes``).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import random
import struct
import sys
import time
import wave
from pathlib import Path
from typing import Any

import jypreview.mlt_backend as mlt_backend
from jypreview.mlt_backend import MltCompiler, PlaybackController
from jypreview.model.timeline import (
    AudioSpec,
    Clip,
    EffectSpec,
    FrameRate,
    MediaRef,
    TextPayload,
    TimelineModel,
    TimeRange,
    Track,
    Transition,
)

ROOT = Path(__file__).resolve().parents[3]
TEMP = ROOT / "temp"
HERE = TEMP / "mlt-benchmark"
FPS = FrameRate(30)
W, H = 300, 180
DURATION_US = 64_000_000
CLIP_COUNT = 105
SEEK_COUNT = 20
SEEK_SEED = 6
CONTINUOUS_MS = 30_000
FIXTURE_NOTE = ("64-second/105-clip sample absent: repo draft library sanitized at b3d3353; "
                "synthetic fixture with the same shape, using the runtime's real "
                "representative media for decode (not the plan's real sample)")


def _require_env(name: str) -> Path:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name} is not set; source temp/mlt-runtime/process-env.ps1 first")
    path = Path(value)
    if not path.is_file():
        raise RuntimeError(f"{name} points at a missing file: {path}")
    return path


def _still(name: str, rgb: tuple[int, int, int]) -> MediaRef:
    """Flat BMP under temp/; a real decodable still for the fixture."""
    path = HERE / "media" / f"{name}.bmp"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = bytes((rgb[2], rgb[1], rgb[0])) * W
    data = row * H
    path.write_bytes(b"BM" + struct.pack("<IHHI", 54 + len(data), 0, 0, 54)
                     + struct.pack("<IiiHHIIiiII", 40, W, H, 1, 24, 0, len(data),
                                   0, 0, 0, 0) + data)
    return MediaRef(name, str(path), True, width=W, height=H, has_audio=False)


def _wav_duration_us(path: Path) -> int:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() * 1_000_000 // handle.getframerate()


def synthetic_sample() -> tuple[TimelineModel, dict[str, Any]]:
    """Exactly 105 clips over 64 s; decodable media from the isolated runtime.

    Measured on this runtime (temp/mlt-benchmark.json explorations): the
    compiler gives every clip its own lane and each visual lane costs roughly
    1.5-4 ms of cairo blend per frame, so a fixture with ~40 visual clips plays
    at under 0.15x realtime.  Visual clips are therefore kept to 14 lanes while
    the remaining 91 clips are audio lanes (measured near-free), preserving the
    plan's shape: 64 s, 105 clips, mixed stills/text/sticker/transitions/audio.
    """
    video_path = _require_env("JY_PREVIEW_TEST_VIDEO")
    audio_path = _require_env("JY_PREVIEW_TEST_AUDIO")
    video = MediaRef("video", str(video_path), True, TimeRange(0, 4_000_000),
                     4_000_000, FrameRate(30), True, W, H)
    wav_us = _wav_duration_us(audio_path)
    if wav_us < 2_000_000:
        raise RuntimeError(f"representative wav too short: {wav_us} us")
    pcm = MediaRef("pcm", str(audio_path), True, TimeRange(0, wav_us), wav_us,
                   has_audio=True)
    stills = [_still("red", (255, 0, 0)), _still("green", (0, 255, 0)),
              _still("blue", (0, 0, 255))]

    # V1: 8 sequential H.264/AAC segments covering the first 32 s (real decode,
    # source spans the whole 4 s file so no handle clamping can occur).
    v1 = [Clip(f"v1-{i}", "video", TimeRange(i * 4_000_000, 4_000_000),
               TimeRange(0, 4_000_000), video) for i in range(8)]
    # V2: 4 still overlays (crossfade handles on stills never clamp).
    v2 = [Clip(f"v2-{i}", "image", TimeRange(i * 16_000_000, 16_000_000),
               media_ref=stills[i % 3]) for i in range(4)]
    # TXT/STK: one Pango title and one sticker (z: video < still < sticker < text).
    txt = [Clip("txt-0", "text", TimeRange(4_000_000, 8_000_000),
                text_payload=TextPayload("Benchmark title", font_size=20))]
    stk = [Clip("stk-0", "sticker", TimeRange(2_000_000, 2_000_000),
                media_ref=stills[2])]
    # A1: 64 sequential 1 s trimmed PCM segments covering the full 64 s.
    a1 = [Clip(f"a1-{i}", "audio", TimeRange(i * 1_000_000, 1_000_000),
               TimeRange(0, 1_000_000), pcm) for i in range(64)]
    # A2: 27 offset/gain/muted variety clips (trim offsets, volume 1.5, one
    # muted, an audio fade-in on the first).
    a2 = []
    for i in range(27):
        offset = (i % 4) * 100_000
        audio = AudioSpec(False) if i == 5 else AudioSpec(volume=1.5 if i % 2 else 1.0)
        effects = (EffectSpec("fadeIn", "audio_fade_in", TimeRange(0, 500_000)),)             if i == 0 else ()
        a2.append(Clip(f"a2-{i}", "audio", TimeRange(i * 2_200_000, 2_000_000),
                       TimeRange(offset, 2_000_000), pcm, audio=audio, effects=effects))

    transitions = (
        Transition("xf-0", "crossfade", TimeRange(16_000_000 - 200_000, 400_000),
                   "v2-0", "v2-1"),
        Transition("xf-1", "crossfade", TimeRange(32_000_000 - 200_000, 400_000),
                   "v2-1", "v2-2"),
        Transition("fade-stk", "fade", TimeRange(2_000_000, 500_000), None, "stk-0"),
    )
    model = TimelineModel(
        "benchmark-synthetic", DURATION_US, FPS, (W, H),
        (Track("V1", "video", tuple(v1)),
         Track("V2", "video", tuple(v2), render_index=1),
         Track("TXT", "text", tuple(txt)),
         Track("STK", "sticker", tuple(stk)),
         Track("A1", "audio", tuple(a1)),
         Track("A2", "audio", tuple(a2))),
        transitions,
    )
    count = sum(len(track.clips) for track in model.tracks)
    assert count == CLIP_COUNT, f"fixture has {count} clips, expected {CLIP_COUNT}"
    assert model.duration_us == DURATION_US, model.duration_us
    fixture = {
        "kind": "synthetic",
        "note": FIXTURE_NOTE,
        "duration_us": model.duration_us,
        "clip_count": count,
        "transitions": len(model.transitions),
        "tracks": {track.id: len(track.clips) for track in model.tracks},
        "visual_clips": sum(len(t.clips) for t in model.tracks
                            if t.type in ("video", "text", "sticker")),
        "media": {"video": str(video_path), "audio": str(audio_path),
                  "audio_duration_us": wav_us,
                  "stills": [str(ref.path) for ref in stills]},
    }
    return model, fixture


def model_from_draft(selector: str) -> tuple[TimelineModel, dict[str, Any]]:
    """Resolve a real draft through the production session; raise with the reason."""
    import jypreview.config as jyconfig
    from jypreview.session import DraftNotFound, PreviewSession, TimelineNotFound

    try:
        config = jyconfig.load()
    except SystemExit:
        # config.load() reports a missing drafts root as a styled SystemExit
        # (already printed); re-raise as this tool's documented failure path.
        raise LookupError("sample missing / draft not found: no drafts root configured "
                          "(set JY_PREVIEW_DRAFTS_ROOT; the repo's sample library was "
                          "sanitized at b3d3353)") from None
    session = PreviewSession(config)
    try:
        view = session.view(selector)
        entry = view.resolve_timeline(None)
        model = view.timeline_model(entry["id"])
    except (DraftNotFound, TimelineNotFound) as exc:
        raise LookupError(f"sample missing / draft not found: {selector} ({exc})") from exc
    fixture = {"kind": "draft", "selector": selector, "did": view.did,
               "name": view.name, "timeline": entry.get("id"),
               "duration_us": model.duration_us,
               "clip_count": sum(len(t.clips) for t in model.tracks)}
    return model, fixture


def _provenance() -> dict[str, Any]:
    available, version_note = MltCompiler.available()
    repo: Any = mlt_backend._repository
    plugins = None
    if repo is not None:
        plugins = {}
        for kind in ("producers", "filters", "transitions"):
            services = getattr(repo, kind)()
            plugins[kind] = sorted(services.get_name(i)
                                   for i in range(services.count()))
    return {
        "python": {"executable": sys.executable, "version": sys.version},
        "mlt": {"available": bool(available), "version": version_note,
                "approved_executable": os.environ.get("JY_PREVIEW_MLT_PYTHON")},
        "repository": {key: os.environ.get(key) for key in
                       ("MLT_REPOSITORY", "MLT_DATA", "MLT_PROFILES_PATH",
                        "MLT_PRESETS_PATH", "FREI0R_PATH", "MLT_REPOSITORY_DENY")},
        "plugins": plugins,
        "hardware": {"platform": platform.platform(), "machine": platform.machine(),
                     "processor": platform.processor(),
                     "cpu_count": os.cpu_count()},
        "audio_sink": mlt_backend._sink_name,
    }


def _run_phases(model: TimelineModel, report: dict[str, Any]) -> None:
    """Cold open, random seeks, 30 s continuous output; fills report in place."""
    controller = PlaybackController()
    failures: list[str] = report.setdefault("failures", [])
    try:
        started = time.perf_counter()
        opened = controller.open(model)
        report["cold_open"] = {
            "ms": round((time.perf_counter() - started) * 1000, 1),
            "phase": opened["phase"],
            "duration_frames": FPS.frame_count(model.duration_us),
        }
        if opened["phase"] != "ready" or not opened["open"]:
            failures.append(f"cold open ended in phase {opened['phase']!r}")
            return
        playback_id = opened["playback_id"]

        # Random seeks: latency from request to settled frame identity.
        rng = random.Random(SEEK_SEED)
        samples: list[dict[str, Any]] = []
        mismatches = 0
        for request_id in range(1, SEEK_COUNT + 1):
            t_us = rng.randrange(0, model.duration_us)
            target = model.frame_rate.quantize(t_us)[0]
            before = time.perf_counter()
            controller.seek(t_us, playback_id=playback_id, request_id=request_id)
            frame = controller.pull_frame(5_000)
            settled = controller.snapshot()
            latency_ms = round((time.perf_counter() - before) * 1000, 2)
            exact = (settled["frame_index"] == target
                     and frame is not None and frame.frame_index == target)
            if not exact:
                mismatches += 1
            samples.append({"request_us": t_us, "target_frame": target,
                            "settled_frame": settled["frame_index"],
                            "pulled_frame": None if frame is None else frame.frame_index,
                            "latency_ms": latency_ms, "phase": settled["phase"]})
        latencies = sorted(row["latency_ms"] for row in samples)
        report["seeks"] = {
            "count": SEEK_COUNT, "seed": SEEK_SEED,
            "target_mismatches": mismatches,
            "latency_ms": {"min": latencies[0],
                           "p50": latencies[len(latencies) // 2],
                           "max": latencies[-1]},
            "samples": samples,
        }

        # Rewind so the 30 s window plays from the start of the 64 s timeline.
        controller.seek(0, playback_id=playback_id, request_id=SEEK_COUNT + 1)
        rewound = controller.snapshot()
        if rewound["frame_index"] != 0:
            failures.append(f"rewind landed on frame {rewound['frame_index']}")
            return

        # Live frame stream: during play the consumer's frame-show listener
        # stamps the controller's frame slot, which pull_frame() returns (the
        # tractor.capture seam fires only on Python-side pulls and stays dead
        # while the consumer pulls natively).  Poll it on a bounded cadence —
        # observed frames dwell ~250 ms of wall time here, far above the 50 ms
        # poll, so distinct-frame gaps are real drops, not sampling misses.
        if controller.play()["phase"] not in ("buffering", "playing"):
            failures.append("play did not enter buffering/playing")
            return
        window_s = CONTINUOUS_MS / 1000.0
        t_start = time.perf_counter()
        last_observed: int | None = None
        next_poll = t_start
        drops = 0
        monotonicity_failures = 0
        clock_failures = 0
        previous_clock = -1
        first_clock_us: int | None = None
        last_clock_us = 0
        max_av_delta_raw = 0
        av_pairs = 0
        max_av_delta_steady = 0
        steady_pairs = 0
        settled = False
        phase = "playing"
        error: str | None = None
        frame_samples: list[dict[str, Any]] = []
        clock_samples: list[dict[str, Any]] = []
        while time.perf_counter() - t_start < window_s:
            snap = controller.snapshot()
            phase = snap["phase"]
            if phase == "error":
                error = snap["error"]
                break
            if phase == "ended":
                break
            clock_us = snap["t_us"]
            now = time.perf_counter()
            live = None
            if now >= next_poll:
                next_poll = now + 0.05
                live = controller.pull_frame(20)
            if live is not None and live.frame_index != last_observed:
                # A distinct presented frame.  Gaps between consecutive
                # observations are frames the consumer never presented; the
                # run-up before the first observation is not counted (nothing
                # before it was sampled).
                if last_observed is not None:
                    if live.frame_index < last_observed:
                        monotonicity_failures += 1
                    elif live.frame_index > last_observed + 1:
                        drops += live.frame_index - last_observed - 1
                last_observed = live.frame_index
                frame_samples.append({
                    "wall_ms": round((now - t_start) * 1000, 1),
                    "frame_index": live.frame_index,
                    "pts_us": live.pts_us,
                })
            if first_clock_us is None:
                first_clock_us = clock_us
            last_clock_us = clock_us
            if clock_us < previous_clock:
                clock_failures += 1
            previous_clock = max(previous_clock, clock_us)
            elapsed_ms = (time.perf_counter() - t_start) * 1000
            if live is not None and phase == "playing":
                # Pair both sides only where both exist: the presented video
                # frame read this iteration vs the audio-mastered consumer
                # clock from the same iteration (sub-millisecond apart).
                # Warmup: startup consumer.position() bookkeeping leads the
                # presented frames (reports frame 3 at wall 0.2 ms while video
                # still presents 0..3); steady state starts at the first pair
                # where the presented frame reached the clock (video >= clock).
                clock_frame = model.frame_rate.quantize(clock_us)[0]
                delta = abs(clock_frame - live.frame_index)
                max_av_delta_raw = max(max_av_delta_raw, delta)
                av_pairs += 1
                if not settled and live.frame_index >= clock_frame:
                    settled = True
                if settled:
                    max_av_delta_steady = max(max_av_delta_steady, delta)
                    steady_pairs += 1
            if not clock_samples or elapsed_ms - clock_samples[-1]["wall_ms"] >= 500:
                clock_samples.append({"wall_ms": round(elapsed_ms, 1),
                                      "t_us": clock_us, "phase": phase})
            time.sleep(0.005)
        controller.pause()
        observed_ms = round((time.perf_counter() - t_start) * 1000, 1)
        frames = len(frame_samples)
        expected = FPS.frame_count(CONTINUOUS_MS * 1000)  # window is in ms; frame math in us
        wall_s = observed_ms / 1000 if observed_ms else 1.0
        clock_span_us = max(0, last_clock_us - (first_clock_us or 0))
        output_fps_clock = round(clock_span_us * FPS.num / (1_000_000 * FPS.den) / wall_s, 3)
        output_fps_frames = round(frames / wall_s, 3)
        frame_stream_observed = frames >= 2
        report["continuous"] = {
            "window_ms": CONTINUOUS_MS,
            "observed_ms": observed_ms,
            "phase": phase,
            "error": error,
            "frames_observed": frames,
            "expected_frames": expected,
            "frame_stream_observed": frame_stream_observed,
            "frame_source": ("live frame-show slot via controller.pull_frame() polled "
                             "every 50 ms during play; drops = gaps between distinct "
                             "presented frame indices (startup run-up excluded)"),
            "dropped_frames": drops if frame_stream_observed else None,
            "output_fps": output_fps_frames,
            "output_fps_clock": output_fps_clock,
            "output_fps_frames": output_fps_frames,
            "clock_span_us": clock_span_us,
            "monotonicity_failures": monotonicity_failures,
            "clock_monotonicity_failures": clock_failures,
            "max_presented_vs_clock_delta_frames_raw": (max_av_delta_raw
                                                         if av_pairs else None),
            "max_presented_vs_clock_delta_frames_steady_state": (max_av_delta_steady
                                                                  if steady_pairs
                                                                  else None),
            "av_pairs": av_pairs,
            "av_steady_pairs": steady_pairs,
            "av_method": ("presented video frame from the live frame-show slot vs the "
                          "audio-mastered consumer clock, both read in the same 5 ms "
                          "loop iteration; pairs form only while playing with a frame "
                          "observed (frame stream dead -> no pairs, values stay null). "
                          "Warmup rule for _steady_state: startup position() "
                          "bookkeeping leads presented frames; steady pairs start at "
                          "the first pair where the presented frame reached the clock "
                          "(presented >= clock) and include everything after. "
                          "_raw covers all pairs. Both are ungated diagnostics."),
            "frame_samples": frame_samples,
            "clock_samples": clock_samples,
        }
        if error:
            failures.append(f"playback error during continuous run: {error}")
        if phase == "ended":
            failures.append("continuous run reached the timeline end before 30 s")
        if clock_span_us == 0:
            failures.append("audio-mastered consumer clock did not advance during the "
                            "continuous window (playback never happened)")
        if monotonicity_failures or clock_failures:
            failures.append(f"timestamp regressions: frames={monotonicity_failures} "
                            f"clock={clock_failures}")
        if mismatches:
            failures.append(f"{mismatches} seeks missed their target frame")
    finally:
        with contextlib.suppress(Exception):
            controller.pause()  # error/already-paused states are fine here
        # A stopped-but-recently-playing 105-lane graph crashes native teardown
        # (observed access violation in _h_close); let the consumer drain first.
        time.sleep(1.5)
        try:
            controller.close()
        except Exception as exc:  # keep the report even if teardown fails
            failures.append(f"close failed: {type(exc).__name__}: {exc}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default="temp/mlt-benchmark.json",
                        help="output path; must stay inside this repository's temp/")
    parser.add_argument("--draft", default=os.environ.get("JY_PREVIEW_TEST_DRAFT"),
                        help="real draft selector (default: env JY_PREVIEW_TEST_DRAFT; "
                             "unset = synthetic fixture)")
    args = parser.parse_args(argv)
    output = Path(args.json)
    output = output if output.is_absolute() else ROOT / output
    if not output.is_relative_to(TEMP):
        parser.error("--json must be inside this repository's root temp/ directory")

    report: dict[str, Any] = {
        "schema": "jypreview/mlt-benchmark@1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "fixture": None,
        "provenance": None,
        "failures": [],
        "ok": False,
        "notes": (
            "A/V metrics live in three places: (1) this benchmark's live diagnostic "
            "max_presented_vs_clock_delta_frames_raw/_steady_state — presented "
            "video frame vs consumer.position() clock, ungated, plan Step 3 "
            "observed-only; (2) max_internal_av_delta_frames — graph PCM vs video "
            "PTS, measured by jypreview.tools.test_mlt_acceptance (the plan's "
            "<=1-frame bound; acceptance reports 0) and the runtime gate; "
            "(3) max_presented_av_delta — Task 6 captured end-to-end metric with "
            "capture uncertainty, owned by the browser/captured-audio acceptance "
            "lane, not measured here."
        ),
    }
    exit_code = 0
    try:
        if args.draft:
            model, fixture = model_from_draft(args.draft)
        else:
            print(f"SYNTHETIC FIXTURE: {FIXTURE_NOTE}")
            model, fixture = synthetic_sample()
        report["fixture"] = fixture
        _run_phases(model, report)
        report["provenance"] = _provenance()
    except LookupError as exc:
        report["failures"].append(str(exc))
        exit_code = 2
    except Exception as exc:
        report["failures"].append(f"{type(exc).__name__}: {exc}")
        exit_code = 1

    failures: list[str] = report["failures"]
    report["ok"] = not failures
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n",
                      encoding="utf-8")

    cold = report.get("cold_open") or {}
    seeks = report.get("seeks") or {}
    continuous = report.get("continuous") or {}
    if cold:
        print(f"cold open: {cold['ms']} ms (phase {cold['phase']})")
    if seeks:
        latency = seeks["latency_ms"]
        print(f"seeks: {seeks['count']} requests, latency ms min/p50/max = "
              f"{latency['min']}/{latency['p50']}/{latency['max']}, "
              f"target mismatches {seeks['target_mismatches']}")
    if continuous:
        dropped = continuous["dropped_frames"]
        raw_delta = continuous["max_presented_vs_clock_delta_frames_raw"]
        steady_delta = continuous["max_presented_vs_clock_delta_frames_steady_state"]
        print(f"continuous {CONTINUOUS_MS // 1000}s: output FPS "
              f"{continuous['output_fps']} "
              f"({continuous['frames_observed']} distinct frames, "
              f"clock FPS {continuous['output_fps_clock']}, "
              f"content {round(continuous['clock_span_us'] / 1e6, 1)}s), "
              f"frame stream {continuous['frames_observed']}/{continuous['expected_frames']} "
              f"({'observed' if continuous['frame_stream_observed'] else 'static: no frames observed'}), "
              f"dropped {dropped if dropped is not None else 'unobservable'}, "
              f"regressions {continuous['monotonicity_failures']}"
              f"+{continuous['clock_monotonicity_failures']}, "
              f"presented-vs-clock delta raw "
              f"{raw_delta if raw_delta is not None else 'unverified'}"
              f" / steady {steady_delta if steady_delta is not None else 'unverified'}"
              f" frames ({continuous['av_pairs']} pairs, "
              f"steady {continuous['av_steady_pairs']})")
    if report.get("provenance"):
        print(f"runtime: {report['provenance']['mlt']['version']}, "
              f"sink {report['provenance']['audio_sink']}")
    print(output)
    if failures:
        for reason in failures:
            print(f"FAIL: {reason}")
        return exit_code or 1
    print("ok: MLT benchmark — observed values recorded (fixture "
          f"{(report['fixture'] or {}).get('kind')}; no thresholds invented)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
