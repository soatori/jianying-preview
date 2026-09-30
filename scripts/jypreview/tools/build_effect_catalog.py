"""Build ``assets/generated/effect_catalog.json``: the 对照表.

Three layers, cheapest first, each cross-validating the previous one:
1. the editor skill's vendored ``pyJianYingDraft`` metadata enums (deterministic,
   offline, ~4.5k rows and complete for transitions/animations/scene effects);
2. JianYing's own resource SDK cache (``ressdk_db/*/rp.db`` -> ``http_cache``),
   which is where 花字/贴纸/模板 names and cover art live;
3. the on-disk bundles under ``Cache/effect`` and ``Cache/artistEffect``, which is
   what decides whether we can actually render something instead of labelling it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))

from jypreview.skill_import import SCRIPTS_DIR, find_jianying_dll  # noqa: E402
from jypreview.model.labels import APPROX_BY_KEYWORD, TRANSITION_APPROX  # noqa: E402

VENDOR_KINDS = (
    ("TransitionType", "transition"),
    ("IntroType", "animation_in"),
    ("OutroType", "animation_out"),
    ("GroupAnimationType", "animation_loop"),
    ("TextIntro", "text_animation_in"),
    ("TextOutro", "text_animation_out"),
    ("TextLoopAnim", "text_animation_loop"),
    ("FilterType", "filter"),
    ("FontType", "font"),
    ("VideoSceneEffectType", "scene_effect"),
    ("VideoCharacterEffectType", "character_effect"),
    ("AudioSceneEffectType", "audio_effect"),
    ("ToneEffectType", "tone"),
    ("MaskType", "mask"),
)

EFFECT_TYPE_KIND = {
    1: "flower", 2: "sticker", 3: "audio_effect", 5: "insert", 6: "text_template",
    7: "scene_effect", 8: "face_prop", 9: "base_image", 12: "filter", 19: "transition",
    20: "beauty", 21: "beauty", 46: "ai_painting", 48: "subtitle_template", 50: "composition",
    58: "digital_human", 97: "mask", 121: "beauty", 148: "beauty",
}

MD5_RE = re.compile(r"^[0-9a-f]{32}$")


def _already_us(value: Any) -> int | None:
    """``AnimationMeta.duration`` and ``TransitionMeta.default_duration`` are already
    microseconds: their constructors convert the seconds literal in the source."""
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _us(seconds: Any) -> int | None:
    try:
        return int(round(float(seconds) * 1_000_000))
    except (TypeError, ValueError):
        return None


def vendor_entries() -> list[dict[str, Any]]:
    sys.path.insert(0, str(SCRIPTS_DIR))
    from pyJianYingDraft import metadata as meta

    out: list[dict[str, Any]] = []
    for class_name, kind in VENDOR_KINDS:
        enum = getattr(meta, class_name, None)
        if enum is None:
            continue
        for member in enum:
            value = member.value
            name = str(getattr(value, "name", None) or getattr(value, "title", "") or
                       member.name.lstrip("_"))
            entry = {
                "kind": kind, "name": name, "enum_key": member.name, "source": "vendor",
                "effect_id": str(getattr(value, "effect_id", "") or "") or None,
                "resource_id": str(getattr(value, "resource_id", "") or "") or None,
                "md5": str(getattr(value, "md5", "") or "") or None,
                "is_vip": bool(getattr(value, "is_vip", False)),
                "duration_us": _already_us(getattr(value, "duration", None)),
                "is_overlap": getattr(value, "is_overlap", None),
                "params": [{"name": param.name, "default": param.default_value,
                            "min": param.min_value, "max": param.max_value}
                           for param in (getattr(value, "params", None) or [])],
            }
            if entry["duration_us"] is None:
                entry["duration_us"] = _already_us(getattr(value, "default_duration", None))
            out.append(entry)
    return out


def _walk_effect_items(node: Any, sink: list[dict]) -> None:
    if isinstance(node, list):
        for item in node:
            _walk_effect_items(item, sink)
        return
    if not isinstance(node, dict):
        return
    common = node.get("common_attr")
    if isinstance(common, dict) and (common.get("id") or common.get("effect_id")):
        sink.append(node)
    for key in ("data", "effect_item_list", "item_list", "list", "result"):
        if key in node:
            _walk_effect_items(node[key], sink)


def rp_db_entries(cache_root: Path, limit_rows: int | None = None) -> tuple[list[dict], dict]:
    """Read-only harvest of JianYing's own resource SDK database."""
    db_root = Path(cache_root) / "ressdk_db"
    entries: list[dict[str, Any]] = []
    categories: dict[str, str] = {}
    stats: dict[str, Any] = {"shards": [], "rows": 0, "items": 0}
    if not db_root.is_dir():
        return entries, stats
    for shard in sorted(db_root.glob("*/rp.db")):
        record = {"shard": shard.parent.name, "size": shard.stat().st_size}
        try:
            connection = sqlite3.connect(f"file:{shard.as_posix()}?mode=ro", uri=True, timeout=0.2)
            connection.text_factory = str
        except sqlite3.Error as exc:
            record["error"] = str(exc)
            stats["shards"].append(record)
            continue
        try:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "http_cache" not in tables:
                record["skipped"] = "no http_cache table"
                stats["shards"].append(record)
                continue
            rows = connection.execute("SELECT url, response_body FROM http_cache")
            shard_items = 0
            for url, body in rows:
                if not body:
                    continue
                stats["rows"] += 1
                try:
                    payload = json.loads(body)
                except (json.JSONDecodeError, TypeError):
                    continue
                found: list[dict] = []
                _walk_effect_items(payload, found)
                for item in found:
                    common = item.get("common_attr") or {}
                    entries.append(_rp_entry(common, url))
                    shard_items += 1
                if "get_panel_info" in str(url):
                    _collect_categories(payload, categories)
                if limit_rows and shard_items >= limit_rows:
                    break
            record["items"] = shard_items
        except sqlite3.Error as exc:
            record["error"] = str(exc)
        finally:
            connection.close()
        stats["shards"].append(record)
        stats["items"] += record.get("items", 0)
    return [entry for entry in entries if entry], stats


