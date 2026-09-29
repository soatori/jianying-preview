"""Runtime lookup over the generated effect catalog."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

PATH_ID_RE = re.compile(r"/(effect|artistEffect)/([^/]+)/([0-9a-f]{32})")

KIND_ALIASES = {
    "transition": ("transition",),
    "animation": ("animation_in", "animation_out", "animation_loop"),
    "animation_in": ("animation_in", "text_animation_in"),
    "animation_out": ("animation_out", "text_animation_out"),
    "animation_loop": ("animation_loop", "text_animation_loop"),
    "video_effect": ("scene_effect", "character_effect"),
    "filter": ("filter",),
    "flower": ("flower", "text_effect"),
    "font": ("font",),
    "sticker": ("sticker",),
    "text_template": ("text_template", "subtitle_template"),
    "mask": ("mask",),
}


def ids_from_path(path: str | None) -> tuple[str | None, str | None]:
    if not path:
        return None, None
    match = PATH_ID_RE.search(str(path).replace("\\", "/"))
    if not match:
        return None, None
    return match.group(2), match.group(3)


class EffectCatalog:
    def __init__(self, entries: list[dict[str, Any]], meta: dict[str, Any] | None = None):
        self.entries = entries
        self.meta = meta or {}
        self.by_effect: dict[str, dict] = {}
        self.by_resource: dict[str, dict] = {}
        self.by_md5: dict[str, dict] = {}
        self.by_name: dict[str, dict] = {}
        for entry in entries:
            for field, index in (("effect_id", self.by_effect), ("resource_id", self.by_resource),
                                 ("md5", self.by_md5)):
                value = entry.get(field)
                if value and value not in index:
                    index[value] = entry
            name = entry.get("name")
            if name:
                self.by_name.setdefault(f"{entry.get('kind')}:{name}", entry)
                self.by_name.setdefault(f"any:{name}", entry)

    @classmethod
    def load(cls, path: Path, jianying_version: str | None = None,
             allow_version_skew: bool = False) -> "EffectCatalog | None":
        path = Path(path)
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries = payload.get("entries") or []
        meta_path = path.with_suffix(".meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
        catalog = cls(entries, meta)
        catalog.version_skew = bool(jianying_version and meta.get("jianying_version")
                                    and str(jianying_version) != str(meta.get("jianying_version")))
        if catalog.version_skew and not allow_version_skew:
            raise RuntimeError(
                f"catalog was built for JianYing {meta.get('jianying_version')} but "
                f"{jianying_version} is installed. Rebuild: python scripts/preview.py catalog")
        return catalog

    def lookup(self, kind: str, material: dict[str, Any], name: str | None = None) -> dict[str, Any]:
        wanted = KIND_ALIASES.get(kind, (kind,))
        path_id, path_md5 = ids_from_path(material.get("path"))
        candidates = [path_md5 and self.by_md5.get(path_md5),
                      material.get("effect_id") and self.by_effect.get(str(material["effect_id"])),
                      (material.get("id") if kind.startswith("animation") else None) and
                      self.by_effect.get(str(material["id"])),
                      material.get("resource_id") and self.by_resource.get(str(material["resource_id"])),
                      path_id and (self.by_resource.get(str(path_id)) or
                                   self.by_effect.get(str(path_id))),
                      (name or material.get("name")) and
                      self.by_name.get(f"{kind}:{name or material.get('name')}"),
                      (name or material.get("name")) and
                      self.by_name.get(f"any:{name or material.get('name')}")]
        for found in candidates:
            if not found:
                continue
            if wanted and found.get("kind") not in wanted and found.get("kind") not in (
                    KIND_ALIASES.get(kind, ())):
                continue
            return found
        for found in filter(None, candidates):
            return found
        return {}

    def flower_lookup(self, effect_style: dict[str, Any], material: dict[str, Any]) -> dict[str, Any]:
        """Resolve a 花字 (text effect style) id into a renderable recipe reference."""
        ident = str(effect_style.get("id") or "") or None
        path_id, path_md5 = ids_from_path(effect_style.get("path") or material.get("path"))
        found = (self.by_md5.get(path_md5 or "") or self.by_resource.get(ident or "")
                 or self.by_effect.get(ident or "") or self.by_name.get(f"flower:{material.get('name')}")
                 or {})
        bundle = found.get("bundle") or {}
        resource_id = str(bundle.get("id") or path_id or ident or "") or None
        md5 = str(bundle.get("md5") or path_md5 or "") or None
        render_class = found.get("render_class") or ("exact" if bundle.get("has_effectstyle")
                                                     else "placeholder")
        if not bundle.get("has_effectstyle"):
            render_class = "placeholder"
        return {
            "resource_id": resource_id or ident, "md5": md5, "name": found.get("name")
            or material.get("name"), "render_class": render_class,
            "recipe": f"/effectstyle?rid={resource_id}&md5={md5}" if resource_id and md5 else None,
            "bundle": bundle.get("rel"), "is_vip": found.get("is_vip"),
        }

    def category_name(self, category_id: Any) -> str | None:
        return (self.meta.get("categories") or {}).get(str(category_id))

    def search(self, query: str = "", kind: str = "", render_class: str = "",
               limit: int = 50) -> list[dict[str, Any]]:
        needle = (query or "").lower()
        out = []
        for entry in self.entries:
            if kind and entry.get("kind") != kind:
                continue
            if render_class and entry.get("render_class") != render_class:
                continue
            if needle and needle not in str(entry.get("name", "")).lower() \
                    and needle not in str(entry.get("effect_id", "")) \
                    and needle not in str(entry.get("resource_id", "")):
                continue
            out.append(entry)
            if len(out) >= limit:
                break
        return out

    def describe(self) -> dict[str, Any]:
        return {"entries": len(self.entries), "built_at": self.meta.get("built_at"),
                "jianying_version": self.meta.get("jianying_version"),
                "counts": self.meta.get("counts"), "render_class_counts": self.meta.get("render_class_counts"),
                "rp_db": self.meta.get("rp_db"), "build_seconds": self.meta.get("build_seconds")}
