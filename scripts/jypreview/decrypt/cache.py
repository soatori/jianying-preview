"""Fenced, content-addressed cache of decrypted draft content.

Fences (see plan "缓存写进草稿目录"):
1. Derived files may only land inside one dot-namespaced directory
   (``<draft>/.jypreview`` or ``~/.jypreview/cache/<did>``) and never inside
   ``Timelines/``, so the editor skill's replica discovery can never see them.
2. Files we did not create are never overwritten or deleted -- ``manifest.txt``
   is the sole proven record of ownership. Anything unexpected falls back to
   the user-level cache instead of touching the draft.
3. Writes are atomic (temp + ``os.replace``) and every read of draft files is
   ``open(..., "rb")``.
"""

from __future__ import annotations

import json
import os
import shutil
import hashlib
from pathlib import Path
from typing import Any

from ..config import DRAFT_CACHE_DIRNAME
from ..draft_id import draft_id, inside, normalize

MANIFEST_NAME = "manifest.txt"
SUBDIRS = ("content", "sidecar", "thumbs", "filmstrip", "shots")


def key_for(src: os.PathLike | str, data: bytes) -> tuple[str, str]:
    """Return ``(cache key, source sha256)``; the key is content-addressed."""
    digest = hashlib.sha256(data).hexdigest()
    return hashlib.sha1(f"{normalize(src)}|{digest}".encode("utf-8")).hexdigest()[:24], digest


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".tmp{os.getpid()}")
    with open(temp, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def _read_manifest(root: Path) -> set[str]:
    path = root / MANIFEST_NAME
    if not path.is_file():
        return set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    return {line.split("\t", 1)[0] for line in lines if line.strip()}


def _append_manifest(root: Path, rel: str) -> None:
    path = root / MANIFEST_NAME
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"{rel}\t{int(time_ns())}\n")


def time_ns() -> int:
    import time
    return time.time_ns()


def _prepared(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name in SUBDIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / "probe").mkdir(parents=True, exist_ok=True)
    return root


