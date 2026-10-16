"""Collect preset identity records from the decrypted corpus plaintext.

The first-level scan keyed materials by their instance UUID, which cannot be
aligned with any resource catalog. This script captures the fields that CAN be
aligned -- resource_id / effect_id / the package md5 directory / default duration
-- and checks whether each preset package actually exists on this machine.

Output: temp/corpus-scan/presets.json + presets.csv (no draft paths, no user text).

Usage:
  python scripts/corpus_presets.py
"""

from __future__ import annotations

import collections
import csv
import json
import pathlib
import re

SCAN = pathlib.Path(__file__).resolve().parents[1] / "temp" / "corpus-scan"
CACHE_ROOTS = [
    pathlib.Path(r"D:\JianyingPro\User Data\Cache\effect"),
    pathlib.Path(r"D:\JianyingPro\User Data\Cache\artistEffect"),
]
MD5_RE = re.compile(r"^[0-9a-f]{32}$")

# bucket -> (list container path, kind field)
BUCKETS = {
    "material_animations": "animations",
    "transitions": None,
    "effects": None,
    "stickers": None,
    "text_templates": None,
    "video_effects": None,
    "audio_effects": None,
    "common_mask": None,
    "masks": None,
    "fonts": None,
    "hsl": None,
    "color_curves": None,
    "shapes": None,
}


def package_md5(path_value: object) -> str | None:
    if not isinstance(path_value, str):
        return None
    parts = pathlib.PurePath(path_value.replace("\\", "/")).parts
    for part in reversed(parts):
        if MD5_RE.match(part):
            return part
    return None


def package_present(resource_id: str | None, md5: str | None) -> bool | None:
    if not resource_id or not md5:
        return None
    for root in CACHE_ROOTS:
        if (root / str(resource_id) / md5).exists():
            return True
    return False


def records_from(container: dict, bucket: str, parent: str = "") -> list[dict]:
    items = container.get(bucket)
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = bucket if bucket != "material_animations" else str(item.get("type") or "animation_set")
        resource_id = item.get("resource_id")
        md5 = package_md5(item.get("path"))
        record = {
            "bucket": bucket,
            "kind": kind,
            "parent": parent,
            "name": item.get("name") if isinstance(item.get("name"), str) else None,
            "type": item.get("type") if isinstance(item.get("type"), str) else None,
            "category_id": str(item.get("category_id")) if item.get("category_id") not in (None, "") else None,
            "category_name": item.get("category_name") if isinstance(item.get("category_name"), str) else None,
            "resource_id": str(resource_id) if resource_id not in (None, "") else None,
            "effect_id": str(item.get("effect_id")) if item.get("effect_id") not in (None, "") else None,
            "md5": md5,
            "duration": item.get("duration"),
            "is_overlap": item.get("is_overlap"),
            "start": item.get("start"),
            "ttype": item.get("ttype"),
            "value": item.get("value"),
            "package_present": package_present(str(resource_id) if resource_id else None, md5),
            "instance_uuid": item.get("id") if isinstance(item.get("id"), str) else None,
        }
        out.append(record)
        nested = item.get("animations")
        if isinstance(nested, list):
            for anim in nested:
                if not isinstance(anim, dict):
                    continue
                rid = anim.get("resource_id")
                md5 = package_md5(anim.get("path"))
                out.append(
                    {
                        "bucket": bucket,
                        "kind": str(anim.get("type") or "animation"),
                        "parent": "material_animations",
                        "name": anim.get("name") if isinstance(anim.get("name"), str) else None,
                        "type": anim.get("type") if isinstance(anim.get("type"), str) else None,
                        "category_id": str(anim.get("category_id")) if anim.get("category_id") not in (None, "") else None,
                        "category_name": anim.get("category_name") if isinstance(anim.get("category_name"), str) else None,
                        "resource_id": str(rid) if rid not in (None, "") else None,
                        "effect_id": str(anim.get("effect_id")) if anim.get("effect_id") not in (None, "") else None,
                        "md5": md5,
                        "duration": anim.get("duration"),
                        "is_overlap": anim.get("is_overlap"),
                        "start": anim.get("start"),
                        "ttype": anim.get("ttype"),
                        "value": None,
                        "package_present": package_present(str(rid) if rid else None, md5),
                        "instance_uuid": anim.get("id") if isinstance(anim.get("id"), str) else None,
                    }
                )
    return out


def main() -> int:
    manifest = json.loads((SCAN / "manifest.json").read_text(encoding="utf-8"))
    records: list[dict] = []
    seen: set[str] = set()
    drafts = 0
    for entry in manifest:
        key = entry.get("key")
        if not key or key in seen:
            continue
        seen.add(key)
        src = pathlib.Path(entry["path"]) if entry.get("encoding") == "plain" else SCAN / "plain" / f"{key}.json"
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
        if not isinstance(materials, dict):
            continue
        for bucket in BUCKETS:
            records.extend(records_from(materials, bucket))
        # 复合片段内部的预设同样要采（外层与嵌套是两套资源引用）
        for nested in materials.get("drafts") or []:
            inner = (nested or {}).get("draft") if isinstance(nested, dict) else None
            inner_materials = (inner or {}).get("materials") if isinstance(inner, dict) else None
            if isinstance(inner_materials, dict):
                for bucket in BUCKETS:
                    records.extend(records_from(inner_materials, bucket, parent="drafts"))

    distinct = collections.Counter(
        (r["bucket"], r["kind"], r["name"], r["resource_id"], r["effect_id"], r["md5"], r["category_name"]) for r in records
    )
    located = [r for r in records if r["resource_id"] and r["md5"]]
    present = sum(1 for r in located if r["package_present"])
    summary = {
        "drafts_scanned": drafts,
        "records": len(records),
        "distinct_presets": len(distinct),
        "records_with_resource_id": sum(1 for r in records if r["resource_id"]),
        "records_locatable": len(located),
        "locatable_package_present": present,
        "by_bucket_records": dict(collections.Counter(r["bucket"] for r in records).most_common()),
        "by_bucket_locatable": dict(collections.Counter(r["bucket"] for r in located).most_common()),
    }
    out_json = SCAN / "presets.json"
    out_json.write_text(json.dumps({"summary": summary, "records_sample": records[:50]}, ensure_ascii=False, indent=1), encoding="utf-8")
    out_csv = SCAN / "presets.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["bucket", "kind", "name", "resource_id", "effect_id", "md5", "category_name", "count", "duration_seen", "overlap_seen"])
        for key, count in distinct.most_common():
            bucket, kind, name, resource_id, effect_id, md5, category_name = key
            sample = next((r for r in records if (r["bucket"], r["kind"], r["name"], r["resource_id"], r["effect_id"], r["md5"], r["category_name"]) == key), {})
            writer.writerow([bucket, kind, name, resource_id, effect_id, md5, category_name, count, sample.get("duration"), sample.get("is_overlap")])
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
