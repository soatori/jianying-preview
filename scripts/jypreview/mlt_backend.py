"""Compile immutable timeline values into an owned MLT graph and drive playback."""

import ctypes
import os
import queue
import threading
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from fractions import Fraction
from math import isfinite, log10
from typing import Any

from .model.content import DEFAULT_RI
from .model.layout import fit_contain
from .model.timeline import FrameRate, TimelineModel, Transform

# SDL2's default WASAPI backend faults with a native access violation when
# mlt_consumer_stop follows >=~25 s of continuous starved playback (heavy
# graphs crawling ~0.13x realtime leave the device in sustained underrun;
# reproduced 6/6, null sink clean). dsound avoids the WASAPI teardown path.
# winmm was equally AV-clean but showed intermittent ~3.8 s "audio timed
# out" start recoveries, so dsound is the default instead. setdefault keeps
# an explicit operator override authoritative — overriding back to WASAPI
# re-exposes the crash.
os.environ.setdefault("SDL_AUDIODRIVER", "dsound")


class BackendUnavailable(RuntimeError):
    """The optional native MLT runtime or required services are unavailable."""


@dataclass(frozen=True)
class RenderedFrame:
    playback_id: str
    generation: int
    seek_request_id: int
    frame_index: int
    pts_us: int
    width: int
    height: int
    rgba: bytes


@dataclass
class CompiledTimeline:
    model: TimelineModel
    profile: object
    tractor: object
    duration_frames: int
    warnings: tuple[str, ...]
    _owned: list = field(default_factory=list, repr=False)

    def close(self) -> None:
        # SWIG owns these references and exposes no close() on these services.
        self.tractor = None
        for child in self._owned:
            if isinstance(child, CompiledTimeline):
                child.close()
        self._owned.clear()
        self.profile = None


_repository = None
_tractor_class = None
_cache_purge = None
_sink_name = None
_libmlt_cache = None
_natives_configured = False
_pango_font_lock = threading.Lock()
_pango_registered_fonts: set[str] = set()
_pango_fontconfig = None


def _pango_font_family(path: str) -> tuple[str | None, bool, bool]:
    """Register a resolved font file with Pango and return its embedded family."""
    global _pango_fontconfig
    if not path or not os.path.isfile(path):
        return None, False, False
    try:
        from PIL import ImageFont
        family = ImageFont.truetype(path, 32).getname()[0]
    except (ImportError, OSError, TypeError, ValueError, AttributeError):
        return None, False, False
    key = os.path.normcase(os.path.abspath(path))
    with _pango_font_lock:
        if key in _pango_registered_fonts:
            return family, True, False
        try:
            loader = ctypes.WinDLL if os.name == "nt" else ctypes.CDLL
            library = _pango_fontconfig or loader(
                "libfontconfig-1.dll" if os.name == "nt" else "fontconfig")
            library.FcConfigGetCurrent.restype = ctypes.c_void_p
            library.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            library.FcConfigAppFontAddFile.restype = ctypes.c_int
            library.FcConfigBuildFonts.argtypes = [ctypes.c_void_p]
            library.FcConfigBuildFonts.restype = ctypes.c_int
            config = library.FcConfigGetCurrent()
            if not config or not library.FcConfigAppFontAddFile(
                    config, os.fsencode(os.path.abspath(path))) or not library.FcConfigBuildFonts(config):
                return family, False, False
            _pango_fontconfig = library
            _pango_registered_fonts.add(key)
            return family, True, True
        except (OSError, AttributeError, TypeError):
            return family, False, False

# (properties, listener_data, event_data) as MLT fires it; event_data carries the frame.
_Listener = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)


def _libmlt() -> ctypes.CDLL:
    """The already-loaded libmlt-7, for C entry points SWIG does not expose."""
    global _libmlt_cache
    if _libmlt_cache is None:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        kernel.GetModuleHandleW.restype = ctypes.c_void_p
        handle = kernel.GetModuleHandleW("libmlt-7.dll")
        if not handle:
            raise BackendUnavailable("Loaded MLT DLL is unavailable")
        _libmlt_cache = ctypes.CDLL("libmlt-7.dll", handle=handle)
    return _libmlt_cache


def _natives() -> ctypes.CDLL:
    """libmlt entry points invoked with the GIL released.

    ctypes drops the GIL around each call, which is what lets MLT join the
    threads that fire the Python frame listener while a stop() in progress
    holds it: the listener can always acquire the GIL, so the join completes.
    The equivalent SWIG call holds the GIL for the whole join and would
    deadlock against a pending listener.
    """
    global _natives_configured
    lib = _libmlt()
    if not _natives_configured:
        lib.mlt_consumer_start.argtypes = [ctypes.c_void_p]
        lib.mlt_consumer_start.restype = ctypes.c_int
        lib.mlt_consumer_stop.argtypes = [ctypes.c_void_p]
        lib.mlt_consumer_stop.restype = ctypes.c_int
        lib.mlt_events_listen.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                          ctypes.c_char_p, ctypes.c_void_p]
        lib.mlt_events_listen.restype = ctypes.c_void_p
        lib.mlt_event_close.argtypes = [ctypes.c_void_p]
        lib.mlt_event_close.restype = None
        lib.mlt_event_data_to_frame.argtypes = [ctypes.c_void_p]
        lib.mlt_event_data_to_frame.restype = ctypes.c_void_p
        lib.mlt_frame_get_position.argtypes = [ctypes.c_void_p]
        lib.mlt_frame_get_position.restype = ctypes.c_int64
        lib.mlt_frame_get_image.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
                                            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                                            ctypes.POINTER(ctypes.c_int), ctypes.c_int]
        lib.mlt_frame_get_image.restype = ctypes.c_int
        _natives_configured = True
    return lib


