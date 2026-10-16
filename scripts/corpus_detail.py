"""Second-level mining over already-decrypted corpus plaintext.

No DLL, no draft access: reads temp/corpus-scan/plain/*.json (plus plaintext
sources listed in the manifest) and answers the structural questions the spec
needs -- above all how compositing order is actually encoded.

Usage:
  python scripts/corpus_detail.py
"""

from __future__ import annotations

import collections
import csv
import json
import math
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS / "jy_crypto"))
from cache import scratch_dir  # noqa: E402

SCAN = scratch_dir("corpus-scan")
OUT = scratch_dir("corpus-detail")

ROOT_FLAGS = (
    "render_index_track_mode_on",
    "free_render_index_mode_on",
    "render_uniform_index",
    "is_minimal_draft",
    "new_version",
    "color_space",
    "fps",
    "draft_type",
    "last_modified_platform",
)
SHAPE_TARGETS = {
    "common_mask": ["config", "position_info", "text_config"],
    "masks": ["config", "position_info"],
    "videos": ["crop", "video_algorithm", "matting", "stable", "freeze"],
    "texts": ["background_style", "content"],
    "transitions": None,
    "material_animations": ["animations"],
    "speeds": None,
    "canvases": None,
    "effects": None,
    "material_colors": None,
    "chromas": None,
    "shapes": None,
    "placeholders": None,
    "drafts": None,
}


def shape_keys(node, prefix: str, counter: collections.Counter, depth: int = 0) -> None:
    """Count every key occurrence in a material item.

    Nothing is sampled: an earlier version looked at only the first few list
    elements, which made every shape table a lower bound instead of a count. The
    depth cap is the only remaining guard.
    """
    if depth > 4:
        return
    if isinstance(node, dict):
        for key, value in node.items():
            counter[f"{prefix}.{key}" if prefix else str(key)] += 1
            if isinstance(value, (dict, list)):
                shape_keys(value, f"{prefix}.{key}" if prefix else str(key), counter, depth + 1)
    elif isinstance(node, list):
        for value in node:
            shape_keys(value, f"{prefix}[]", counter, depth + 1)


