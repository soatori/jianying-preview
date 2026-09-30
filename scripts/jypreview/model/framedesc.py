"""FrameDescriptor builder: the deterministic core of the previewer.

Every number the browser needs is resolved here (time mapping, z-order, geometry,
text metrics, labels), so ``/api/frame`` is a pure function of ``(draft, timeline, t)``
and an agent can assert on the JSON without rendering it.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .content import DEFAULT_RI, MEDIA_TRACKS, TimelineContent, timerange, us
from . import labels as labels_mod
from . import layout as layout_mod
from . import paint, timing

LABEL_KINDS = ("effect", "filter", "adjust", "none", "")


def normalize_window(window: tuple[int, int] | None) -> tuple[int, int] | None:
    """A playback window is half-open ``[from, to)`` in µs; degenerate ones are dropped."""
    if window is None:
        return None
    low, high = int(min(window[0], window[1])), int(max(window[0], window[1]))
    return (low, high) if high > low else None


def _overlaps(start: int, end: int, window: tuple[int, int]) -> bool:
    return start < window[1] and end > window[0]


def _sample_inside(start: int, duration: int, window: tuple[int, int]) -> int:
    """An instant inside the segment and inside the window, for the fields that are
    still sampled per-instance (``local_us`` / ``progress`` / ``source_time_us``).

    The browser recomputes those from ``target_start_us`` / ``source_start_us`` / ``speed``
    on every frame, so this value only has to be *representative*, never exact.
    """
    end = start + max(int(duration), 0)
    value = max(start, window[0])
    if value >= end:
        value = end - 1
    return max(value, start)


def _nested_time(tinfo: dict[str, Any], outer_local: int) -> int:
    """Map an outer-clip local time into the compound clip's own timeline."""
    return timing.source_time_us(int(outer_local), int(tinfo.get("source_start_us") or 0),
                                 float(tinfo.get("speed") or 1.0), bool(tinfo.get("reverse")),
                                 int(tinfo.get("target_duration_us") or 0),
                                 int(tinfo.get("source_duration_us") or 0))


def _canvas_of(content: TimelineContent, warnings: list[str]) -> tuple[int, int, str]:
    width, height, ratio = content.canvas
    if width <= 0 or height <= 0:
        preset = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080),
                  "4:3": (1440, 1080), "3:4": (1080, 1440)}.get(ratio)
        if preset:
            width, height = preset
            warnings.append(f"canvas_config empty; assumed {width}x{height} from ratio {ratio}")
        else:
            width, height = 1080, 1920
            warnings.append(f"canvas_config empty; defaulted to {width}x{height}")
    return int(width), int(height), ratio or f"{width}:{height}"


RATIOS = ("16:9", "16:10", "4:3", "3:4", "1:1", "9:16", "2:1", "21:9")


def apply_ratio(width: int, height: int, ratio: str) -> tuple[int, int] | None:
    """Resize the canvas box to `ratio`, keeping the long edge — what 剪映 does when you
    switch 画幅 on a 1080×1920 project (9:16 → 16:9 becomes 1920×1080)."""
    try:
        a, _, b = str(ratio).partition(":")
        num, den = float(a), float(b)
    except (TypeError, ValueError):
        return None
    if not num or not den:
        return None
    long_side = max(int(width), int(height))
    scale = num / den
    if scale >= 1:
        return long_side, max(1, round(long_side / scale))
    return max(1, round(long_side * scale)), long_side


def _fps(content: TimelineContent, config, warnings: list[str]) -> float:
    rate = content.fps
    if not rate or rate <= 0:
        warnings.append(f"fps absent; defaulted to {config.default_fps}")
        return float(config.default_fps)
    return float(rate)


def _z_key(segment: dict, track: dict, track_index: int, position: int) -> dict[str, Any]:
    ri = segment.get("render_index")
    source = "segment.render_index"
    if ri is None:
        ri = track.get("render_index")
        source = "track.render_index"
    if ri is None:
        ri = DEFAULT_RI.get(str(track.get("type") or ""), 0)
        source = f"default:{track.get('type') or 'video'}"
    return {"global": us(ri), "source": source, "track_index": track_index, "position": position,
            "track_ri": us(segment.get("track_render_index"))}