def _safe_json(text: Any) -> dict:
    if isinstance(text, dict):
        return text
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _rp_entry(common: dict, url: str) -> dict[str, Any] | None:
    ident = str(common.get("effect_id") or common.get("id") or "") or None
    resource = str(common.get("resource_id") or common.get("id") or "") or None
    if not ident and not resource:
        return None
    sdk = _safe_json(common.get("sdk_extra"))
    extra = _safe_json(common.get("extra"))
    transition = sdk.get("transition") if isinstance(sdk.get("transition"), dict) else {}
    panel = ""
    match = re.search(r"_([a-z0-9\-]+)_jianyingpro", str(url))
    if match:
        panel = match.group(1)
    kind = EFFECT_TYPE_KIND.get(int(common.get("effect_type") or 0)) or panel or "unknown"
    return {
        "kind": kind, "name": str(common.get("title") or common.get("description") or "") or None,
        "source": "rp_db", "effect_id": ident, "resource_id": resource,
        "md5": str(common.get("md5") or "") or None, "is_vip": bool(extra.get("is_vip")),
        "duration_us": _us(transition.get("defaultDura")),
        "is_overlap": transition.get("isOverlap"),
        "cover_url": ((common.get("cover_url") or {}).get("static_img")
                      or (common.get("cover_url") or {}).get("small")),
        "panel": panel, "effect_type": common.get("effect_type"),
        "category_ids": common.get("category_ids") or [],
    }


def _collect_categories(payload: Any, sink: dict[str, str]) -> None:
    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if isinstance(node, dict):
            ident = node.get("category_id") or node.get("id")
            title = node.get("title") or node.get("name") or node.get("category_name")
            if ident is not None and isinstance(title, str) and title:
                sink[str(ident)] = title
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)

    walk(payload)


def probe_bundle(cache_root: Path, entry: dict[str, Any]) -> dict[str, Any] | None:
    cache_root = Path(cache_root)
    for bucket, ident in (("effect", entry.get("effect_id")), ("effect", entry.get("resource_id")),
                          ("artistEffect", entry.get("resource_id")), ("artistEffect", entry.get("effect_id"))):
        if not ident:
            continue
        base = cache_root / bucket / str(ident)
        if not base.is_dir():
            continue
        for md5_dir in sorted(base.iterdir()):
            if not md5_dir.is_dir():
                continue
            files = [path.name for path in md5_dir.iterdir()]
            font_file = next((name for name in files
                              if Path(name).suffix.lower() in (".ttf", ".otf")), None)
            return {"bucket": bucket, "id": str(ident), "md5": md5_dir.name,
                    "rel": f"{bucket}/{ident}/{md5_dir.name}", "files": files[:40],
                    "has_frag": any(name.endswith(".frag") for name in files),
                    "has_effectstyle": "effectStyle.json" in files,
                    "has_cover": any(name in ("cover_icon.png", "cover_icon.gif") for name in files),
                    "font_file": font_file}
    return None


def keyword_approx(kind: str, name: str | None) -> dict[str, Any] | None:
    text = (name or "").lower()
    if kind.startswith("transition"):
        for keywords, impl in TRANSITION_APPROX:
            if any(keyword.lower() in text for keyword in keywords):
                return {"impl": impl}
    for keywords, (impl, start, end) in APPROX_BY_KEYWORD:
        if any(keyword.lower() in text for keyword in keywords):
            return {"impl": impl, "from": start, "to": end}
    return None