def iter_contents():
    manifest = json.loads((SCAN / "manifest.json").read_text(encoding="utf-8"))
    seen = set()
    for record in manifest:
        key = record.get("key")
        if not key or key in seen:
            continue
        seen.add(key)
        # The frozen snapshot first, the live draft file only as a fallback: counts
        # must be reproducible, and the corpus is being edited while we measure it.
        frozen = SCAN / "plain" / f"{key}.json"
        if record.get("encoding") == "plain" and not frozen.exists() and record.get("path"):
            source = Path(record["path"])
        elif frozen.exists():
            source = frozen
        else:
            source = SCAN / "plain" / f"{key}.json"
        if not source.exists():
            continue
        try:
            content = json.loads(source.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(content, dict):
            yield record, content


def mine_anim_timing(content: dict, durations: dict, starts: dict) -> None:
    """Preset timing per animation type: how long it runs and when it starts.

    The renderer needs both; the key-name mining in ``shape_keys`` cannot show that
    ``start`` is only ever non-zero on ``out``/``group`` entries.
    """
    for item in (content.get("materials") or {}).get("material_animations") or []:
        if not isinstance(item, dict):
            continue
        for anim in item.get("animations") or []:
            if not isinstance(anim, dict):
                continue
            kind = str(anim.get("type"))
            durations[kind][anim.get("duration")] += 1
            starts[kind][bool(anim.get("start"))] += 1


def mine_relations(content: dict, acc: dict) -> None:
    """Check the equalities the spec now claims, and count every exception.

    These are derived caches JianYing keeps next to their sources. A write-back that
    changes one side without the other leaves a stale value, so the fit rate has to
    be re-measurable, not just asserted once from a screenshot.
    """
    materials = content.get("materials") or {}
    speeds = {item.get("id"): item for item in materials.get("speeds") or [] if isinstance(item, dict)}
    owners = set()
    for items in materials.values():
        for item in items or []:
            if isinstance(item, dict):
                owners.add(item.get("constant_material_id"))
                owners.add(item.get("id"))

    for track in content.get("tracks") or []:
        if not isinstance(track, dict):
            continue
        for segment in track.get("segments") or []:
            if not isinstance(segment, dict):
                continue
            speed = segment.get("speed")
            if speed is not None:
                refs = [speeds[ref] for ref in segment.get("extra_material_refs") or [] if ref in speeds]
                if not refs:
                    acc["speeds_mirror"][f"no speeds[] ref (speed={'1' if speed == 1 else 'other'})"] += 1
                for ref in refs:
                    acc["speeds_mirror"]["equal" if ref.get("speed") == speed else f"MISMATCH segment={speed} speeds={ref.get('speed')}"] += 1

            us = segment.get("uniform_scale")
            if isinstance(us, dict):
                scale = (segment.get("clip") or {}).get("scale") or {}
                x, y = scale.get("x"), scale.get("y")
                if "value" in us and isinstance(x, (int, float)) and isinstance(y, (int, float)) and y:
                    acc["uniform_value"]["value == clip.scale.x/y" if abs(us["value"] - x / y) < 1e-9 else "stale value"] += 1
                elif "on" in us:
                    acc["uniform_value"][f"on={us.get('on')} -> clip.x==clip.y: {x == y}"] += 1

            for record in segment.get("common_keyframes") or []:
                if isinstance(record, dict) and record.get("material_id"):
                    acc["kf_material_id"]["resolves to a material id/constant_material_id"
                                            if record["material_id"] in owners else "unresolved material_id"] += 1

    for item in materials.get("texts") or []:
        if not isinstance(item, dict):
            continue
        point, distance, angle, alpha = item.get("shadow_point"), item.get("shadow_distance"), item.get("shadow_angle"), item.get("shadow_alpha")
        if isinstance(point, dict) and "x" in point:
            magnitude = math.hypot(point.get("x") or 0, point.get("y") or 0)
            usable = isinstance(distance, (int, float)) and distance
            acc["shadow_point_magnitude"]["|point| == 0.18 * distance"
                                          if usable and abs(magnitude - 0.18 * distance) < 1e-6
                                          else ("no usable distance" if not usable else "stale/other")] += 1
            acc["shadow_point_alpha_fit"]["|point| == shadow_alpha" if isinstance(alpha, (int, float)) and abs(magnitude - alpha) < 1e-6 else "not alpha"] += 1
            if isinstance(angle, (int, float)):
                want_x = math.cos(math.radians(angle))
                want_y = math.sin(math.radians(angle))
                sign_ok = (magnitude < 1e-9) or (abs(point.get("x") or 0) < 1e-9 and abs(point.get("y") or 0) < 1e-9) or (
                    abs((point.get("x") or 0) / max(magnitude, 1e-12) - want_x) < 1e-6
                    and abs((point.get("y") or 0) / max(magnitude, 1e-12) - want_y) < 1e-6
                )
                acc["shadow_point_direction"]["direction == (cos, sin)(shadow_angle)" if sign_ok else "direction differs"] += 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    root_flags = collections.defaultdict(collections.Counter)
    index_band = collections.defaultdict(collections.Counter)
    order_agreement = collections.Counter()
    order_samples = collections.defaultdict(list)
    shapes = collections.defaultdict(collections.Counter)
    text_style_shapes = collections.Counter()
    text_fill_shapes = collections.Counter()
    stroke_shapes = collections.Counter()
    shadow_shapes = collections.Counter()
    anim_item_shapes = collections.Counter()
    animations = collections.Counter()
    transitions = collections.Counter()
    extra_refs = collections.Counter()
    segment_fields = collections.defaultdict(collections.Counter)
    canvas_ratios = collections.Counter()
    anim_durations = collections.defaultdict(collections.Counter)
    anim_starts = collections.defaultdict(collections.Counter)
    relations = {
        "speeds_mirror": collections.Counter(),
        "uniform_value": collections.Counter(),
        "kf_material_id": collections.Counter(),
        "shadow_point_magnitude": collections.Counter(),
        "shadow_point_alpha_fit": collections.Counter(),
        "shadow_point_direction": collections.Counter(),
    }
    parsed = 0

    for record, content in iter_contents():
        parsed += 1
        for flag in ROOT_FLAGS:
            if flag in content:
                value = content[flag]
                root_flags[flag][json.dumps(value, ensure_ascii=False)[:40] if isinstance(value, (dict, list)) else str(value)] += 1
        canvas = content.get("canvas_config") or {}
        if isinstance(canvas, dict) and canvas.get("ratio"):
            canvas_ratios[str(canvas.get("ratio"))] += 1

        mode = content.get("render_index_track_mode_on")
        tracks = content.get("tracks") or []
        flat = []
        for position, track in enumerate(tracks):
            if not isinstance(track, dict):
                continue
            ttype = str(track.get("type"))
            for segment in track.get("segments") or []:
                if not isinstance(segment, dict):
                    continue
                for field in segment:
                    segment_fields[ttype][field] += 1
                index = segment.get("render_index")
                if isinstance(index, int):
                    index_band[ttype][index // 1000 * 1000] += 1
                    flat.append((position, ttype, index))
                for ref in segment.get("extra_material_refs") or []:
                    extra_refs[type(ref).__name__] += 1
                if len(order_samples[ str(mode) ]) < 3 and len(flat) > 2:
                    order_samples[str(mode)].append({"draft": record["draft"], "layout": record["layout"], "seq": flat[:8]})
            if isinstance(track.get("attribute"), int):
                index_band[f"track_attribute:{ttype}"][track["attribute"] // 1000 * 1000] += 1

        if len(flat) > 2:
            ascending = all(flat[i][2] <= flat[i + 1][2] for i in range(len(flat) - 1))
            same_as_track_order = all(flat[i][0] <= flat[i + 1][0] for i in range(len(flat) - 1))
            order_agreement[f"mode={mode}|render_index_ascending={ascending}|track_order_monotonic={same_as_track_order}"] += 1

        materials = content.get("materials") or {}
        for bucket, targets in SHAPE_TARGETS.items():
            items = materials.get(bucket)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                if targets is None:
                    shape_keys(item, bucket, shapes[bucket])
                else:
                    for key in item:
                        shapes[bucket][f"{bucket}.{key}"] += 1
                    for key in targets:
                        if key in item:
                            shape_keys(item[key], f"{bucket}.{key}", shapes[bucket])
                if bucket == "material_animations":
                    for anim in item.get("animations") or []:
                        if isinstance(anim, dict):
                            shape_keys(anim, "animations[]", anim_item_shapes)
                            animations[(str(anim.get("type")), str(anim.get("name")), str(anim.get("id")), str(anim.get("category_name")))] += 1
                if bucket == "transitions":
                    transitions[(str(item.get("name")), str(item.get("id")), str(item.get("category_name")), str(item.get("effect_id")))] += 1
                if bucket == "texts":
                    raw = item.get("content")
                    if isinstance(raw, str) and raw[:1] == "{":
                        try:
                            parsed_text = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        shape_keys({k: v for k, v in parsed_text.items() if k != "styles"}, "text_content", text_style_shapes)
                        for style in parsed_text.get("styles") or []:
                            if not isinstance(style, dict):
                                continue
                            shape_keys(style, "styles[]", text_style_shapes)
                            fill = style.get("fill")
                            if isinstance(fill, dict):
                                shape_keys(fill, "fill", text_fill_shapes)
                            for stroke in style.get("strokes") or []:
                                shape_keys(stroke, "strokes[]", stroke_shapes)
                            for shadow in style.get("shadows") or []:
                                shape_keys(shadow, "shadows[]", shadow_shapes)

        mine_anim_timing(content, anim_durations, anim_starts)
        mine_relations(content, relations)

    def dump_counter(name: str, counter: collections.Counter, header: list[str], split: bool = False) -> None:
        with (OUT / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            for key, value in counter.most_common():
                writer.writerow(list(key) + [value] if split else [key, value])

    dump_counter("root_flags.csv", collections.Counter({f"{k}={v}": c for k, vals in root_flags.items() for v, c in vals.most_common(25)}), ["flag_value", "count"])
    dump_counter("render_index_bands.csv", collections.Counter({f"{t}|{band}": c for t, bands in index_band.items() for band, c in bands.most_common(10)}), ["track_type|band", "count"])
    dump_counter("order_agreement.csv", order_agreement, ["case", "count"])
    dump_counter("animations.csv", animations, ["type", "name", "id", "category", "count"], split=True)
    dump_counter("transitions.csv", transitions, ["name", "id", "category", "effect_id", "count"], split=True)
    dump_counter("canvas_ratios.csv", canvas_ratios, ["ratio", "count"])
    dump_counter("extra_material_refs_seen.csv", extra_refs, ["id", "count"])
    for name, counter in (("text_style_shapes", text_style_shapes), ("text_fill_shapes", text_fill_shapes),
                          ("stroke_shapes", stroke_shapes), ("shadow_shapes", shadow_shapes),
                          ("anim_item_shapes", anim_item_shapes)):
        dump_counter(f"{name}.csv", counter, ["key_path", "count"])
    for bucket, counter in shapes.items():
        dump_counter(f"shape_{bucket}.csv", counter, ["key_path", "count"])
    with (OUT / "animation_timing.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["type", "entries", "duration_values", "duration_min", "duration_max", "start_nonzero", "start_zero"])
        for kind in sorted(anim_durations):
            durations = anim_durations[kind]
            numeric = [value for value, count in durations.items() if isinstance(value, (int, float))]
            writer.writerow([
                kind,
                sum(durations.values()),
                len(numeric),
                min(numeric) if numeric else "",
                max(numeric) if numeric else "",
                anim_starts[kind].get(True, 0),
                anim_starts[kind].get(False, 0),
            ])
    with (OUT / "relations.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["relation", "case", "count"])
        for relation, counter in relations.items():
            for case, count in counter.most_common():
                writer.writerow([relation, case, count])
    with (OUT / "segment_fields.json").open("w", encoding="utf-8") as handle:
        json.dump({k: dict(v.most_common()) for k, v in segment_fields.items()}, handle, ensure_ascii=False, indent=1)
    with (OUT / "order_samples.json").open("w", encoding="utf-8") as handle:
        json.dump(order_samples, handle, ensure_ascii=False, indent=1)

    print(json.dumps({
        "parsed": parsed,
        "root_flags": {k: dict(v.most_common(8)) for k, v in root_flags.items()},
        "render_index_bands": {k: dict(v.most_common(4)) for k, v in index_band.items()},
        "order_agreement_top": dict(order_agreement.most_common(12)),
        "canvas_ratios_top": dict(canvas_ratios.most_common(10)),
        "animations_distinct": len(animations),
        "animation_timing": {kind: {"entries": sum(vals.values()),
                                     "distinct_durations": len([v for v in vals if isinstance(v, (int, float))])}
                             for kind, vals in anim_durations.items()},
        "relations": {name: dict(counter.most_common(6)) for name, counter in relations.items()},
        "transitions_distinct": len(transitions),
        "out": str(OUT),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
