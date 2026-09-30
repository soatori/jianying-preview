"""Opaque key -> absolute path registry for every file the server may serve.

Serving is allow-list based: ``/media``, ``/font`` and ``/image`` only accept
``?f=<key>`` and never a caller-supplied path, so there is no traversal surface.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from .draft_id import draft_id, normalize

MAX_RECORDS = 20000


class FileRegistry:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._records: dict[str, dict[str, Any]] = {}
        self._by_file: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        records = data.get("records") if isinstance(data, dict) else None
        if isinstance(records, dict):
            self._records = records
            self._by_file = {rec["norm"]: key for key, rec in self._records.items()
                             if isinstance(rec, dict) and rec.get("norm")}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps({"saved_at": int(time.time()), "records": self._records},
                                   ensure_ascii=False), encoding="utf-8")
        os.replace(temp, self.path)

    def register(self, target: str | os.PathLike, kind: str = "media") -> str | None:
        path = Path(str(target))
        if not path.is_file():
            return None
        norm = normalize(path)
        key = draft_id(norm)
        with self._lock:
            existing = self._records.get(key)
            if existing and existing.get("norm") == norm:
                existing["kind"] = kind
                existing["seen"] = int(time.time())
                return key
            self._records[key] = {"norm": norm, "path": str(path), "kind": kind,
                                  "seen": int(time.time())}
            self._by_file[norm] = key
            if len(self._records) > MAX_RECORDS:
                self._prune_locked()
            self._save()
        return key

    def key_for(self, target: str | os.PathLike) -> str | None:
        key = self._by_file.get(normalize(target))
        return key if key and key in self._records else None

    def resolve(self, key: str) -> dict[str, Any] | None:
        record = self._records.get(str(key))
        if not record:
            return None
        path = Path(record["path"])
        if not path.is_file():
            record["missing"] = True
            return None
        return {**record, "path": str(path), "size": path.stat().st_size,
                "mtime": path.stat().st_mtime, "missing": False}

    def _prune_locked(self) -> None:
        stale = [key for key, record in self._records.items() if record.get("missing")]
        for key in stale[: len(self._records) // 2]:
            record = self._records.pop(key, None)
            if record:
                self._by_file.pop(record.get("norm", ""), None)
        if len(self._records) > MAX_RECORDS:
            ordered = sorted(self._records.items(), key=lambda item: item[1].get("seen", 0))
            for key, record in ordered[: len(self._records) - MAX_RECORDS]:
                self._records.pop(key, None)
                self._by_file.pop(record.get("norm", ""), None)