def _label_only(z: dict, segment: dict, tinfo: dict, resolved: dict, kind: str | None = None) -> dict:
    return {
        "layer_id": str(segment.get("id")), "kind": kind or str(z["track"].get("type") or "effect"),
        "track": z["track"], "z": z["z"], "time": tinfo,
        "media": None, "rect": None, "css": None, "text": None,
        "labels": resolved["labels"], "transition": resolved["transition"],
        "animation": resolved["animation"], "keyframes": resolved["keyframes"],
        "applies": resolved["applies"], "nest": None,
    }


def _audio_source(resolved: dict, registry, draft_root: Path, tinfo: dict) -> dict[str, Any]:
    """Locate an audio clip's file so the browser can actually play it."""
    from .. import media as media_mod

    material = resolved.get("material") or {}
    raw_path = str(material.get("path") or "")
    if not raw_path:
        return {"audio": None}
    located = media_mod.resolve(raw_path, Path(draft_root))
    if not located["exists"]:
        return {"audio": {"name": Path(raw_path.replace("\\", "/")).name, "exists": False,
                          "how": located["how"]}}
    key = registry.register(located["path"], "media") if registry is not None else None
    return {"audio": {
        "name": material.get("material_name") or Path(raw_path.replace("\\", "/")).name,
        "path_raw": raw_path, "path": str(located["path"]),
        "served": f"/media?f={key}" if key else None, "exists": True,
        # target_start/duration/source_start/speed are what a *rolling* playhead needs to
        # decide whether this clip should be audible right now; source_time_us is only the
        # value at the sampling instant, so it is not enough on its own.
        "source_time_us": tinfo["source_time_us"], "speed": tinfo["speed"],
        "source_start_us": int(tinfo["source_start_us"]),
        "source_duration_us": int(tinfo["source_duration_us"]),
        "reverse": bool(tinfo["reverse"]),
        "target_start_us": tinfo["target_start_us"], "duration_us": tinfo["target_duration_us"],
        "target_duration_us": tinfo["target_duration_us"],
    }}