def assign_class(entry: dict[str, Any], bundle: dict | None, overrides: dict[str, Any]) -> None:
    name = entry.get("name")
    key = f"{entry.get('kind')}:{name}" if name else None
    override = overrides.get(key) or overrides.get(str(entry.get("effect_id"))) or \
        overrides.get(str(entry.get("resource_id")))
    if override:
        entry["approx"] = override
        entry["render_class"] = "exact" if override.get("impl") == "exact" else "approx"
        return
    if bundle and bundle.get("has_effectstyle"):
        entry["render_class"] = "exact"
        return
    if entry.get("kind") == "font" and bundle and bundle.get("font_file"):
        entry["render_class"] = "exact"
        return
    approx = keyword_approx(str(entry.get("kind")), name)
    if approx and entry.get("kind") != "font":
        entry["approx"] = approx
        entry["render_class"] = "approx"
        return
    entry["render_class"] = "placeholder"


def build(cache_root: Path | None, out_dir: Path, use_rp_db: bool = True,
          skip_names: bool = False) -> dict[str, Any]:
    started = time.monotonic()
    entries = vendor_entries()
    if use_rp_db and cache_root:
        rp_entries, rp_stats = rp_db_entries(Path(cache_root))
        seen = {(entry.get("kind"), entry.get("effect_id"), entry.get("resource_id"), entry.get("md5"))
                for entry in entries}
        for entry in rp_entries:
            key = (entry.get("kind"), entry.get("effect_id"), entry.get("resource_id"), entry.get("md5"))
            if key in seen:
                continue
            seen.add(key)
            entries.append(entry)
    else:
        rp_stats = {"skipped": "disabled" if not use_rp_db else "no cache root"}

    overrides_path = out_dir / "approx_overrides.json"
    overrides = json.loads(overrides_path.read_text(encoding="utf-8")) if overrides_path.is_file() else {}

    if cache_root:
        for entry in entries:
            bundle = probe_bundle(Path(cache_root), entry)
            if bundle:
                entry["bundle"] = bundle
            assign_class(entry, bundle, overrides)
    else:
        for entry in entries:
            entry["render_class"] = "placeholder"

    by_effect: dict[str, dict] = {}
    by_resource: dict[str, dict] = {}
    by_md5: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    for entry in entries:
        for field, index in (("effect_id", by_effect), ("resource_id", by_resource), ("md5", by_md5)):
            value = entry.get(field)
            if value and value not in index:
                index[value] = entry
        name = entry.get("name")
        if name:
            by_name.setdefault(f"{entry.get('kind')}:{name}", entry)

    dll = None
    version = None
    try:
        dll = find_jianying_dll()
        version = Path(dll).parent.name
    except Exception:
        pass
    counts: dict[str, int] = {}
    classes: dict[str, int] = {}
    for entry in entries:
        counts[entry["kind"]] = counts.get(entry["kind"], 0) + 1
        classes[entry["render_class"]] = classes.get(entry["render_class"], 0) + 1

    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {"schema": "jy-preview/catalog@1", "entries": entries,
               "categories": rp_stats.get("categories") or {}}
    (out_dir / "effect_catalog.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    metadata = {
        "built_at": int(time.time()), "jianying_version": version, "dll": dll,
        "vendor_metadata_sha256": _hash_tree(SCRIPTS_DIR / "vendor" / "pyJianYingDraft" / "metadata"),
        "cache_root": str(cache_root) if cache_root else None,
        "rp_db": {key: value for key, value in rp_stats.items() if key != "categories"},
        "counts": counts, "render_class_counts": classes, "total": len(entries),
        "build_seconds": round(time.monotonic() - started, 2),
    }
    (out_dir / "effect_catalog.meta.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=1), encoding="utf-8")
    return metadata


def _hash_tree(root: Path) -> str | None:
    if not root.is_dir():
        return None
    digest = hashlib.sha256()
    for path in sorted(root.glob("*.py")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", help="JianYing data root holding User Data/Cache")
    parser.add_argument("--out", default=str(SKILL_ROOT / "assets" / "generated"))
    parser.add_argument("--no-rp-db", action="store_true", help="vendor enums only (fast, offline-safe)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    cache_root = Path(args.cache_root) if args.cache_root else None
    if cache_root is None:
        from jypreview.config import detect_drafts_root, detect_jianying_root

        jianying = detect_jianying_root(detect_drafts_root())
        cache_root = (Path(jianying) / "User Data" / "Cache") if jianying else None
    metadata = build(cache_root, Path(args.out), use_rp_db=not args.no_rp_db)
    if args.json:
        print(json.dumps({"ok": True, "code": "ok", "reason": "", "data": metadata},
                         ensure_ascii=False))
    else:
        print(json.dumps(metadata, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
