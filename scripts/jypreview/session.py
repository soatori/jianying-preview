"""One place that wires config + ingest + model together (used by CLI and server)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from . import corpus
from .config import Config
from .decrypt.cache import DraftCache
from .decrypt.manager import DecryptManager
from .draft_id import draft_id
from .files import FileRegistry
from .model.content import TimelineContent
from .model.fonts import FontIndex
from .model import framedesc


class DraftNotFound(LookupError):
    def __init__(self, selector: str, code: str = "draft_not_found",
                 candidates: list[dict[str, Any]] | None = None, hint: str = ""):
        super().__init__(f"cannot resolve draft: {selector!r}")
        self.selector, self.code = selector, code
        self.candidates = candidates or []
        self.hint = hint


class TimelineNotFound(LookupError):
    def __init__(self, selector: str, available: list[str]):
        super().__init__(f"cannot resolve timeline: {selector!r}")
        self.selector, self.available = selector, available


class DraftView:
    def __init__(self, session: "PreviewSession", row: dict[str, Any], cache: DraftCache,
                 probe: dict[str, Any]):
        self.session = session
        self.row = row
        self.cache = cache
        self.probe = probe
        self.root = Path(row["path"])
        self.did = row["did"]
        self._contents: dict[str, tuple[TimelineContent, dict]] = {}

    @property
    def name(self) -> str:
        return self.row["name"]

    @property
    def layout(self) -> str:
        return self.probe.get("layout") or self.row.get("layout") or "unknown"

    @property
    def timelines(self) -> list[dict[str, Any]]:
        return self.probe.get("timelines", [])

    @property
    def active_timeline_id(self) -> str | None:
        return self.probe.get("active_timeline_id")

    @property
    def mirror(self) -> dict[str, Any]:
        if not hasattr(self, "_mirror"):
            self._mirror = self.session.manager.mirror_drift(self.probe)
        return self._mirror

    def resolve_timeline(self, selector: str | None) -> dict[str, Any]:
        entries = self.timelines
        if not entries:
            raise TimelineNotFound(str(selector), [])
        if selector in (None, "", "active"):
            active = self.active_timeline_id
            if not active:
                raise TimelineNotFound("active", [str(item.get("id")) for item in entries])
            selector = active
        text = str(selector)
        matches = [item for item in entries if str(item.get("id")).upper() == text.upper()
                   or str(item.get("name")) == text]
        if not matches:
            try:
                index = int(text)
                if 0 <= index < len(entries):
                    matches = [entries[index]]
            except ValueError:
                pass
        if len(matches) != 1:
            raise TimelineNotFound(text, [str(item.get("id")) for item in entries])
        return matches[0]

    def content(self, tid: str) -> tuple[TimelineContent, dict]:
        entry = next((item for item in self.timelines if str(item.get("id")).upper() == str(tid).upper()), None)
        if entry is None:
            raise TimelineNotFound(tid, [str(item.get("id")) for item in self.timelines])
        cached = self._contents.get(str(tid))
        if cached:
            return cached
        value, meta = self.session.manager.content(self.root, tid, self.probe, cache=self.cache)
        content = TimelineContent.build(value, meta={**meta, "tid": tid, "layout": self.layout})
        self._contents[str(tid)] = (content, meta)
        return self._contents[str(tid)]

    def describe(self) -> dict[str, Any]:
        mirror = self.mirror
        timelines = []
        for entry in self.timelines:
            primary = entry.get("primary")
            rel = None
            if primary:
                try:
                    rel = str(Path(primary).relative_to(self.root)).replace("\\", "/")
                except ValueError:
                    rel = Path(primary).name
            timelines.append({
                "id": entry.get("id"), "name": entry.get("name"), "deleted": entry.get("deleted"),
                "active": entry.get("id") == self.active_timeline_id,
                "encoding": entry.get("encoding"), "duration_us": entry.get("duration_us"),
                "content_rel": rel, "content_exists": bool(primary) and Path(primary).is_file(),
                "replica_count": len(entry.get("replicas", [])),
                "replica_errors": entry.get("replica_errors", []),
            })
        return {
            "did": self.did, "name": self.name, "path": str(self.root), "layout": self.layout,
            "active_timeline_id": self.active_timeline_id,
            "active_evidence": self.probe.get("active_evidence", []),
            "mirror_drift": mirror, "timelines": timelines, "cache": self.cache.describe(),
        }

    def frame(self, tid: str, t_us: int, ratio: str | None = None,
              window: tuple[int, int] | None = None) -> dict[str, Any]:
        content, meta = self.content(tid)
        entry = next((item for item in self.timelines if str(item.get("id")).upper() == str(tid).upper()), {})
        primary = entry.get("primary")
        rel = None
        if primary:
            try:
                rel = str(Path(primary).relative_to(self.root)).replace("\\", "/")
            except ValueError:
                rel = Path(primary).name
        return self.session.frame(content, meta, t_us, draft_root=self.root, did=self.did,
                                  timeline_info={"layout": self.layout, "name": entry.get("name"),
                                                 "encoding": entry.get("encoding"),
                                                 "content_rel": rel,
                                                 "mirror_drift": self.mirror.get("drift", False),
                                                 "replica_errors": entry.get("replica_errors", [])},
                                  ratio=ratio, window=window)


class PreviewSession:
    def __init__(self, config: Config):
        self.config = config
        self.manager = DecryptManager(config)
        self.registry = FileRegistry(Path(config.user_state_dir) / "file_registry.json")
        self._views: dict[str, DraftView] = {}
        self._lock = threading.Lock()
        self._last_rescan = 0.0
        roots: list[Path] = []
        if config.effect_cache:
            roots.append(Path(config.effect_cache))
        if config.install_root:
            roots.append(Path(config.install_root))
        self.font_index = FontIndex(roots, Path(config.user_state_dir))
        self.catalog = None
        self.catalog_error: str | None = None
        self.catalog_path = Path(__file__).resolve().parents[2] / "assets" / "generated" / \
            "effect_catalog.json"
        try:
            from .model.catalog import EffectCatalog

            version = Path(self.manager.dll_path).parent.name if self.manager.dll_path else None
            self.catalog = EffectCatalog.load(self.catalog_path, jianying_version=version,
                                              allow_version_skew=config.allow_catalog_skew)
        except Exception as exc:
            self.catalog_error = f"{exc.__class__.__name__}: {exc}"

    # -- corpus ------------------------------------------------------------
    def index(self, refresh: bool = False) -> dict[str, Any]:
        data = corpus.load_index(self.config.corpus_index_path)
        if data is None or refresh:
            summary = corpus.write_index(self.config.corpus_index_path, self.config.drafts_root,
                                         corpus.scan(self.config.drafts_root))
            data = corpus.load_index(self.config.corpus_index_path) or {"rows": []}
            data["rescan"] = summary
        return data

    def row(self, selector: str) -> dict[str, Any]:
        raw = str(selector or "").strip().strip('"').strip()
        path = Path(raw)
        if not path.is_dir() and Path(raw.replace("\\", "/")).is_dir():
            path = Path(raw.replace("\\", "/"))
        if path.is_dir():
            return corpus.classify(path)
        data = self.index()
        found = corpus.resolve(data, raw)
        if found is None and time.time() - self._last_rescan > 60:
            # Drafts created after the index was built are invisible until a rescan; a miss is
            # the only signal we need, so re-scan once instead of telling the user "not found".
            self._last_rescan = time.time()
            data = self.index(refresh=True)
            found = corpus.resolve(data, raw)
        if found is None:
            hint = ""
            if path.is_absolute():
                hint = (f"{path} exists but is not a JianYing draft folder (no draft_content.json "
                        f"and no Timelines/<id>/draft_content.json)") if path.parent.is_dir() else \
                       f"{path} does not exist"
            raise DraftNotFound(raw, candidates=corpus.suggest(data, raw), hint=hint)
        return found

    def view(self, selector: str, force: bool = False) -> DraftView:
        row = self.row(selector)
        if not row.get("has_content"):
            raise DraftNotFound(row["name"], "draft_without_content")
        cache = self.manager.cache_for(Path(row["path"]), row["did"])
        with self._lock:
            key = f"{row['did']}:{cache.location}"
            existing = self._views.get(key)
            if existing and not force:
                return existing
            probe = self.manager.probe(Path(row["path"]), row["did"], force=force, cache=cache)
            view = DraftView(self, row, cache, probe)
            self._views[key] = view
            return view

    # -- model -------------------------------------------------------------
    def frame(self, content: TimelineContent, meta: dict, t_us: int, *, draft_root: Path, did: str,
              timeline_info: dict | None = None, ratio: str | None = None,
              window: tuple[int, int] | None = None) -> dict[str, Any]:
        return framedesc.build_frame(
            content, int(t_us), self.config, draft_root=Path(draft_root), did=did,
            timeline_info=timeline_info or {}, registry=self.registry, font_index=self.font_index,
            effect_cache=self.config.effect_cache, install_fonts=self.config.install_fonts,
            catalog=self.catalog, probe_cache=Path(self.config.user_state_dir) / "probes",
            ratio=ratio, window=window)

    def state(self) -> dict[str, Any]:
        return {
            "config": self.config.to_dict(), "jianying_dll": self.manager.dll_path,
            "decrypt": self.manager.stats, "cache_views": len(self._views),
            "font_index": {"files": self.font_index.size()},
            "catalog": None if self.catalog is None else self.catalog.describe(),
            "catalog_error": self.catalog_error,
            "catalog_path": str(self.catalog_path),
        }