def build_frame(content: TimelineContent, t_us: int, config, *, draft_root: Path, did: str,
                timeline_info: dict | None = None, registry=None, font_index=None,
                effect_cache: Path | None = None, install_fonts: Path | None = None,
                catalog=None, probe_cache: Path | None = None, depth: int = 0,
                ratio: str | None = None, window: tuple[int, int] | None = None) -> dict[str, Any]:
    """One instant (``window is None``) or every layer touching ``[from, to)``.

    Window mode is what playback runs on: the browser gets the whole span of layers up
    front, so a cut becomes a CSS visibility change instead of a fresh round-trip.
    """
    warnings: list[str] = []
    window = normalize_window(window)
    width, height, draft_ratio = _canvas_of(content, warnings)
    ratio_view = draft_ratio
    if ratio and ratio not in ("", "draft", "原始"):
        sized = apply_ratio(width, height, ratio)
        if sized:
            width, height, ratio_view = sized[0], sized[1], str(ratio)
        else:
            warnings.append(f"ignored unparseable 画幅 {ratio!r}")
    ratio = ratio_view
    fps = _fps(content, config, warnings)
    frame_dur = timing.frame_duration_us(fps, config.default_fps)
    stats = {"layers_total": 0, "media_missing": 0, "fonts": {},
             "labels": {"exact": 0, "approx": 0, "placeholder": 0}, "flowers": 0}

    layers: list[dict[str, Any]] = []
    audio_labels: list[dict[str, Any]] = []
    font_refs: list[Any] = []

    for track_index, (track, segment, position) in enumerate(
            (item for item in content.segments() if isinstance(item[1], dict))):
        track_type = str(track.get("type") or "")
        target_start, target_duration = timerange(segment.get("target_timerange"))
        if segment.get("visible") is False:
            continue
        if window is None:
            if not timing.is_visible(t_us, target_start, target_duration):
                continue
            sample = t_us
        else:
            if not _overlaps(target_start, target_start + max(target_duration, 0), window):
                continue
            sample = _sample_inside(target_start, target_duration, window)
        local = timing.local_us(sample, target_start)
        source_start, source_duration = timerange(segment.get("source_timerange"))
        speed = float(segment.get("speed") or (content.material(segment.get("material_id")) or
                                               (None, {}))[1].get("speed") or 1.0)
        reverse = bool(segment.get("reverse"))
        source_time = timing.source_time_us(local, source_start, speed, reverse, target_duration,
                                           source_duration)
        key = _z_key(segment, track, track_index, position)
        z = {
            "global": key["global"], "tie": key["track_index"], "position": key["position"],
            "track_ri": key["track_ri"], "source": key["source"],
            "label": f"{track_type} #{position} · track {track_index} · {track.get('name') or ''}".strip(),
            "track": {"id": track.get("id"), "index": track_index, "name": track.get("name"),
                      "type": track_type, "flag": track.get("flag"), "attribute": track.get("attribute"),
                      "render_index": track.get("render_index"),
                      "segment_count": len(track.get("segments") or [])},
        }
        z["z"] = {"global": z["global"], "tie": f"{key['track_index']:03d}/"
                                              f"{key['track_ri']:03d}/{key['position']:04d}",
                  "source": z["source"], "label": z["label"]}
        tinfo = {
            "target_start_us": target_start, "target_duration_us": target_duration,
            "end_us": target_start + target_duration, "local_us": local,
            "progress": timing.progress(local, target_duration),
            "source_start_us": source_start, "source_time_us": source_time,
            "source_duration_us": source_duration, "speed": speed, "reverse": reverse,
        }
        resolved = labels_mod.resolve(segment, content, catalog, sample, tinfo, config)

        for label in resolved["labels"]:
            stats["labels"][label.get("render_class", "placeholder")] = \
                stats["labels"].get(label.get("render_class", "placeholder"), 0) + 1

        if track_type == "audio":
            audio_labels.append({"segment_id": str(segment.get("id")), "track": track.get("name") or track_type,
                                 "track_index": track_index, "volume": float(segment.get("volume", 1.0) or 0.0),
                                 "muted": bool(track.get("muted")) or bool(track.get("attribute")),
                                 "badges": [label.get("name") for label in resolved["labels"]] or
                                           [resolved["media_name"] or "audio"],
                                 "fade_in_us": resolved["fade_in_us"], "fade_out_us": resolved["fade_out_us"],
                                 **_audio_source(resolved, registry, draft_root, tinfo)})
            continue

        if track_type in ("effect", "filter", "adjust"):
            label_layer = _label_only(z, segment, tinfo, resolved)
            label_layer["_sort"] = (key["global"], key["track_index"], key["track_ri"], key["position"])
            layers.append(label_layer)
            stats["layers_total"] += 1
            continue

        if track_type == "text":
            layer = _text_layer(content, segment, z, tinfo, resolved, width, height, config,
                                font_index, effect_cache, install_fonts, registry, catalog, stats,
                                warnings)
        elif resolved["is_subdraft"]:
            layer = _subdraft_layer(content, segment, z, tinfo, resolved, width, height, config,
                                    registry, effect_cache, install_fonts, catalog, warnings, depth,
                                    draft_root, did, timeline_info, probe_cache, font_index,
                                    window=window)
        else:
            layer = _media_layer(content, segment, z, tinfo, resolved, track_type, width, height,
                                 config, registry, probe_cache, stats, warnings, draft_root)
        if layer is not None:
            layer["_sort"] = (key["global"], key["track_index"], key["track_ri"], key["position"])
            layers.append(layer)
            stats["layers_total"] += 1
            if layer.get("text") and layer["text"].get("font"):
                font_refs.append(layer["text"]["font"])

    layers.sort(key=lambda item: item.pop("_sort"))
    for index, layer in enumerate(layers):
        layer["z"]["order"] = index
    if window is not None:
        # `layers` is the whole window, not one instant: say so instead of letting the
        # info panel read a window-sized count as a per-frame count.
        stats["mode"] = "window"
        stats["window_layers"] = len(layers)

    for note in content.unsupported():
        warnings.append(note)

    info = timeline_info or {}
    return {
        "schema": "jy-preview/framedesc@1",
        "draft": {"id": did, "name": Path(draft_root).name, "path": str(draft_root),
                  "layout": info.get("layout")},
        "timeline": {"id": content.timeline_id, "name": info.get("name"),
                     "encoding": info.get("encoding"), "content_file": info.get("content_rel"),
                     "source_sha256": (content.meta.get("sidecar") or {}).get("src_sha256"),
                     "replica_drift": bool(info.get("replica_errors")),
                     "mirror_drift": bool(info.get("mirror_drift"))},
        "canvas": {"width": width, "height": height, "ratio": ratio, "ratio_draft": draft_ratio,
                   "background": "#000000"},
        "fps": fps, "duration_us": content.duration_us,
        "size_rule": {"px_per_size": round(width * config.text_scale_factor, 4),
                      "basis": config.text_size_basis, "scale_factor": config.text_scale_factor,
                      "fit_mode": config.fit_mode},
        "time": {"t_us": int(t_us), "frame_index": timing.frame_index(t_us, fps, config.default_fps),
                 "frame_start_us": int(timing.frame_index(t_us, fps, config.default_fps) * (1e6 / fps)),
                 "frame_dur_us": frame_dur},
        "window": None if window is None else {"from_us": window[0], "to_us": window[1],
                                               "sample_us": int(t_us)},
        "layers": layers,
        "audio_labels": audio_labels,
        "fonts": list({ref["family"]: ref for ref in font_refs if ref.get("family")}.values()),
        "warnings": warnings,
        "stats": stats,
    }