def _start_consumer(consumer) -> int:
    return _natives().mlt_consumer_start(int(consumer.get_consumer()))


def _stop_consumer(consumer) -> int:
    """Stop the sink and join its frame-show threads (see _natives)."""
    return _natives().mlt_consumer_stop(int(consumer.get_consumer()))


def _purge_audio_caches(graph, position):
    """Worker-only native cache reset for discontinuous source positions."""
    if graph._audio_frame is not None:
        frame, sources = graph._audio_frame
        if frame.get_int("audio_samples") and not frame.get_int("test_audio"):
            graph._last_audio_positions.update(sources)
            graph._audio_frame = None
    for decoder, positions in graph._audio_decoders:
        source = positions.get(position)
        key = int(decoder.get_service())
        previous = graph._last_audio_positions.get(key)
        if source is not None and (previous is None or source != previous + 1):
            _cache_purge(key)


def _tractor(mlt, profile):
    global _tractor_class, _cache_purge
    if _tractor_class is None:
        # ponytail: SWIG omits cache purge; use the loaded C API until bindings expose it.
        purge = _libmlt().mlt_service_cache_purge
        purge.argtypes = [ctypes.c_void_p]
        purge.restype = None
        _cache_purge = purge

        class Graph(mlt.Tractor):
            def __init__(self, profile):
                super().__init__(profile)
                self._audio_decoders = []
                self._last_audio_positions = {}
                self._audio_frame = None
                self.capture = None

            def get_frame(self, *args):
                position = self.position()
                _purge_audio_caches(self, position)
                frame = super().get_frame(*args)
                sources = {int(decoder.get_service()): positions[position]
                           for decoder, positions in self._audio_decoders if position in positions}
                # Retain the last lazy frame until the next serialized pull observes PCM consumption.
                self._audio_frame = (frame, sources)
                if self.capture is not None:
                    self.capture(frame)
                return frame

        _tractor_class = Graph
    return _tractor_class(profile)


