"""Normalize draft dictionaries into the immutable playback model."""

from __future__ import annotations

from fractions import Fraction
from math import isfinite
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .. import media
from . import fonts, labels, layout, paint
from .content import TimelineContent
from .timeline import (AudioSpec, Clip, EffectSpec, FrameRate, MediaRef, Params,
                       TextPayload, TimelineModel, TimeMapping, TimeRange, Track,
                       Transform, Transition)


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if isfinite(result) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _rate(value: Any) -> FrameRate | None:
    try:
        if isinstance(value, dict):
            return FrameRate(int(value["num"]), int(value.get("den", 1)))
        rate = Fraction(str(value)).limit_denominator(1_000_000)
        for rounded, num in (("23.976", 24_000), ("29.97", 30_000), ("59.94", 60_000)):
            if rate == Fraction(rounded):
                rate = Fraction(num, 1001)
                break
        return FrameRate(rate.numerator, rate.denominator)
    except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None


def _flatten(value: Any, prefix: str = "") -> Params:
    """Keep normalized paint/catalog metadata as immutable scalar paths."""
    if isinstance(value, dict):
        return tuple(pair for key, item in value.items()
                     for pair in _flatten(item, f"{prefix}.{key}" if prefix else str(key)))
    if isinstance(value, (tuple, list)):
        return tuple(pair for index, item in enumerate(value)
                     for pair in _flatten(item, f"{prefix}.{index}"))
    if isinstance(value, (str, int, float, bool, type(None))):
        return ((prefix, value if not isinstance(value, float) or isfinite(value) else None),)
    return ()


def _range(value: Any, name: str, warnings: list[str]) -> TimeRange:
    raw = _dict(value)
    start, duration = _integer(raw.get("start")), _integer(raw.get("duration"))
    if not raw or "duration" not in raw or any(
            _number(raw.get(key), float("nan")) != result
            for key, result in (("start", start), ("duration", duration)) if key in raw):
        warnings.append(f"{name}_range_invalid")
    if start < 0 or duration < 0:
        warnings.append(f"{name}_range_negative")
    # Retain the representable part of a damaged interval, rather than shifting its end.
    return TimeRange(max(start, 0), max(0, start + max(duration, 0) - max(start, 0)))