def _media_layer(content, segment, z, tinfo, resolved, track_type, width, height, config,
                 registry, probe_cache, stats, warnings, draft_root) -> dict | None:
    from .. import media as media_mod

    material = resolved["material"] or {}
    raw_path = str(material.get("path") or "")
    family = resolved["family"] or media_mod.media_family(raw_path)
    material_type = str(material.get("type") or ("photo" if family == "image" else "video"))
    located = media_mod.resolve(raw_path, Path(draft_root)) if raw_path else \
        {"path": None, "exists": False, "how": "empty_path", "family": family,
         "name": "", "recovered": False}
    served = None
    probe_info = None
    if located["exists"]:
        if registry is not None:
            key = registry.register(located["path"], "media")
            served = f"/media?f={key}" if key else None
        if probe_cache is not None and family in ("video", "audio"):
            probe_info = media_mod.probe(located["path"], Path(probe_cache))
    else:
        stats["media_missing"] += 1

    media_w = float(material.get("width") or (probe_info or {}).get("width") or 0) or 0
    media_h = float(material.get("height") or (probe_info or {}).get("height") or 0) or 0
    if family == "image" or material_type == "photo":
        media_w = media_w or width
        media_h = media_h or height
    if not media_w or not media_h:
        media_w, media_h = float(width), float(height)

    rect = layout_mod.layer_geometry(segment, media_w, media_h, width, height, config)
    layer = {
        "layer_id": str(segment.get("id")), "kind": material_type if family != "audio" else "audio",
        "track": z["track"], "z": z["z"], "time": tinfo,
        "media": {
            "material_id": segment.get("material_id"), "material_type": material_type,
            "material_name": material.get("material_name") or Path(raw_path.replace("\\", "/")).name,
            "family": family, "path_raw": raw_path,
            "path": located["path"], "path_served": served, "exists": located["exists"],
            "how": located["how"], "recovered": located.get("recovered", False),
            "material_duration_us": us(material.get("duration")),
            "probe": {"codec": (probe_info or {}).get("codec"), "width": (probe_info or {}).get("width"),
                      "height": (probe_info or {}).get("height"),
                      "duration_us": (probe_info or {}).get("duration_us"),
                      "frame_rate": (probe_info or {}).get("frame_rate"),
                      "audio_codec": (probe_info or {}).get("audio_codec")} if probe_info else None,
            "placeholder_reason": None if located["exists"] else located["how"],
        },
        "rect": rect, "css": rect["css"], "text": None,
        "labels": resolved["labels"], "transition": resolved["transition"],
        "animation": resolved["animation"], "keyframes": resolved["keyframes"],
        "applies": resolved["applies"], "nest": None,
        "volume": _num_or_none(segment.get("volume")),
    }
    canvas_fill = resolved["canvas_fill"]
    if canvas_fill:
        layer["canvas_fill"] = canvas_fill
    return layer


