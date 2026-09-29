"""Measure how many real draft material ids the catalog actually resolves.

Only plaintext drafts are scanned: decrypting 316 files to run a lookup report would
cost more than it teaches, and the plaintext half is representative of every bucket.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from jypreview import corpus  # noqa: E402
from jypreview.draft_id import draft_id  # noqa: E402
from jypreview.model.catalog import EffectCatalog, ids_from_path  # noqa: E402

BUCKETS = ("transitions", "video_effects", "effects", "material_animations", "stickers",
           "text_templates")


def collect(draft_root: Path, limit: int | None = None) -> dict[str, dict[str, str]]:
    """bucket -> {lookup key: display name} for every plaintext draft in the corpus."""
    found: dict[str, dict[str, str]] = {name: {} for name in BUCKETS}
    found["fonts"] = {}
    found["flowers"] = {}
    rows = corpus.scan(draft_root)
    scanned = 0
    for row in rows:
        if row.get("encoding") != "plaintext":
            continue
        if limit and scanned >= limit:
            break
        path = Path(row["path"]) / "draft_content.json"
        if not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        scanned += 1
        materials = value.get("materials") or {}
        for bucket in BUCKETS:
            for item in materials.get(bucket) or []:
                if not isinstance(item, dict):
                    continue
                key = _key_for(bucket, item)
                if key:
                    found[bucket].setdefault(key, str(item.get("name") or ""))
        for text in materials.get("texts") or []:
            if not isinstance(text, dict):
                continue
            if text.get("font_resource_id"):
                found["fonts"].setdefault(f"rid:{text['font_resource_id']}",
                                          str(text.get("font_title") or ""))
            content = text.get("content")
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except json.JSONDecodeError:
                    continue
            for style in (content or {}).get("styles") or []:
                font = style.get("font") or {}
                if font.get("id"):
                    found["fonts"].setdefault(f"rid:{font['id']}", "")
                flower = style.get("effectStyle") or {}
                if flower.get("id"):
                    found["flowers"].setdefault(f"rid:{flower['id']}",
                                                str(text.get("name") or ""))
    return found


def _key_for(bucket: str, item: dict[str, Any]) -> str | None:
    path_id, path_md5 = ids_from_path(item.get("path"))
    if path_md5:
        return f"md5:{path_md5}"
    if path_id:
        return f"id:{path_id}"
    if bucket == "material_animations":
        for inner in item.get("animations") or []:
            ident = inner.get("resource_id") or inner.get("id")
            if ident:
                return f"id:{ident}"
        return None
    for field in ("effect_id", "resource_id"):
        if item.get(field):
            return f"id:{item[field]}"
    return None


def report(catalog: EffectCatalog, collected: dict[str, dict[str, str]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for bucket, keys in collected.items():
        resolved = 0
        named = 0
        unresolved: list[str] = []
        for key, name in keys.items():
            kind = {"effects": "flower", "fonts": "font", "material_animations": "animation",
                    "transitions": "transition", "video_effects": "video_effect",
                    "stickers": "sticker", "text_templates": "text_template"}.get(bucket, bucket)
            ident = key.split(":", 1)[1]
            if key.startswith("md5"):
                found = catalog.by_md5.get(ident)
            else:
                found = catalog.by_resource.get(ident) or catalog.by_effect.get(ident)
            if not found and name:
                found = catalog.by_name.get(f"any:{name}")
            if found:
                resolved += 1
                if found.get("name"):
                    named += 1
            elif len(unresolved) < 8:
                unresolved.append(f"{key} {name}".strip())
        out[bucket] = {"unique_ids": len(keys), "resolved": resolved,
                       "with_chinese_name": named,
                       "ratio": round(resolved / len(keys), 3) if keys else None,
                       "unresolved_sample": unresolved}
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drafts-root", required=True)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    catalog = EffectCatalog.load(Path(args.catalog))
    if catalog is None:
        print(json.dumps({"ok": False, "code": "catalog_missing", "reason": args.catalog, "data": {}}))
        return 1
    collected = collect(Path(args.drafts_root), args.limit)
    data = report(catalog, collected)
    total_ids = sum(item["unique_ids"] for item in data.values())
    total_resolved = sum(item["resolved"] for item in data.values())
    payload = {"drafts_scanned": "plaintext only", "total_unique_ids": total_ids,
               "total_resolved": total_resolved,
               "overall_ratio": round(total_resolved / total_ids, 3) if total_ids else None,
               "buckets": data}
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps({"ok": True, "code": "ok", "reason": "", "data": payload},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    main()
