"""Segment labels: transitions, animations, effects, and their approximation tiers.

JianYing stores these as resource ids whose real motion curves live inside its own
effect bundles, so the previewer resolves each id to a name from the catalog and
then either reproduces it (``exact``), fakes it with a documented stand-in
(``approx``), or shows a labelled chip (``placeholder``). A miss never renders as
blank space -- it always carries its Chinese name.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .content import TimelineContent, timerange, us

EASE_OUT = lambda p: 1 - (1 - p) ** 2
LINEAR = lambda p: p

APPROX_BY_KEYWORD = (
    (("渐隐", "淡出", "闪黑", "out"), ("fade", 1.0, 0.0)),
    (("渐显", "淡入", "入", "in"), ("fade", 0.0, 1.0)),
    (("放大", "推近", "zoom in", "缩放进入"), ("zoom_in", 0.6, 1.0)),
    (("缩小", "拉远", "zoom out"), ("zoom_out", 1.6, 1.0)),
    (("向右", "右滑", "slide right"), ("slide_x", -0.15, 0.0)),
    (("向左", "左滑", "slide left"), ("slide_x", 0.15, 0.0)),
    (("向上", "上移", "slide up"), ("slide_y", 0.15, 0.0)),
    (("向下", "下移", "slide down"), ("slide_y", -0.15, 0.0)),
    (("旋转", "rotate"), ("rotate", -25.0, 0.0)),
    (("抖动", "震动", "shake"), ("shake", 0.0, 0.0)),
    (("模糊", "blur"), ("blur", 12.0, 0.0)),
    (("叠化", "交叉", "溶解", "dissolve", "crossfade"), ("crossfade", 0.0, 1.0)),
)

TRANSITION_APPROX = (
    (("叠化", "溶解", "交叉", "dissolve"), "crossfade"),
    (("闪黑", "黑场", "fade_black"), "flash_black"),
    (("闪白", "白场", "fade_white"), "flash_white"),
    (("推", "拉", "缩放", "zoom"), "zoom"),
    (("擦", "wipe", "分割"), "wipe"),
)


def _keyword_approx(name: str) -> tuple[str, float, float] | None:
    lowered = (name or "").lower()
    for keywords, impl in APPROX_BY_KEYWORD:
        if any(keyword.lower() in lowered for keyword in keywords):
            return impl
    return None


def transition_approx(name: str) -> str | None:
    lowered = (name or "").lower()
    for keywords, impl in TRANSITION_APPROX:
        if any(keyword.lower() in lowered for keyword in keywords):
            return impl
    return _keyword_approx(name) and _keyword_approx(name)[0]


def _state(impl: tuple[str, float, float] | None, progress: float) -> dict[str, Any] | None:
    if not impl:
        return None
    kind, start, end = impl
    eased = EASE_OUT(max(0.0, min(progress, 1.0)))
    value = start + (end - start) * eased
    state: dict[str, Any] = {"opacity": 1.0, "scale": 1.0, "translate_offset_px": [0.0, 0.0],
                             "rotation_deg": 0.0, "blur_px": 0.0}
    if kind == "fade":
        state["opacity"] = round(value, 4)
    elif kind == "zoom_in":
        state["scale"] = round(start + (end - start) * eased, 4)
    elif kind == "zoom_out":
        state["scale"] = round(start + (end - start) * eased, 4)
    elif kind == "slide_x":
        state["translate_offset_px"] = [round(value * 1000, 2), 0.0]
    elif kind == "slide_y":
        state["translate_offset_px"] = [0.0, round(value * 1000, 2)]
    elif kind == "rotate":
        state["rotation_deg"] = round(value, 3)
    elif kind == "shake":
        import math

        offset = (1 - progress) * 18
        state["translate_offset_px"] = [round(math.sin(progress * 40) * offset, 2),
                                        round(math.cos(progress * 33) * offset * 0.6, 2)]
    elif kind == "blur":
        state["blur_px"] = round(max(end - value, 0.0) if start > end else max(start * (1 - progress), 0.0), 2)
    elif kind == "crossfade":
        state["opacity"] = round(0.0 + progress, 4)
    return state


# -- keyframes ---------------------------------------------------------------
def _bezier_at(p: float, p1: float, p2: float) -> float:
    return 3 * (1 - p) ** 2 * p * p1 + 3 * (1 - p) * p ** 2 * p2 + p ** 3


def keyframe_value(curves: list[dict], local_us: int, duration_us: int) -> dict[str, Any]:
    """Sample ``segment.common_keyframes`` at a local time (linear + bezier)."""
    out: dict[str, Any] = {}
    for curve in curves or []:
        if not isinstance(curve, dict):
            continue
        items = [item for item in (curve.get("keyframe_list") or []) if isinstance(item, dict)]
        if len(items) < 2:
            continue
        property_name = str(curve.get("property_type") or curve.get("property") or "")
        target = int(local_us)
        previous, following = items[0], items[-1]
        for item in items:
            offset = us(item.get("time_offset"))
            if offset <= target:
                previous = item
            if offset >= target and following is items[0]:
                following = item
        for index, item in enumerate(items):
            if us(item.get("time_offset")) >= target:
                following = item
                previous = items[max(index - 1, 0)]
                break
        span = us(following.get("time_offset")) - us(previous.get("time_offset"))
        raw = 0.0 if span <= 0 else (target - us(previous.get("time_offset"))) / span
        curve_type = str(previous.get("curveType") or "Line")
        if curve_type.lower() == "line":
            eased = max(0.0, min(raw, 1.0))
        else:
            left = previous.get("left_control") or {}
            right = following.get("right_control") or {}
            eased = _bezier_at(max(0.0, min(raw, 1.0)), us(left.get("y", 0.0), 0.0),
                               us(right.get("y", 1.0), 1.0))
        before, after = previous.get("values") or [], following.get("values") or []
        values = []
        for index in range(max(len(before), len(after))):
            first = us(before[index], 0) if index < len(before) else 0
            second = us(after[index], 0) if index < len(after) else 0
            values.append(round(first + (second - first) * eased, 6))
        out[property_name] = {"from": before, "to": after, "values": values,
                              "curve": curve_type, "raw": round(raw, 4),
                              "time_offset_us": target}
    return out


def resolve(segment: dict[str, Any], content: TimelineContent, catalog, t_us: int,
            tinfo: dict[str, Any], config) -> dict[str, Any]:
    bucket_material = content.material(segment.get("material_id"))
    material = bucket_material[1] if bucket_material else {}
    raw_path = str(material.get("path") or "")
    family = _family(material, raw_path)

    labels: list[dict[str, Any]] = []
    transition = None
    animation = None
    canvas_fill = None
    fade_in = fade_out = 0
    subdraft = None
    subdraft_entry: dict[str, Any] | None = None
    applies = None

    for bucket, item in content.refs(segment):
        kind = str(item.get("type") or bucket)
        name = str(item.get("name") or "")
        if bucket == "transitions":
            duration = us(item.get("duration"), 0)
            entry = _catalog_entry(catalog, "transition", item, name)
            window_start, window_end = _window(tinfo, duration)
            impl = transition_approx(entry.get("name") or name) or "placeholder"
            transition = {
                "name": entry.get("name") or name or None, "effect_id": str(item.get("effect_id") or "") or None,
                "resource_id": str(item.get("resource_id") or "") or None,
                "duration_us": duration, "window": {"start_us": window_start, "end_us": window_end},
                "cut_us": int(tinfo["target_start_us"] + tinfo["target_duration_us"]),
                "is_overlap": bool(item.get("is_overlap")), "side": "out",
                "render_class": entry.get("render_class") or ("approx" if impl != "placeholder" else "placeholder"),
                "approx": None if impl == "placeholder" else {"impl": impl, "to_segment": None},
                "bundle": entry.get("bundle"), "category_name": item.get("category_name"),
            }
            labels.append({"bucket": "transitions", "kind": "transition", "name": transition["name"] or "转场",
                           "effect_id": transition["effect_id"], "resource_id": transition["resource_id"],
                           "render_class": transition["render_class"], "duration_us": duration,
                           "params": [], "bundle": entry.get("bundle")})
        elif bucket == "material_animations":
            for inner in item.get("animations") or []:
                if not isinstance(inner, dict):
                    continue
                duration = us(inner.get("duration"), 0)
                start = us(inner.get("start"), 0)
                ident = str(inner.get("id") or inner.get("effect_id") or "")
                entry = _catalog_entry(catalog, "animation", inner, str(inner.get("name") or ""))
                resolved_name = entry.get("name") or inner.get("name") or None
                impl = _keyword_approx(resolved_name or "")
                local = int(tinfo["local_us"]) - start
                progress = 0.0 if duration <= 0 else max(0.0, min(local / duration, 1.0))
                inside = 0 <= local <= duration
                render_class = entry.get("render_class") or ("approx" if impl else "placeholder")
                animation = {
                    "name": resolved_name, "anim_type": str(inner.get("type") or "in"),
                    "effect_id": ident or None, "resource_id": str(inner.get("resource_id") or "") or None,
                    "start_us": start, "duration_us": duration, "inside": inside,
                    "render_class": render_class, "material_type": inner.get("material_type"),
                    "approx": None if not impl else {"impl": impl[0], "from": impl[1], "to": impl[2]},
                    "at_t": _state(impl, progress) if inside else None,
                    "bundle": entry.get("bundle"),
                }
                labels.append({"bucket": "material_animations", "kind": str(inner.get("type") or "in"),
                               "name": resolved_name or "动画", "effect_id": ident or None,
                               "resource_id": str(inner.get("resource_id") or "") or None,
                               "render_class": render_class, "params": [],
                               "bundle": entry.get("bundle")})
        elif bucket in ("video_effects", "effects"):
            entry = _catalog_entry(catalog, bucket, item, name)
            render_class = entry.get("render_class") or "placeholder"
            labels.append({
                "bucket": bucket, "kind": kind, "name": entry.get("name") or name or bucket,
                "effect_id": str(item.get("effect_id") or "") or None,
                "resource_id": str(item.get("resource_id") or "") or None,
                "render_class": render_class, "params": _params(item),
                "value": item.get("value"), "bundle": entry.get("bundle"),
                "category_name": item.get("category_name"), "apply_target_type": item.get("apply_target_type"),
            })
            if kind in ("figure", "makeup_root", "smart_color_adjust"):
                applies = "algorithm"
        elif bucket == "audio_fades":
            fade_in = us(item.get("fade_in_duration"))
            fade_out = us(item.get("fade_out_duration"))
        elif bucket == "canvases":
            canvas_fill = _canvas_fill(item)
        elif bucket == "speeds":
            rate = us(item.get("speed"), 0) or float(item.get("value", 0) or 0)
            if rate and abs(rate - float(tinfo.get("speed") or 1.0)) > 0.001:
                labels.append({"bucket": "speeds", "kind": "speed", "name": f"变速 ×{rate:g}",
                               "render_class": "placeholder", "params": []})
        elif bucket == "drafts":
            subdraft_entry = item
            subdraft = item.get("draft") if isinstance(item.get("draft"), dict) else None
            labels.append({"bucket": "drafts", "kind": "subdraft",
                           "name": str(item.get("name") or "复合片段"), "render_class": "placeholder"})
        elif bucket == "masks":
            labels.append({"bucket": "masks", "kind": "mask",
                           "name": str(item.get("name") or "蒙版"), "render_class": "placeholder",
                           "params": _params(item)})

    curves = segment.get("common_keyframes") or []
    sampled = keyframe_value(curves, int(tinfo["local_us"]), int(tinfo["target_duration_us"])) if curves else {}
    keyframes = [{"property": name, **state} for name, state in sampled.items()] or None

    return {
        "material": material, "material_bucket": bucket_material[0] if bucket_material else None,
        "family": family, "media_name": material.get("material_name") or material.get("name"),
        "is_subdraft": bool(subdraft or subdraft_entry), "subdraft": subdraft,
        "subdraft_entry": subdraft_entry,
        "labels": labels, "transition": transition, "animation": animation,
        "keyframes": keyframes, "applies": applies, "canvas_fill": canvas_fill,
        "fade_in_us": fade_in, "fade_out_us": fade_out,
    }


def _window(tinfo: dict[str, Any], duration_us: int) -> tuple[int, int]:
    from .timing import transition_window

    cut = int(tinfo["target_start_us"]) + int(tinfo["target_duration_us"])
    return transition_window(cut, duration_us)


def _family(material: dict[str, Any], raw_path: str) -> str:
    kind = str(material.get("type") or "")
    suffix = Path(str(raw_path).replace("\\", "/")).suffix.lower()
    if kind == "photo" or suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
        return "image"
    if kind == "audio" or suffix in {".mp3", ".aac", ".wav", ".m4a", ".ogg", ".flac"}:
        return "audio"
    if kind == "sticker":
        return "sticker"
    return "video"


def _params(item: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for param in item.get("adjust_params") or []:
        if isinstance(param, dict):
            out.append({"name": param.get("name"), "value": param.get("value"),
                        "default": param.get("default_value"), "min": param.get("min_value"),
                        "max": param.get("max_value")})
    return out


def _canvas_fill(item: dict[str, Any]) -> dict[str, Any] | None:
    kind = str(item.get("canvas_color") or item.get("type") or "")
    blur = item.get("canvas_blur")
    color = item.get("canvas_color")
    if not kind and blur in (None, 0.0) and not color:
        return None
    return {"type": "canvas_blur" if blur else "canvas_color", "blur": blur, "color": color,
            "ratio": item.get("canvas_alpha")}


def _catalog_entry(catalog, kind: str, item: dict[str, Any], name: str) -> dict[str, Any]:
    if catalog is None:
        return {"name": name or None, "render_class": None, "bundle": None}
    return catalog.lookup(kind, item, name) or {"name": name or None, "render_class": None, "bundle": None}
