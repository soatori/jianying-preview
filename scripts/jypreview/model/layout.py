"""Geometry: JianYing clip space to CSS pixels.

Clip conventions verified against the corpus:
* ``clip.transform`` is in half-canvas units (x over half width, y over half height)
  and JianYing's y axis points up while CSS points down, so ``cy = H/2 - y*H/2``.
* ``clip.scale`` is a ratio (1.0 = 100%), ``rotation`` is clockwise degrees.
* Draw size is the media rect fitted *before* rotation ("contain_unrotated"):
  a -90 deg landscape talking-head clip at scale 1.8 fills a 9:16 canvas that way.
"""

from __future__ import annotations

import math
from typing import Any

ROUND = 4


def _num(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def basis_px(width: int, height: int, basis: str) -> int:
    if basis == "height":
        return int(height)
    if basis == "min_side":
        return int(min(width, height))
    return int(width)


def em_px(font_size: Any, width: int, height: int, config) -> float:
    basis = basis_px(width, height, config.text_size_basis)
    return round(_num(font_size, 0.0) * basis * config.text_scale_factor, ROUND)


def clip_of(segment: dict[str, Any]) -> dict[str, Any]:
    clip = segment.get("clip")
    return clip if isinstance(clip, dict) else {}


def transform_center(clip: dict[str, Any], width: int, height: int,
                     config) -> tuple[float, float, float]:
    """``clip.transform`` -> canvas pixel centre.

    JianYing's y axis points up, CSS's points down, so the default
    ``y_sign="jianying_up"`` negates it: ``y=-0.8`` on a 1920-tall canvas gives
    ``cy=1728``, the standard subtitle position.
    """
    transform = clip.get("transform") or {}
    tx = _num(transform.get("x"))
    ty = _num(transform.get("y"))
    tz = _num(transform.get("z"))
    span = float(height) if config.transform_y_basis == "full" else float(height) / 2
    cx = width / 2 + tx * (width / 2)
    cy = height / 2 - ty * span if config.y_sign == "jianying_up" else height / 2 + ty * span
    return round(cx, ROUND), round(cy, ROUND), round(tz, ROUND)


def fit_contain(media_w: float, media_h: float, width: int, height: int) -> tuple[float, float]:
    if media_w <= 0 or media_h <= 0:
        return float(width), float(height)
    scale = min(width / media_w, height / media_h)
    return round(media_w * scale, ROUND), round(media_h * scale, ROUND)


def cover(media_w: float, media_h: float, width: int, height: int) -> tuple[float, float]:
    if media_w <= 0 or media_h <= 0:
        return float(width), float(height)
    scale = max(width / media_w, height / media_h)
    return round(media_w * scale, ROUND), round(media_h * scale, ROUND)


def clip_scale(clip: dict[str, Any], segment: dict[str, Any]) -> tuple[float, float]:
    scale = clip.get("scale") or {}
    sx, sy = _num(scale.get("x"), 1.0), _num(scale.get("y"), 1.0)
    uniform = segment.get("uniform_scale") or {}
    if isinstance(uniform, dict) and uniform.get("on"):
        value = _num(uniform.get("value"), 1.0)
        sx = sy = sx * value if value else sx
    return sx or 1.0, sy or 1.0


def layer_geometry(segment: dict[str, Any], media_w: float, media_h: float,
                   width: int, height: int, config, *, text_em: float | None = None,
                   text_lines: tuple[int, int] | None = None) -> dict[str, Any]:
    """Resolve one segment's on-canvas rectangle plus a ready CSS transform."""
    clip = clip_of(segment)
    cx, cy, cz = transform_center(clip, width, height, config)
    sx, sy = clip_scale(clip, segment)
    rotation = _num(clip.get("rotation"))
    flip = clip.get("flip") or {}
    flip_x = bool(flip.get("horizontal"))
    flip_y = bool(flip.get("vertical"))
    alpha = _num(clip.get("alpha"), 1.0)

    if text_em is not None:
        line_count, max_line_len = (text_lines or (1, 1))
        box_w = max(text_em * max_line_len, text_em)
        box_h = max(text_em * line_count, text_em)
        w_px, h_px = box_w, box_h
    else:
        if config.fit_mode == "contain_rotated" and abs(((rotation % 180) + 180) % 180 - 90) < 1:
            base_w, base_h = fit_contain(media_h or height, media_w or width, width, height)
        else:
            base_w, base_h = fit_contain(media_w or width, media_h or height, width, height)
        w_px, h_px = round(base_w * sx, ROUND), round(base_h * sy, ROUND)

    transform = (f"translate({round(cx - w_px / 2, ROUND)}px, {round(cy - h_px / 2, ROUND)}px) "
                 f"rotate({round(rotation, ROUND)}deg)")
    if flip_x or flip_y:
        transform += f" scale({-1 if flip_x else 1}, {-1 if flip_y else 1})"

    return {
        "cx_px": cx, "cy_px": cy, "w_px": w_px, "h_px": h_px,
        "rotation_deg": round(rotation, ROUND), "flip_x": flip_x, "flip_y": flip_y,
        "alpha": round(alpha, ROUND), "scale_x": sx, "scale_y": sy, "z_px": round(cz, ROUND),
        "css": {
            "width": f"{w_px}px", "height": f"{h_px}px",
            "transform": transform, "transform-origin": "center",
            "opacity": f"{round(alpha, ROUND)}",
        },
    }


def stage_css(width: int, height: int) -> dict[str, str]:
    return {"width": f"{width}px", "height": f"{height}px"}
