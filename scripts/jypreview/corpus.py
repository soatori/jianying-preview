"""Corpus enumeration and cheap classification (never decrypts, never writes to drafts)."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import DRAFT_CACHE_DIRNAME
from .draft_id import draft_id

CONTENT_NAMES = ("draft_content.json", "draft_info.json")
SKIP_EXACT = {DRAFT_CACHE_DIRNAME, ".recycle_bin", ".workbuddy", "__pycache__", "Resources",
              "OnlineResources", "Cache", "Apps", "User Data"}
SKIP_PREFIXES = (".cloud_cache_", ".tmp", "~$", "$")


def _is_skipped(name: str) -> bool:
    return name in SKIP_EXACT or any(name.startswith(prefix) for prefix in SKIP_PREFIXES)


def looks_like_draft(path: Path) -> bool:
    if not path.is_dir():
        return False
    for name in CONTENT_NAMES:
        if (path / name).is_file():
            return True
    if (path / "draft_meta_info.json").is_file() and (path / "Timelines").is_dir():
        return True
    timelines = path / "Timelines"
    if timelines.is_dir():
        for entry in timelines.iterdir():
            if entry.is_dir() and any((entry / name).is_file() for name in CONTENT_NAMES):
                return True
    return False


def _plain_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return None
    if not data.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"{"):
        return None
    try:
        value = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _first_byte(path: Path) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read(1)
    except OSError:
        return b""


def primary_for(draft: Path, tid: str | None = None) -> Path | None:
    """Always prefer ``Timelines/<tid>/draft_content.json`` over the root mirror."""
    if tid:
        for name in CONTENT_NAMES:
            candidate = draft / "Timelines" / str(tid) / name
            if candidate.is_file():
                return candidate
        matches = sorted(path for name in CONTENT_NAMES
                         for path in (draft / "Timelines").glob(f"*/{name}"))
        if matches:
            return matches[0]
    for name in CONTENT_NAMES:
        candidate = draft / name
        if candidate.is_file():
            return candidate
    return None


def layout_kind(draft: Path, index: dict | None, entries: list[dict]) -> str:
    has_root = any((draft / name).is_file() for name in CONTENT_NAMES)
    has_index = bool(index) and bool(entries)
    has_per_timeline = any((draft / "Timelines" / str(item.get("id"))).is_dir() for item in entries)
    if has_index and has_per_timeline and has_root:
        return "hybrid"
    if has_index and has_per_timeline:
        return "multi-timeline"
    if has_root and not has_index:
        return "legacy-single"
    return "unknown"


def classify(draft: Path) -> dict[str, Any]:
    draft = Path(draft)
    index = _plain_json(draft / "Timelines" / "project.json") or _plain_json(draft / "project.json")
    entries = [item for item in ((index or {}).get("timelines") or []) if isinstance(item, dict)]
    layout = _plain_json(draft / "timeline_layout.json")
    primary = primary_for(draft, entries[0]["id"] if entries else None)
    encoding = "unknown"
    if primary is not None:
        encoding = "plaintext" if _first_byte(primary) == b"{" else "jianying-dll"
    root_primary = next((draft / name for name in CONTENT_NAMES if (draft / name).is_file()), None)
    root_id = None
    if root_primary is not None and _first_byte(root_primary) == b"{":
        root_id = str((_plain_json(root_primary) or {}).get("id") or "") or None

    active = None
    source = None
    if layout:
        for key in ("activeTimeline", "active_timeline_id", "timeline_id"):
            value = layout.get(key)
            if isinstance(value, str) and value:
                active, source = value, f"timeline_layout.json:{key}"
                break
    if not active and root_id:
        active, source = root_id, "root draft_content.json:id"
    if not active and isinstance(index, dict) and index.get("main_timeline_id"):
        active, source = str(index["main_timeline_id"]), "project index:main_timeline_id"
    if not active and len(entries) == 1:
        active, source = str(entries[0].get("id")), "sole non-deleted timeline"

    known_ids = {str(item.get("id")) for item in entries}
    if active and known_ids and active not in known_ids:
        active, source = None, f"unresolved (layout pointed at {active})"

    timelines = []
    for item in entries:
        tid = str(item.get("id"))
        path = primary_for(draft, tid)
        timelines.append({
            "id": tid,
            "name": item.get("name") or draft.name,
            "deleted": bool(item.get("is_marked_delete", False)),
            "active": tid == active,
            "primary": str(path) if path else None,
            "primary_rel": str(path.relative_to(draft)).replace("\\", "/") if path else None,
            "encoding": ("plaintext" if path and _first_byte(path) == b"{" else
                         "jianying-dll" if path else "unknown"),
            "create_time": item.get("create_time"),
            "update_time": item.get("update_time"),
        })
    if not timelines and root_primary is not None:
        path = root_primary
        timelines.append({
            "id": root_id or "legacy-root", "name": draft.name, "deleted": False, "active": True,
            "primary": str(path), "primary_rel": path.name,
            "encoding": "plaintext" if _first_byte(path) == b"{" else "jianying-dll",
            "create_time": None, "update_time": None,
        })
        if not active:
            active, source = timelines[0]["id"], "legacy root content"

    try:
        mtime = (root_primary or draft).stat().st_mtime
    except OSError:
        mtime = 0
    cached_index = _plain_json(draft / DRAFT_CACHE_DIRNAME / "index.json") or {}
    durations = {str(key): value.get("duration_us") for key, value in cached_index.items()
                 if isinstance(value, dict)}
    for item in timelines:
        item["duration_us"] = durations.get(item["id"])

    return {
        "did": draft_id(draft),
        "name": draft.name,
        "path": str(draft),
        "layout": layout_kind(draft, index, entries),
        "has_content": primary is not None,
        "encoding": encoding,
        "timeline_count": len(timelines),
        "active_timeline_id": active,
        "active_source": source,
        "timelines": timelines,
        "cover": (draft / "draft_cover.jpg").is_file(),
        "note": None if primary is not None else "no draft_content.json under root or Timelines/<id>/",
        "mtime_iso": datetime.fromtimestamp(mtime, timezone.utc).astimezone().isoformat(timespec="seconds")
                     if mtime else None,
        "cache_present": (draft / DRAFT_CACHE_DIRNAME).is_dir(),
    }


def draft_dirs(root: Path, include_empty: bool = True) -> Iterable[Path]:
    """Yield draft candidates.

    ``include_empty`` keeps project folders that have no parseable content so the
    UI can say why they cannot be opened instead of silently hiding them.
    """
    root = Path(root)
    if looks_like_draft(root):
        yield root
        return
    try:
        children = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name)
    except OSError:
        return
    for child in children:
        if _is_skipped(child.name):
            continue
        if include_empty or looks_like_draft(child):
            yield child


def scan(root: Path, progress: bool = False) -> list[dict]:
    rows = []
    started = time.monotonic()
    for index, draft in enumerate(draft_dirs(root), 1):
        try:
            rows.append(classify(draft))
        except Exception as exc:
            rows.append({"did": draft_id(draft), "name": draft.name, "path": str(draft),
                         "has_content": False, "error": f"{exc.__class__.__name__}: {exc}",
                         "timelines": [], "layout": "unknown", "encoding": "unknown",
                         "timeline_count": 0, "active_timeline_id": None, "cover": False})
        if progress and index % 100 == 0:
            print(f"scanned {index} ({time.monotonic() - started:.1f}s)", flush=True)
    return rows


def write_index(path: Path, drafts_root: Path, rows: list[dict]) -> dict:
    summary = {
        "built_at": int(time.time()),
        "drafts_root": str(drafts_root),
        "count": len(rows),
        "encrypted": sum(1 for row in rows if row.get("encoding") == "jianying-dll"),
        "plaintext": sum(1 for row in rows if row.get("encoding") == "plaintext"),
        "without_content": sum(1 for row in rows if not row.get("has_content")),
        "rows": rows,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)
    return {key: value for key, value in summary.items() if key != "rows"}


def load_index(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) and "rows" in value else None


def normalize_selector(selector: str) -> str:
    """Trim the noise people paste with a path: quotes, whitespace, trailing separators."""
    text = str(selector or "").strip().strip('"').strip("'").strip()
    while text[-1:] in ("\\", "/"):
        text = text[:-1].rstrip()
    return text


def _mtime_key(row: dict) -> str:
    return str(row.get("mtime_iso") or row.get("mtime") or "")


def _tiers(rows: list[dict], needle: str) -> dict[int, list[dict]]:
    """Group candidate drafts by match quality: 0 exact, 1 prefix, 2 substring, 3 word overlap."""
    lowered = needle.lower()
    buckets: dict[int, list[dict]] = {}
    for row in rows:
        low = str(row.get("name", "")).lower()
        if low == lowered:
            score = 0
        elif low.startswith(lowered):
            score = 1
        elif lowered in low:
            score = 2
        elif any(part and part.lower() in lowered for part in low.split()):
            score = 3          # "<日期> <英文名>" style word overlap
        else:
            continue
        buckets.setdefault(score, []).append(row)
    for bucket in buckets.values():
        bucket.sort(key=_mtime_key, reverse=True)
    return buckets


def suggest(index: dict, selector: str, limit: int = 8) -> list[dict]:
    """Ranked near-misses so the caller can show "did you mean" instead of a dead end."""
    needle = normalize_selector(selector)
    if not needle:
        return []
    rows = [row for row in index.get("rows", []) if row.get("has_content")]
    out, seen = [], set()
    tiers = _tiers(rows, needle)
    for score in sorted(tiers):
        for row in tiers[score]:
            if row["did"] in seen:
                continue
            seen.add(row["did"])
            out.append({"did": row["did"], "name": row.get("name"), "path": row.get("path"),
                        "mtime": row.get("mtime_iso"), "timeline_count": row.get("timeline_count"),
                        "layout": row.get("layout")})
            if len(out) >= limit:
                return out
    return out


def resolve(index: dict, selector: str) -> dict | None:
    """Accept a draft id, an exact folder name, an unambiguous partial name, or a draft path.

    An ambiguous partial name returns None on purpose: this tool exists to verify edits against
    one specific draft, so quietly substituting a similarly named draft would validate the wrong
    timeline. Callers should offer suggest() instead of guessing.
    """
    rows = index.get("rows", [])
    needle = normalize_selector(selector)
    if not needle:
        return None
    # First try: treat as an absolute path and match directly by path
    for candidate in (needle, needle.replace("\\", "/")):
        as_path = Path(candidate)
        if as_path.is_dir():
            target = draft_id(as_path)
            found = next((row for row in rows if row["did"] == target), None)
            if found:
                return found
    direct = next((row for row in rows if row["did"] == needle), None)
    if direct:
        return direct
    term = needle.split("/")[-1].split("\\")[-1] if Path(needle).is_absolute() else needle
    buckets = _tiers([row for row in rows if row.get("has_content")], term)
    if not buckets:
        return None
    best = buckets[min(buckets)]
    return best[0] if len(best) == 1 else None
