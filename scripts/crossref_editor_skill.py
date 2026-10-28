"""Cross-reference our measured draft inventory against jianying-editor-skill's docs and catalogs.

Read-only: it parses their text as data (regex over source text, never importing or
executing it) and compares with our corpus inventory. Nothing from their repo is
copied into this repository -- output is counts, match rates and mismatch samples.

Usage:
  python scripts/crossref_editor_skill.py            # summary to stdout
  python scripts/crossref_editor_skill.py --json      # machine-readable
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import pathlib
import re
import sys

SKILL = pathlib.Path.home() / ".agents/skills/jianying-editor-skill"
CATALOG_DIR = SKILL / "scripts" / "vendor" / "pyJianYingDraft" / "metadata"
SCAN = pathlib.Path(__file__).resolve().parents[1] / "temp" / "corpus-scan"
TEXT_EXT = {".md", ".py", ".json", ".txt", ".yaml", ".yml", ".toml", ".html", ".js", ".cfg", ".ini"}

META_CALL = re.compile(r"=\s*(\w+Meta)\((.*?)\)\s*$")

# 我们的 bucket -> 他们 metadata 目录里对应的文件（空列表表示他们根本没有这类目录）
CATALOG_MAP = {
    "material_animations": ["text_intro", "text_outro", "text_loop", "video_group_animation", "video_intro", "video_outro"],
    "transitions": ["transition_meta"],
    "effects": ["video_scene_effect", "video_character_effect", "filter_meta", "tone_effect", "audio_scene_effect"],
    "stickers": [],
    "text_templates": [],
    "common_mask": ["mask_meta"],
    "masks": ["mask_meta"],
}
STR_ARG = re.compile(r'"((?:[^"\\]|\\.)*)"')
NUM_ARG = re.compile(r"-?\d+(?:\.\d+)?")


def their_text() -> tuple[str, int]:
    chunks = []
    count = 0
    for path in SKILL.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_EXT:
            continue
        if "__pycache__" in path.parts or ".git" in path.parts:
            continue
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
            count += 1
        except OSError:
            continue
    return "\n".join(chunks), count


def load_our_inventory() -> dict[str, set[str]]:
    stats = json.loads((SCAN / "stats.json").read_text(encoding="utf-8"))
    rows = list(csv.reader((SCAN / "csv" / "bucket_keys.csv").open(encoding="utf-8")))[1:]
    bucket_leaf = {r[1].split(".")[-1] for r in rows if len(r) > 1}
    return {
        "bucket键": bucket_leaf,
        "segment字段": {k for v in stats["segment_keys"].values() for k in v},
        "styles键": set(stats["text_style_keys"]),
        "关键帧类型": set(stats["keyframe_property_types"]),
        "material bucket": set(stats["buckets"]),
        "顶层键": set(stats["top_level_keys"]),
    }


def parse_catalog() -> dict[str, list[dict]]:
    """Extract (name, resource_id, effect_id, md5, numbers, booleans) per catalog entry."""
    out: dict[str, list[dict]] = {}
    for path in sorted(CATALOG_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        entries = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = META_CALL.search(line.strip())
            if not match:
                continue
            kind, arglist = match.groups()
            strings = STR_ARG.findall(arglist)
            numbers = [float(n) for n in NUM_ARG.findall(arglist)]
            flags = re.findall(r"\b(True|False)\b", arglist)
            if not strings:
                continue
            resource_id = next((s for s in strings if s.isdigit() and len(s) >= 10), None)
            effect_id = next((s for s in strings if s.isdigit() and 5 <= len(s) <= 9), None)
            digest = next((s for s in strings if re.fullmatch(r"[0-9a-f]{32}", s)), None)
            entries.append(
                {
                    "meta_kind": kind,
                    "name": strings[0],
                    "resource_id": resource_id,
                    "effect_id": effect_id,
                    "md5": digest,
                    "numbers": numbers,
                    "flags": flags,
                }
            )
        if entries:
            out[path.stem] = entries
    return out


def observed_ids() -> dict[str, dict[str, str]]:
    """Observed preset resource-ids by bucket, collected by corpus_presets.py (catalog-ready)."""
    presets = SCAN / "presets.csv"
    buckets = ("material_animations", "transitions", "effects", "stickers", "text_templates",
               "video_effects", "audio_effects", "common_mask", "masks")
    observed: dict[str, dict[str, str]] = {b: {} for b in buckets}
    if not presets.exists():
        return observed
    for row in csv.DictReader(presets.open(encoding="utf-8")):
        rid = row.get("resource_id") or ""
        bucket = row.get("bucket") or ""
        if not rid or rid == "None" or bucket not in observed:
            continue
        observed[bucket][rid] = row.get("name") or ""
    return observed


def check_package_locator(catalog: dict[str, list[dict]], per_file: int = 25) -> dict:
    """Sample each catalog file: can resource_id + md5 from their table find the package here?"""
    roots = [pathlib.Path(r"D:\JianyingPro\User Data\Cache\effect"),
             pathlib.Path(r"D:\JianyingPro\User Data\Cache\artistEffect")]
    per_file_result = {}
    for kind, entries in catalog.items():
        checked = hits = 0
        for item in entries:
            if not (item["resource_id"] and item["md5"]):
                continue
            checked += 1
            if any((root / item["resource_id"] / item["md5"]).exists() for root in roots):
                hits += 1
            if checked >= per_file:
                break
        if checked:
            per_file_result[kind] = {"checked": checked, "present": hits}
    total_checked = sum(v["checked"] for v in per_file_result.values())
    total_hits = sum(v["present"] for v in per_file_result.values())
    return {"per_file": per_file_result, "checked": total_checked, "package_present": total_hits,
            "present_pct": round(100 * total_hits / max(1, total_checked))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    blob, file_count = their_text()
    ours = load_our_inventory()
    coverage = {}
    for name, tokens in ours.items():
        present = {t for t in tokens if t in blob}
        coverage[name] = {"ours": len(tokens), "theirs": len(present), "pct": round(100 * len(present) / max(1, len(tokens)))}

    catalog = parse_catalog()
    observed = observed_ids()
    cat_names = {kind: {e["name"] for e in entries} for kind, entries in catalog.items()}
    cat_ids = {kind: {e["resource_id"] for e in entries if e["resource_id"]} for kind, entries in catalog.items()}

    def overlap(bucket: str, kinds: list[str]) -> dict:
        mapping = observed.get(bucket, {})
        ids = set().union(*(cat_ids.get(k, set()) for k in kinds)) if kinds else set()
        names = set().union(*(cat_names.get(k, set()) for k in kinds)) if kinds else set()
        hit_ids = {i for i in mapping if i in ids}
        hit_names = {n for n in mapping.values() if n in names}
        return {
            "catalog_entries": len(ids),
            "catalog_names": len(names),
            "observed_distinct": len(mapping),
            "observed_ids_in_catalog": len(hit_ids),
            "id_pct": round(100 * len(hit_ids) / max(1, len(mapping))),
            "observed_names_in_catalog": len(hit_names),
            "name_pct": round(100 * len(hit_names) / max(1, len({n for n in mapping.values() if n}))),
            "unmatched_samples": [mapping[i] for i in list(set(mapping) - ids)[:6]],
        }

    matches = {bucket: overlap(bucket, kinds) for bucket, kinds in CATALOG_MAP.items()}
    locator = check_package_locator(catalog)

    concepts = ["mix_mode", "common_mask", "responsive_layout", "is_minimal_draft", "animation_duration",
                "TextAnim", "useLetterColor", "thickness_projection_angle", "contour_path",
                "crypto_key_store", "track_render_index", "ShaderData", "BlendPreMul"]
    zero_hit = [c for c in concepts if c not in blob]

    result = {
        "their_files": file_count,
        "their_text_mb": round(len(blob) / 1e6, 2),
        "field_coverage": coverage,
        "zero_hit_concepts": zero_hit,
        "catalog_files": {k: len(v) for k, v in sorted(catalog.items(), key=lambda kv: -len(kv[1]))},
        "catalog_total_entries": sum(len(v) for v in catalog.values()),
        "catalog_match": matches,
        "package_locator_probe": locator,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0

    print(f"他们: {file_count} 个文本文件 / {result['their_text_mb']} MB")
    print("字段覆盖（我们清点 vs 他们提及）:")
    for k, v in coverage.items():
        print(f"  {k:16s} {v['ours']:4d} vs {v['theirs']:4d}  ({v['pct']}%)")
    print(f"他们零命中的概念: {zero_hit}")
    print(f"目录条目合计 {result['catalog_total_entries']}，分布: " +
          ", ".join(f"{k}={n}" for k, n in list(result['catalog_files'].items())[:8]))
    for bucket, match in matches.items():
        print(f"  [{bucket:20s}] 目录{match['catalog_entries']:5d} 条 | 我们观测{match['observed_distinct']:6d} 个 id | "
              f"id 命中 {match['id_pct']:3d}% | 名称命中 {match['name_pct']:3d}% | 未匹配样例 {match['unmatched_samples'][:4]}")
    print("包定位探针（用他们的 resource_id+md5 找本机预设包）:", json.dumps(locator, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
