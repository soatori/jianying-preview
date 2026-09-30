"""Whole-timeline read-only project snapshot (``jypreview/editor-project@1``).

The frame IR answers "what is on screen at t"; the editor needs "what is on the
timeline", once, without a round-trip per clip. This module reshapes a single
full-span window pass of :func:`jypreview.model.framedesc.build_frame`, so every
number a clip carries is the same number ``/api/frame`` would report for it -- the
web editor cannot drift from the Python oracle it is supposed to mirror.

Nothing here can write: the payload carries served media URLs and read-only
metadata, never a material path the frontend could post back to.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

AUDIO_TRACK = "audio"
VISUAL_KINDS = ("video", "photo", "image", "sticker", "text", "subdraft", "effect", "filter",
                "adjust")
LAYER_FIELDS = ("rect", "css", "text", "labels", "transition", "animation", "keyframes",
                "applies", "nest", "canvas_fill", "volume")


class TimelineAmbiguous(LookupError):
    """No active timeline is provable, and guessing would show the wrong draft."""

    def __init__(self, available: list[str]):
        super().__init__("draft has no provable active timeline; select one explicitly")
        self.available = available


def select_timeline_entry(view, requested: Any = None) -> dict[str, Any]:
    """Resolve ``?timeline=`` to one of the draft's own timeline entries."""
    text = "" if requested is None else str(requested).strip()
    entries = [item for item in (view.timelines or []) if isinstance(item, dict)]
    if text in ("", "active"):
        active = str(view.active_timeline_id or "").strip()
        matches = [item for item in entries if str(item.get("id")).upper() == active.upper()]
        if active and len(matches) == 1:
            return matches[0]
        raise TimelineAmbiguous([str(item.get("id")) for item in entries])
    return view.resolve_timeline(text)


def build_editor_project(view, timeline_id: Any = None) -> dict[str, Any]:
    entry = select_timeline_entry(view, timeline_id)
    tid = str(entry["id"])
    content, meta = view.content(tid)
    declared = int(content.duration_us or 0)

    rows = _segment_rows(content)
    span_end = max([row["end_us"] for row in rows], default=0)
    duration = max(declared, span_end)
    frame = view.frame(tid, 0, window=(0, max(duration, 1)))

    warnings = list(frame["warnings"])
    if span_end > declared:
        warnings.append(f"declared duration {declared}us is shorter than the last clip "
                        f"({span_end}us); ruler uses {duration}us")

    order = {row["segment_id"]: index for index, row in
             enumerate(sorted(rows, key=lambda row: row["sort_key"]))}
    tracks = _build_tracks(content, rows, warnings)
    clips = _build_clips(frame, rows, order, warnings)
    assets = _build_assets(clips)
    missing = [clip["clip_id"] for clip in clips if isinstance(clip.get("asset"), dict)
               and not clip["asset"]["exists"]]
    if missing:
        warnings.append(f"{len(missing)} clip(s) reference media that could not be located: "
                        f"{', '.join(missing[:5])}")

    payload = {
        "schema": "jypreview/editor-project@1",
        "read_only": True,
        "draft": {**frame["draft"], "active_timeline_id": view.active_timeline_id,
                  "timelines": view.describe()["timelines"]},
        "timeline": {**frame["timeline"],
                     "active": str(entry.get("id")).upper() ==
                     str(view.active_timeline_id or "").upper(),
                     "encoding": entry.get("encoding") or entry.get("content_encoding"),
                     "name": entry.get("name"),
                     "content_file": _posix(frame["timeline"].get("content_file")),
                     "source_path": _posix(meta.get("src")),
                     "source_sha256": (meta.get("sidecar") or {}).get("src_sha256"),
                     "duration_us": duration, "declared_duration_us": declared,
                     "segment_count": len(rows)},
        "canvas": {key: frame["canvas"][key] for key in ("width", "height", "ratio", "background")},
        "fps": frame["fps"], "duration_us": duration,
        "declared_duration_us": declared,
        "size_rule": frame["size_rule"],
        "scene_rules": {"time_unit": "us", "interval": "half_open",
                        "clip_is_visible_at": "target_start_us <= t_us < target_end_us",
                        "paint_order": "ascending z_index", "visual_kinds": list(VISUAL_KINDS)},
        "tracks": tracks, "clips": clips, "assets": assets,
        "warnings": warnings, "stats": frame["stats"],
    }
    _intify(payload)
    return payload


