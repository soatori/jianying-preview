"""Text material -> renderable paint runs + deterministic line layout.

Units found in the corpus (verified against real drafts, which disagree with the
editor skill's ``material-structures.md``):
* colours are ``[r,g,b]`` floats in 0..1 (``solid.color``), sometimes ``#rrggbb``
  on the flat fallback fields;
* ``range`` is ``[start, end]`` char indices in real drafts (a ``{start,end}``
  dict appears in older/material-structure form) -- both are accepted;
* stroke ``width`` is em-relative; shadow ``distance`` is a percentage of the em;
* ``size`` is JianYing's UI size, converted by :mod:`jypreview.model.layout`.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

try:
    from PIL import ImageFont
except ImportError:  # pragma: no cover - pillow is present on this box
    ImageFont = None

_FONT_CACHE: dict[tuple[str, int], Any] = {}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def rgb(color: Any, alpha: Any = None) -> dict[str, Any] | None:
    if color is None:
        return None
    if isinstance(color, str):
        value = color.strip()
        if value.startswith("#"):
            return {"css": value if len(value) >= 7 else value, "alpha": _num(alpha, 1.0)}
        return {"css": value, "alpha": _num(alpha, 1.0)}
    if isinstance(color, (list, tuple)):
        parts = [_num(p) for p in color[:3]]
        if len(color) > 3 and alpha is None:
            alpha = color[3]
        r, g, b = (int(round(min(max(p, 0.0), 1.0) * 255)) for p in parts)
        return {"css": f"#{r:02x}{g:02x}{b:02x}", "alpha": round(_num(alpha, 1.0), 4)}
    if isinstance(color, dict):
        return rgb(color.get("color"), color.get("alpha", alpha))
    return None


def _solid(content: dict) -> dict[str, Any] | None:
    solid = content.get("solid") or {}
    if not solid:
        return None
    return {"render_type": "solid", "color": rgb(solid.get("color"), solid.get("alpha"))}


def fill_of(fill: Any) -> dict[str, Any] | None:
    if not isinstance(fill, dict):
        return None
    content = fill.get("content") if isinstance(fill.get("content"), dict) else fill
    render_type = str(content.get("render_type") or "").lower()
    alpha = _num(fill.get("alpha", content.get("alpha")), 1.0)
    if render_type == "gradient" or "gradient" in content:
        gradient = content.get("gradient") or {}
        colors = [rgb(value) for value in (gradient.get("color") or [])]
        stops = []
        for index, color in enumerate(colors):
            if not color:
                continue
            percent = gradient.get("percent") or []
            offset = _num(percent[index], index / max(len(colors) - 1, 1)) if index < len(percent) \
                else index / max(len(colors) - 1, 1)
            stops.append({"offset": round(min(max(offset, 0.0), 1.0), 4), **color})
        return {"render_type": "gradient", "alpha": round(alpha, 4),
                "angle": _num(gradient.get("angle")), "mode": str(gradient.get("mode") or "all"),
                "stops": stops}
    if render_type == "texture" or "texture" in content:
        texture = content.get("texture") or {}
        return {"render_type": "texture", "alpha": round(alpha, 4),
                "path": texture.get("path"), "angle": _num(texture.get("angle")),
                "scale": _num(texture.get("scale"), 1.0), "blend": texture.get("blend")}
    solid = _solid(content)
    if solid and solid.get("color"):
        return {"render_type": "solid", "alpha": round(alpha, 4), **solid["color"]}
    return None


def strokes_of(style: dict) -> list[dict[str, Any]]:
    out = []
    items = style.get("strokes")
    if isinstance(items, dict):
        items = [items]
    for item in items or []:
        if not isinstance(item, dict):
            continue
        content = item.get("content") or {}
        solid = content.get("solid") or {}
        color = rgb(solid.get("color"), solid.get("alpha"))
        width = _num(item.get("width"))
        if color or width:
            out.append({"width_em": round(width, 6), "render_type": "solid",
                        "color": (color or {}).get("css"), "alpha": (color or {}).get("alpha", 1.0)})
    flat = style.get("stroke")
    if isinstance(flat, dict) and not out:
        color = flat.get("color")
        out.append({"width_em": round(_num(flat.get("width")), 6), "render_type": "solid",
                    "color": (rgb(color) or {}).get("css"), "alpha": (rgb(color) or {}).get("alpha", 1.0)})
    return out


def shadows_of(style: dict) -> list[dict[str, Any]]:
    out = []
    for item in style.get("shadows") or []:
        if not isinstance(item, dict):
            continue
        content = item.get("content") or {}
        color = rgb((content.get("solid") or {}).get("color"), (content.get("solid") or {}).get("alpha"))
        distance = _num(item.get("distance"))
        angle = _num(item.get("angle"))
        # JianYing's shadow distance is a percentage of the em, not a whole em:
        # distance 5 with a 247px em is a 17px drop, which matches the app.
        out.append({
            "distance_em": round(distance / 100.0, 6), "angle_deg": round(angle, 4),
            "alpha": round(_num(item.get("alpha"), 1.0), 4),
            "diffuse": round(_num(item.get("diffuse")), 6),
            "feather": round(_num(item.get("feather")), 6),
            "color": (color or {}).get("css"),
        })
    return out


def inner_shadows_of(style: dict) -> list[dict[str, Any]]:
    out = []
    for item in style.get("inner_shadows") or []:
        if isinstance(item, dict):
            content = item.get("content") or {}
            color = rgb((content.get("solid") or {}).get("color"))
            out.append({"distance_em": round(_num(item.get("distance")), 6),
                        "angle_deg": round(_num(item.get("angle")), 4),
                        "alpha": round(_num(item.get("alpha"), 1.0), 4),
                        "color": (color or {}).get("css")})
    return out


def _ranges(style: dict, total: int) -> tuple[int, int]:
    raw = style.get("range")
    if isinstance(raw, dict):
        start, end = int(raw.get("start", 0)), int(raw.get("end", total))
    elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
        start, end = int(raw[0]), int(raw[1])
    else:
        start, end = 0, total
    start = max(min(start, total), 0)
    end = max(min(end, total), start)
    return start, end


def parse_content(material: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    content = material.get("content")
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            content = {"text": content, "styles": []}
    if not isinstance(content, dict):
        text = str(material.get("text") or "")
        return text, []
    text = str(content.get("text") or material.get("text") or "")
    styles = [item for item in (content.get("styles") or []) if isinstance(item, dict)]
    return text, styles


def flat_style(material: dict[str, Any]) -> dict[str, Any]:
    """Outer-material fallback when ``styles[]`` omits a property."""
    style: dict[str, Any] = {"size": _num(material.get("font_size"), 10.0)}
    if material.get("text_color"):
        style["fill"] = {"render_type": "solid", **(rgb(material["text_color"]) or {})}
    if material.get("border_width"):
        style["strokes"] = [{"content": {"solid": {"color": _hex_tuple(material.get("border_color")),
                                                   "alpha": _num(material.get("border_alpha"), 1.0)}},
                             "width": _num(material.get("border_width"))}]
    if material.get("has_shadow"):
        style["shadows"] = [{"distance": _num(material.get("shadow_distance")),
                             "angle": _num(material.get("shadow_angle")),
                             "alpha": _num(material.get("shadow_alpha"), 1.0),
                             "content": {"solid": {"color": _hex_tuple(material.get("shadow_color"))}}}]
    return style


def _hex_tuple(value: Any) -> list[float] | None:
    if not isinstance(value, str) or not value.startswith("#"):
        return None
    digits = value[1:]
    if len(digits) == 6:
        return [int(digits[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return None


def background_of(material: dict[str, Any]) -> dict[str, Any] | None:
    style = int(_num(material.get("background_style"), 0))
    if style <= 0:
        return None
    return {"style": style, "color": (rgb(material.get("background_color")) or {}).get("css", "#000000"),
            "alpha": round(_num(material.get("background_alpha"), 1.0), 4),
            "round_radius": _num(material.get("background_round_radius")),
            "width": _num(material.get("background_width")),
            "height": _num(material.get("background_height")),
            "horizontal_offset": _num(material.get("background_horizontal_offset")),
            "vertical_offset": _num(material.get("background_vertical_offset"))}


def _font_for(style: dict, material: dict) -> dict[str, Any]:
    font = style.get("font")
    if isinstance(font, dict) and (font.get("path") or font.get("id")):
        return font
    entries = [item for item in (material.get("fonts") or []) if isinstance(item, dict)]
    return entries[0] if entries else {}


def build(material: dict[str, Any], em_for_size, config, flower_lookup=None) -> dict[str, Any]:
    text, styles = parse_content(material)
    total = len(text)
    if not styles:
        styles = [dict(flat_style(material), range=[0, total])]
    runs = []
    for style in styles:
        start, end = _ranges(style, total)
        if end <= start and total:
            continue
        em = em_for_size(style.get("size", flat_style(material).get("size", 10.0)))
        fill = fill_of(style.get("fill")) or fill_of(flat_style(material).get("fill", {}))
        effect = style.get("effectStyle") if isinstance(style.get("effectStyle"), dict) else None
        run = {
            "start": start, "end": end, "text": text[start:end],
            "size_raw": _num(style.get("size"), _num(material.get("font_size"), 10.0)),
            "em_px": round(em, 4),
            "bold": bool(style.get("bold")), "italic": bool(style.get("italic")),
            "underline": bool(style.get("underline")),
            "fill": fill,
            "strokes": strokes_of(style) or _flat_strokes(material),
            "shadows": shadows_of(style) or _flat_shadows(material),
            "inner_shadows": inner_shadows_of(style),
            "font": _font_for(style, material),
            "use_letter_color": bool(style.get("useLetterColor")),
            "flower": None,
        }
        if effect and effect.get("id"):
            run["flower"] = {"resource_id": str(effect.get("id")),
                             "path": effect.get("path"),
                             "name": None, "render_class": "placeholder"}
            if flower_lookup:
                run["flower"] = flower_lookup(effect, material) or run["flower"]
        runs.append(run)
    if not runs:
        em = em_for_size(flat_style(material).get("size", 10.0))
        runs = [{"start": 0, "end": total, "text": text, "size_raw": flat_style(material).get("size", 10.0),
                 "em_px": round(em, 4), "bold": False,
                 "italic": False, "underline": False,
                 "fill": {"render_type": "solid", **(rgb(material.get("text_color")) or {"css": "#ffffff"})},
                 "strokes": _flat_strokes(material), "shadows": _flat_shadows(material),
                 "inner_shadows": [], "font": _font_for({}, material),
                 "use_letter_color": False, "flower": None}]

    alignment = int(_num(material.get("alignment"), 1))
    typesetting = int(_num(material.get("typesetting"), 0))
    vertical = bool(int(_num(material.get("vertical"), 0))) if material.get("vertical") is not None else bool(typesetting)
    letter_spacing = _num(material.get("letter_spacing"))
    line_spacing = _num(material.get("line_spacing"), 0.02)
    return {
        "material_id": material.get("id"), "type": str(material.get("type") or "text"),
        "text": text, "runs": runs,
        "alignment": alignment, "vertical": vertical,
        "check_flag": int(_num(material.get("check_flag"), 7)),
        "letter_spacing_em": round(letter_spacing, 6),
        "line_spacing_raw": round(line_spacing, 6),
        "max_line_ratio": _num(material.get("line_max_width") or material.get("max_line"), 0.0),
        "auto_wrapping": bool(material.get("auto_wrapping", False)),
        "global_alpha": round(_num(material.get("global_alpha"), 1.0), 4),
        "background": background_of(material),
        "layer_weight": _num(material.get("layer_weight"), 1),
        "words": material.get("words") if isinstance(material.get("words"), dict) else None,
        "font_resource_id": str(material.get("font_resource_id") or "") or None,
        "recognize_text": material.get("recognize_text"),
    }


def _flat_strokes(material: dict[str, Any]) -> list[dict[str, Any]]:
    if not material.get("border_width"):
        return []
    color = rgb(material.get("border_color"), material.get("border_alpha")) or {}
    return [{"width_em": round(_num(material.get("border_width")), 6), "render_type": "solid",
             "color": color.get("css", "#000000"), "alpha": color.get("alpha", 1.0)}]


def _flat_shadows(material: dict[str, Any]) -> list[dict[str, Any]]:
    if not material.get("has_shadow"):
        return []
    color = rgb(material.get("shadow_color"), material.get("shadow_alpha")) or {}
    return [{"distance_em": round(_num(material.get("shadow_distance")) / 100.0, 6),
             "angle_deg": round(_num(material.get("shadow_angle")), 4),
             "alpha": color.get("alpha", 1.0), "diffuse": _num(material.get("shadow_smoothing")),
             "feather": 0.0, "color": color.get("css", "#000000")}]


# -- deterministic line layout ------------------------------------------------
def measure(font_path: str | None, em_px: float) -> Any:
    key = (str(font_path or ""), int(round(em_px * 4)))
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    font = None
    if ImageFont is not None and font_path and Path(font_path).is_file():
        try:
            font = ImageFont.truetype(str(font_path), max(int(round(em_px)), 1))
        except OSError:
            font = None
    _FONT_CACHE[key] = font
    return font


def char_advance(ch: str, em_px: float, font=None) -> float:
    if font is not None:
        try:
            return float(font.getlength(ch))
        except Exception:
            pass
    code = ord(ch)
    if code >= 0x2E80 or code in (0x3000, 0xFF0C, 0x3002):
        return em_px
    if ch.isdigit():
        return em_px * 0.55
    if ch == " ":
        return em_px * 0.28
    return em_px * 0.52


def layout_lines(text_payload: dict[str, Any], box_width_px: float, font_path: str | None) -> dict[str, Any]:
    """Greedy wrap identical to JianYing's CJK behaviour, using the real font metrics."""
    runs = text_payload["runs"] or []
    em_px = max(run["em_px"] for run in runs) if runs else 0.0
    font = measure(font_path, em_px)
    lines: list[list[dict[str, Any]]] = [[]]
    width = 0.0
    index = 0
    for ch in text_payload["text"]:
        index += 1
        if ch == "\n":
            lines.append([])
            width = 0.0
            continue
        advance = char_advance(ch, em_px, font)
        if box_width_px > 0 and width + advance > box_width_px and lines[-1]:
            lines.append([])
            width = 0.0
        lines[-1].append({"ch": ch, "i": index - 1, "advance": round(advance, 4)})
        width += advance
    built = []
    for cells in lines:
        if not cells:
            continue
        built.append({"text": "".join(cell["ch"] for cell in cells),
                      "start": cells[0]["i"], "end": cells[-1]["i"] + 1,
                      "width_px": round(sum(cell["advance"] for cell in cells), 4),
                      "spans": [{"i": cell["i"], "advance": cell["advance"]} for cell in cells]})
    if not built:
        built = [{"text": "", "start": 0, "end": len(text_payload["text"]), "width_px": 0.0, "spans": []}]
    line_count = len(built)
    spacing = text_payload["line_spacing_raw"]
    ratio = 1.0 + spacing if spacing <= 1.0 else 1.0 + spacing / 50.0
    line_height = round(em_px * ratio, 4)
    return {
        "lines": built, "line_count": line_count, "line_height_px": line_height,
        "em_px": round(em_px, 4), "box_w_px": round(max((line["width_px"] for line in built), default=em_px), 4),
        "box_h_px": round(line_height * line_count, 4), "metrics": "font" if font else "estimated",
    }
