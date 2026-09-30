"""Font resolution for text layers.

JianYing stores a font as ``{resource_id, path}`` where ``path`` points into its
material cache. In this corpus the recorded absolute path only hits 38.8% of the
time (drive letters move, caches get pruned), so the ladder below walks the
alternative keys ``Cache/effect`` uses before giving up.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..draft_id import draft_id

SYSTEM_STACK = '"Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif'
FONT_SUFFIXES = {".ttf", ".otf", ".ttc"}
LADDER = ("exact_path", "rid_dir", "effectid_dir", "ai_text_template", "cache_basename",
          "install_font", "system_stack")


@dataclass
class FontRef:
    family: str
    path: str | None
    source: str
    resource_id: str | None = None
    title: str | None = None
    served: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"family": self.family, "resource_id": self.resource_id, "title": self.title,
                "source": self.source, "src": self.served, "file": self.path}


class FontIndex:
    """Lazily built ``basename -> paths`` map over the JianYing material caches."""

    def __init__(self, search_roots: list[Path], state_dir: Path):
        self.search_roots = [Path(root) for root in search_roots if root]
        self.state_path = Path(state_dir) / "font_index.json"
        self._by_name: dict[str, list[str]] = {}
        self._loaded = False

    def _signature(self) -> str:
        return "|".join(sorted(str(root) for root in self.search_roots))

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        signature = self._signature()
        if self.state_path.is_file():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                if data.get("roots") == signature and isinstance(data.get("index"), dict):
                    self._by_name = data["index"]
                    return
            except (OSError, json.JSONDecodeError):
                pass
        index: dict[str, list[str]] = {}
        for root in self.search_roots:
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if path.is_file() and path.suffix.lower() in FONT_SUFFIXES:
                    index.setdefault(path.name.lower(), []).append(str(path.resolve()))
        self._by_name = index
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps({"roots": signature, "index": index},
                                                  ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def by_name(self, name: str) -> list[str]:
        if not name:
            return []
        self._load()
        return self._by_name.get(name.lower(), [])

    def size(self) -> int:
        self._load()
        return sum(len(v) for v in self._by_name.values())


def _names(index, name: str) -> list[str]:
    return index.by_name(name) if index is not None and name else []


def _font_entries(material: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in (material.get("fonts") or []) if isinstance(item, dict)]


def _glob_id_dir(cache: Path, ident: str, name: str) -> Path | None:
    if not cache.is_dir() or not ident:
        return None
    for pattern in (f"effect/{ident}/*/{name}", f"artistEffect/{ident}/*/{name}",
                    f"effect/{ident}/*/*{Path(name).stem}*"):
        matches = sorted(cache.glob(pattern))
        for match in matches:
            if match.is_file() and match.suffix.lower() in FONT_SUFFIXES:
                return match
    return None


def resolve(material: dict[str, Any], style_font: dict[str, Any] | None, index: FontIndex,
            effect_cache: Path | None, install_fonts: Path | None, registry=None) -> FontRef:
    """Return the first font the browser can actually load, plus how it was found."""
    style_font = style_font or {}
    raw_path = str(style_font.get("path") or material.get("font_path") or "").strip()
    name = Path(raw_path.replace("\\", "/")).name if raw_path else ""
    rid = str(style_font.get("id") or material.get("font_resource_id") or "").strip() or None
    title = (str(material.get("font_title") or "").strip()
             or str(material.get("font_name") or "").strip() or None)
    ids = [rid] + [str(item.get("resource_id") or "") or str(item.get("effect_id") or "")
                   for item in _font_entries(material)]
    ids = [item for item in ids if item]
    cache = Path(effect_cache) if effect_cache else None

    hits: list[tuple[str, Path]] = []
    if raw_path:
        hits.append(("exact_path", Path(raw_path)))
    if cache and name:
        for ident in ids[:1]:
            found = _glob_id_dir(cache, ident, name)
            if found:
                hits.append(("rid_dir", found))
        for ident in ids[1:]:
            found = _glob_id_dir(cache, ident, name)
            if found:
                hits.append(("effectid_dir", found))
                break
        for candidate in _names(index, name):
            path = Path(candidate)
            if "AITextTemplate" in str(path):
                hits.append(("ai_text_template", path))
                break
        for candidate in _names(index, name):
            hits.append(("cache_basename", Path(candidate)))
    if title and install_fonts:
        for suffix in (".ttf", ".otf"):
            hits.append(("install_font", Path(install_fonts) / f"{title}{suffix}"))

    for source, path in hits:
        if path.is_file():
            key = draft_id(path)
            served = None
            if registry is not None:
                registered = registry.register(path, "font")
                served = f"/font?f={registered}" if registered else None
            return FontRef(family=f"jyfont-{key[:12]}", path=str(path.resolve()), source=source,
                           resource_id=rid, title=title, served=served or f"/font?f={key}")
    return FontRef(family=SYSTEM_STACK, path=None, source="system_stack", resource_id=rid,
                   title=title, served=None)


def css_block(refs: list[FontRef]) -> str:
    rules = []
    seen = set()
    for ref in refs:
        if not ref.path or not ref.served or ref.family in seen:
            continue
        seen.add(ref.family)
        rules.append(f"/* {ref.source}: {ref.title or ref.resource_id or ''} */\n"
                     f"@font-face {{ font-family: '{ref.family}'; src: url('{ref.served}');"
                     f" font-display: block; }}")
    return "\n".join(rules) if rules else "/* no loadable fonts */"
