"""Opaque identifiers for drafts whose folder names carry CJK, spaces and parens."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def normalize(path: os.PathLike | str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(str(path))))


def draft_id(path: os.PathLike | str) -> str:
    return hashlib.sha1(normalize(path).encode("utf-8")).hexdigest()[:16]


def is_same(a: os.PathLike | str, b: os.PathLike | str) -> bool:
    return normalize(a) == normalize(b)


def safe_rel(path: str) -> str:
    """Reject traversal/absolute fragments coming from query strings."""
    if not path or path.startswith(("/", "\\")) or "\x00" in path:
        raise ValueError(f"unsafe relative path: {path!r}")
    parts = path.replace("\\", "/").split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"unsafe relative path: {path!r}")
    return os.path.join(*parts)


def inside(parent: Path, target: Path) -> bool:
    base = normalize(parent)
    value = normalize(target)
    return value == base or value.startswith(base.rstrip("\\/") + os.sep)
