"""Executable assertions for immutable timeline values and canonical evaluation."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jypreview.model import fonts, framedesc, timing
from jypreview.model.content import TimelineContent
from jypreview.model.draft_adapter import DraftAdapter

from jypreview.model.timeline import (
    AudioSpec, Clip, EffectSpec, ExpectedScene, FrameRate, MediaRef, SceneItem,
    TextPayload, TimeMapping, TimeRange, TimelineModel, Track, Transform,
    Transition, evaluate,
)
from jypreview.session import DraftView, PreviewSession, TimelineNotFound


TEMP = Path(__file__).resolve().parents[3] / "temp"
LOCATED = {"path": str(TEMP / "fixture.mp4"), "exists": True,
           "how": "fixture", "recovered": False}
PROBE = {"codec": "h264", "width": 1920, "height": 1080,
         "duration_us": 10_000_000, "frame_rate": 23.976,
         "audio_codec": "aac", "error": None}


def fixture():
    config = SimpleNamespace(max_nest_depth=2, effect_cache=None, install_fonts=None,
                             user_state_dir=TEMP, default_fps=30,
                             text_size_basis="width", text_scale_factor=0.00625,
                             transform_y_basis="half", y_sign="jianying_up",
                             fit_mode="contain_unrotated")
    segment = {"id": "clip", "material_id": "v", "render_index": 9,
               "target_timerange": {"start": 0, "duration": 1_000_000},
               "source_timerange": {"start": 2_000_000, "duration": 2_000_000},
               "speed": 2, "reverse": True, "volume": 1.5,
               "clip": {"transform": {"x": 0.2, "y": -0.2},
                        "scale": {"x": 2, "y": 3}, "rotation": 90,
                        "alpha": 0.4, "flip": {"horizontal": True}},
               "crop": {"left": 0.1, "top": 0.2, "right": 0.9, "bottom": 0.8},
               "blend_mode": "multiply"}
    value = {"id": "timeline", "fps": 30, "duration": 2_000_000,
             "canvas_config": {"width": 1920, "height": 1080},
             "materials": {"videos": [{"id": "v", "type": "video", "path": "fixture.mp4"}]},
             "tracks": [{"id": "track", "type": "video", "render_index": 7,
                         "segments": [segment]}]}
    return config, value


def build(value, config):
    return DraftAdapter(config, None, None, None, TEMP / "probes").build(
        TimelineContent.build(value), draft_root=TEMP, did="draft", timeline_info={})


def adapter_assertions():
    config, value = fixture()
    with patch("jypreview.media.resolve", side_effect=lambda raw, root: LOCATED if raw else dict(LOCATED, exists=False, path=None)), patch("jypreview.media.probe", return_value=PROBE):
        snapshot = deepcopy(value)
        model = build(value, config)
        clip = model.tracks[0].clips[0]
        assert value == snapshot
        assert (model.id, model.duration_us, model.canvas) == ("timeline", 2_000_000, (1920, 1080))
        assert (clip.id, clip.kind, clip.timeline_range, clip.source_range) == (
            "clip", "video", TimeRange(0, 1_000_000), TimeRange(2_000_000, 2_000_000))
        assert not clip.placeholder and clip.audio == AudioSpec(True, 1.5)
        assert clip.media_ref == MediaRef("v", LOCATED["path"], True, TimeRange(0, 10_000_000),
                                          10_000_000, FrameRate(24_000, 1001), True, 1920, 1080)
        assert clip.transform == Transform(1152, 648, 1920, 1080, 90, 2, 3, flip_x=True)
        assert (clip.crop, clip.opacity, clip.blend_mode) == ((0.1, 0.2, 0.9, 0.8), 0.4, "multiply")
        assert (clip.time_mapping, clip.render_index) == (TimeMapping(2, direction="reverse"), 9)
        assert evaluate(model, 500_000).video[0].source_us == 2_999_999
        for fps, expected in ((None, FrameRate(30)), (29.97, FrameRate(30_000, 1001)),
                              (59.94, FrameRate(60_000, 1001)), (23.976, FrameRate(24_000, 1001)),
                              ({"num": 30_000, "den": 1001}, FrameRate(30_000, 1001))):
            normalized = build(dict(value, fps=fps), config)
            assert normalized.frame_rate == expected
            assert ("fps_defaulted" in normalized.warnings) == (fps is None)
        # Dictionary mutation after build cannot change any model field.
        value["tracks"][0]["segments"][0]["volume"] = 0
        assert clip.audio.volume == 1.5
        value = snapshot

        for changes, video_ids, audio_ids in (
            ({"visible": False}, [], []), ({"audio": {"enabled": False}}, ["clip"], []),
            ({"enable_audio": False}, ["clip"], []), ({"audio": {"volume": 1.5}}, ["clip"], ["clip"]),
        ):
            changed = deepcopy(value)
            changed["tracks"][0]["segments"][0].update(changes)
            scene = evaluate(build(changed, config), 0)
            assert [i.clip_id for i in scene.video] == video_ids
            assert [i.clip_id for i in scene.audio] == audio_ids
            if audio_ids:
                assert scene.audio[0].volume == 1.5
        for flag, video_ids in (("enabled", []), ("muted", ["clip"])):
            changed = deepcopy(value)
            changed["tracks"][0][flag] = flag == "muted"
            scene = evaluate(build(changed, config), 0)
            assert [i.clip_id for i in scene.video] == video_ids and scene.audio == ()
        audio = deepcopy(value)
        audio["materials"] = {"audios": [{"id": "v", "type": "audio", "path": "fixture.wav"}]}
        audio["tracks"][0]["type"] = "audio"
        with patch("jypreview.media.probe", return_value=dict(PROBE, codec="pcm_s16le", audio_codec="pcm_s16le", frame_rate=None)):
            audio_model = build(audio, config)
        assert not audio_model.tracks[0].clips[0].placeholder
        audio_scene = evaluate(audio_model, 0)
        assert audio_scene.video == () and audio_scene.audio[0].volume == 1.5

        for field, damaged, expected_range, note in (
            ("target_timerange", {"start": -20, "duration": 100}, TimeRange(0, 80), "target_range_negative"),
            ("target_timerange", {"start": 20, "duration": -100}, TimeRange(20, 0), "target_range_negative"),
            ("target_timerange", {"start": 20, "duration": "invalid"}, TimeRange(20, 0), "target_range_invalid"),
            ("source_timerange", {"start": -20, "duration": 100}, TimeRange(0, 80), "source_range_negative"),
            ("source_timerange", {"start": 20, "duration": 0}, TimeRange(20, 0), "source_range_empty"),
        ):
            changed = deepcopy(value)
            changed["tracks"][0]["segments"][0][field] = damaged
            malformed = build(changed, config).tracks[0].clips[0]
            assert malformed.placeholder and malformed.render_index == 9 and note in malformed.warnings
            assert getattr(malformed, "timeline_range" if field == "target_timerange" else "source_range") == expected_range
        for material_id in ("missing", ""):
            changed = deepcopy(value)
            changed["tracks"][0]["segments"][0]["material_id"] = material_id
            missing_model = build(changed, config)
            missing = evaluate(missing_model, 0).video[0]
            assert missing.clip.placeholder and missing.render_index == 9
            assert missing.clip.timeline_range == TimeRange(0, 1_000_000)
            assert "material_missing" in missing.warnings
        empty_path = deepcopy(value)
        empty_path["materials"]["videos"][0]["path"] = ""
        missing_path = evaluate(build(empty_path, config), 0).video[0]
        assert missing_path.clip.placeholder and "media_missing" in missing_path.warnings
        assert missing_path.render_index == 9 and missing_path.clip.timeline_range == clip.timeline_range
        invalid_refs = deepcopy(value)
        invalid_refs["tracks"][0]["segments"][0]["extra_material_refs"] = 5
        damaged_clip = build(invalid_refs, config).tracks[0].clips[0]
        assert damaged_clip.placeholder and "clip_invalid" in damaged_clip.warnings
        assert damaged_clip.timeline_range == clip.timeline_range and damaged_clip.render_index == 9
        for located, probe, note in (
            (dict(LOCATED, exists=False, path=None), PROBE, "media_missing"),
            (LOCATED, {"error": "decoder_error"}, "media_undecodable"),
        ):
            with patch("jypreview.media.resolve", return_value=located), patch("jypreview.media.probe", return_value=probe):
                broken = evaluate(build(value, config), 0).video[0]
            assert broken.clip.placeholder and broken.render_index == 9 and note in broken.warnings
            assert broken.clip.timeline_range == TimeRange(0, 1_000_000)

        text = deepcopy(value)
        text["materials"] = {"texts": [{"id": "v", "type": "text", "font_size": 10,
                                         "content": '{"text":"hello","styles":[{"range":[0,5],"size":10,"bold":true,"fill":{"content":{"solid":{"color":[1,0,0]}}}}]}',
                                         "global_alpha": 0.5}]}
        text["tracks"][0]["type"] = "text"
        text_clip = build(text, config).tracks[0].clips[0]
        assert not text_clip.placeholder and text_clip.text_payload.text == "hello"
        assert text_clip.text_payload.font_size == 120 and text_clip.text_payload.font_family == fonts.SYSTEM_STACK
        assert text_clip.text_payload.font_path == ""
        assert text_clip.text_payload.color == "#ff0000"
        assert text_clip.text_payload.box == (1152, 648, 312, 122.4)
        assert dict(text_clip.text_payload.style)["runs.0.text"] == "hello"
        assert dict(text_clip.text_payload.style)["runs.0.bold"] is True
        assert text_clip.opacity == 0.2 and text_clip.blend_mode == "multiply"

        curve = deepcopy(value)
        curve_segment = curve["tracks"][0]["segments"][0]
        curve_segment.update(speed_curve={"nodes": []}, source_timerange={"start": 2_000_000, "duration": 1_500_000})
        averaged = build(curve, config).tracks[0].clips[0]
        assert averaged.time_mapping == TimeMapping(3, 2, "reverse", "average_curve")
        assert not averaged.placeholder and "speed_curve_approximated" in averaged.warnings
        assert averaged.timeline_range == TimeRange(0, 1_000_000)
        assert evaluate(build(curve, config), 500_000).video[0].source_us == 2_749_999
        curve_segment.pop("source_timerange")
        unreadable = build(curve, config).tracks[0].clips[0]
        assert unreadable.placeholder and "speed_curve_unreadable" in unreadable.warnings
        half = deepcopy(value)
        half["fps"] = 1_000_000
        half["tracks"][0]["segments"][0].update(speed=0.5, reverse=False)
        half_model = build(half, config)
        assert half_model.tracks[0].clips[0].time_mapping == TimeMapping(1, 2)
        assert evaluate(half_model, 3).video[0].source_us == 2_000_001

        unsupported = deepcopy(value)
        unsupported["materials"]["video_effects"] = [{"id": "fx", "type": "unknown"}]
        unsupported["materials"]["material_animations"] = [{"id": "anim", "animations": [{"start": 100_000, "duration": 200_000}]}]
        unsupported["tracks"][0]["segments"][0]["extra_material_refs"] = ["fx", "anim"]
        unsupported["tracks"].append({"id": "fx-track", "type": "effect", "segments": [
            dict(value["tracks"][0]["segments"][0], id="fx-clip", material_id="fx")]})
        unsupported_model = build(unsupported, config)
        fx_clip, label_clip = unsupported_model.tracks[0].clips[0], unsupported_model.tracks[1].clips[0]
        assert fx_clip.visible and not fx_clip.placeholder and not fx_clip.effects[0].supported
        assert fx_clip.animations[0].window == TimeRange(100_000, 200_000)
        assert "effect_unsupported" in fx_clip.warnings and "animation_unsupported" in fx_clip.warnings
        assert not label_clip.visible and label_clip.timeline_range == clip.timeline_range
        assert [i.clip_id for i in evaluate(unsupported_model, 0).video] == ["clip"]

        child = deepcopy(value)
        child["tracks"][0]["segments"][0]["id"] = "child"
        nested = deepcopy(value)
        nested["materials"]["drafts"] = [{"id": "d", "draft": child}]
        nested["tracks"][0]["segments"] = [dict(value["tracks"][0]["segments"][0], id=f"parent{n}", material_id="d") for n in (1, 2)]
        nested_model = build(nested, config)
        parents = nested_model.tracks[0].clips
        assert [p.nested.tracks[0].clips[0].id for p in parents] == ["parent1/child", "parent2/child"]
        assert [p.nested.tracks[0].id for p in parents] == ["parent1/track", "parent2/track"]
        assert [p.nested.id for p in parents] == ["parent1/timeline", "parent2/timeline"]
        recursive = deepcopy(value)
        recursive["materials"]["drafts"] = [{"id": "d", "draft": recursive}]
        recursive["tracks"][0]["segments"][0]["material_id"] = "d"
        deep = build(recursive, config).tracks[0].clips[0]
        for _ in range(config.max_nest_depth):
            assert deep.nested is not None and not deep.placeholder
            deep = deep.nested.tracks[0].clips[0]
        assert deep.nested is None and deep.placeholder and "max_nest_depth" in deep.warnings
        assert deep.timeline_range == TimeRange(0, 1_000_000) and deep.render_index == 9

        transition = deepcopy(value)
        transition["materials"]["transitions"] = [{"id": "xf", "type": "transition", "name": "叠化", "duration": 400_000}]
        out = transition["tracks"][0]["segments"][0]
        out.update(extra_material_refs=["xf"], speed=1, reverse=False,
                   source_timerange={"start": 2_000_000, "duration": 1_000_000})
        transition["tracks"][0]["segments"].append(dict(out, id="next", extra_material_refs=[],
            target_timerange={"start": 1_000_000, "duration": 1_000_000},
            source_timerange={"start": 5_000_000, "duration": 1_000_000}))
        transitioned = build(transition, config)
        xf = transitioned.transitions[0]
        assert (xf.kind, xf.window, xf.duration_us, xf.from_clip_id, xf.to_clip_id) == (
            "crossfade", TimeRange(800_000, 400_000), 400_000, "clip", "next")
        handles = evaluate(transitioned, 900_000)
        assert [i.source_us for i in handles.video] == [2_900_000, 4_900_000]
        assert "source_time_clamped" not in handles.warnings and "transition_handle_clamped" not in handles.warnings
        transition["materials"]["videos"][0]["available_range"] = {"start": 2_000_000, "duration": 1_000_000}
        missing_handle = evaluate(build(transition, config), 1_000_000)
        assert missing_handle.video[0].source_us == 2_999_999
        assert "transition_handle_clamped" in missing_handle.warnings
        fade = deepcopy(value)
        fade["materials"]["audio_fades"] = [{"id": "af", "fade_in_duration": 200_000, "fade_out_duration": 300_000}]
        fade["tracks"][0]["segments"][0]["extra_material_refs"] = ["af"]
        assert [(fx.kind, fx.window) for fx in build(fade, config).tracks[0].clips[0].effects] == [
            ("audio_fade_in", TimeRange(0, 200_000)), ("audio_fade_out", TimeRange(700_000, 300_000))]


def parity_and_cache_assertions():
    config, value = fixture()
    a = dict(value["tracks"][0]["segments"][0], id="a", reverse=False, render_index=7,
             target_timerange={"start": 0, "duration": 600_000},
             source_timerange={"start": 2_000_000, "duration": 1_200_000})
    b = dict(a, id="b", speed=1, target_timerange={"start": 600_000, "duration": 1_000_000},
             source_timerange={"start": 4_000_000, "duration": 1_000_000})
    c = dict(a, id="c", speed=1, target_timerange={"start": 0, "duration": 2_000_000},
             source_timerange={"start": 6_000_000, "duration": 2_000_000})
    value["tracks"] = [{"id": "A", "type": "video", "segments": [a, b]},
                       {"id": "B", "type": "video", "segments": [c]}]
    with patch("jypreview.media.resolve", return_value=LOCATED), patch("jypreview.media.probe", return_value=PROBE):
        content = TimelineContent.build(value)
        model = build(value, config)
        for requested, expected_ids in ((0, ["a", "c"]), (333_335, ["a", "c"]),
                                       (600_000, ["b", "c"]), (1_000_000, ["b", "c"]),
                                       (1_900_000, ["c"])):
            scene = evaluate(model, requested)
            legacy = framedesc.build_frame(content, scene.sample_us, config, draft_root=TEMP, did="draft")
            assert [i.clip_id for i in scene.video] == expected_ids
            assert [(i.clip_id, i.track_id, i.render_index) for i in scene.video] == [
                (layer["layer_id"], layer["track"]["id"], layer["z"]["global"]) for layer in legacy["layers"]]
            assert [i.source_us for i in scene.video] == [layer["time"]["source_time_us"] for layer in legacy["layers"]]
        # These corrected cases have independent expectations, outside legacy parity.
        assert TimeMapping(2, direction="reverse").source_us(250_000, TimeRange(2_000_000, 1_000_000)) == 2_499_999
        assert timing.source_time_us(250_000, 2_000_000, 2, True, 500_000, 1_000_000) == 2_500_000
        assert TimeMapping(1, 2).source_us(3, TimeRange(2_000_000, 1_000_000)) == 2_000_001

        reads = []
        def load_content(root, tid, probe, *, cache):
            reads.append((root, tid))
            return dict(value, id=tid.upper()), {"encoding": "plain"}
        session = PreviewSession.__new__(PreviewSession)
        session.config, session.registry, session.font_index, session.catalog = config, None, None, None
        session.manager = SimpleNamespace(content=load_content, mirror_drift=lambda probe: {"drift": False})
        probe = {"layout": "fixture", "timelines": [{"id": "T1", "name": "one"}, {"id": "T2", "name": "two"}]}
        view = DraftView(session, {"did": "draft", "path": str(TEMP), "name": "fixture"}, None, probe)
        before = view.frame("T1", 333_335)
        cached = view.timeline_model("T1")
        assert cached is view.timeline_model("t1") is view.timeline_model("T1")
        second = view.timeline_model("T2")
        assert second is not cached and second.id == "T2" and cached.id == "T1"
        assert reads == [(TEMP, "T1"), (TEMP, "T2")]
        assert view.frame("T1", 333_335) == before
        assert before["layers"][0]["time"]["local_us"] == 333_335
        assert evaluate(cached, 333_335).sample_us == 333_334
        other = DraftView(session, {"did": "another", "path": str(TEMP / "other"), "name": "other"}, None, probe)
        assert other.timeline_model("T1") is not cached
        try:
            view.timeline_model("absent")
        except TimelineNotFound:
            pass
        else:
            raise AssertionError("unknown timeline accepted")


def rejects(call):
    try:
        call()
    except (TypeError, ValueError):
        return
    raise AssertionError("invalid value accepted")


def run():
    rate = FrameRate(30_000, 1_001)
    assert rate.quantize(1_000_000) == (29, 967_634)
    assert rate.quantize(rate.sample_us(29)) == (29, 967_634)
    rate30 = FrameRate(30)
    assert rate30.sample_us(1) == 33_334
    assert rate30.quantize(33_334) == (1, 33_334)
    assert rate30.first_frame_at_or_after(33_334) == 1
    assert rate30.first_frame_at_or_after(33_335) == 2
    assert rate30.frame_count(0) == 0
    assert rate30.frame_count(33_334) == 1
    assert rate30.frame_count(33_335) == 2
    assert FrameRate(60, 2) == rate30
    for fps in (FrameRate(24), FrameRate(25), rate30, FrameRate(60),
                FrameRate(24_000, 1_001), rate, FrameRate(60_000, 1_001),
                FrameRate(1_000_000)):
        for frame in (0, 1, 2, 29, 59, 1000, 100_000, 10**12):
            sample = fps.sample_us(frame)
            assert fps.quantize(sample) == (frame, sample)
            assert fps.first_frame_at_or_after(sample) == frame
            assert fps.frame_count(sample) == frame
            assert fps.first_frame_at_or_after(sample + 1) == frame + 1
        for time in (0, 1, 33_333, 33_334, 33_335, 1_000_000, 10**15):
            first = fps.quantize(time)
            assert fps.quantize(first[1]) == first
            assert first[1] <= time
    for args in ((0,), (-1,), (30, 0), (30, -1), (1_000_001,), (30.0,), (True,)):
        rejects(lambda args=args: FrameRate(*args))
    for fn in (rate30.quantize, rate30.sample_us, rate30.first_frame_at_or_after,
               rate30.frame_count):
        for bad in (-1, 1.2, True):
            rejects(lambda fn=fn, bad=bad: fn(bad))
    for args in ((-1, 1), (1, -1), (0.5, 1)):
        rejects(lambda args=args: TimeRange(*args))
    assert TimeRange(5, 0).end_us == 5
    assert not TimeRange(5, 0).contains(5)
    assert TimeRange(5, 2).contains(5) and not TimeRange(5, 2).contains(7)
    source = TimeRange(2_000_000, 1_000_000)
    forward = TimeMapping(2)
    reverse = TimeMapping(2, direction="reverse")
    assert forward.source_us(250_000, source) == 2_500_000
    assert reverse.source_us(250_000, source) == 2_499_999
    assert TimeMapping(1, 2).source_us(3, source) == 2_000_001
    for mapping, expected in ((TimeMapping(1, 2), 2_125_000),
                              (TimeMapping(), 2_250_000), (forward, 2_500_000)):
        assert mapping.source_us(250_000, source) == expected
        assert replace(mapping, direction="reverse").source_us(250_000, source) == 4_999_999 - expected
        assert mapping.source_us(10_000_000, source) == 2_999_999
        assert replace(mapping, direction="reverse").source_us(10_000_000, source) == 2_000_000
    assert forward.source_us(0, TimeRange(3, 0)) is None
    for call in (lambda: TimeMapping(0), lambda: TimeMapping(1, 0),
                 lambda: TimeMapping(direction="sideways"),
                 lambda: forward.source_us(-1, source), lambda: AudioSpec(volume=-1),
                 lambda: AudioSpec(volume=float("nan"))):
        rejects(call)

    media = MediaRef("media", "clip.mp4", True, TimeRange(0, 10_000_000),
                     duration_us=10_000_000, frame_rate=FrameRate(24), has_audio=True)
    clip = Clip("a", "video", TimeRange(0, 1_000_000), source,
                media_ref=media, time_mapping=forward, audio=AudioSpec(volume=1.5))
    model = TimelineModel("timeline", 2_000_000, tracks=(Track("track", "video", (clip,)),))
    scene = evaluate(model, 250_000)
    assert (scene.frame_index, scene.sample_us) == (7, 233_334)
    assert scene.video[0].source_us == 2_466_668
    assert scene.audio[0].volume == 1.5
    assert scene.video[0].track_id == "track" and scene.video[0].clip_id == "a"
    assert scene == evaluate(model, scene.sample_us) == evaluate(model, 250_000)
    samples = (0, 250_000, 666_667, 1_000_000, 333_334)
    expected_scenes = {time: evaluate(model, time) for time in samples}
    assert all(evaluate(model, time) == expected_scenes[time] for time in reversed(samples))
    for time in (model.duration_us, model.duration_us + 1, 10**12):
        ended = evaluate(model, time)
        assert ended.state == "ended" and ended.video == ended.audio == ()
    assert evaluate(TimelineModel("empty", 0), 0).state == "ended"
    rejects(lambda: evaluate(model, -1))
    rejects(lambda: TimelineModel("bad", -1))
    for value in (rate30, source, forward, media, clip.audio, clip.transform,
                  TextPayload("hello"), EffectSpec("fx", "fade"), clip,
                  model.tracks[0], Transition("fade", "fade", TimeRange(0, 1)),
                  model, scene.video[0], scene):
        try:
            value.extra = 1
        except FrozenInstanceError:
            pass
        else:
            raise AssertionError(f"mutable model value: {type(value).__name__}")

    tiny = replace(clip, id="tiny", timeline_range=TimeRange(33_334, 1))
    unsampled = replace(clip, id="unsampled", timeline_range=TimeRange(33_335, 33_332))
    boundaries = replace(model, tracks=(Track("t", "video", (tiny, unsampled)),))
    assert [item.clip_id for item in evaluate(boundaries, 33_334).video] == ["tiny"]
    assert [item.clip_id for item in evaluate(boundaries, 33_335).video] == ["tiny"]
    assert evaluate(boundaries, 66_667).video == ()
    before = replace(clip, timeline_range=TimeRange(0, 33_335), render_index=0)
    after = replace(clip, id="b", timeline_range=TimeRange(33_335, 1_000_000), render_index=2)
    middle = replace(clip, id="middle", render_index=1)
    seams = replace(model, tracks=(Track("A", "video", (before, after)),
                                  Track("B", "video", (middle,))))
    assert [i.clip_id for i in evaluate(seams, 33_334).video] == ["a", "middle"]
    assert [i.clip_id for i in evaluate(seams, 66_667).video] == ["middle", "b"]
    ties = replace(model, tracks=(Track("A", "video", (clip, replace(clip, id="b")), order=99),
                                 Track("B", "video", (replace(clip, id="c"),), order=-5)))
    assert [i.clip_id for i in evaluate(ties, 0).video] == ["a", "b", "c"]
    assert [(i.original_track_index, i.original_segment_index) for i in evaluate(ties, 0).video] == [(0, 0), (0, 1), (1, 0)]
    assert evaluate(replace(model, tracks=(replace(model.tracks[0], enabled=False),)), 0).video == ()
    hidden = replace(model, tracks=(Track("t", "video", (replace(clip, visible=False),)),))
    assert evaluate(hidden, 0).video == evaluate(hidden, 0).audio == ()
    muted = evaluate(replace(model, tracks=(replace(model.tracks[0], muted=True),)), 0)
    assert len(muted.video) == 1 and muted.audio == ()
    silent = evaluate(replace(model, tracks=(Track("t", "video", (replace(clip, audio=AudioSpec(False)),)),)), 0)
    assert len(silent.video) == 1 and silent.audio == ()
    audio_only = evaluate(replace(model, tracks=(Track("t", "audio", (replace(clip, kind="audio"),)),)), 0)
    assert audio_only.video == () and len(audio_only.audio) == 1
    clamped = evaluate(replace(model, tracks=(Track("t", "video", (replace(clip, source_range=TimeRange(100, 2)),)),)), 250_000)
    assert clamped.video[0].source_us == 101
    assert "source_time_clamped" in clamped.video[0].warnings
    assert "source_time_clamped" in clamped.warnings
    unavailable = replace(clip, media_ref=replace(media, available_range=TimeRange(0, 100)))
    no_source = evaluate(replace(model, tracks=(Track("t", "video", (unavailable,)),)), 0)
    assert no_source.video[0].source_us is None
    assert "source_range_unavailable" in no_source.warnings
    partially_available = replace(clip, media_ref=replace(media, available_range=TimeRange(2_000_050, 100)))
    partial = evaluate(replace(model, tracks=(Track("t", "video", (partially_available,)),)), 0)
    assert partial.video[0].source_us == 2_000_050
    assert "source_time_clamped" in partial.warnings
    defaults = replace(model, tracks=(Track("text", "text", (replace(clip, id="text", kind="text"),)),
                                     Track("video", "video", (replace(clip, id="track-z"),), render_index=100),
                                     Track("other", "video", (replace(clip, id="clip-z", render_index=99),), render_index=101)))
    assert [(i.clip_id, i.render_index) for i in evaluate(defaults, 0).video] == [("clip-z", 99), ("track-z", 100), ("text", 14000)]
    assert evaluate(replace(model, duration_us=33_334), 33_334).video == ()
    assert len(evaluate(replace(model, duration_us=33_335), 33_334).video) == 1
    still = replace(clip, kind="image", time_mapping=reverse)
    assert evaluate(replace(model, tracks=(Track("t", "image", (still,)),)), 250_000).video[0].source_us == source.start_us
    missing = replace(clip, id="missing", media_ref=replace(media, exists=False), placeholder=True,
                      warnings=("media_missing:missing",))
    missing_scene = evaluate(replace(model, tracks=(Track("t", "video", (missing,)),)), 0)
    assert missing_scene.video[0].clip.placeholder
    assert "media_missing:missing" in missing_scene.warnings

    outgoing = replace(clip, id="out", timeline_range=TimeRange(0, 1_000_000),
                       source_range=TimeRange(2_000_000, 1_000_000), time_mapping=TimeMapping())
    incoming = replace(clip, id="in", timeline_range=TimeRange(1_000_000, 1_000_000),
                       source_range=TimeRange(5_000_000, 1_000_000), time_mapping=TimeMapping())
    crossfade = Transition("xf", "crossfade", TimeRange(900_000, 200_000), "out", "in")
    crossed = replace(model, tracks=(Track("t", "video", (outgoing, incoming)),), transitions=(crossfade,))
    left = evaluate(crossed, 900_000)
    assert [i.clip_id for i in left.video] == ["out", "in"]
    assert [i.source_us for i in left.video] == [2_900_000, 4_900_000]
    right = evaluate(crossed, 1_000_000)
    assert [i.source_us for i in right.video] == [3_000_000, 5_000_000]
    assert right.transitions == (crossfade,)
    assert crossed.tracks[0].clips[0].timeline_range == TimeRange(0, 1_000_000)
    short = replace(outgoing, media_ref=replace(media, available_range=outgoing.source_range))
    clamped_transition = evaluate(replace(crossed, tracks=(Track("t", "video", (short, incoming)),)), 1_000_000)
    assert clamped_transition.video[0].source_us == 2_999_999
    assert "transition_handle_clamped" in clamped_transition.warnings
    assert [i.clip_id for i in evaluate(crossed, 1_100_000).video] == ["in"]
    assert evaluate(replace(crossed, tracks=(replace(crossed.tracks[0], enabled=False),)), 1_000_000).video == ()
    fade = Transition("fade", "fade", TimeRange(0, 1_000_000), to_clip_id="a")
    faded = evaluate(replace(model, transitions=(fade,)), 500_000)
    assert faded.video[0].opacity == 0.5 and faded.audio[0].volume == 0.75
    assert faded.video[0].transform == clip.transform
    supplied_warnings = ["test"]
    immutable_scene = ExpectedScene("active", 0, 0, warnings=supplied_warnings)
    immutable_item = replace(scene.video[0], warnings=supplied_warnings)
    supplied_warnings.append("mutation")
    assert immutable_scene.warnings == immutable_item.warnings == ("test",)

    adapter_assertions()
    parity_and_cache_assertions()
    print("ok: timeline model, adapter, and evaluator regressions")


if __name__ == "__main__":
    run()
