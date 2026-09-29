"""Media path recovery and codec probing.

Most recent drafts reference media that still exists; older drafts in this corpus
reference files that were moved or deleted, so every miss has to become an honest
placeholder tile rather than a black box.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
AUDIO_EXTS = {".mp3", ".aac", ".m4a", ".wav", ".ogg", ".flac"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts"}
CHROMIUM_VIDEO = {"h264", "vp8", "vp9", "av1"}
CHROMIUM_AUDIO = {"aac", "mp3", "opus", "vorbis", "flac", "pcm_s16le"}

PLACEHOLDER_RE = re.compile(r"^##(_?draftpath_placeholder_?[0-9A-Fa-f\-]+)_?_##[/\\]?(.*)$")

_basename_cache: dict[tuple[str, str], str | None] = {}


def is_image(path: str) -> bool:
    return Path(str(path)).suffix.lower() in IMAGE_EXTS


def media_family(path: str | None) -> str:
    if not path:
        return "unknown"
    suffix = Path(str(path)).suffix.lower()
    if suffix in IMAGE_EXTS:
        return "image"
    if suffix in AUDIO_EXTS:
        return "audio"
    if suffix in VIDEO_EXTS:
        return "video"
    return "unknown"


def _candidates(raw: str, draft_root: Path) -> list[Path]:
    root = Path(draft_root)
    value = str(raw or "").strip().strip('"')
    if not value:
        return []
    out: list[Path] = []
    direct = Path(value)
    out.append(direct)
    match = PLACEHOLDER_RE.match(value)
    if match:
        rest = match.group(2)
        if rest:
            out.append(root / rest.replace("/", os.sep))
    if not direct.is_absolute() and not re.match(r"^[A-Za-z]:", value):
        out.append(root / value.replace("/", os.sep))
    out.append(root / "materials" / direct.name)
    out.append(root / "media" / direct.name)
    if match:
        out.append(root / "materials" / Path(match.group(2)).name)
    moved = re.match(r"^([A-Za-z]:)[/\\]+JianyingPro Materials[/\\](.*)$", value)
    if moved:
        out.append(Path(f"{moved.group(1)}{os.sep}JianyingPro{os.sep}JianyingPro Materials"
                        f"{os.sep}{moved.group(2)}"))
    return out


def resolve(raw: str, draft_root: Path, *, scan_basenames: bool = True) -> dict[str, Any]:
    """Locate a material's file on disk, recording how it was found."""
    value = str(raw or "")
    if not value:
        return {"path": None, "exists": False, "how": "empty_path", "family": "unknown",
                "name": "", "recovered": False}
    for candidate in _candidates(value, draft_root):
        if candidate.is_file():
            return {"path": str(candidate.resolve()), "exists": True, "how": "direct",
                    "family": media_family(str(candidate)), "name": candidate.name,
                    "recovered": normalize_compare(candidate) != normalize_compare(Path(value))
                    if _is_abs(value) else False}
    if scan_basenames:
        name = Path(value.replace("/", os.sep)).name
        if name:
            found = _find_by_name(draft_root, name)
            if found:
                return {"path": found, "exists": True, "how": "basename_index",
                        "family": media_family(found), "name": Path(found).name, "recovered": True}
    return {"path": None, "exists": False, "how": "missing",
            "family": media_family(value), "name": Path(value.replace("/", os.sep)).name,
            "recovered": False}


def _is_abs(value: str) -> bool:
    try:
        return bool(re.match(r"^[A-Za-z]:[\\/]", value)) or Path(value).is_absolute()
    except OSError:
        return False


def normalize_compare(path: Path) -> str:
    return os.path.normcase(str(path))


def _find_by_name(draft_root: Path, name: str) -> str | None:
    key = (normalize_compare(Path(draft_root)), name)
    if key in _basename_cache:
        return _basename_cache[key]
    found = None
    try:
        for candidate in Path(draft_root).rglob(name):
            if candidate.is_file():
                found = str(candidate.resolve())
                break
    except (OSError, RecursionError):
        found = None
    _basename_cache[key] = found
    return found


def probe(path: str, cache_dir: Path, timeout: float = 8.0) -> dict[str, Any]:
    """ffprobe JSON, cached by path identity. Never raises."""
    record = {"path": path, "codec": None, "width": None, "height": None,
              "duration_us": None, "frame_rate": None, "audio_codec": None, "error": None}
    target = Path(path)
    if not target.is_file():
        record["error"] = "missing"
        return record
    info = target.stat()
    key = f"{os.path.normcase(str(target))}|{info.st_mtime_ns}|{info.st_size}"
    import hashlib

    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{digest}.json"
    if cached.is_file():
        try:
            stored = json.loads(cached.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                return stored
        except (OSError, json.JSONDecodeError):
            pass
    cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(target)]
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, creationflags=flags)
        data = json.loads(done.stdout or "{}")
    except FileNotFoundError:
        record["error"] = "ffprobe_missing"
        return record
    except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
        record["error"] = f"{exc.__class__.__name__}"
        return record
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    fmt = data.get("format", {})
    record.update({
        "codec": video.get("codec_name") or (audio.get("codec_name") if not video else None),
        "width": int(video["width"]) if video.get("width") else None,
        "height": int(video["height"]) if video.get("height") else None,
        "pix_fmt": video.get("pix_fmt"),
        "duration_us": int(round(float(fmt["duration"]) * 1e6)) if fmt.get("duration") else None,
        "frame_rate": _rate(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        "audio_codec": audio.get("codec_name"),
        "channels": int(audio["channels"]) if audio.get("channels") else None,
    })
    try:
        cached.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return record


def _rate(value: str | None) -> float | None:
    if not value or value in ("0/0", "0/1"):
        return None
    try:
        num, _, den = str(value).partition("/")
        left, right = float(num), float(den or 1)
        return round(left / right, 4) if right else None
    except ValueError:
        return None


def playable_in_browser(probe_result: dict[str, Any], family: str) -> tuple[bool, str | None]:
    if family == "audio":
        codec = probe_result.get("audio_codec") or probe_result.get("codec")
    else:
        codec = probe_result.get("codec")
    if not codec:
        return False, "codec_unknown"
    allowed = CHROMIUM_AUDIO if family == "audio" else (
        CHROMIUM_VIDEO | {"png", "mjpeg", "gif", "webp", "bmp"} if family == "image" else CHROMIUM_VIDEO)
    if codec in allowed:
        return True, None
    return False, f"codec_{codec}"
