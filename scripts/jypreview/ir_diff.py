"""Layer-level diff of two FrameDescriptors: the agent's edit-verification channel."""

from __future__ import annotations

from typing import Any

TEXT_FIELDS = ("text", "em_px", "font_family", "fill", "stroke_count", "shadow_count",
               "flower", "cx_px", "cy_px", "alignment")
MEDIA_FIELDS = ("material_name", "exists", "path", "codec", "w_px", "h_px", "cx_px", "cy_px",
                "rotation_deg", "alpha", "source_time_us", "speed")
LABEL_FIELDS = ("label_names", "transition", "animation", "keyframe_props")


def _fill_text(run: dict) -> str:
    fill = run.get("fill") or {}
    if fill.get("render_type") == "gradient":
        return "gradient:" + "/".join(stop.get("css", "") for stop in fill.get("stops") or [])
    return f"{fill.get('render_type')}:{fill.get('css')}"


def fingerprint(layer: dict[str, Any]) -> dict[str, Any]:
    time = layer.get("time") or {}
    base = {
        "kind": layer.get("kind"), "track": (layer.get("track") or {}).get("name"),
        "track_type": (layer.get("track") or {}).get("type"),
        "z_order": (layer.get("z") or {}).get("order"),
        "start_us": time.get("target_start_us"), "duration_us": time.get("target_duration_us"),
        "label_names": ",".join(f"{label.get('name')}[{label.get('render_class')}]"
                                for label in layer.get("labels") or []),
        "transition": ((layer.get("transition") or {}).get("name")),
        "animation": ((layer.get("animation") or {}).get("name")),
        "keyframe_props": ",".join(item.get("property", "") for item in layer.get("keyframes") or []),
    }
    rect = layer.get("rect") or {}
    base.update({"cx_px": rect.get("cx_px"), "cy_px": rect.get("cy_px"), "w_px": rect.get("w_px"),
                 "h_px": rect.get("h_px"), "rotation_deg": rect.get("rotation_deg"),
                 "alpha": rect.get("alpha")})
    media = layer.get("media") or {}
    if media:
        base.update({"material_name": media.get("material_name"), "exists": media.get("exists"),
                     "path": media.get("path"), "how": media.get("how"),
                     "codec": (media.get("probe") or {}).get("codec"),
                     "source_time_us": time.get("source_time_us"), "speed": time.get("speed")})
    text = layer.get("text") or {}
    if text:
        runs = text.get("runs") or []
        first = runs[0] if runs else {}
        box = text.get("box") or {}
        base.update({"text": text.get("text"), "em_px": box.get("em_px"),
                     "font_family": (text.get("font") or {}).get("title")
                                    or (text.get("font") or {}).get("resource_id"),
                     "font_source": (text.get("font") or {}).get("source"),
                     "fill": _fill_text(first), "stroke_count": len(first.get("strokes") or []),
                     "shadow_count": len(first.get("shadows") or []),
                     "flower": (first.get("flower") or {}).get("resource_id"),
                     "alignment": box.get("alignment"), "line_count": box.get("line_count"),
                     "letter_spacing_px": (text.get("deco") or {}).get("letter_spacing_px")})
    return base


def diff(left: dict[str, Any], right: dict[str, Any], *, only: list[str] | None = None) -> dict[str, Any]:
    a = {layer["layer_id"]: fingerprint(layer) for layer in left.get("layers", [])}
    b = {layer["layer_id"]: fingerprint(layer) for layer in right.get("layers", [])}
    ids = list(dict.fromkeys([*a, *b]))
    added, removed, changed = [], [], []
    for ident in ids:
        if ident not in a:
            added.append({"layer_id": ident, **b[ident]})
        elif ident not in b:
            removed.append({"layer_id": ident, **a[ident]})
        else:
            fields = {key: [a[ident].get(key), b[ident].get(key)]
                      for key in a[ident] if a[ident].get(key) != b[ident].get(key)}
            if fields:
                changed.append({"layer_id": ident, "fields": fields})
    if only:
        wanted = set(only)
        changed = [item for item in changed if wanted & set(item["fields"])]
    return {"summary": {"added": len(added), "removed": len(removed), "changed": len(changed),
                        "left_layers": len(a), "right_layers": len(b),
                        "duration_us": [left.get("duration_us"), right.get("duration_us")]},
            "added": added, "removed": removed, "changed": changed}