def scene_clips(project: dict[str, Any], t_us: int, kinds: tuple[str, ...] | None = VISUAL_KINDS,
                include_hidden_tracks: bool = False) -> list[dict[str, Any]]:
    """The pure timeline query the browser's resolver has to agree with."""
    stamp = int(t_us)
    hidden = {track["id"] for track in project["tracks"] if not track["visible"]}
    out = []
    for clip in project["clips"]:
        if not clip["visible"] or clip["kind"] == "none":
            continue
        if kinds is not None and clip["kind"] not in kinds:
            continue
        if not include_hidden_tracks and clip["track_id"] in hidden:
            continue
        if clip["target_start_us"] <= stamp < clip["target_end_us"]:
            out.append(clip)
    return sorted(out, key=lambda clip: clip["z_index"])


# -- segment sweep -----------------------------------------------------------
def _segment_rows(content) -> list[dict[str, Any]]:
    from . import framedesc

    rows = []
    for track_index, (track, segment, position) in enumerate(content.segments()):
        target_start, target_duration = _range(segment.get("target_timerange"))
        source_start, source_duration = _range(segment.get("source_timerange"))
        rows.append({
            "segment_id": str(segment.get("id")), "track_id": str(track.get("id")),
            "track_index": track_index, "position": position,
            "track_type": str(track.get("type") or ""),
            "start_us": target_start, "end_us": target_start + max(target_duration, 0),
            "duration_us": max(target_duration, 0), "target_start_us": target_start,
            "source_start_us": source_start, "source_duration_us": source_duration,
            "visible": segment.get("visible") is not False,
            "speed": _speed(segment), "reverse": bool(segment.get("reverse")),
            "material_id": segment.get("material_id"), "segment": segment, "track": track,
            "sort_key": _sort_key(framedesc, segment, track, track_index, position),
        })
    return rows


def _sort_key(framedesc, segment: dict, track: dict, track_index: int, position: int) -> tuple:
    key = framedesc._z_key(segment, track, track_index, position)  # noqa: SLF001
    return (key["global"], key["track_index"], key["track_ri"], key["position"])


def _range(value: Any) -> tuple[int, int]:
    item = value if isinstance(value, dict) else {}
    return _int(item.get("start")), _int(item.get("duration"))


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _posix(value: Any) -> str:
    return str(value or "").replace("\\", "/")


def _speed(segment: dict) -> float:
    try:
        value = float(segment.get("speed"))
    except (TypeError, ValueError):
        return 1.0
    return value if value > 0 else 1.0


# -- tracks ------------------------------------------------------------------
def _build_tracks(content, rows: list[dict[str, Any]], warnings: list[str]) -> list[dict[str, Any]]:
    from .content import DEFAULT_RI

    by_track: dict[str, list[dict]] = {}
    for row in rows:
        by_track.setdefault(row["track_id"], []).append(row)

    tracks = []
    for index, track in enumerate(content.tracks):
        ident = str(track.get("id"))
        track_type = str(track.get("type") or "")
        members = by_track.get(ident, [])
        ri_values = [_int(track.get("render_index"))] if track.get("render_index") is not None else []
        for row in members:
            value = row["segment"].get("render_index")
            if value is not None:
                ri_values.append(_int(value))
        hidden = bool(track.get("is_hidden")) or bool(track.get("is_hide"))
        muted = bool(track.get("muted")) or (track_type == AUDIO_TRACK and bool(track.get("attribute")))
        tracks.append({
            "id": ident, "index": index, "type": track_type, "name": track.get("name"),
            "group": "audio" if track_type == AUDIO_TRACK else "visual",
            "visible": not hidden, "muted": muted, "flag": track.get("flag"),
            "attribute": track.get("attribute"), "render_index": track.get("render_index"),
            "z_ri": max(ri_values, default=int(DEFAULT_RI.get(track_type, 0))),
            "clip_ids": [row["segment_id"] for row in members], "clip_count": len(members),
            "span_end_us": max((row["end_us"] for row in members), default=0),
            "hidden_segment_count": sum(1 for row in members if not row["visible"]),
        })
    if not tracks:
        warnings.append("timeline declares no tracks")
    lanes = sorted([t for t in tracks if t["group"] == "visual"], key=lambda t: (-t["z_ri"], t["index"])) + \
        sorted([t for t in tracks if t["group"] == "audio"], key=lambda t: t["index"])
    for lane, track in enumerate(lanes):
        track["lane"] = lane
    return tracks


