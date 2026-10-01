"""Isolated Windows/Python 3.14 MLT capability gate; no application imports."""

import argparse
from array import array
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import wave


POSITIONS = (0, 15, 3, 30)
WIDTH, HEIGHT, FPS, FREQUENCY = 300, 180, 30, 48000
MARKER_BASE, MARKER_STEP, MARKER_FRAMES = 1000, 100, 120


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def write_audio_markers(path):
    """Independent 48 kHz/stereo PCM oracle: one amplitude code per 30 FPS frame."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setparams((2, 2, FREQUENCY, 0, "NONE", "not compressed"))
        for position in range(MARKER_FRAMES):
            output.writeframes(array("h", [MARKER_BASE + MARKER_STEP * position]
                                     * (2 * FREQUENCY // FPS)).tobytes())


def marker_av_delta(video_position, mixed):
    """Identify audio time from PCM content, independently of MLT frame metadata."""
    audio_position = round((sum(mixed) / len(mixed) / 2 - MARKER_BASE) / MARKER_STEP)
    require(0 <= audio_position < MARKER_FRAMES, "Audio marker frame is out of range")
    expected = 2 * (MARKER_BASE + MARKER_STEP * audio_position)
    error = max(abs(actual - expected) for actual in mixed)
    require(error <= 2, f"Two-lane PCM marker sum differs from expected by {error}")
    delta = abs(video_position - audio_position)
    require(delta <= 1, f"Internal A/V offset is {delta} project frames (maximum 1)")
    return audio_position, error, delta


def loaded_audio_api():
    """Reuse the DLL loaded by mlt7, never load a second native runtime.

    C signature: official src/framework/mlt_frame.h, mlt_frame_get_audio.
    Python's src/swig/mlt.i has an image-byte wrapper but no PCM-byte wrapper.
    """
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    kernel.GetModuleHandleW.restype = ctypes.c_void_p
    kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint]
    kernel.GetModuleFileNameW.restype = ctypes.c_uint
    handle = kernel.GetModuleHandleW("libmlt-7.dll")
    require(handle, "mlt7 did not load libmlt-7.dll; PCM bridge unavailable")
    path = ctypes.create_unicode_buffer(32768)
    require(kernel.GetModuleFileNameW(handle, path, len(path)), "Cannot resolve loaded MLT DLL")
    library = ctypes.CDLL(path.value, handle=handle)
    function = library.mlt_frame_get_audio
    function.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)] + [
        ctypes.POINTER(ctypes.c_int)
    ] * 4
    function.restype = ctypes.c_int
    return library, function, path.value


def pcm(frame, get_audio, mlt):
    pointer = ctypes.c_void_p()
    fmt, frequency, channels, samples = (
        ctypes.c_int(value) for value in (mlt.mlt_audio_s16, FREQUENCY, 2, FREQUENCY // FPS)
    )
    error = get_audio(int(frame.get_frame()), ctypes.byref(pointer), ctypes.byref(fmt),
                      ctypes.byref(frequency), ctypes.byref(channels), ctypes.byref(samples))
    require(error == 0 and pointer.value, "PCM decode failed")
    require(fmt.value == mlt.mlt_audio_s16 and frequency.value == FREQUENCY
            and channels.value == 2 and samples.value == FREQUENCY // FPS,
            "PCM output format/sample count differs from project frame")
    require(not frame.get_int("test_audio"), "MLT substituted test/silent audio")
    values = array("h", ctypes.string_at(pointer, samples.value * channels.value * 2))
    require(any(values), "PCM is silent: use an audible representative fixture")
    return values


def rgba(frame, mlt):
    require(frame.is_valid(), "Invalid MLT frame")
    pixels = bytes(frame.get_image(mlt.mlt_image_rgba, WIDTH, HEIGHT))
    require(len(pixels) == WIDTH * HEIGHT * 4 and any(pixels[3::4]), "Empty RGBA output")
    require(not frame.get_int("test_image"), "MLT substituted a test image")
    return pixels


def seek_frame(producer, position):
    require(producer.seek(position) == 0, f"Seek failed at {position}")
    frame = producer.get_frame()
    require(frame.is_valid() and frame.get_position() == position,
            f"Expected project frame {position}, got {frame.get_position()}")
    return frame


def drive_consumer(consumer, graph):
    """Check actual consumer startup and frame advancement, with a bounded wait."""
    require(graph.seek(0) == 0, "Consumer source seek failed")
    graph.set_speed(1)
    consumer.set("real_time", 1)
    consumer.set("terminate_on_pause", 0)
    require(consumer.connect(graph) == 0, "Consumer connect failed")
    try:
        require(consumer.start() == 0, "Consumer start failed")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if consumer.position() >= 3:
                return {"position": consumer.position(), "started": True}
            require(not consumer.is_stopped(), "Consumer stopped before output")
            time.sleep(0.02)
        raise RuntimeError("Consumer did not advance three project frames in five seconds")
    finally:
        consumer.stop()


def run_gate(args, result):
    require(os.name == "nt" and sys.version_info[:2] == (3, 14),
            "Gate requires Windows/Python 3.14")
    approved = os.environ.get("JY_PREVIEW_MLT_PYTHON")
    require(approved and Path(approved).resolve() == Path(sys.executable).resolve(),
            "Run with the absolute JY_PREVIEW_MLT_PYTHON executable")
    for path in (args.video, args.audio):
        require(path and Path(path).is_file(), "Provide existing --video and --audio fixtures")

    import mlt7 as mlt

    repository = mlt.Factory().init(None)
    profile = mlt.Profile()
    profile.set_frame_rate(FPS, 1)
    profile.set_width(WIDTH)
    profile.set_height(HEIGHT)
    profile.set_progressive(1)
    profile.set_sample_aspect(1, 1)
    profile.set_display_aspect(5, 3)
    profile.set_explicit(1)
    result["mlt_version"] = mlt.mlt_version_get_string()
    result["python"]["binding"] = str(Path(mlt.__file__).resolve())
    result["repository"] = {name: os.environ.get(name) for name in (
        "MLT_REPOSITORY", "MLT_DATA", "MLT_PROFILES_PATH", "FREI0R_PATH")}
    result["repository"]["factory_directory"] = mlt.mlt_factory_directory()
    for kind in ("producers", "transitions", "consumers"):
        properties = getattr(repository, kind)()
        result["plugins"][kind] = [properties.get_name(i) for i in range(properties.count())]
    for kind, names in {"producers": ("avformat", "loader", "timewarp", "pango", "color"),
                        "transitions": ("frei0r.cairoaffineblend", "mix"),
                        "consumers": ("null",)}.items():
        for name in names:
            require(name in result["plugins"][kind], f"Missing {kind} plugin: {name}")
    library, get_audio, dll_path = loaded_audio_api()
    result["repository"]["pcm_library"] = dll_path

    def producer(service, resource):
        value = mlt.Producer(profile, service, resource)
        require(value.is_valid(), f"Cannot instantiate {service}")
        value.set_speed(1)
        return value

    producer("avformat", str(Path(args.video).resolve()))
    video = producer("loader", str(Path(args.video).resolve()))
    producer("avformat", str(Path(args.audio).resolve()))
    audio = producer("loader", str(Path(args.audio).resolve()))
    require(video.get_length() > 60 and audio.get_length() > 30,
            "Fixtures must cover frames 0..60 video and 0..30 audio at 30 FPS")
    loader = producer("loader", str(Path(args.video).resolve()))
    rgba(seek_frame(loader, 0), mlt)
    video_hashes = {}
    for position in POSITIONS:
        pixels = rgba(seek_frame(video, position), mlt)
        values = pcm(seek_frame(audio, position), get_audio, mlt)
        video_hashes[position] = hashlib.sha256(pixels).hexdigest()
        result["decoded_media"].append({"position": position, "rgba_bytes": len(pixels),
                                        "pcm_samples": len(values), "pcm_peak": max(map(abs, values))})
    require(video_hashes[0] != video_hashes[30], "Video fixture must vary over time to verify timewarp")
    producer("pango", "+MLT gate")
    title = producer("loader", "pango:+MLT gate")
    title_pixels = rgba(seek_frame(title, 0), mlt)
    require(any(title_pixels[i] for i in range(0, len(title_pixels), 4)), "Pango title is blank")

    # Three visible RGB bands prove affine scale/translation and both blend hops.
    graph = mlt.Tractor(profile)
    lanes = [producer("color", color) for color in ("#ff0000", "#00ff00", "#0000ff")]
    marker_path = Path(__file__).resolve().parents[3] / "temp" / "mlt-frame-markers.wav"
    write_audio_markers(marker_path)
    result["audio_marker_fixture"] = {"path": str(marker_path), "base": MARKER_BASE,
                                      "step": MARKER_STEP, "frames": MARKER_FRAMES,
                                      "samples_per_frame": FREQUENCY // FPS}
    audio_lanes = [producer("loader", str(marker_path)) for _ in range(2)]
    for lane in lanes:
        lane.set("set.test_audio", 1)
    for lane in audio_lanes:
        lane.set("set.test_image", 1)
    for index, lane in enumerate(lanes + audio_lanes):
        require(graph.set_track(lane, index) == 0, "Cannot attach tractor track")
    transitions = []
    for index in (1, 2):
        blend = mlt.Transition(profile, "frei0r.cairoaffineblend")
        require(blend.is_valid(), "Cannot instantiate cairoaffineblend")
        for key, value in {"0": 0.4 + index / 15, "1": 0.4, "2": 1 / 15,
                           "3": 0.2, "4": 0.0, "5": 1.0, "6": "normal"}.items():
            blend.set(key, value)
        blend.set("disable", 0)
        blend.set("always_active", 1)
        graph.plant_transition(blend, 0, index)
        transitions.append(blend)
    mix = mlt.Transition(profile, "mix")
    require(mix.is_valid(), "Cannot instantiate mix")
    mix.set("sum", 1)
    mix.set("always_active", 1)
    graph.plant_transition(mix, 3, 4)
    transitions.append(mix)
    deltas = []
    for position in POSITIONS:
        frame = seek_frame(graph, position)
        pixels = rgba(frame, mlt)
        video_position = frame.get_position()
        mixed = pcm(frame, get_audio, mlt)
        audio_position, error, delta = marker_av_delta(video_position, mixed)
        probes = [list(pixels[(HEIGHT // 2 * WIDTH + x) * 4:][:4])
                  for x in (WIDTH // 6, WIDTH // 2, WIDTH * 5 // 6)]
        for index, pixel in enumerate(probes):
            require(pixel[index] > 240 and all(pixel[j] < 15 for j in range(3) if j != index),
                    f"Three-layer affine blend failed: {probes}")
        deltas.append(delta)
        result["frame_positions"].append({"requested": position, "video": video_position,
                                           "audio": audio_position, "pcm_samples": len(mixed),
                                           "pcm_sum_max_error": error})
        result["three_layer_rgba"].append({"position": position, "bytes": len(pixels), "pixels": probes})
    result["max_internal_av_delta_frames"] = max(deltas)
    result["internal_pts_basis"] = "Video frame position versus independently encoded PCM frame marker"
    require(max(deltas) <= 1, "Internal audio/video PTS differ by more than one project frame")

    # Advance the actual audio sources by two frames; the same gate must reject it.
    shifted = [lane.cut(2, MARKER_FRAMES - 1) for lane in audio_lanes]
    for index, lane in enumerate(shifted, 3):
        require(graph.set_track(lane, index) == 0, "Cannot inject audio offset")
    offset_frame = seek_frame(graph, 15)
    rgba(offset_frame, mlt)
    offset_pcm = pcm(offset_frame, get_audio, mlt)
    try:
        marker_av_delta(offset_frame.get_position(), offset_pcm)
    except RuntimeError as exc:
        require(str(exc) == "Internal A/V offset is 2 project frames (maximum 1)",
                f"Offset control failed for a different reason: {exc}")
        result["audio_offset_selfcheck"] = {"injected_frames": 2, "rejected": True,
                                           "error": str(exc)}
    else:
        raise RuntimeError("Gate accepted an injected two-frame audio offset")
    for index, lane in enumerate(audio_lanes, 3):
        require(graph.set_track(lane, index) == 0, "Cannot restore aligned audio")

    for speed in (0.5, 2.0, -1.0):
        warped = producer("loader", f"timewarp:{speed}:{Path(args.video).resolve()}")
        require(warped.get_double("warp_speed") == speed, "Timewarp ignored requested speed")
        rows = []
        for position in POSITIONS:
            pixels = rgba(seek_frame(warped, position), mlt)
            source = position * speed if speed > 0 else warped.get_out() - position
            candidates = sorted({math.floor(source), math.ceil(source)})
            matches = [candidate for candidate in candidates
                       if pixels == rgba(seek_frame(video, candidate), mlt)]
            require(matches, f"Timewarp {speed} at {position} does not match source {candidates}")
            rows.append({"project_position": position, "source_candidates": candidates,
                         "matched_source_positions": matches, "rgba_bytes": len(pixels)})
        result["timewarp"][str(speed)] = rows

    pull = mlt.Consumer(profile, "null")
    require(pull.is_valid(), "Cannot create frame-pulling null consumer")
    result["frame_pulling_consumer"] = drive_consumer(pull, graph)
    sink_errors = {}
    for name in ("sdl2_audio", "rtaudio"):
        if name not in result["plugins"]["consumers"]:
            sink_errors[name] = "not in repository"
            continue
        sink = mlt.Consumer(profile, name)
        try:
            require(sink.is_valid(), f"Cannot instantiate {name}")
            result["audio_sink"] = {"service": name, **drive_consumer(sink, graph)}
            break
        except RuntimeError as exc:
            sink_errors[name] = str(exc)
    require(result["audio_sink"], f"No working audio sink: {sink_errors}")
    result["ok"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", default=os.environ.get("JY_PREVIEW_TEST_VIDEO"))
    parser.add_argument("--audio", default=os.environ.get("JY_PREVIEW_TEST_AUDIO"))
    parser.add_argument("--json", default="temp/mlt-runtime-gate.json")
    args = parser.parse_args()
    output = Path(args.json).resolve()
    temp = Path(__file__).resolve().parents[3] / "temp"
    if not output.is_relative_to(temp):
        parser.error("--json must be inside this repository's root temp/ directory")
    result = {"python": {"executable": sys.executable, "version": sys.version,
                          "approved_executable": os.environ.get("JY_PREVIEW_MLT_PYTHON")},
              "mlt_version": None, "repository": {}, "plugins": {}, "decoded_media": [],
              "frame_positions": [], "audio_sink": None, "three_layer_rgba": [],
              "timewarp": {}, "max_internal_av_delta_frames": None, "ok": False}
    try:
        run_gate(args, result)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{'PASS' if result['ok'] else 'FAIL'}: {result.get('error', 'MLT runtime gate')}")
    print(output)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