class MltCompiler:
    @staticmethod
    def _runtime():
        global _repository
        try:
            import mlt7 as mlt
            if _repository is None:
                _repository = mlt.Factory().init(None)
            for kind, names in (("producers", ("loader", "color", "timewarp", "pango")),
                                ("transitions", ("frei0r.cairoaffineblend", "mix")),
                                ("filters", ("volume", "frei0r.flippo", "frei0r.alphaspot"))):
                services = getattr(_repository, kind)()
                installed = {services.get_name(i) for i in range(services.count())}
                if not set(names) <= installed:
                    raise RuntimeError(f"Missing MLT {kind}: {set(names) - installed}")
            return mlt
        except Exception as exc:
            raise BackendUnavailable(f"MLT unavailable: {exc}") from exc

    @staticmethod
    def available() -> tuple[bool, str]:
        try:
            mlt = MltCompiler._runtime()
            _tractor(mlt, mlt.Profile())
            return True, f"MLT {mlt.mlt_version_get_string()}"
        except Exception as exc:
            return False, str(exc)

    @staticmethod
    def _profile(mlt, model, rate=None):
        rate = rate or model.frame_rate
        int_max = (1 << 31) - 1
        if rate.num > int_max or rate.den > int_max:
            # SWIG exposes MLT's profile rate as two C ints. Timewarp can
            # produce a valid rate whose exact rational exceeds that range.
            exact = Fraction(rate.num, rate.den)
            max_den = int_max - 1
            if exact > 1:
                max_den = min(max_den, (int_max - 1) * exact.denominator // exact.numerator)
            if max_den < 1:
                raise BackendUnavailable(f"MLT profile rate is out of range: {rate.num}/{rate.den}")
            bounded = exact.limit_denominator(max_den)
            if bounded.numerator > int_max or bounded.denominator > int_max:
                raise BackendUnavailable(f"MLT profile rate is out of range: {rate.num}/{rate.den}")
            if bounded.numerator <= 0:
                raise BackendUnavailable(f"MLT profile rate is below supported precision: {rate.num}/{rate.den}")
            rate = FrameRate(bounded.numerator, bounded.denominator)
        width, height = model.canvas
        profile = mlt.Profile()
        profile.set_frame_rate(rate.num, rate.den)
        profile.set_width(width)
        profile.set_height(height)
        profile.set_progressive(1)
        profile.set_sample_aspect(1, 1)
        profile.set_display_aspect(width, height)
        profile.set_explicit(1)
        return profile

    def compile(self, model: TimelineModel) -> CompiledTimeline:
        if not isinstance(model, TimelineModel):
            raise TypeError("MltCompiler requires TimelineModel")
        return self._compile(model, 0)

    def _compile(self, model, depth):
        mlt = self._runtime()
        profile = self._profile(mlt, model)
        count = model.frame_rate.frame_count(model.duration_us)
        owned, warnings = [], list(model.warnings)
        compiled = CompiledTimeline(model, profile, None, count, (), owned)
        if not count:
            compiled.warnings = tuple(warnings)
            return compiled
        try:
            tractor = _tractor(mlt, profile)
            compiled.tractor = tractor

            def keep(value):
                if not value.is_valid():
                    raise BackendUnavailable("MLT service could not be constructed")
                owned.append(value)
                return value

            background = keep(mlt.Producer(profile, "color",
                                           "0x00000000" if depth else "#000000"))
            background.set("set.test_audio", 1)
            background.set("length", count)
            background.set_in_and_out(0, count - 1)
            tractor.set_track(background, 0)
            clips = []
            for ti, track in enumerate(model.tracks):
                if not track.enabled:
                    continue
                for si, clip in enumerate(track.clips):
                    if not clip.visible:
                        continue
                    if clip.kind in ("effect", "filter", "adjust", "none", ""):
                        warnings.extend(clip.warnings)
                        warnings.append(f"effect_unsupported:{clip.id}")
                        continue
                    z = clip.render_index if clip.render_index is not None else track.render_index
                    z = DEFAULT_RI.get(track.type, 0) if z is None else z
                    if clip.kind != "audio" and track.type != "audio":
                        clips.append((z, ti, si, track, clip, "video"))
                    if (clip.audio.enabled and not track.muted and clip.kind in
                            ("audio", "video", "draft", "compound") and
                            (clip.media_ref is None or clip.media_ref.has_audio is not False)):
                        clips.append((z, ti, si, track, clip, "audio"))
            # Higher model z is blended later into MLT's base track (priority reversal).
            clips.sort(key=lambda row: row[:3])
            for transition in model.transitions:
                warnings.extend(transition.warnings)
                if transition.kind not in ("fade", "crossfade"):
                    warnings.append(f"transition_unsupported:{transition.id}")

            for _, _, _, track, clip, mode in clips:
                warnings.extend(clip.warnings)
                for effect in clip.effects + clip.animations:
                    warnings.extend(effect.warnings)
                    if effect.kind not in ("audio_fade_in", "audio_fade_out"):
                        warnings.append(f"effect_unsupported:{effect.id}")
                linked = [t for t in model.transitions if t.kind in ("fade", "crossfade")
                          and clip.id in (t.from_clip_id, t.to_clip_id) and t.window.duration_us]
                windows = [clip.timeline_range] + [t.window for t in linked if t.kind == "crossfade"]
                intervals = sorted((model.frame_rate.first_frame_at_or_after(w.start_us),
                                    min(count, model.frame_rate.first_frame_at_or_after(w.end_us)))
                                   for w in windows)
                merged = []
                for start, end in intervals:
                    if end <= start:
                        continue
                    if merged and start <= merged[-1][1]:
                        merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
                    else:
                        merged.append((start, end))
                if not merged:
                    continue
                still = clip.kind in ("image", "photo", "sticker", "text")
                source_rate = clip.media_ref.frame_rate if clip.media_ref else None
                source_rate = source_rate or (clip.nested.frame_rate if clip.nested else model.frame_rate)
                if mode == "audio" and clip.nested is None:
                    source_rate = model.frame_rate
                mapping = clip.time_mapping
                speed = mapping.rate_num / mapping.rate_den
                reverse = mapping.direction == "reverse"
                broken = clip.placeholder
                if clip.media_ref is not None and not still and not clip.source_range.duration_us:
                    warnings.append("source_range_empty")
                    broken = True
                if clip.media_ref is not None and not still and clip.media_ref.available_range is not None:
                    available = clip.media_ref.available_range
                    if max(clip.source_range.start_us, available.start_us) >= min(clip.source_range.end_us, available.end_us):
                        warnings.append("source_range_unavailable")
                        broken = True
                producer = None
                title_size = None
                decoded_size = None
                if not broken and clip.nested is not None:
                    if depth >= 2:
                        warnings.append("max_nest_depth")
                        broken = True
                    else:
                        child = self._compile(clip.nested, depth + 1)
                        owned.append(child)
                        warnings.extend(child.warnings)
                        producer = child.tractor
                        if producer is None:
                            broken = True
                        elif speed != 1 or reverse:
                            # Native timewarp only accepts a resource; cut mapping handles nested clocks.
                            warnings.append("nested_time_mapping")
                elif not broken and clip.kind == "text" and clip.text_payload:
                    text = clip.text_payload
                    native_family, font_registered, reload_fontmap = _pango_font_family(text.font_path)
                    if text.font_path and not font_registered:
                        warnings.append(f"text_font_native_unavailable:{clip.id}")
                    producer = keep(mlt.Producer(profile, "loader", "pango:"))
                    if reload_fontmap:
                        producer.fire_event("fontmap-reload")
                    for key, value in {"text": text.text, "family": native_family or text.font_family or "Sans",
                                       "size": round(text.font_size), "fgcolour": text.color,
                                       "bgcolour": "0x00000000", "align": "centre"}.items():
                        producer.set(key, value)
                    for key, value in text.style:
                        if key in ("weight", "style", "underline", "strikethrough", "align"):
                            producer.set(key, value)
                    style = dict(text.style)
                    stroke = style.get("runs.0.strokes.0.width_em", 0)
                    if isinstance(stroke, (int, float)) and isfinite(stroke) and stroke > 0 \
                            and style.get("runs.0.strokes.0.render_type") == "solid":
                        producer.set("outline", round(text.font_size * stroke))
                        color = style.get("runs.0.strokes.0.color") or "#000000"
                        alpha = style.get("runs.0.strokes.0.alpha", 1.0)
                        if isinstance(alpha, (int, float)) and isfinite(alpha) \
                                and isinstance(color, str) and color.startswith("#") and len(color) == 7:
                            color = f"0x{color[1:]}{round(255 * max(0, min(1, alpha))):02x}"
                        producer.set("olcolour", color)
                    producer.get_frame().get_image(mlt.mlt_image_rgba, *model.canvas)
                    title_size = (producer.get_int("meta.media.width"), producer.get_int("meta.media.height"))
                elif not broken and clip.media_ref and clip.media_ref.exists:
                    if mode == "video" and not still and clip.media_ref.frame_rate is None:
                        probe = mlt.Producer(profile, "loader", clip.media_ref.path)
                        owned.append(probe)
                        if probe.is_valid():
                            probe.get_frame().get_image(mlt.mlt_image_rgba, *model.canvas)
                        num, den = probe.get_int("meta.media.frame_rate_num"), probe.get_int("meta.media.frame_rate_den")
                        if num > 0 and den > 0:
                            source_rate = FrameRate(num, den)
                        else:
                            warnings.append(f"source_frame_rate_unknown:{clip.id}")
                    source_profile = self._profile(mlt, model, source_rate)
                    owned.append(source_profile)
                    resource = clip.media_ref.path
                    if not still and (speed != 1 or reverse):
                        # This profile makes each warped position address one native source frame.
                        warp_rate = source_rate if mode == "audio" else FrameRate(
                            source_rate.num * mapping.rate_num, source_rate.den * mapping.rate_den)
                        source_profile = self._profile(mlt, model, warp_rate)
                        owned.append(source_profile)
                        resource = f"timewarp:{-speed if reverse else speed}:{resource}"
                    producer = mlt.Producer(source_profile, "loader", resource)
                    if producer.is_valid():
                        producer.seek(0)
                        frame = producer.get_frame()
                        if mode == "audio":
                            broken = producer.get_int("audio_index") < 0
                        else:
                            data = frame.get_image(mlt.mlt_image_rgba, *model.canvas)
                            broken = data is None or frame.get_int("test_image") != 0
                            decoded_size = (producer.get_int("meta.media.width"),
                                            producer.get_int("meta.media.height"))
                            if min(decoded_size) <= 0:
                                decoded_size = None
                            elif not broken and min(clip.media_ref.width, clip.media_ref.height) > 0 \
                                    and decoded_size != (clip.media_ref.width, clip.media_ref.height):
                                warnings.append(f"media_dimensions_mismatch:{clip.id}")
                        owned.append(producer)
                    else:
                        broken = True
                else:
                    broken = True
                visual, audio = mode == "video", mode == "audio"
                if broken:
                    warnings.append(f"media_placeholder:{clip.id}")
                    producer = keep(mlt.Producer(profile, "color", "#e040a0"))
                    audio, still = False, True
                producer.set_speed(1)
                decoder = None
                if audio and clip.media_ref is not None:
                    producer.seek(0)
                    decoder_frame = producer.get_frame()
                    decoder = decoder_frame.get_original_producer()
                    keep(decoder)
                    if decoder.get("mlt_service") != "avformat":
                        raise BackendUnavailable("Decoder cache purge requires a live avformat service")
                if still:
                    length = max(count, max(end for _, end in merged))
                    producer.set("length", length)
                    producer.set_in_and_out(0, length - 1)
                lane = keep(mlt.Playlist(profile))
                lane.set("jypreview.clip_id", clip.id)
                lane.set("jypreview.track_id", track.id)
                if not visual:
                    lane.set("hide", 1)
                if not audio:
                    lane.set("hide", 2 if visual else 3)
                if audio:
                    lane.set("set.test_audio", 0)
                positions, weights, volumes = [], {}, {}
                for start, end in merged:
                    for pos in range(start, end):
                        stamp = model.frame_rate.sample_us(pos)
                        active = [t for t in linked if t.window.contains(stamp)]
                        handle = any(t.kind == "crossfade" for t in active)
                        local = stamp - clip.timeline_range.start_us
                        src = mapping._unclamped_us(local, clip.source_range)
                        bounds = clip.source_range
                        available = clip.media_ref.available_range if clip.media_ref else None
                        if handle and available is not None:
                            low, high = available.start_us, available.end_us
                        else:
                            low, high = bounds.start_us, bounds.end_us
                            if available is not None:
                                low, high = max(low, available.start_us), min(high, available.end_us)
                        if not still and high > low:
                            bounded = min(max(src, low), high - 1)
                            if bounded != src:
                                warnings.append("transition_handle_clamped" if handle else "source_time_clamped")
                            src = bounded
                        elif not still:
                            warnings.append("source_range_empty")
                            src = 0
                        native = source_rate.quantize(max(0, src))[0]
                        if audio and clip.media_ref is not None and (speed != 1 or reverse):
                            native = (max(0,src) * source_rate.num * mapping.rate_den
                                      // (1_000_000 * source_rate.den * mapping.rate_num))
                        if clip.nested is not None and not broken:
                            source_pos = min(native, producer.get_out())
                        elif still:
                            source_pos = pos - merged[0][0]
                        else:
                            source_pos = producer.get_out() - native if reverse else native
                            source_pos = max(0, min(source_pos, producer.get_out()))
                        positions.append((pos, source_pos))
                        weight = 1.0
                        for transition in active:
                            progress = (stamp - transition.window.start_us) / transition.window.duration_us
                            weight *= 1 - progress if clip.id == transition.from_clip_id else progress
                        weights[pos] = clip.opacity * weight
                        gain = clip.audio.volume * weight
                        for effect in clip.effects:
                            if effect.window and effect.window.contains(stamp) and effect.window.duration_us:
                                progress = (stamp - effect.window.start_us) / effect.window.duration_us
                                if effect.kind == "audio_fade_in":
                                    gain *= progress
                                elif effect.kind == "audio_fade_out":
                                    gain *= 1 - progress
                        volumes[pos] = gain
                if decoder is not None:
                    tractor._audio_decoders.append((decoder, dict(positions)))
                elif audio and clip.nested is not None:
                    for descendant, child_positions in producer._audio_decoders:
                        mapped = {pos: child_positions[source] for pos,source in positions if source in child_positions}
                        tractor._audio_decoders.append((descendant, mapped))
                # ponytail: scan project samples once at compile time; group consecutive cuts.
                # Add piecewise rational runs only if large timelines make compilation expensive.
                cursor, i = 0, 0
                while i < len(positions):
                    pos, source_pos = positions[i]
                    if pos > cursor:
                        lane.blank(pos - cursor - 1)
                    j = i + 1
                    while j < len(positions) and positions[j] == (pos + j-i, source_pos + j-i):
                        j += 1
                    lane.append(producer, source_pos, source_pos + j-i-1)
                    cursor = pos + j-i
                    i = j
                if cursor < count:
                    lane.blank(count - cursor - 1)
                if audio:
                    gain_filter = keep(mlt.Filter(profile, "volume"))
                    if all(value == clip.audio.volume for value in volumes.values()):
                        gain_filter.set("gain", clip.audio.volume)
                    else:
                        gain_filter.set("level", ";".join(f"{pos}={20*log10(max(gain,1e-10))}"
                                                           for pos,gain in volumes.items()))
                    lane.attach(gain_filter)
                if visual:
                    if clip.crop != (0, 0, 1, 1):
                        left, top, right, bottom = clip.crop
                        mask = keep(mlt.Filter(profile, "frei0r.alphaspot"))
                        for key,value in {"0":0.0,"1":(left+right)/2,"2":(top+bottom)/2,
                                           "3":(right-left)/2,"4":(bottom-top)/2,
                                           "5":.5,"6":0,"7":0,"8":1,"9":.5}.items():
                            mask.set(key,value)
                        lane.attach(mask)
                    if clip.transform.flip_x or clip.transform.flip_y:
                        flip = keep(mlt.Filter(profile, "frei0r.flippo"))
                        flip.set("0", int(clip.transform.flip_x))
                        flip.set("1", int(clip.transform.flip_y))
                        lane.attach(flip)
                index = tractor.multitrack().count()
                tractor.set_track(lane, index)
                if visual:
                    blend = keep(mlt.Transition(profile, "frei0r.cairoaffineblend"))
                    width, height = model.canvas
                    t = clip.transform
                    default_transform = t == Transform()
                    if default_transform:
                        tw, th = title_size or (width, height)
                        t = Transform(width/2, height/2, tw or width, th or height)
                    base_w, base_h = width, height
                    if title_size is not None:
                        base_w, base_h = fit_contain(*title_size, width, height)
                    if not broken and not default_transform and title_size is None and clip.nested is None \
                            and clip.media_ref is not None:
                        dimensions = decoded_size or (clip.media_ref.width, clip.media_ref.height)
                        base_w, base_h = fit_contain(*dimensions, width, height)
                    for key,value in {"0":.4+t.x/(5*width),"1":.4+t.y/(5*height),
                                       "2":(t.width or base_w)*t.scale_x/(5*base_w),
                                       "3":(t.height or base_h)*t.scale_y/(5*base_h),
                                       "4":(t.rotation%360)/360,"5":clip.opacity,"6":clip.blend_mode,
                                       "7":t.anchor_x,"8":t.anchor_y,"always_active":1}.items():
                        blend.set(key,value)
                    if linked:
                        blend.set("5", ";".join(f"{pos}={value}" for pos,value in weights.items()))
                    if depth:
                        # frei0r.cairoaffineblend writes its result onto A's frame.
                        # Nested tractors can reuse that cached frame across seeks;
                        # target B (the clip frame) to keep the transparent base fresh.
                        blend.set("invert", 1)
                    tractor.plant_transition(blend, 0, index)
                if audio:
                    mix = keep(mlt.Transition(profile, "mix"))
                    mix.set("sum", 1)
                    mix.set("always_active", 1)
                    tractor.plant_transition(mix, 0, index)
            tractor.set("length", count)
            tractor.set_in_and_out(0, count - 1)
            tractor.set_speed(1)
            compiled.warnings = tuple(dict.fromkeys(warnings))
            return compiled
        except Exception:
            compiled.close()
            raise


class PlaybackController:
    """Serialized MLT transport with per-seek generation frame identity.

    One worker thread owns all state; the MLT audio consumer is the master
    clock and only worker-initiated renders stamp frame identity.
    """

    def __init__(self) -> None:
        self._commands: queue.Queue = queue.Queue()
        self._phase = "idle"
        self._playback_id = ""
        self._seek_request_id = 0
        self._generation = 0
        self._frame_index = 0
        self._t_us = 0
        self._duration_us = 0
        self._duration_frames = 0
        self._error: str | None = None
        self._open = False
        self._intent = False
        self._pending: int | None = None
        self._fps: FrameRate | None = None
        self._frame_slot: RenderedFrame | None = None
        self._seek_frame: RenderedFrame | None = None
        self._output_position: tuple[int, int] | None = None
        self._output_deadline: float | None = None
        self._compiled: CompiledTimeline | None = None
        self._consumer: Any = None
        self._mlt = None
        self._width = self._height = 0
        # Live frame source: a consumer-frame-show listener stamps frames from
        # the sink's own thread while the transport plays.
        self._frame_event: Any = None
        self._frame_listener: Any = None
        self._worker: threading.Thread | None = None
        self._spawn()

    # -- public API -----------------------------------------------------

    def open(self, model: TimelineModel) -> dict[str, Any]:
        if self._worker is None or not self._worker.is_alive():
            # close() retired the worker; a reopen needs a fresh one.
            self._spawn()
        return self._submit(self._h_open, model)

    def play(self) -> dict[str, Any]:
        return self._submit(self._h_play)

    def pause(self) -> dict[str, Any]:
        return self._submit(self._h_pause)

    def seek(self, t_us: int, *, playback_id: str, request_id: int) -> dict[str, Any]:
        return self._submit(self._h_seek, t_us, playback_id, request_id)

    def snapshot(self) -> dict[str, Any]:
        return self._submit(self._h_snapshot)

    def close(self) -> None:
        """Shut down and retire the worker thread; safe to call repeatedly."""
        worker = self._worker
        if worker is not None and worker.is_alive():
            try:
                self._submit(self._h_close)
            finally:
                worker.join(timeout=5)
        else:
            self._h_close()  # a failed close may retain native owners after worker retirement

    def pull_frame(self, timeout_ms: int = 100, *, seek_target: bool = False) -> RenderedFrame | None:
        phase, intent = self._submit(self._h_prepare_pull)
        if phase == "error":
            # Surface a dead sink instead of returning None forever so callers
            # (the multipart stream) can terminate with a readable error.
            raise RuntimeError(f"playback failed: {self._error}")
        # Capture before buffering waits. /render retains the immutable seek
        # target; streaming reads the live slot advanced by frame-show output.
        frame = self._seek_frame if seek_target else self._frame_slot
        end = time.monotonic() + max(0, int(timeout_ms)) / 1000.0
        if intent:
            while self._phase == "buffering" and time.monotonic() < end:
                time.sleep(0.005)
        while frame is None and time.monotonic() < end:
            frame = self._seek_frame if seek_target else self._frame_slot
            if frame is None:
                time.sleep(0.005)
        return frame

    # -- worker plumbing ------------------------------------------------

    def _spawn(self) -> None:
        self._worker = threading.Thread(target=self._run, name="jypreview-playback", daemon=True)
        self._worker.start()

    def _run(self) -> None:
        while True:
            try:
                self._tick()
            except Exception as exc:
                self._fail(exc)
            try:
                handler, args, reply = self._commands.get(timeout=0.01)
            except queue.Empty:
                continue
            try:
                result = handler(*args)
            except ValueError as exc:
                # Command validation never mutates state; keep the snapshot intact.
                reply.put(("err", exc))
            except Exception as exc:
                self._fail(exc)
                reply.put(("err", exc))
            else:
                reply.put(("ok", result))
            if handler == self._h_close:
                # Poison pill: close() joins this worker before returning.
                # (Bound methods are rebuilt per access, so compare with ==).
                return

    def _submit(self, handler, *args):
        worker = self._worker
        if worker is None or not worker.is_alive():
            # Retired worker means the controller is idle, so a read-only or
            # rejecting handler is safe to run on the caller's thread.
            return handler(*args)
        reply: queue.Queue = queue.Queue(maxsize=1)
        self._commands.put((handler, args, reply))
        kind, payload = reply.get()
        if kind == "err":
            raise payload
        return payload

    def _snapshot(self) -> dict[str, Any]:
        return {"backend": "mlt", "phase": self._phase,
                "playback_id": self._playback_id,
                "seek_request_id": self._seek_request_id,
                "generation": self._generation,
                "frame_index": self._frame_index, "t_us": self._t_us,
                "duration_us": self._duration_us,
                "playing": self._phase == "playing",
                "error": self._error, "open": self._open}

    # -- command handlers -----------------------------------------------

    def _h_open(self, model: TimelineModel) -> dict[str, Any]:
        if not isinstance(model, TimelineModel):
            raise ValueError("PlaybackController requires TimelineModel")
        self._shutdown()
        compiled = MltCompiler().compile(model)
        self._compiled = compiled  # close also owns graphs whose sink probe fails
        tractor: Any = compiled.tractor
        if tractor is None:
            raise BackendUnavailable("Timeline has no frames to play")
        consumer = self._make_consumer(MltCompiler._runtime(), compiled)
        self._mlt = MltCompiler._runtime()
        self._width, self._height = model.canvas
        self._fps = model.frame_rate
        self._duration_us = model.duration_us
        self._duration_frames = compiled.duration_frames
        self._playback_id = uuid.uuid4().hex
        self._seek_request_id = 0
        self._generation = 0
        self._frame_index = 0
        self._t_us = 0
        self._error = None
        self._intent = False
        self._pending = None
        self._frame_slot = None
        self._seek_frame = None
        self._output_position = None
        self._output_deadline = None
        self._consumer = consumer
        self._open = True
        self._phase = "ready"
        tractor.capture = self._capture
        self._listen(consumer)
        if tractor.seek(0) != 0:
            raise RuntimeError("MLT seek to the first frame failed")
        tractor.get_frame()
        self._seek_frame = self._frame_slot
        return self._snapshot()

    def _h_close(self) -> None:
        self._shutdown()

    def _h_snapshot(self) -> dict[str, Any]:
        self._tick()
        self._settle()
        return self._snapshot()

    def _h_prepare_pull(self) -> tuple[str, bool]:
        if not self._open:
            raise ValueError("playback controller is not open")
        self._tick()
        self._settle()
        return self._phase, self._intent

    def _h_play(self) -> dict[str, Any]:
        self._require_commandable()
        self._settle()
        self._intent = True
        if self._consumer is not None and self._consumer.is_stopped():
            self._output_position = None
            if _start_consumer(self._consumer) != 0:
                raise RuntimeError("MLT consumer failed to start playback")
            self._output_deadline = time.monotonic() + 1.5
        self._phase = "buffering"
        return self._snapshot()

    def _h_pause(self) -> dict[str, Any]:
        self._require_commandable()
        self._settle()
        self._intent = False
        if self._consumer is not None and not self._consumer.is_stopped():
            _stop_consumer(self._consumer)
        self._phase = "paused"
        return self._snapshot()

    def _h_seek(self, t_us, playback_id, request_id) -> dict[str, Any]:
        self._require_commandable()
        if playback_id != self._playback_id:
            raise ValueError("stale playback_id")
        if isinstance(request_id, bool) or not isinstance(request_id, int) or request_id <= 0:
            raise ValueError("request_id must be a positive integer")
        if request_id <= self._seek_request_id:
            # Older or repeated requests are idempotent: return current state untouched.
            return self._snapshot()
        try:
            target = int(t_us)
        except (TypeError, ValueError):
            raise ValueError("t_us must be an integer microsecond position") from None
        # Quiesce the consumer before mutating identity so no frame can stamp late.
        if self._consumer is not None and not self._consumer.is_stopped():
            _stop_consumer(self._consumer)
        if self._consumer is not None:
            self._consumer.purge()
        self._generation += 1
        self._seek_request_id = request_id
        self._frame_slot = None
        self._seek_frame = None
        self._output_position = None
        self._output_deadline = None
        frame, sample = self._fps.quantize(max(0, target))
        if frame >= self._duration_frames:
            self._pending = None
            self._intent = False
            self._phase = "ended"
            self._frame_index = frame
            self._t_us = sample
        else:
            self._pending = max(0, target)
            self._phase = "seeking"
        return self._snapshot()

    def _require_commandable(self) -> None:
        if not self._open or self._phase == "idle":
            raise ValueError("playback controller is not open")
        if self._phase == "error":
            raise ValueError(f"playback failed: {self._error}")

    # -- worker-side mechanics ------------------------------------------

    def _tick(self) -> None:
        if not self._open or self._phase not in ("buffering", "playing"):
            return
        if self._consumer is None:
            return
        output = self._output_position
        if output is None or output[0] != self._generation:
            if self._output_deadline is not None and time.monotonic() >= self._output_deadline:
                self._fail(RuntimeError("MLT consumer produced no frame after 1.5 seconds"))
            return
        self._output_deadline = None
        pos = output[1]
        if pos >= self._duration_frames - 1:
            self._end_of_stream()
            return
        if self._phase == "playing" and self._consumer.is_stopped():
            self._fail(RuntimeError("MLT consumer stopped unexpectedly"))
            return
        if self._phase == "buffering" and pos >= self._frame_index:
            self._phase = "playing"
        sample = self._fps.sample_us(pos)
        if sample >= self._t_us:
            self._t_us = sample
            self._frame_index = pos

    def _settle(self) -> None:
        if self._pending is None or self._phase != "seeking":
            return
        target = self._pending
        self._pending = None
        compiled, fps, consumer = self._compiled, self._fps, self._consumer
        if compiled is None or fps is None or consumer is None:
            raise RuntimeError("playback state is incomplete")
        frame, sample = fps.quantize(max(0, target))
        tractor: Any = compiled.tractor
        if tractor.seek(frame) != 0:
            raise RuntimeError(f"MLT seek to frame {frame} failed")
        tractor.get_frame()  # capture stamps the slot with current identity
        self._seek_frame = self._frame_slot  # immutable target survives live frame-show updates
        self._frame_index = frame
        self._t_us = sample
        self._phase = "buffering" if self._intent else "ready"
        if self._intent and consumer.is_stopped():
            if _start_consumer(consumer) != 0:
                raise RuntimeError("MLT consumer failed to resume after seek")
            self._output_deadline = time.monotonic() + 1.5

    def _end_of_stream(self) -> None:
        # Stop first so the frame-show listener is quiesced before clearing the slot.
        if self._consumer is not None and not self._consumer.is_stopped():
            _stop_consumer(self._consumer)
        self._intent = False
        self._phase = "ended"
        self._frame_slot = None
        self._seek_frame = None

    def _fail(self, exc) -> None:
        self._phase = "error"
        self._error = str(exc) or exc.__class__.__name__
        self._intent = False
        if self._consumer is not None:
            with suppress(Exception):
                _stop_consumer(self._consumer)
        self._frame_slot = None
        self._seek_frame = None

    def _shutdown(self) -> None:
        if self._consumer is not None:
            with suppress(Exception):
                _stop_consumer(self._consumer)
        # Do not mlt_event_close here: the consumer destructor already releases
        # its listener registrations, and closing first double-frees the event.
        self._frame_event = None
        if self._compiled is not None:
            tractor: Any = self._compiled.tractor
            if tractor is not None:
                tractor.capture = None
            self._compiled.close()
        self._consumer = None
        # Free the callback thunk only after the consumer (the sole frame-show
        # source) is gone, so its destructor can never run freed memory.
        self._frame_listener = None
        self._compiled = None
        self._mlt = None
        self._frame_slot = None
        self._seek_frame = None
        self._pending = None
        self._output_position = None
        self._output_deadline = None
        self._intent = False
        self._open = False
        self._phase = "idle"
        self._error = None
        self._playback_id = ""
        self._seek_request_id = 0
        self._generation = 0
        self._frame_index = 0
        self._t_us = 0
        self._duration_us = 0
        self._duration_frames = 0

    def _capture(self, mlt_frame) -> None:
        """Worker-side stamp from a tractor pull (seek/open, consumer stopped).

        While the consumer runs, pulls arrive on its own audio-clock thread:
        stamping there would force a full-frame render per frame on the master
        clock and starve the audio queue, so playback frames are stamped only
        by the consumer-frame-show listener instead.
        """
        consumer = self._consumer
        if consumer is not None and not consumer.is_stopped():
            return
        self._stamp(mlt_frame.get_position(),
                    bytes(mlt_frame.get_image(self._mlt.mlt_image_rgba,
                                              self._width, self._height)))

    def _listen(self, consumer) -> None:
        """Stamp frames from the sink's frame-show thread during playback.

        The audio consumer is the master clock, so its own thread is the only
        place a continuous frame index can be read.  Identity still mutates
        only while the consumer is stopped (which joins this thread), keeping
        stamping and identity changes disjoint.
        """
        listener = _Listener(self._on_frame_show)
        event = _natives().mlt_events_listen(int(consumer.get_consumer()), None,
                                             b"consumer-frame-show",
                                             ctypes.cast(listener, ctypes.c_void_p).value)
        if not event:
            raise RuntimeError("MLT consumer-frame-show listener could not be registered")
        # The C side keeps the raw callback pointer, so its thunk must outlive
        # the registration and is released only in _shutdown.
        self._frame_listener = listener
        self._frame_event = event

    def _on_frame_show(self, _properties, _data, event_data) -> None:
        """Runs on the MLT consumer thread; never let an exception escape into MLT."""
        with suppress(Exception):
            lib = _natives()
            frame = lib.mlt_event_data_to_frame(event_data)
            if frame:
                pos = lib.mlt_frame_get_position(frame)
                self._stamp(pos, self._native_image(lib, frame))
                # Only actual audio-consumer output owns the clock. position()
                # retains the previous seek's position even after stop/purge.
                self._output_position = (self._generation, pos)

    def _native_image(self, lib, frame) -> bytes:
        buffer, fmt = ctypes.c_void_p(), ctypes.c_int(int(self._mlt.mlt_image_rgba))
        width, height = ctypes.c_int(self._width), ctypes.c_int(self._height)
        if lib.mlt_frame_get_image(frame, ctypes.byref(buffer), ctypes.byref(fmt),
                                   ctypes.byref(width), ctypes.byref(height),
                                   ctypes.c_int(0)) != 0 or not buffer.value:
            raise RuntimeError("MLT could not render the frame-show image")
        return ctypes.string_at(buffer.value, width.value * height.value * 4)

    def _stamp(self, position, rgba) -> None:
        if not self._open or not self._playback_id:
            return
        self._frame_slot = RenderedFrame(
            self._playback_id, self._generation, self._seek_request_id,
            position, self._fps.sample_us(position), self._width, self._height, rgba)

    def _make_consumer(self, mlt, compiled):
        global _sink_name
        order = [_sink_name] if _sink_name else []
        order += [name for name in ("sdl2_audio", "rtaudio", "null") if name not in order]
        for name in order:
            consumer = mlt.Consumer(compiled.profile, name)
            if not consumer.is_valid():
                continue
            consumer.set("real_time", 1)
            consumer.set("loop", 0)
            if consumer.connect(compiled.tractor) != 0:
                continue
            if self._drives(consumer):
                _sink_name = name
                return consumer
        raise BackendUnavailable("No MLT consumer can drive the timeline clock")

    @staticmethod
    def _drives(consumer) -> bool:
        """Prove the sink advances the project clock before committing to it."""
        try:
            if _start_consumer(consumer) != 0:
                return False
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline:
                if consumer.position() >= 2:
                    return True
                if consumer.is_stopped():
                    return False
                time.sleep(0.02)
            return False
        finally:
            _stop_consumer(consumer)