# -- clips -------------------------------------------------------------------
def _build_clips(frame: dict[str, Any], rows: list[dict[str, Any]], order: dict[str, int],
                 warnings: list[str]) -> list[dict[str, Any]]:
    rows_by_id: dict[str, list[dict]] = {}
    for row in rows:
        rows_by_id.setdefault(row["segment_id"], []).append(row)
    for ident, group in rows_by_id.items():
        if len(group) > 1:
            warnings.append(f"duplicate segment id {ident}: the editor shows the first one")

    clips: list[dict[str, Any]] = []
    taken: set[str] = set()
    for layer in frame["layers"]:
        clips.append(_clip_from_layer(layer, rows_by_id, order, taken, warnings))
    for entry in frame["audio_labels"]:
        ident = str(entry.get("segment_id"))
        if ident in taken:
            continue
        clips.append(_clip_from_audio(entry, rows_by_id, order, taken))
    for row in rows:
        if row["segment_id"] in taken:
            continue
        clips.append(_clip_placeholder(row, order, taken, frame["canvas"]))
    return sorted(clips, key=lambda clip: clip["z_index"])


def _base_clip(row: dict[str, Any] | None, ident: str, order: dict[str, int],
               kind: str) -> dict[str, Any]:
    return {
        "clip_id": ident, "kind": kind,
        "segment_id": ident,
        "track_id": row["track_id"] if row else "",
        "track_index": row["track_index"] if row else -1,
        "track_type": row["track_type"] if row else "",
        "position": row["position"] if row else 0,
        "z_index": order.get(ident, -1),
        "visible": bool(row and row["visible"]),
        "muted": False,
        "target_start_us": row["target_start_us"] if row else 0,
        "target_end_us": row["end_us"] if row else 0,
        "target_duration_us": row["duration_us"] if row else 0,
        "source_start_us": row["source_start_us"] if row else 0,
        "source_duration_us": row["source_duration_us"] if row else 0,
        "source_end_us": (row["source_start_us"] + row["source_duration_us"]) if row else 0,
        "speed": row["speed"] if row else 1.0, "reverse": bool(row and row["reverse"]),
        "material_id": row["material_id"] if row else None,
        "asset": None, "asset_id": None, "warnings": [],
        "sampled": None, "media": None,
    }


def _clip_from_layer(layer: dict[str, Any], rows_by_id: dict, order: dict, taken: set,
                     warnings: list[str]) -> dict[str, Any]:
    ident = str(layer["layer_id"])
    row = (rows_by_id.get(ident) or [None])[0]
    time = layer.get("time") or {}
    clip = _base_clip(row, ident, order, str(layer.get("kind") or "none"))
    taken.add(ident)
    clip["visible"] = True
    clip["sampled"] = time
    for field in LAYER_FIELDS:
        if field in layer:
            clip[field] = layer[field]
    clip["track"] = layer.get("track")
    clip["z"] = layer.get("z")
    if row:
        clip["target_start_us"] = _int(time.get("target_start_us"), row["target_start_us"])
        clip["target_duration_us"] = _int(time.get("target_duration_us"), row["duration_us"])
        clip["target_end_us"] = clip["target_start_us"] + clip["target_duration_us"]
    media = layer.get("media")
    if isinstance(media, dict):
        clip["asset"] = _asset_from_media(media)
        clip["asset_id"] = _asset_id(media)
        if not media.get("exists"):
            clip["warnings"].append(f"media unavailable ({media.get('how') or 'unresolved'}): "
                                    f"{media.get('material_name') or media.get('path_raw') or ''}".strip())
    if layer.get("nest") and not (layer["nest"] or {}).get("layers"):
        clip["warnings"].append(f"compound clip not rendered: {layer['nest'].get('reason') or ''}".strip())
    if isinstance(layer.get("text"), dict) and not (layer["text"].get("runs") or []):
        clip["warnings"].append("text material produced no styled runs")
    if clip["reverse"]:
        clip["warnings"].append("reverse playback is annotated, not re-timed in the preview")
    _flag_placeholders(clip, layer, warnings)
    return clip


def _flag_placeholders(clip: dict[str, Any], layer: dict[str, Any], warnings: list[str]) -> None:
    """Anything the renderer can only label has to say so on the clip, not just in a
    global list the timeline UI may have scrolled past."""
    tiers = []
    for label in layer.get("labels") or []:
        if label.get("render_class") == "placeholder":
            tiers.append(str(label.get("name") or label.get("kind")))
    if tiers:
        clip["warnings"].append(f"not rendered: {', '.join(tiers[:6])}")
    animation = layer.get("animation") or {}
    if animation.get("render_class") == "placeholder":
        clip["warnings"].append(f"animation not rendered: {animation.get('name') or 'unknown'}")


