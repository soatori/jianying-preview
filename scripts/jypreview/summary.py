"""Context-cheap text views of a FrameDescriptor, for agents and terminals."""

from __future__ import annotations

from typing import Any


def ms(t_us: int | None) -> str:
    if t_us is None:
        return "-"
    return f"{t_us / 1_000_000:.3f}s"


def _label_brief(labels: list[dict[str, Any]]) -> str:
    parts = []
    for label in labels or []:
        parts.append(f"{label.get('name')}[{label.get('render_class', '?')}]")
    return ",".join(parts)


def layer_line(layer: dict[str, Any]) -> str:
    kind = layer.get("kind")
    z = layer.get("z") or {}
    time = layer.get("time") or {}
    rect = layer.get("rect") or {}
    head = (f"z{z.get('order', '?'):>2} {str(kind):<8} {ms(time.get('target_start_us'))}→"
            f"{ms(time.get('end_us'))} src={ms(time.get('source_time_us'))}")
    if kind == "text":
        text = layer.get("text") or {}
        font = text.get("font") or {}
        box = text.get("box") or {}
        runs = text.get("runs") or []
        fill = (runs[0].get("fill") or {}) if runs else {}
        strokes = len(runs[0].get("strokes") or []) if runs else 0
        shadows = len(runs[0].get("shadows") or []) if runs else 0
        flower = runs[0].get("flower") if runs else None
        return (f"{head} TEXT {text.get('text')!r} em={box.get('em_px')} @({box.get('cx_px')},"
                f"{box.get('cy_px')}) lines={box.get('line_count')} align={box.get('alignment')}"
                f" fill={fill.get('css') or fill.get('render_type')} stroke×{strokes} shadow×{shadows}"
                f" font={font.get('title') or font.get('resource_id')}({font.get('source')})"
                + (f" 花字={flower.get('name') or flower.get('resource_id')}[{flower.get('render_class')}]"
                   if flower else ""))
    media = layer.get("media") or {}
    if media:
        mark = "OK " if media.get("exists") else "MISS"
        return (f"{head} {str(media.get('material_type')):<5} {mark} {media.get('material_name')} "
                f"{media.get('probe', {}).get('codec') if media.get('probe') else ''} "
                f"rect={rect.get('w_px')}x{rect.get('h_px')}@({rect.get('cx_px')},{rect.get('cy_px')})"
                f" rot={rect.get('rotation_deg')} a={rect.get('alpha')}"
                + (f" !{media.get('placeholder_reason')}" if not media.get("exists") else ""))
    if layer.get("nest"):
        nest = layer["nest"]
        return (f"{head} SUBDRAFT depth={nest.get('depth')} layers="
                f"{len(nest.get('layers') or [])} {nest.get('reason') or ''}".rstrip())
    return f"{head} {str(kind).upper()} (label-only)" + (f" {_label_brief(layer.get('labels'))}"
                                                        if layer.get("labels") else "")


def compact_frame(ir: dict[str, Any], *, max_layers: int = 40) -> dict[str, Any]:
    layers = ir.get("layers", [])
    return {
        "t": ms((ir.get("time") or {}).get("t_us")),
        "canvas": ir.get("canvas"),
        "timeline": {**(ir.get("timeline") or {}), "duration": ms(ir.get("duration_us"))},
        "layer_count": len(layers),
        "layers": [layer_line(layer) for layer in layers[:max_layers]],
        "labels": {
            "transition": [layer_line_placeholder(layer) for layer in layers if layer.get("transition")],
            "animation": [str((layer.get("animation") or {}).get("name")) for layer in layers
                          if layer.get("animation")],
        },
        "audio": ir.get("audio_labels"),
        "stats": ir.get("stats"),
        "warnings": ir.get("warnings"),
        "truncated": max(len(layers) - max_layers, 0),
    }


def layer_line_placeholder(layer: dict[str, Any]) -> str:
    transition = layer.get("transition") or {}
    return (f"{layer.get('layer_id')[:8]} {transition.get('name')} "
            f"{ms(transition.get('duration_us'))} window={ms((transition.get('window') or {}).get('start_us'))}"
            f"→{ms((transition.get('window') or {}).get('end_us'))} "
            f"[{transition.get('render_class')}] overlap={transition.get('is_overlap')}")


def who_at(ir: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for layer in ir.get("layers", []):
        entry: dict[str, Any] = {
            "layer_id": layer.get("layer_id"), "kind": layer.get("kind"),
            "z_order": (layer.get("z") or {}).get("order"),
            "track": (layer.get("track") or {}).get("name") or (layer.get("track") or {}).get("type"),
            "name": None, "text": None, "at_px": None, "badges": [],
        }
        if layer.get("text"):
            entry["name"] = ((layer["text"].get("font") or {}).get("title")
                             or (layer["text"].get("font") or {}).get("resource_id"))
            entry["text"] = layer["text"].get("text")
            box = layer["text"].get("box") or {}
            entry["at_px"] = [box.get("cx_px"), box.get("cy_px")]
            entry["em_px"] = box.get("em_px")
            entry["badges"].extend(f"strokes×{len(run.get('strokes') or [])}" for run in
                                   layer["text"].get("runs") or [])
            entry["badges"].extend(f"shadow×{len(run.get('shadows') or [])}" for run in
                                   layer["text"].get("runs") or [])
            entry["badges"].extend(f"花字:{run['flower'].get('name') or run['flower'].get('resource_id')}"
                                   for run in layer["text"].get("runs") or [] if run.get("flower"))
        elif layer.get("media"):
            entry["name"] = layer["media"].get("material_name")
            entry["badges"].append("media_ok" if layer["media"].get("exists")
                                   else f"media_missing:{layer['media'].get('how')}")
            rect = layer.get("rect") or {}
            entry["at_px"] = [rect.get("cx_px"), rect.get("cy_px")]
            entry["size_px"] = [rect.get("w_px"), rect.get("h_px")]
        for label in layer.get("labels") or []:
            entry["badges"].append(f"{label.get('kind')}:{label.get('name')}[{label.get('render_class')}]")
        if layer.get("transition"):
            entry["badges"].append(f"transition:{layer['transition'].get('name')}"
                                   f"[{layer['transition'].get('render_class')}]")
        if layer.get("animation"):
            entry["badges"].append(f"anim:{layer['animation'].get('name')}"
                                   f"[{layer['animation'].get('render_class')}]")
        if layer.get("keyframes"):
            entry["badges"].append("keyframes:" + ",".join(item["property"] for item in layer["keyframes"]))
        out.append(entry)
    return out
