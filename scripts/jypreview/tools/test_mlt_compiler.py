"""Synthetic pixel/PCM integration assertions for the model-only MLT compiler."""

from array import array
from contextlib import contextmanager
import ctypes
from dataclasses import FrozenInstanceError, replace
import os
from pathlib import Path
import struct
import wave

from jypreview.mlt_backend import MltCompiler, RenderedFrame
from jypreview.model.timeline import (AudioSpec, Clip, EffectSpec, FrameRate, MediaRef,
                                     TextPayload, TimelineModel, TimeMapping, TimeRange,
                                     Track, Transform, Transition)
from jypreview.tools.test_mlt_runtime import loaded_audio_api, pcm, write_audio_markers

W, H = 300, 180
FPS = FrameRate(30)
ROOT = Path(__file__).resolve().parents[3] / "temp" / "mlt-compiler"


@contextmanager
def corrupt_decode_log():
    """Isolate only the deliberately corrupt fixture's expected native diagnostics."""
    path = ROOT / "corrupt-decode.stderr"
    saved = os.dup(2)
    try:
        with path.open("wb") as output:
            os.dup2(output.fileno(), 2)
            try:
                yield
            finally:
                os.dup2(saved, 2)
    finally:
        os.close(saved)
    lines = path.read_text().splitlines()
    assert lines and all("moov atom not found" in line or "misdetection possible" in line
                         for line in lines), lines


def still(name, rgb):
    path = ROOT / f"{name}.bmp"
    row = bytes((rgb[2], rgb[1], rgb[0])) * W
    data = row * H
    path.write_bytes(b"BM" + struct.pack("<IHHI", 54 + len(data), 0, 0, 54)
                     + struct.pack("<IiiHHIIiiII", 40, W, H, 1, 24, 0, len(data), 0, 0, 0, 0)
                     + data)
    return MediaRef(name, str(path), True, width=W, height=H, has_audio=False)


def picture(name, media, start=0, duration=1_000_000, z=0, **kw):
    return Clip(name, "image", TimeRange(start, duration), media_ref=media,
                render_index=z, **kw)


def model(*tracks, duration=1_000_000, transitions=(), rate=FPS):
    return TimelineModel("synthetic", duration, rate, (W, H), tracks, transitions)


def pixels(compiled, position):
    import mlt7 as mlt
    assert 0 <= position < compiled.duration_frames
    assert compiled.tractor.seek(position) == 0
    frame = compiled.tractor.get_frame()
    assert frame.is_valid() and frame.get_position() == position
    data = bytes(frame.get_image(mlt.mlt_image_rgba, W, H))
    assert len(data) == W * H * 4
    return data