class DraftCache:
    """Per-draft derived-artifact store. Always construct through :meth:`open`."""

    def __init__(self, cfg, draft_dir: Path, did: str, root: Path, location: str,
                 fallback_reason: str | None = None):
        self.cfg = cfg
        self.draft_dir = Path(draft_dir)
        self.did = did
        self.root = Path(root)
        self.location = location
        self.fallback_reason = fallback_reason
        self._manifest = _read_manifest(self.root)
        self._new_files: list[str] = []

    @classmethod
    def user(cls, cfg, draft_dir: Path, did: str | None = None) -> "DraftCache":
        did = did or draft_id(draft_dir)
        return cls(cfg, Path(draft_dir), did, _prepared(Path(cfg.user_state_dir) / "cache" / did), "user")

    @classmethod
    def open(cls, cfg, draft_dir: Path, did: str | None = None) -> "DraftCache":
        did = did or draft_id(draft_dir)
        if cfg.cache_location == "user":
            return cls.user(cfg, draft_dir, did)

        draft_root = Path(draft_dir) / DRAFT_CACHE_DIRNAME
        if draft_root.exists() and not draft_root.is_dir():
            return cls(cfg, draft_dir, did, _prepared(Path(cfg.user_state_dir) / "cache" / did), "user",
                       f"{draft_root} exists as a file; using user cache")
        try:
            root = _prepared(draft_root)
            probe_file = root / ".writeprobe"
            probe_file.write_bytes(b"")
            probe_file.unlink()
        except OSError as exc:
            return cls(cfg, draft_dir, did, _prepared(Path(cfg.user_state_dir) / "cache" / did), "user",
                       f"draft cache unavailable ({exc.__class__.__name__}); using user cache")
        return cls(cfg, draft_dir, did, root, "draft")

    # -- guards ------------------------------------------------------------
    def _guard(self, target: Path) -> Path:
        resolved = Path(os.path.normcase(str(target.resolve() if target.exists() else
                                         (target.parent.resolve() / target.name))))
        if not inside(self.root, resolved):
            raise RuntimeError(f"cache fence violation: {resolved} is outside {self.root}")
        rel = os.path.relpath(str(resolved), str(self.root)).replace("\\", "/")
        if rel.startswith("Timelines/") or rel == "Timelines":
            raise RuntimeError("cache fence violation: never write under Timelines/")
        return resolved

    def _claim(self, target: Path) -> Path | None:
        resolved = self._guard(target)
        rel = os.path.relpath(str(resolved), str(self.root)).replace("\\", "/")
        if resolved.exists() and rel not in self._manifest:
            return None
        return resolved

    # -- content -----------------------------------------------------------
    def content_path(self, key: str) -> Path:
        return self.root / "content" / f"{key}.json"

    def sidecar_path(self, key: str) -> Path:
        return self.root / "sidecar" / f"{key}.json"

    def get(self, key: str) -> tuple[bytes, dict] | None:
        content, sidecar = self.content_path(key), self.sidecar_path(key)
        if not content.is_file() or not sidecar.is_file():
            return None
        try:
            data = content.read_bytes()
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if hashlib.sha256(data).hexdigest() != meta.get("plain_sha256"):
            return None
        return data, meta

    def put(self, key: str, payload: bytes, sidecar: dict) -> tuple[Path, str | None]:
        """Write canonical JSON + sidecar. Returns (path, fallback_reason)."""
        sidecar = dict(sidecar)
        sidecar["plain_sha256"] = hashlib.sha256(payload).hexdigest()
        targets = [(self.content_path(f"{key}.json"), payload),
                   (self.sidecar_path(f"{key}.json"),
                    json.dumps(sidecar, ensure_ascii=False, sort_keys=True).encode("utf-8"))]
        claimed = []
        for target, blob in targets:
            resolved = self._claim(target)
            if resolved is None:
                return target, "unowned path"
            claimed.append((resolved, blob))
        for resolved, blob in claimed:
            _write_atomic(resolved, blob)
            rel = os.path.relpath(str(resolved), str(self.root)).replace("\\", "/")
            if rel not in self._manifest:
                self._manifest.add(rel)
                self._new_files.append(rel)
                _append_manifest(self.root, rel)
        return claimed[0][0], None

    def put_extra(self, rel: str, payload: bytes) -> Path | None:
        """Cache auxiliary artifacts (filmstrips, shots). Same ownership rules."""
        target = self._claim(self.root / rel)
        if target is None:
            return None
        _write_atomic(target, payload)
        key = os.path.relpath(str(target), str(self.root)).replace("\\", "/")
        if key not in self._manifest:
            self._manifest.add(key)
            self._new_files.append(key)
            _append_manifest(self.root, key)
        return target

    def get_extra(self, rel: str) -> bytes | None:
        target = self.root / rel
        if not target.is_file():
            return None
        try:
            self._guard(target)
        except RuntimeError:
            return None
        return target.read_bytes()

    # -- timeline index ----------------------------------------------------
    @property
    def index_path(self) -> Path:
        return self.root / "index.json"

    def load_index(self) -> dict[str, Any]:
        if not self.index_path.is_file():
            return {}
        try:
            value = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def save_index(self, data: dict[str, Any]) -> None:
        payload = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
        target = self._claim(self.index_path)
        if target is None:
            return
        _write_atomic(target, payload)
        rel = os.path.relpath(str(target), str(self.root)).replace("\\", "/")
        if rel not in self._manifest:
            self._manifest.add(rel)
            self._new_files.append(rel)
            _append_manifest(self.root, rel)

    # -- maintenance -------------------------------------------------------
    def total_bytes(self) -> int:
        return sum(f.stat().st_size for f in self.root.rglob("*") if f.is_file())

    def prune(self, max_mb: int) -> int:
        limit = max_mb * 1024 * 1024
        current = self.total_bytes()
        if current <= limit:
            return 0
        files = [f for f in (self.root / "content").glob("*.json") if f.is_file()]
        files.sort(key=lambda f: max(f.stat().st_atime_ns, f.stat().st_mtime_ns))
        rel_prefix = "content/"
        removed = 0
        for path in files:
            if current <= limit:
                break
            rel = rel_prefix + path.name
            if rel not in self._manifest:
                continue
            sidecar = self.sidecar_path(path.stem)
            size = path.stat().st_size
            path.unlink(missing_ok=True)
            if sidecar.is_file() and f"sidecar/{sidecar.name}" in self._manifest:
                size += sidecar.stat().st_size
                sidecar.unlink(missing_ok=True)
            current -= size
            removed += 1
        return removed

    def clean(self) -> int:
        """Delete only what this cache owns; keep the dir if anything is left."""
        removed = 0
        for rel in sorted(self._manifest, key=lambda value: value.count("/"), reverse=True):
            target = self.root / rel
            if target.is_file():
                target.unlink()
                removed += 1
        manifest = self.root / MANIFEST_NAME
        if manifest.is_file():
            manifest.unlink()
            removed += 1
        leftovers = [p for p in self.root.rglob("*") if p.is_file()]
        if not leftovers:
            shutil.rmtree(self.root, ignore_errors=True)
        return removed

    def describe(self) -> dict[str, Any]:
        return {
            "did": self.did,
            "root": str(self.root),
            "location": self.location,
            "fallback_reason": self.fallback_reason,
            "owned_files": len(self._manifest),
            "bytes": self.total_bytes(),
        }
