"""Audit the spec against the real corpus: what is measured but not documented.

Two jobs:
1. coverage ledger -- every field name observed in real drafts, marked as
   documented / undocumented in docs/spec, so the spec cannot silently drift
   behind the measurements.
2. extra measurement for structures the spec currently lacks: what buckets a
   segment's extra_material_refs actually points at, the shape of a keyframe
   record, and the shape of responsive_layout (which comes in two forms - an
   empty object and an all-default five-key object; see corpus_scan field_states).

Read-only over temp/corpus-scan. Output: temp/spec-audit/ + a printed summary.

Usage:
  python scripts/spec_audit.py
"""

from __future__ import annotations

import collections
import csv
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCAN = ROOT / "temp" / "corpus-scan"
SPEC_TEXT = ROOT / "docs" / "spec"
OUT = ROOT / "temp" / "spec-audit"

MEASURED_FIELDS = {
    "顶层键": "top_level_keys",
    "material bucket": "buckets",
    "styles键": "text_style_keys",
    "关键帧类型": "keyframe_property_types",
    "clip字段": "clip_fields",
}


def spec_tokens() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(SPEC_TEXT.glob("*")))


def load_inventory() -> dict[str, set[str]]:
    stats = json.loads((SCAN / "stats.json").read_text(encoding="utf-8"))
    inv = {label: set(stats[key]) for label, key in MEASURED_FIELDS.items()}
    rows = list(csv.reader((SCAN / "csv" / "bucket_keys.csv").open(encoding="utf-8")))[1:]
    inv["bucket.键"] = {f"{r[0]}.{r[1]}" for r in rows if len(r) > 1}
    inv["segment字段"] = {k for v in stats["segment_keys"].values() for k in v}
    inv["轨道字段"] = {k for v in stats["track_field_keys"].values() for k in v}
    effects_types = collections.Counter()
    for field, values in stats["bucket_enum_values"].items():
        if field.endswith(".type") or field.endswith(".category_name"):
            for value in values:
                effects_types[f"{field}={value}"] += 1
    inv["枚举取值"] = {f"{k}={v}" for k, values in stats["bucket_enum_values"].items() for v in list(values)[:6]}
    return inv


def coverage_ledger(blob: str, inv: dict[str, set[str]]) -> tuple[list[list], dict]:
    rows = []
    summary = {}
    for label, tokens in inv.items():
        documented = 0
        for token in sorted(tokens):
            leaf = token.split(".")[-1].split("=")[0]
            hit = leaf and (token in blob or leaf in blob)
            documented += bool(hit)
            rows.append([label, token, "已记录" if hit else "未记录"])
        summary[label] = {"total": len(tokens), "documented": documented,
                          "pct": round(100 * documented / max(1, len(tokens)))}
    return rows, summary


def measure_structures() -> dict:
    """Sample the decrypted corpus for three shapes the spec lacks."""
    manifest = json.loads((SCAN / "manifest.json").read_text(encoding="utf-8"))
    ref_by_track = collections.defaultdict(collections.Counter)
    keyframe_keys = collections.Counter()
    keyframe_sample = None
    responsive_keys = collections.Counter()
    responsive_values = collections.Counter()
    transition_keys = collections.Counter()
    mask_types = collections.Counter()
    mask_names = collections.Counter()
    segment_only_keys = collections.Counter()
    seen: set[str] = set()
    drafts = 0
    for entry in manifest:
        key = entry.get("key")
        if not key or key in seen:
            continue
        seen.add(key)
        # Prefer the frozen snapshot written by corpus_scan so the audit and the
        # first/second-level tables describe the same bytes.
        frozen = SCAN / "plain" / f"{key}.json"
        if frozen.exists():
            src = frozen
        elif entry.get("encoding") == "plain":
            src = pathlib.Path(entry["path"])
        else:
            continue
        if not src.exists():
            continue
        try:
            content = json.loads(src.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(content, dict):
            continue
        drafts += 1
        materials = content.get("materials") or {}
        bucket_of: dict[str, str] = {}
        for name, items in materials.items():
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and isinstance(item.get("id"), str):
                        bucket_of[item["id"]] = name
        for track in content.get("tracks") or []:
            if not isinstance(track, dict):
                continue
            ttype = str(track.get("type"))
            for segment in track.get("segments") or []:
                if not isinstance(segment, dict):
                    continue
                for ref in segment.get("extra_material_refs") or []:
                    ref_by_track[ttype][bucket_of.get(ref, "<未解析>")] += 1
                kfs = segment.get("common_keyframes")
                if isinstance(kfs, list) and kfs:
                    for kf in kfs:
                        if isinstance(kf, dict):
                            for k in kf:
                                keyframe_keys[k] += 1
                            if keyframe_sample is None and len(str(kf)) < 400:
                                keyframe_sample = kf
                layout = segment.get("responsive_layout")
                if isinstance(layout, dict):
                    for k in layout:
                        responsive_keys[k] += 1
                        value = layout[k]
                        if isinstance(value, (int, float, str, bool, type(None))):
                            responsive_values[f"{k}={value}"] += 1
        for item in materials.get("transitions") or []:
            if isinstance(item, dict):
                for k in item:
                    transition_keys[k] += 1
        for item in materials.get("common_mask") or []:
            if isinstance(item, dict):
                mask_types[str(item.get("type"))] += 1
                if isinstance(item.get("name"), str):
                    mask_names[item["name"]] += 1
    return {
        "drafts": drafts,
        "extra_material_refs_by_track": {k: dict(v.most_common(12)) for k, v in ref_by_track.items()},
        "keyframe_record_keys": dict(keyframe_keys.most_common(20)),
        "keyframe_sample": keyframe_sample,
        "responsive_layout_keys": dict(responsive_keys.most_common(20)),
        "responsive_layout_values_top": dict(responsive_values.most_common(15)),
        "transition_record_keys": dict(transition_keys.most_common(25)),
        "common_mask_types": dict(mask_types.most_common(20)),
        "common_mask_names_top": dict(mask_names.most_common(20)),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    blob = spec_tokens()
    inv = load_inventory()
    rows, summary = coverage_ledger(blob, inv)
    with (OUT / "spec_coverage.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["类别", "实测字段", "规格状态"])
        writer.writerows(rows)
    missing = [r for r in rows if r[2] == "未记录"]
    structures = measure_structures()
    (OUT / "structures.json").write_text(json.dumps(structures, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"coverage": summary, "undocumented_total": len(missing)}, ensure_ascii=False, indent=1))
    print("\n未记录字段样例:")
    by_cat = collections.Counter(r[0] for r in missing)
    for cat, count in by_cat.most_common():
        sample = [r[1] for r in missing if r[0] == cat][:12]
        print(f"  [{cat}] {count} 个: {sample}")
    print("\n结构补采:")
    print(json.dumps({k: v for k, v in structures.items() if k != "keyframe_sample"}, ensure_ascii=False)[:1600])
    print("\n关键帧记录样例:", json.dumps(structures.get("keyframe_sample"), ensure_ascii=False)[:300])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