def pixel(data, x=W//2, y=H//2):
    i = (y * W + x) * 4
    return tuple(data[i:i+4])


def color(compiled, position, expected, x=W//2, y=H//2):
    actual = pixel(pixels(compiled, position), x, y)
    assert all(abs(a-b) <= 3 for a, b in zip(actual[:3], expected)), (position, actual, expected)


def review_regressions(compiler, video, marker_media, mlt, get_audio):
    def marker_read(graph, position, expected):
        graph.tractor.seek(position)
        frame = graph.tractor.get_frame()
        pointer = ctypes.c_void_p()
        rate = graph.model.frame_rate
        count = round(48000 * rate.den / rate.num)
        fmt, frequency, channels, samples = (ctypes.c_int(v) for v in (mlt.mlt_audio_s16,48000,2,count))
        assert get_audio(int(frame.get_frame()),ctypes.byref(pointer),ctypes.byref(fmt),
                         ctypes.byref(frequency),ctypes.byref(channels),ctypes.byref(samples)) == 0
        assert samples.value == count and not frame.get_int("test_audio")
        values = array("h",ctypes.string_at(pointer,samples.value*channels.value*2))
        assert max(abs(v-expected) for v in values) <= 2, (position,expected,min(values),max(values))

    marker = Clip("marker","audio",TimeRange(0,300_000),TimeRange(0,300_000),marker_media)
    def gap_and_lazy_history():
        graph = compiler.compile(model(Track("t","audio",(marker,))))
        marker_read(graph,3,1300)
        pixels(graph,15)  # Inactive lane must retain the last consumed source position.
        assert set(graph.tractor._last_audio_positions.values()) == {3}
        marker_read(graph,7,1700)
        marker_read(graph,3,1300)
        pixels(graph,6)   # Pulling an image must not claim that frame 6 PCM was consumed.
        assert set(graph.tractor._last_audio_positions.values()) == {3}
        marker_read(graph,7,1700)
        graph.close()

    child = model(Track("audio","audio",(replace(marker,timeline_range=TimeRange(0,1_000_000),
                                              source_range=TimeRange(0,1_000_000)),)))
    compound = Clip("child","compound",TimeRange(0,1_000_000),TimeRange(0,1_000_000),nested=child)
    def nested_discontinuities():
        for mapping in (TimeMapping(),TimeMapping(2)):
            graph = compiler.compile(model(Track("compound","compound",(replace(compound,time_mapping=mapping),))))
            for pos in (0,1,3,7,2):
                wanted = FPS.quantize(mapping.source_us(FPS.sample_us(pos),compound.source_range))[0]
                marker_read(graph,pos,1000+100*wanted)
            graph.close()

    def nested_frame_rates():
        graph = compiler.compile(model(Track("compound","compound",(compound,)),rate=FrameRate(24)))
        marker_read(graph,12,2500)  # Parent 12 at 24 FPS is child 15 at 30 FPS.
        marker_read(graph,3,1300)
        graph.close()

    def unavailable_intersection():
        missing = Clip("disjoint","video",TimeRange(0,1_000_000),TimeRange(0,500_000),
                       replace(video,available_range=TimeRange(1_000_000,500_000)))
        graph = compiler.compile(model(Track("video","video",(missing,))))
        assert "source_range_unavailable" in graph.warnings
        color(graph,0,(224,64,160))
        graph.tractor.seek(0); frame=graph.tractor.get_frame()
        pointer=ctypes.c_void_p(); values=[ctypes.c_int(v) for v in (mlt.mlt_audio_s16,48000,2,1600)]
        assert get_audio(int(frame.get_frame()),ctypes.byref(pointer),*(ctypes.byref(v) for v in values)) == 0
        assert not any(array("h",ctypes.string_at(pointer,values[2].value*values[3].value*2)))
        graph.close()

    failures=[]
    for check in (gap_and_lazy_history,nested_discontinuities,nested_frame_rates,unavailable_intersection):
        try: check()
        except (AssertionError,RuntimeError) as exc: failures.append(f"{check.__name__}: {exc}")
    assert not failures, "\n".join(failures)


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    compiler = MltCompiler()
    assert compiler.available()[0], compiler.available()
    red, green, blue = (still(n, c) for n, c in (
        ("red", (255, 0, 0)), ("green", (0, 255, 0)), ("blue", (0, 0, 255))))
    # A's adjacent z crossing must cross B's continuous lane at exactly frame 15.
    graph = compiler.compile(model(
        Track("A", "video", (picture("a0", red, duration=500_000, z=0),
                              picture("a2", red, start=500_000, duration=500_000, z=2))),
        Track("B", "video", (picture("b", green, z=1),))))
    assert graph.duration_frames == 30 and graph.tractor is not None
    assert graph.tractor.get_out() == 29 and graph.tractor.get_length() == 30
    color(graph, 14, (0, 255, 0)); color(graph, 15, (255, 0, 0))
    graph.close(); graph.close()
    assert graph.tractor is None
    # Stable equal-z ties and same-track overlapping clips have separate lanes.
    graph = compiler.compile(model(Track("A", "video", (picture("a", red), picture("b", green))),
                                   Track("B", "video", (picture("c", blue, start=500_000, duration=500_000),))))
    color(graph, 0, (0, 255, 0)); color(graph, 15, (0, 0, 255)); graph.close()
    # Three bands, opacity, crop, flips, rotation, and anchor use actual RGBA.
    bands = tuple(picture(str(i), media, transform=Transform(50+100*i, 90, 100, 180))
                  for i, media in enumerate((red, green, blue)))
    graph = compiler.compile(model(Track("bands", "video", bands)))
    for x, expected in ((50,(255,0,0)), (150,(0,255,0)), (250,(0,0,255))):
        color(graph, 0, expected, x)
    graph.close()
    graph = compiler.compile(model(Track("alpha", "video", (picture("red", red), picture("blue", blue, opacity=.5)))))
    color(graph, 0, (127,0,128)); graph.close()
    graph = compiler.compile(model(Track("crop", "image", (picture("r",red,crop=(.25,0,.75,1)),))))
    color(graph,0,(0,0,0),25); color(graph,0,(255,0,0),150); color(graph,0,(0,0,0),275)
    graph.close()
    half = ROOT / "halves.bmp"
    header = (ROOT / "red.bmp").read_bytes()[:54]
    half.write_bytes(header + (bytes((0,0,255))*(W//2) + bytes((255,0,0))*(W//2))*H)
    halves = replace(red,id="halves",path=str(half))
    graph = compiler.compile(model(Track("flip","image",(picture("h",halves,
                        transform=Transform(W/2,H/2,W,H,flip_x=True)),))))
    color(graph,0,(0,0,255),50); color(graph,0,(255,0,0),250); graph.close()
    graph = compiler.compile(model(Track("rotation","image",(picture("r",red,
                        transform=Transform(150,90,120,30,rotation=90)),))))
    color(graph,0,(255,0,0),150,45); color(graph,0,(0,0,0),100,90); graph.close()
    graph = compiler.compile(model(Track("anchor","image",(picture("r",red,
                        transform=Transform(30,30,100,60,anchor_x=0,anchor_y=0)),))))
    color(graph,0,(255,0,0),40,40); color(graph,0,(0,0,0),20,40); graph.close()
    graph = compiler.compile(model(Track("blend","image",(picture("r",red),
                              picture("b",blue,blend_mode="add")))))
    color(graph,0,(255,0,255)); graph.close()
    # Boundary examples use canonical sample intervals, including a zero-frame clip.
    for rate, duration, count in ((FPS,33334,1),(FPS,33335,2),(FrameRate(30000,1001),967634,29),
                                   (FrameRate(30000,1001),967635,30)):
        graph = compiler.compile(model(Track("t", "image", (picture("r", red, start=33334, duration=1),)),
                                       duration=duration, rate=rate))
        assert graph.duration_frames == count
        color(graph, 0, (0,0,0))
        if rate == FPS and count == 2: color(graph, 1, (255,0,0))
        graph.close()
    graph = compiler.compile(model(duration=0))
    assert graph.duration_frames == 0 and graph.tractor is None
    graph.close()
    # Basic text and missing/undecodable clips preserve their visible intervals.
    missing = Clip("missing", "video", TimeRange(500_000,500_000), placeholder=True)
    broken_path = ROOT / "broken.mp4"; broken_path.write_bytes(b"not media")
    broken = replace(missing, id="broken", placeholder=False,
                     source_range=TimeRange(0,500_000),
                     media_ref=MediaRef("bad", str(broken_path), True))
    title = Clip("text", "text", TimeRange(0,500_000), text_payload=TextPayload("MLT", font_size=40))
    graph = compiler.compile(model(Track("title","text",(title,))))
    rendered = pixels(graph,0)
    lit = [x for y in range(H) for x in range(W) if rendered[(y*W+x)*4] > 128]
    assert lit and max(lit)-min(lit) < 120, "Pango must preserve the requested basic font size"
    graph.close()
    for bad in (missing, broken):
        if bad is broken:
            with corrupt_decode_log():
                graph = compiler.compile(model(Track("t", "video", (title,bad))))
        else:
            graph = compiler.compile(model(Track("t", "video", (title,bad))))
        assert any(pixels(graph, 0)[0::4]) and pixel(pixels(graph,15))[:3] != (0,0,0)
        assert any("placeholder" in w for w in graph.warnings)
        graph.close()
    # Independent native-source decode is the speed and source-FPS oracle.
    import mlt7 as mlt
    video = MediaRef("video", os.environ["JY_PREVIEW_TEST_VIDEO"], True,
                     TimeRange(0,4_000_000),4_000_000,FrameRate(30),True,W,H)
    for rate in (FPS, FrameRate(24)):
        for mapping in (TimeMapping(),TimeMapping(1,2),TimeMapping(2),TimeMapping(direction="reverse")):
            clip = Clip("video", "video",TimeRange(0,1_000_000),TimeRange(500_000,1_000_000),video,
                        mapping, AudioSpec(False))
            graph = compiler.compile(model(Track("t","video",(clip,)),rate=rate))
            native_profile = mlt.Profile(); native_profile.set_width(W); native_profile.set_height(H)
            native_profile.set_frame_rate(30,1); native_profile.set_sample_aspect(1,1)
            native_profile.set_display_aspect(5,3); native_profile.set_progressive(1); native_profile.set_explicit(1)
            reference = mlt.Producer(native_profile,"loader",video.path)
            # Match the compositor's RGBA normalization, not the loader's direct scaler.
            oracle = mlt.Tractor(native_profile)
            background = mlt.Producer(native_profile,"color","#000000")
            oracle.set_track(background,0); oracle.set_track(reference,1)
            blend = mlt.Transition(native_profile,"frei0r.cairoaffineblend")
            for key,value in {"0":.5,"1":.5,"2":.2,"3":.2,"7":.5,"8":.5,"always_active":1}.items():
                blend.set(key,value)
            oracle.plant_transition(blend,0,1)
            for pos in (0,3,12,23):
                source_us = mapping.source_us(rate.sample_us(pos),clip.source_range)
                native_pos = video.frame_rate.quantize(source_us)[0]
                oracle.seek(native_pos)
                expected = bytes(oracle.get_frame().get_image(mlt.mlt_image_rgba,W,H))
                actual = pixels(graph,pos)
                assert actual == expected, (rate,mapping,pos,native_pos)
            graph.close()
    unknown_rate = replace(video,frame_rate=None)
    clip = Clip("unknown-rate","video",TimeRange(0,1_000_000),TimeRange(500_000,1_000_000),
                unknown_rate,audio=AudioSpec(False))
    known = compiler.compile(model(Track("t","video",(replace(clip,media_ref=video),)),rate=FrameRate(24)))
    inferred = compiler.compile(model(Track("t","video",(clip,)),rate=FrameRate(24)))
    assert pixels(inferred,12) == pixels(known,12)
    inferred.close(); known.close()
    empty_source = compiler.compile(model(Track("t","video",(replace(clip,source_range=TimeRange(0,0)),))))
    assert "source_range_empty" in empty_source.warnings
    assert pixel(pixels(empty_source,0))[:3] == (224,64,160)
    empty_source.close()
    # Audio: both lanes sum, mute/enabled is respected, gain above one survives.
    sound = ROOT / "constant.wav"
    with wave.open(str(sound),"wb") as out:
        out.setparams((2,2,48000,0,"NONE","none"))
        out.writeframes(array("h",[2000]*(2*48000*2)).tobytes())
    audio = MediaRef("pcm",str(sound),True,TimeRange(0,2_000_000),2_000_000,has_audio=True)
    a = Clip("a","audio",TimeRange(0,1_000_000),TimeRange(0,1_000_000),audio,audio=AudioSpec(volume=1.5))
    b = replace(a,id="b",audio=AudioSpec(volume=1))
    graph = compiler.compile(model(Track("a","audio",(a,)),Track("b","audio",(b,)),
                                   Track("muted","audio",(b,),muted=True),
                                   Track("disabled","audio",(b,),enabled=False),
                                   Track("off","audio",(replace(b,audio=AudioSpec(False)),))))
    library,get_audio,_ = loaded_audio_api()
    graph.tractor.seek(3); samples = pcm(graph.tractor.get_frame(),get_audio,mlt)
    assert max(abs(s-5000) for s in samples) <= 2, (min(samples),max(samples))
    graph.close()
    # Source audio follows the video source clock and sums with independent audio.
    v = Clip("v","video",TimeRange(0,1_000_000),TimeRange(500_000,1_000_000),
             video,audio=AudioSpec(volume=1.5))
    graph = compiler.compile(model(Track("video","video",(v,)),Track("audio","audio",(b,))))
    source = mlt.Producer(graph.profile,"loader",video.path)
    source.seek(18); original = pcm(source.get_frame(),get_audio,mlt)
    graph.tractor.seek(3); mixed = pcm(graph.tractor.get_frame(),get_audio,mlt)
    assert max(abs(actual-(round(sample*1.5)+2000)) for actual,sample in zip(mixed,original)) <= 3
    graph.close()
    marker_path = ROOT / "markers.wav"; write_audio_markers(marker_path)
    marker_media = replace(audio,path=str(marker_path),available_range=TimeRange(0,4_000_000),duration_us=4_000_000)
    for mapping in (TimeMapping(),TimeMapping(1,2),TimeMapping(2),TimeMapping(direction="reverse")):
        marker = replace(a,media_ref=marker_media,source_range=TimeRange(500_000,1_000_000),
                         time_mapping=mapping,audio=AudioSpec())
        graph = compiler.compile(model(Track("markers","audio",(marker,))))
        for pos in (0,1,2,3,4,5,12,23,3):
            graph.tractor.seek(pos); values = pcm(graph.tractor.get_frame(),get_audio,mlt)
            wanted = FPS.quantize(mapping.source_us(FPS.sample_us(pos),marker.source_range))[0]
            assert abs(sum(values)/len(values) - (1000+100*wanted)) <= 101, (mapping,pos,wanted,min(values),max(values))
    graph.close()
    # Fade and crossfade use the same half-open window; missing handles freeze.
    review_regressions(compiler,video,marker_media,mlt,get_audio)
    left = picture("left",red,duration=500_000)
    right = picture("right",blue,start=500_000,duration=500_000,z=1)
    cross = Transition("cross","crossfade",TimeRange(400_000,200_000),"left","right")
    graph = compiler.compile(model(Track("t","video",(left,right)),transitions=(cross,)))
    color(graph,15,(64,0,128))  # Both weights .5: normal alpha-over on the background.
    color(graph,18,(0,0,255)); graph.close()
    left = replace(clip,id="left",timeline_range=TimeRange(0,500_000),
                   source_range=TimeRange(500_000,500_000),time_mapping=TimeMapping())
    right = replace(left,id="right",timeline_range=TimeRange(500_000,500_000),
                    source_range=TimeRange(0,500_000),render_index=1)
    graph = compiler.compile(model(Track("t","video",(left,right)),transitions=(cross,)))
    assert "transition_handle_clamped" in graph.warnings
    pixels(graph,12); pixels(graph,15); graph.close()
    right = replace(right,source_range=TimeRange(1_000_000,500_000))
    graph = compiler.compile(model(Track("t","video",(left,right)),transitions=(cross,)))
    assert "transition_handle_clamped" not in graph.warnings
    pixels(graph,15); graph.close()
    fade = Transition("fade","fade",TimeRange(0,1_000_000),None,"r")
    graph = compiler.compile(model(Track("t","video",(picture("r",red),)),transitions=(fade,)))
    color(graph,0,(0,0,0)); color(graph,15,(128,0,0)); graph.close()
    inner = model(Track("t","image",(picture("r",red),)))
    compound = Clip("nested","compound",TimeRange(0,1_000_000),TimeRange(0,1_000_000),nested=inner)
    graph = compiler.compile(model(Track("t","compound",(compound,))))
    color(graph,0,(255,0,0)); color(graph,29,(255,0,0)); graph.close()
    effect = EffectSpec("unsupported","mystery",supported=False)
    graph = compiler.compile(model(Track("t","image",(picture("r",red,effects=(effect,)),))))
    color(graph,0,(255,0,0)); assert "effect_unsupported:unsupported" in graph.warnings; graph.close()
    diagnostic = Clip("diagnostic","effect",TimeRange(0,1_000_000),render_index=99,
                      effects=(effect,))
    graph = compiler.compile(model(Track("t","image",(picture("r",red),)),
                                   Track("diagnostics","effect",(diagnostic,))))
    color(graph,0,(255,0,0)); assert "effect_unsupported:diagnostic" in graph.warnings; graph.close()
    envelope = RenderedFrame("p",1,2,3,100000,W,H,b"rgba")
    try: envelope.generation = 2
    except FrozenInstanceError: pass
    else: raise AssertionError("RenderedFrame must be frozen")
    print("ok: MLT graph composition regressions")


if __name__ == "__main__":
    main()