def _text_layer(content, segment, z, tinfo, resolved, width, height, config, font_index,
                effect_cache, install_fonts, registry, catalog, stats, warnings) -> dict | None:
    from .fonts import resolve as resolve_font

    material = resolved["material"] or {}
    if not material:
        return None

    def em_for_size(size):
        return layout_mod.em_px(size, width, height, config)

    payload = paint.build(material, em_for_size, config,
                          flower_lookup=(getattr(catalog, "flower_lookup", None) if catalog else None))
    style_font = payload["runs"][0]["font"] if payload["runs"] else {}
    font = resolve_font(material, style_font, font_index, effect_cache, install_fonts, registry)
    stats["fonts"][font.source] = stats["fonts"].get(font.source, 0) + 1

    clip = layout_mod.clip_of(segment)
    cx, cy, _cz = layout_mod.transform_center(clip, width, height, config)
    sx, sy = layout_mod.clip_scale(clip, segment)
    box_width_px = width * payload["max_line_ratio"] if payload["max_line_ratio"] else 0.0
    lines = paint.layout_lines(payload, box_width_px / sx if box_width_px else 0.0, font.path)
    em = lines["em_px"] or (payload["runs"][0]["em_px"] if payload["runs"] else 0.0)

    box = {
        "anchor": "center", "cx_px": cx, "cy_px": cy,
        "rotation_deg": layout_mod._num(clip.get("rotation")),
        "alpha": layout_mod._num(clip.get("alpha"), 1.0),
        "max_line_px": round(box_width_px, 4),
        "line_height_px": lines["line_height_px"], "vertical": payload["vertical"],
        "alignment": {0: "left", 1: "center", 2: "right"}.get(payload["alignment"], "center"),
        "w_px": round(lines["box_w_px"] * sx, 4), "h_px": round(lines["box_h_px"] * sy, 4),
        "em_px": round(em * sx, 4), "line_count": lines["line_count"],
        "lines": lines["lines"], "metrics": lines["metrics"],
    }
    scale_note = "" if sx == sy == 1.0 else " (clip scale folded into box)"
    rect = {"cx_px": cx, "cy_px": cy, "w_px": box["w_px"], "h_px": box["h_px"],
            "rotation_deg": box["rotation_deg"], "flip_x": bool((clip.get("flip") or {}).get("horizontal")),
            "flip_y": bool((clip.get("flip") or {}).get("vertical")), "alpha": box["alpha"],
            "scale_x": sx, "scale_y": sy}
    rect["css"] = {
        "width": f"{rect['w_px']}px", "height": f"{rect['h_px']}px",
        "transform": (f"translate({round(rect['cx_px'] - rect['w_px'] / 2, 4)}px, "
                      f"{round(rect['cy_px'] - rect['h_px'] / 2, 4)}px)"
                      + (f" rotate({rect['rotation_deg']}deg)" if rect["rotation_deg"] else "")),
        "transform-origin": "center", "opacity": f"{rect['alpha']}",
    }

    runs = []
    for run in payload["runs"]:
        font_run = resolve_font(material, run["font"], font_index, effect_cache, install_fonts,
                                registry) if run["font"] != style_font else font
        runs.append({
            "start": run["start"], "end": run["end"], "text": run["text"],
            "size_raw": run.get("size_raw"),
            "em_px": round(run["em_px"] * sx, 4), "bold": run["bold"], "italic": run["italic"],
            "underline": run["underline"], "fill": run["fill"], "strokes": run["strokes"],
            "shadows": run["shadows"], "inner_shadows": run["inner_shadows"],
            "use_letter_color": run["use_letter_color"], "flower": run["flower"],
            "font": {"family": font_run.family, "source": font_run.source, "src": font_run.served,
                     "title": font_run.title, "resource_id": font_run.resource_id},
        })
        if run.get("flower"):
            stats["flowers"] += 1
    if font.path is None and box["metrics"] != "font":
        warnings.append("text metrics estimated (no font file) for "
                        f"{material.get('font_title') or material.get('font_resource_id')}; "
                        "box widths may drift")

    text = {
        "material_id": payload["material_id"], "type": payload["type"], "text": payload["text"],
        "font": {"family": font.family, "resource_id": font.resource_id, "title": font.title,
                 "src": font.served, "source": font.source, "file": None},
        "size": {"font_size": payload["runs"][0].get("size_raw") if payload["runs"] else None,
                 "em_px": round(em * sx, 4), "basis": config.text_size_basis,
                 "scale_factor": config.text_scale_factor},
        "box": box,
        "deco": {"background": payload["background"],
                 "has_shadow": bool(any(run["shadows"] for run in payload["runs"])),
                 "global_alpha": payload["global_alpha"],
                 "letter_spacing_px": round(payload["letter_spacing_em"] * em * sx, 4),
                 "line_spacing_raw": payload["line_spacing_raw"],
                 "alignment": box["alignment"], "vertical": payload["vertical"]},
        "runs": runs,
    }
    layer = {
        "layer_id": str(segment.get("id")), "kind": "text",
        "track": z["track"], "z": z["z"], "time": tinfo,
        "media": None, "rect": rect, "css": rect["css"], "text": text,
        "labels": resolved["labels"], "transition": resolved["transition"],
        "animation": resolved["animation"], "keyframes": resolved["keyframes"],
        "applies": resolved["applies"], "nest": None,
    }
    return layer