def _clip_from_audio(entry: dict[str, Any], rows_by_id: dict, order: dict, taken: set) -> dict:
    ident = str(entry.get("segment_id"))
    row = (rows_by_id.get(ident) or [None])[0]
    clip = _base_clip(row, ident, order, AUDIO_TRACK)
    taken.add(ident)
    clip["visible"] = bool(row and row["visible"])
    clip["muted"] = bool(entry.get("muted"))
    clip["volume"] = entry.get("volume")
    clip["fade_in_us"] = _int(entry.get("fade_in_us"))
    clip["fade_out_us"] = _int(entry.get("fade_out_us"))
    clip["labels"] = [{"bucket": "audio", "kind": "audio", "name": name, "render_class": "exact"}
                      for name in entry.get("badges") or []]
    clip["z"] = None
    source = entry.get("audio")
    if isinstance(source, dict):
        clip["asset"] = {"asset_id": None, "kind": AUDIO_TRACK,
                         "name": source.get("name"), "path_raw": source.get("path_raw"),
                         "path_served": source.get("served"), "exists": bool(source.get("exists")),
                         "how": source.get("how") or ("direct" if source.get("exists") else "missing"),
                         "material_duration_us": _int(source.get("source_duration_us")),
                         "probe": None, "placeholder_reason": None if source.get("exists") else "missing"}
        clip["asset"]["asset_id"] = _asset_id(clip["asset"])
        clip["asset_id"] = clip["asset"]["asset_id"]
        if not source.get("exists"):
            clip["warnings"].append(f"audio unavailable ({clip['asset']['how']})")
    else:
        clip["warnings"].append("audio segment references no locatable file")
    return clip


def _clip_placeholder(row: dict[str, Any], order: dict, taken: set, canvas: dict) -> dict:
    ident = row["segment_id"]
    taken.add(ident)
    kind = row["track_type"] or "none"
    clip = _base_clip(row, ident, order, kind)
    segment = row["segment"]
    clip["z_index"] = order.get(ident, -1)
    reason = ("segment marked hidden in the draft" if not row["visible"]
              else "segment produced no renderable layer")
    if not isinstance(segment.get("clip"), dict):
        clip["rect"] = {"cx_px": canvas["width"] / 2.0, "cy_px": canvas["height"] / 2.0,
                        "w_px": float(canvas["width"]), "h_px": float(canvas["height"]),
                        "rotation_deg": 0.0, "flip_x": False, "flip_y": False, "alpha": 1.0,
                        "scale_x": 1.0, "scale_y": 1.0, "z_px": 0.0}
    clip["warnings"].append(reason)
    clip["placeholder"] = True
    return clip


# -- assets ------------------------------------------------------------------
def _asset_from_media(media: dict[str, Any]) -> dict[str, Any]:
    return {
        "asset_id": _asset_id(media), "kind": media.get("family") or media.get("material_type"),
        "material_id": media.get("material_id"), "name": media.get("material_name"),
        "path_raw": media.get("path_raw"), "path_served": media.get("path_served"),
        "exists": bool(media.get("exists")), "how": media.get("how"),
        "recovered": bool(media.get("recovered")), "material_type": media.get("material_type"),
        "material_duration_us": media.get("material_duration_us"), "probe": media.get("probe"),
        "placeholder_reason": media.get("placeholder_reason"),
    }


def _asset_id(candidate: dict[str, Any]) -> str:
    material_id = str(candidate.get("material_id") or "").strip()
    if material_id:
        return f"m:{material_id}"
    path = str(candidate.get("path_raw") or candidate.get("path") or "").strip()
    return f"p:{Path(path.replace(chr(92), '/')).name.lower()}" if path else "a:unknown"


def _build_assets(clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    assets: dict[str, dict[str, Any]] = {}
    for clip in clips:
        asset = clip.get("asset")
        if not isinstance(asset, dict):
            continue
        ident = asset["asset_id"]
        known = assets.get(ident)
        if known is None:
            assets[ident] = {**asset, "clip_ids": [clip["clip_id"]]}
            continue
        known["clip_ids"].append(clip["clip_id"])
        if not known.get("path_served") and asset.get("path_served"):
            assets[ident] = {**known, "path_served": asset["path_served"],
                             "exists": asset["exists"], "placeholder_reason": None}
    return list(assets.values())


# -- integer-microsecond guarantee -------------------------------------------
def _intify(node: Any) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key.endswith("_us") and value is not None:
                node[key] = _int(value)
            else:
                _intify(value)
    elif isinstance(node, list):
        for item in node:
            _intify(item)
