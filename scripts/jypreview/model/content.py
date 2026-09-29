"""Normalized access to one decrypted timeline's content JSON."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

DEFAULT_RI = {"video": 0, "audio": 0, "effect": 10000, "filter": 11000, "sticker": 12000,
              "adjust": 12000, "text": 14000, "draft": 0, "none": 0}
MEDIA_TRACKS = {"video", "image", "sticker", "photo"}
VISUAL_TRACK_TYPES = {"video", "text", "sticker", "effect", "filter", "adjust", "draft", "image"}


def us(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def timerange(timerange_: Any) -> tuple[int, int]:
    item = timerange_ if isinstance(timerange_, dict) else {}
    return us(item.get("start"), 0), us(item.get("duration"), 0)


@dataclass
class TimelineContent:
    value: dict[str, Any]
    meta: dict[str, Any] = field(default_factory=dict)
    _materials: dict[str, dict[str, dict]] = field(default_factory=dict, repr=False)
    _by_id: dict[str, tuple[str, dict]] = field(default_factory=dict, repr=False)
    _track_of_segment: dict[str, dict] = field(default_factory=dict, repr=False)
    _segment_by_id: dict[str, dict] = field(default_factory=dict, repr=False)

    @classmethod
    def build(cls, value: dict[str, Any], meta: dict[str, Any] | None = None) -> "TimelineContent":
        content = cls(value=value, meta=meta or {})
        content._index()
        return content

    def _index(self) -> None:
        materials = self.value.get("materials") or {}
        if not isinstance(materials, dict):
            materials = {}
        for bucket, items in materials.items():
            if not isinstance(items, list):
                continue
            table: dict[str, dict] = {}
            for item in items:
                if isinstance(item, dict) and item.get("id"):
                    ident = str(item["id"])
                    table[ident] = item
                    self._by_id.setdefault(ident, (bucket, item))
            self._materials[bucket] = table
        for track in self.tracks:
            for segment in track.get("segments") or []:
                if not isinstance(segment, dict):
                    continue
                self._segment_by_id[str(segment.get("id"))] = segment
                self._track_of_segment[str(segment.get("id"))] = track

    # -- structure ---------------------------------------------------------
    @property
    def tracks(self) -> list[dict[str, Any]]:
        return [t for t in (self.value.get("tracks") or []) if isinstance(t, dict)]

    @property
    def timeline_id(self) -> str:
        return str(self.value.get("id") or self.meta.get("tid") or "")

    @property
    def duration_us(self) -> int:
        return us(self.value.get("duration"), 0)

    @property
    def fps(self) -> float:
        value = self.value.get("fps")
        try:
            rate = float(value)
        except (TypeError, ValueError):
            return 0.0
        return rate

    @property
    def canvas(self) -> tuple[int, int, str]:
        config = self.value.get("canvas_config") or {}
        width = us(config.get("width"), 0)
        height = us(config.get("height"), 0)
        ratio = str(config.get("ratio") or "")
        return width, height, ratio

    @property
    def render_index_track_mode(self) -> bool:
        return bool(self.value.get("render_index_track_mode_on", True))

    def segments(self) -> Iterator[tuple[dict[str, Any], dict[str, Any], int]]:
        for track_index, track in enumerate(self.tracks):
            track_type = str(track.get("type") or "")
            for position, segment in enumerate(track.get("segments") or []):
                if isinstance(segment, dict):
                    yield track, segment, position

    def track_for(self, segment_id: str) -> dict[str, Any] | None:
        return self._track_of_segment.get(str(segment_id))

    def segment(self, segment_id: str) -> dict[str, Any] | None:
        return self._segment_by_id.get(str(segment_id))

    # -- materials ---------------------------------------------------------
    def bucket(self, name: str) -> dict[str, dict[str, Any]]:
        return self._materials.get(name, {})

    def material(self, material_id: Any, expected_bucket: str | None = None) -> tuple[str, dict] | None:
        key = str(material_id)
        if expected_bucket:
            item = self._materials.get(expected_bucket, {}).get(key)
            return (expected_bucket, item) if item else None
        return self._by_id.get(key)

    def material_kind(self, material_id: Any) -> str | None:
        found = self._by_id.get(str(material_id))
        return found[0] if found else None

    def refs(self, segment: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        out = []
        for ident in segment.get("extra_material_refs") or []:
            found = self._by_id.get(str(ident))
            if found:
                out.append((found[0], found[1]))
        return out

    def counts(self) -> dict[str, int]:
        return {name: len(table) for name, table in self._materials.items()}

    def unsupported(self) -> list[str]:
        """Buckets present with data that phase 1 deliberately does not render."""
        notes = []
        for name in ("masks", "color_curves", "hsl", "log_color_wheels", "primary_color_wheels",
                     "smart_crops", "green_screens", "beats", "audio_effects", "digital_humans"):
            if self.bucket(name):
                notes.append(f"{name}: {len(self.bucket(name))} item(s) not previewed")
        if self.bucket("text_templates"):
            notes.append(f"text_templates: {len(self.bucket('text_templates'))} (placeholder labels only)")
        return notes