def _subdraft_layer(content, segment, z, tinfo, resolved, width, height, config, registry,
                    effect_cache, install_fonts, catalog, warnings, depth, draft_root, did,
                    timeline_info, probe_cache, font_index=None,
                    window: tuple[int, int] | None = None) -> dict | None:
    """Compound clips render their own inner content instead of a placeholder tile.

    Nested media is addressed as ``##_draftpath_placeholder_<guid>_##/...``, which resolves
    against the subdraft's own folder (``draft_file_path``) rather than the parent draft;
    when even that yields nothing, fall back to the cover JianYing stored for the clip.

    Inner layers carry the *inner* timeline's seconds, so the outer window is mapped through
    this segment's own ``source_timerange``/``speed`` before recursing — a compound clip
    placed at 30s must not be asked for its 0s..5s content when the playhead is at 30s.
    """
    inner = resolved.get("subdraft")
    entry = resolved.get("subdraft_entry") or {}
    sub_root = Path(draft_root)
    draft_file = str(entry.get("draft_file_path") or "").replace("\\", "/")
    if draft_file and Path(draft_file).is_file():
        sub_root = Path(draft_file).parent
    embeddable = isinstance(inner, dict) and bool(inner.get("tracks"))

    if embeddable and depth < config.max_nest_depth:
        child = TimelineContent.build(inner, meta={"nested": True})
        child_warnings: list[str] = []
        child_width, child_height, _ = _canvas_of(child, child_warnings)
        child_t = _nested_time(tinfo, tinfo["local_us"])
        child_window = None
        if window is not None:
            target_start = int(tinfo["target_start_us"])
            lo = _nested_time(tinfo, max(window[0] - target_start, 0))
            hi = _nested_time(tinfo, max(window[1] - target_start, 0))
            span = normalize_window((min(lo, hi), max(lo, hi)))
            if span is not None:
                span = (max(span[0], 0), min(span[1], max(int(child.duration_us), 1)))
                # A window that clamps away to nothing means this clip only clips the window's
                # edge; one sampled instant is then the honest answer.
                child_window = span if span[1] > span[0] else None
            if child_window is not None:
                child_t = _sample_inside(0, max(int(child.duration_us), 1), child_window)
        scaled = build_frame(child, child_t, config, draft_root=sub_root, did=did,
                             timeline_info={"layout": "nested", "name": "subdraft"}, registry=registry,
                             font_index=font_index, effect_cache=effect_cache,
                             install_fonts=install_fonts, catalog=catalog, probe_cache=probe_cache,
                             depth=depth + 1, window=child_window)
        factor = (width / child_width) if child_width else 1.0
        for layer in scaled["layers"]:
            _rescale_layer(layer, factor)
        if scaled["layers"]:
            return {
                "layer_id": str(segment.get("id")), "kind": "subdraft", "track": z["track"],
                "z": z["z"], "time": tinfo, "media": None, "rect": None, "css": None, "text": None,
                "labels": resolved["labels"], "transition": resolved["transition"],
                "animation": resolved["animation"], "keyframes": resolved["keyframes"],
                "applies": resolved["applies"],
                "nest": {"depth": depth + 1, "root": str(sub_root),
                         "canvas": {"width": child_width, "height": child_height},
                         "scale_to_parent": round(factor, 6), "duration_us": child.duration_us,
                         "layers": scaled["layers"],
                         "warnings": (child_warnings + scaled["warnings"])[:6]},
            }

    cover = _subdraft_cover(entry, sub_root)
    if cover is not None:
        layer = _still_layer(z, segment, tinfo, resolved, cover, width, height, registry,
                             label=str(entry.get("name") or "复合片段封面"))
        layer["nest"] = {"depth": depth, "embeddable": False,
                         "reason": "inner media unresolved; showing JianYing's stored cover"}
        warnings.append("复合片段内层素材不可解析，改用剪映自带的复合片段封面")
        return layer

    layer = _label_only(z, segment, tinfo, resolved, kind="subdraft")
    layer["nest"] = {"depth": depth, "embeddable": embeddable,
                     "reason": "compound clip content and cover are both unavailable on disk"}
    warnings.append("subdraft shown as placeholder tile (no inner content, no cover)")
    return layer


