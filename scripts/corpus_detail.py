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
    if depth > 4:
        return
    if isinstance(node, dict):
        for key, value in node.items():
            counter[f"{prefix}.{key}" if prefix else str(key)] += 1
            if isinstance(value, (dict, list)):
                shape_keys(value, f"{prefix}.{key}" if prefix else str(key), counter, depth + 1)
    elif isinstance(node, list):
        for value in node[:4]:
            shape_keys(value, f"{prefix}[]", counter, depth + 1)


def iter_contents():
    manifest = json.loads((SCAN / "manifest.json").read_text(encoding="utf-8"))
    seen = set()
    for record in manifest:
        key = record.get("key")
        if not key or key in seen:
            continue
        seen.add(key)
        if record.get("encoding") == "plain" and record.get("path"):
            source = Path(record["path"])
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
            for item in items[:20]:
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
        "transitions_distinct": len(transitions),
        "out": str(OUT),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
