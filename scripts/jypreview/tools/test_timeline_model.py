"""Executable assertions for immutable timeline values and canonical evaluation."""

from dataclasses import FrozenInstanceError, replace

from jypreview.model.timeline import (
    AudioSpec, Clip, EffectSpec, ExpectedScene, FrameRate, MediaRef, SceneItem,
    TextPayload, TimeMapping, TimeRange, TimelineModel, Track, Transform,
    Transition, evaluate,
)


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

    print("ok: timeline model core and evaluator regressions")


if __name__ == "__main__":
    run()