def _rescale_layer(layer: dict[str, Any], factor: float) -> None:
    """Nested geometry is in the child canvas; scale the box and rebuild its CSS transform."""
    rect = layer.get("rect")
    if not rect:
        return
    rect["w_px"] = round(rect["w_px"] * factor, 4)
    rect["h_px"] = round(rect["h_px"] * factor, 4)
    text = layer.get("text")
    if text and text.get("box"):
        box = text["box"]
        for key in ("em_px", "w_px", "h_px", "line_height_px", "max_line_px"):
            if box.get(key) is not None:
                box[key] = round(box[key] * factor, 4)
        for run in text.get("runs") or []:
            if run.get("em_px") is not None:
                run["em_px"] = round(run["em_px"] * factor, 4)
    transform = (f"translate({round(rect['cx_px'] - rect['w_px'] / 2, 4)}px, "
                 f"{round(rect['cy_px'] - rect['h_px'] / 2, 4)}px)")
    if rect.get("rotation_deg"):
        transform += f" rotate({rect['rotation_deg']}deg)"
    css = rect.get("css") or {}
    css.update({"width": f"{rect['w_px']}px", "height": f"{rect['h_px']}px",
                "transform": transform, "transform-origin": "center"})
    rect["css"] = css
    layer["css"] = css


def _subdraft_cover(entry: dict[str, Any], sub_root: Path) -> Path | None:
    for field in ("draft_cover_path", "cover_path", "path"):
        value = str(entry.get(field) or "").replace("\\", "/")
        if not value:
            continue
        candidate = Path(value)
        if candidate.is_file():
            return candidate
        relative = sub_root / value
        if relative.is_file():
            return relative
    return None


def _still_layer(z, segment, tinfo, resolved, path: Path, width, height, registry,
                 label: str) -> dict:
    served = None
    if registry is not None:
        key = registry.register(str(path), "media")
        served = f"/media?f={key}" if key else None
    rect = {"cx_px": width / 2.0, "cy_px": height / 2.0, "w_px": float(width),
            "h_px": float(height), "rotation_deg": 0.0, "flip_x": False, "flip_y": False,
            "alpha": 1.0, "scale_x": 1.0, "scale_y": 1.0}
    rect["css"] = {"width": f"{width}px", "height": f"{height}px",
                   "transform": "translate(0px, 0px)", "transform-origin": "center",
                   "opacity": "1"}
    return {
        "layer_id": str(segment.get("id")), "kind": "photo", "track": z["track"], "z": z["z"],
        "time": tinfo,
        "media": {"material_id": segment.get("material_id"), "material_type": "photo",
                  "material_name": label, "family": "image", "path_raw": str(path),
                  "path": str(path), "path_served": served, "exists": True,
                  "how": "subdraft_cover", "recovered": True, "material_duration_us": None,
                  "probe": None, "placeholder_reason": None},
        "rect": rect, "css": rect["css"], "text": None,
        "labels": resolved["labels"], "transition": resolved["transition"],
        "animation": resolved["animation"], "keyframes": resolved["keyframes"],
        "applies": resolved["applies"], "nest": None,
    }


def _num_or_none(value) -> float | None:
    try:
        return None if value is None else round(float(value), 4)
    except (TypeError, ValueError):
        return None