class DraftAdapter:
    def __init__(self, config, registry, font_index, catalog, probe_cache):
        self.config = config
        self.registry = registry
        self.font_index = font_index
        self.catalog = catalog
        self.probe_cache = probe_cache

    def build(self, content: TimelineContent, *, draft_root: Path, did: str,
              timeline_info: dict[str, Any]) -> TimelineModel:
        return self._build(content, Path(draft_root), did, timeline_info, "", 0)

    def _build(self, content, root, did, info, prefix, depth):
        warnings, tracks, transitions = [], [], []
        rate = _rate(content.value.get("fps"))
        if rate is None:
            rate = FrameRate(30)
            warnings.append("fps_defaulted")
        canvas = _dict(content.value.get("canvas_config"))
        width, height = _integer(canvas.get("width")), _integer(canvas.get("height"))
        if width <= 0 or height <= 0:
            width, height = 1920, 1080
            warnings.append("canvas_defaulted")
        seen_tracks, seen_clips = set(), set()
        for order, raw_track in enumerate(content.tracks):
            track_id = str(raw_track.get("id") or f"track-{order}")
            track_id = f"{prefix}/{quote(track_id, safe='')}" if prefix else track_id
            if track_id in seen_tracks:
                while track_id in seen_tracks:
                    track_id += f"@{order}"
                warnings.append(f"duplicate_track_id:{track_id}")
            seen_tracks.add(track_id)
            kind = str(raw_track.get("type") or "video")
            clips, pending = [], []
            for position, segment in enumerate(raw_track.get("segments") or []):
                if not isinstance(segment, dict):
                    warnings.append(f"segment_invalid:{track_id}/{position}")
                    continue
                ident = str(segment.get("id") or f"{track_id}/segment-{position}")
                ident = f"{prefix}/{quote(ident, safe='')}" if prefix else ident
                if ident in seen_clips:
                    while ident in seen_clips:
                        ident += f"@{order}-{position}"
                    warnings.append(f"duplicate_clip_id:{ident}")
                seen_clips.add(ident)
                try:
                    clip, transition = self._clip(content, segment, kind, ident, root,
                                                  did, (width, height), depth)
                except (TypeError, ValueError, KeyError, AttributeError, OverflowError, OSError):
                    notes = ["clip_invalid"]
                    target = _range(segment.get("target_timerange"), "target", notes)
                    clip = Clip(ident, kind, target, placeholder=True,
                                render_index=_integer(segment["render_index"]) if segment.get("render_index") is not None else None,
                                visible=segment.get("visible") is not False and kind not in ("effect", "filter", "adjust", "none", ""),
                                warnings=tuple(notes))
                    transition = None
                clips.append(clip)
                warnings.extend(f"{note}:{ident}" for note in clip.warnings)
                if transition:
                    pending.append((clip, transition))
            for clip, transition in pending:
                successors = [other for other in clips if other.timeline_range.start_us
                              > clip.timeline_range.start_us and other.timeline_range.start_us
                              <= clip.timeline_range.end_us]
                following = min(successors, key=lambda other: other.timeline_range.start_us,
                                default=None)
                impl = _dict(transition.get("approx")).get("impl")
                supported = impl in ("fade", "crossfade")
                notes = [] if supported else ["transition_unsupported"]
                if impl == "crossfade" and following is None:
                    notes.append("transition_target_missing")
                window = _dict(transition.get("window"))
                start, end = max(0, _integer(window.get("start_us"))), max(0, _integer(window.get("end_us")))
                transitions.append(Transition(
                    f"{clip.id}/transition", impl if supported else "unsupported",
                    TimeRange(start, max(0, end - start)), clip.id,
                    following.id if impl == "crossfade" and following else None,
                    params=_flatten({"name": transition.get("name"),
                                     "effect_id": transition.get("effect_id")}),
                    warnings=tuple(notes)))
            muted = bool(raw_track.get("muted") or raw_track.get("is_muted")
                         or (_integer(raw_track.get("attribute")) & 1))
            enabled = all(raw_track.get(key) is not False
                          for key in ("enabled", "enable", "is_enabled", "visible"))
            tracks.append(Track(track_id, kind, tuple(clips), order, enabled, muted,
                                _integer(raw_track["render_index"]) if raw_track.get("render_index") is not None else None))
        duration = _integer(content.value.get("duration"), -1)
        if duration < 0:
            duration = max((clip.timeline_range.end_us for track in tracks for clip in track.clips), default=0)
            warnings.append("duration_inferred")
        ident = str(content.timeline_id or info.get("id") or info.get("tid") or did)
        if prefix:
            ident = f"{prefix}/{quote(ident, safe='')}"
        return TimelineModel(ident, duration, rate, (width, height), tuple(tracks),
                             tuple(transitions), tuple(dict.fromkeys(warnings)))

    def _mapping(self, content, segment, material, source, target, warnings):
        curve = any(segment.get(key) is not None for key in ("speed_curve", "curve_speed"))
        speed_material = {}
        for bucket, item in content.refs(segment):
            if bucket == "speeds":
                speed_material = item
                curve = curve or any(item.get(key) is not None for key in ("curve_speed", "speed_curve"))
                curve = curve or item.get("type") in ("curve_speed", "speed_curve")
        rate = segment.get("speed", material.get("speed", speed_material.get("speed", 1)))
        if curve:
            if (segment.get("source_timerange") is not None and source.duration_us
                    and target.duration_us and not any(note.startswith("source_range_") for note in warnings)):
                rate = Fraction(source.duration_us, target.duration_us)
                # ponytail: average the whole curve; add per-frame curve integration when needed.
                warnings.append("speed_curve_approximated")
            else:
                warnings.append("speed_curve_unreadable")
                return TimeMapping(kind="unreadable_curve"), True
        try:
            rate = Fraction(str(rate)).limit_denominator(1_000_000)
            if rate <= 0:
                raise ValueError("nonpositive rate")
        except (ValueError, TypeError, ZeroDivisionError, OverflowError):
            warnings.append("speed_invalid")
            return TimeMapping(), True
        if not curve and rate not in (Fraction(1, 2), Fraction(1), Fraction(2)):
            warnings.append("speed_unsupported")
            return TimeMapping(rate.numerator, rate.denominator), True
        return TimeMapping(rate.numerator, rate.denominator,
                           "reverse" if segment.get("reverse") else "forward",
                           "average_curve" if curve else "constant"), False

    def _media(self, material, material_id, kind, root, warnings):
        located = media.resolve(str(material.get("path") or ""), root)
        path = str(located.get("path") or "")
        exists = bool(located.get("exists"))
        probe = {}
        if exists and self.probe_cache is not None:
            try:
                probe = media.probe(path, Path(self.probe_cache))
            except (TypeError, ValueError, OSError, OverflowError):
                probe = {"error": "probe_failed"}
        broken = not exists or bool(probe.get("error")) or bool(probe and not probe.get("codec"))
        if broken:
            warnings.append("media_missing" if not exists else "media_undecodable")
        if exists and self.registry is not None:
            self.registry.register(path, "media")
        duration = probe.get("duration_us")
        duration = material.get("duration") if duration is None else duration
        duration = max(0, _integer(duration)) if duration is not None else None
        if material.get("available_range") is not None:
            available = _range(material["available_range"], "available", warnings)
        else:
            available = TimeRange(0, duration) if duration is not None else None
        has_audio = material.get("has_audio")
        if probe and not broken:
            has_audio = bool(probe.get("audio_codec"))
        elif kind in ("image", "sticker"):
            has_audio = False
        elif kind == "audio":
            has_audio = True
        elif has_audio is None:
            warnings.append("audio_presence_unknown")
        return MediaRef(str(material_id or ""), path, exists, available, duration,
                        _rate(probe.get("frame_rate") or material.get("fps") or material.get("frame_rate")),
                        bool(has_audio) if has_audio is not None else None,
                        max(0, _integer(material.get("width") or probe.get("width"))),
                        max(0, _integer(material.get("height") or probe.get("height")))), broken

    def _text(self, material, segment, canvas, warnings):
        width, height = canvas
        payload = paint.build(material, lambda size: layout.em_px(size, width, height, self.config),
                              self.config, getattr(self.catalog, "flower_lookup", None))
        for run in payload["runs"]:
            ref = fonts.resolve(material, run["font"], self.font_index,
                                self.config.effect_cache, self.config.install_fonts, self.registry)
            run["font"] = {"family": ref.family, "path": ref.path or "", "source": ref.source}
        run = payload["runs"][0]
        sx, sy = layout.clip_scale(layout.clip_of(segment), segment)
        max_width = width * payload["max_line_ratio"]
        lines = paint.layout_lines(payload, max_width / sx if max_width else 0,
                                   run["font"]["path"] or None)
        rect = layout.layer_geometry(segment, 0, 0, width, height, self.config,
                                     text_em=lines["em_px"])
        rect["w_px"], rect["h_px"] = lines["box_w_px"] * sx, lines["box_h_px"] * sy
        if lines["metrics"] != "font":
            warnings.append("text_metrics_estimated")
        if any(item.get("flower") for item in payload["runs"]):
            warnings.append("text_effect_unsupported")
        text = TextPayload(payload["text"], run["font"]["family"], run["font"]["path"],
                           run["em_px"], str(_dict(run.get("fill")).get("css") or "#ffffff"),
                           (rect["cx_px"], rect["cy_px"], lines["box_w_px"], lines["box_h_px"]),
                           _flatten(payload))
        return text, rect, payload["global_alpha"]

    def _clip(self, content, segment, track_type, ident, root, did, canvas, depth):
        warnings = []
        target = _range(segment.get("target_timerange"), "target", warnings)
        found = content.material(segment.get("material_id"))
        bucket, material = found if found else ("", {})
        if not found:
            warnings.append("material_missing")
        kind = "text" if bucket == "texts" or track_type == "text" else (
            "audio" if bucket == "audios" or track_type == "audio" else (
                "sticker" if bucket == "stickers" or track_type == "sticker" else labels._family(material, str(material.get("path") or ""))))
        label_only = track_type in ("effect", "filter", "adjust", "none", "")
        if label_only:
            kind = track_type or "effect"
        source = _range(segment["source_timerange"], "source", warnings) if segment.get("source_timerange") is not None else TimeRange(0, target.duration_us)
        if kind in ("video", "audio") and not label_only and segment.get("source_timerange") is None:
            warnings.append("source_range_missing")
        if kind in ("video", "audio") and not source.duration_us:
            warnings.append("source_range_empty")
        mapping, bad_mapping = self._mapping(content, segment, material, source, target, warnings)
        tinfo = {"target_start_us": target.start_us, "target_duration_us": target.duration_us,
                 "source_start_us": source.start_us, "source_duration_us": source.duration_us,
                 "speed": mapping.rate_num / mapping.rate_den, "local_us": 0}
        try:
            resolved = labels.resolve(segment, content, self.catalog, target.start_us, tinfo, self.config)
        except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
            resolved = {}
            warnings.append("labels_invalid")
        nested, media_ref, text = None, None, None
        placeholder = not found or bad_mapping or any(note.startswith(("target_range_", "source_range_")) for note in warnings)
        if target.duration_us == 0:
            warnings.append("target_range_empty")
            placeholder = True
        entry = _dict(resolved.get("subdraft_entry"))
        inner = resolved.get("subdraft") or material.get("draft")
        if resolved.get("is_subdraft") or bucket == "drafts" or isinstance(inner, dict):
            kind = "compound"
            if depth >= self.config.max_nest_depth:
                warnings.append("max_nest_depth")
                placeholder = True
            elif isinstance(inner, dict):
                draft_file = str(entry.get("draft_file_path") or material.get("draft_file_path") or "")
                child_root = Path(draft_file).parent if draft_file else root
                if draft_file and not child_root.is_absolute():
                    child_root = root / child_root
                try:
                    nested = self._build(TimelineContent.build(inner), child_root, did, {}, ident, depth + 1)
                except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
                    warnings.append("nested_content_invalid")
                    placeholder = True
            else:
                warnings.append("nested_content_missing")
                placeholder = True
        elif kind in ("video", "image", "audio", "sticker"):
            media_ref, broken = self._media(material, segment.get("material_id"), kind, root, warnings)
            placeholder |= broken
            available = media_ref.available_range
            if kind in ("video", "audio") and available is not None and (
                    max(source.start_us, available.start_us) >= min(source.end_us, available.end_us)):
                warnings.append("source_range_unavailable")
                placeholder = True
        rect = layout.layer_geometry({}, 0, 0, *canvas, self.config)
        alpha = 1.0
        try:
            if kind == "text" and material:
                text, rect, alpha = self._text(material, segment, canvas, warnings)
            else:
                rect = layout.layer_geometry(segment, media_ref.width if media_ref else 0,
                                             media_ref.height if media_ref else 0, *canvas, self.config)
        except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
            warnings.append("geometry_or_text_invalid")
            placeholder = True
        clip_data = layout.clip_of(segment)
        anchor = _dict(clip_data.get("anchor"))
        transform = Transform(rect["cx_px"], rect["cy_px"], rect["w_px"] / rect["scale_x"],
                              rect["h_px"] / rect["scale_y"], rect["rotation_deg"],
                              rect["scale_x"], rect["scale_y"], _number(anchor.get("x"), 0.5),
                              _number(anchor.get("y"), 0.5), rect["flip_x"], rect["flip_y"])
        crop = segment.get("crop", clip_data.get("crop", material.get("crop")))
        if isinstance(crop, dict):
            if "upper_left_x" in crop:
                crop = [crop.get("upper_left_x", 0), crop.get("upper_left_y", 0),
                        crop.get("lower_right_x", 1), crop.get("lower_right_y", 1)]
            else:
                crop = [crop.get("left", 0), crop.get("top", 0), crop.get("right", 1), crop.get("bottom", 1)]
        if not isinstance(crop, (tuple, list)) or len(crop) != 4:
            if crop is not None:
                warnings.append("crop_invalid")
            crop = (0, 0, 1, 1)
        crop = tuple(max(0.0, min(1.0, _number(value))) for value in crop)
        if crop[2] <= crop[0] or crop[3] <= crop[1]:
            warnings.append("crop_invalid")
            crop = (0.0, 0.0, 1.0, 1.0)
        volume = _number(segment.get("volume", 1), -1)
        if volume < 0:
            volume = 1.0
            warnings.append("audio_volume_invalid")
        audio_data = _dict(segment.get("audio"))
        enabled = all(segment.get(key) is not False for key in ("enable_audio", "audio_enabled"))
        enabled = enabled and audio_data.get("enabled") is not False and not segment.get("muted", False)
        if "volume" in audio_data:
            volume = max(0.0, _number(audio_data["volume"], volume))
        effects, animations = [], []
        for index, label in enumerate(resolved.get("labels") or []):
            label_bucket = label.get("bucket")
            if label_bucket in ("drafts", "speeds", "transitions", "material_animations"):
                continue
            effects.append(EffectSpec(f"{ident}/effect-{index}", str(label.get("kind") or label_bucket),
                                      target, _flatten(label), False, ("effect_unsupported",)))
            warnings.append("effect_unsupported")
        for bucket_name, item in content.refs(segment):
            if bucket_name == "material_animations":
                for index, animation in enumerate(item.get("animations") or []):
                    if not isinstance(animation, dict):
                        continue
                    window = TimeRange(target.start_us + max(0, _integer(animation.get("start"))),
                                       max(0, _integer(animation.get("duration"))))
                    animations.append(EffectSpec(f"{ident}/animation-{len(animations)}", "animation", window,
                                                 _flatten(animation), False, ("animation_unsupported",)))
                    warnings.append("animation_unsupported")
        for side in ("in", "out"):
            duration = min(target.duration_us, max(0, _integer(resolved.get(f"fade_{side}_us"))))
            if duration:
                start = target.start_us if side == "in" else target.end_us - duration
                effects.append(EffectSpec(f"{ident}/audio-fade-{side}", f"audio_fade_{side}", TimeRange(start, duration)))
        if segment.get("common_keyframes"):
            warnings.append("keyframes_unsupported")
        if label_only:
            warnings.append("effect_unsupported")
        return Clip(ident, kind, target, source, media_ref, mapping, AudioSpec(bool(enabled), volume),
                    text, transform, max(0.0, min(1.0, rect["alpha"] * _number(alpha, 1))), crop,
                    str(segment.get("blend_mode") or clip_data.get("blend_mode") or material.get("blend_mode") or "normal"),
                    tuple(effects), tuple(animations),
                    _integer(segment["render_index"]) if segment.get("render_index") is not None else None,
                    segment.get("visible") is not False and not label_only, nested,
                    tuple(dict.fromkeys(warnings)), bool(placeholder)), resolved.get("transition")
