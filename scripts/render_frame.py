"""Channel-2 frame compositor: render one timeline position of a JianYing draft to a PNG
without opening JianYing and without a browser.

Why this exists: the render-base decision (base-selection.md 定案) keeps two channels -
the browser for interactive preview and PIL+ffmpeg for agent-side frame output/verification.
The spike that proved the rates (temp/px-probe/spike_pipeline_rate.py) was decode+pad only;
this is the same channel upgraded to read the playback model, so an agent can ask "what does
second 12.4 of this timeline look like" and get a byte-stable PNG.

Deliberate limits (each is an open item in the docs, not a silent assumption):
  - draw order uses track index then render_index, larger = on top (U-15 is uncalibrated);
  - fit law matches the browser player: scale each axis to the canvas (identity for matching
    aspect ratios; the real 剪映 fit rule for mismatched aspects is unmeasured);
  - masks / transitions are not applied; colour grading is skipped by phase scope;
  - mix_mode IS applied (F-077/F-079): the layer is composited with the vendor's own
    premultiplied blend math via mixmode_blend.blend(), verified equal to the package GLSL
    at 1/255 over 13,872 channel comparisons per mode. A segment whose mode cannot be
    resolved (difference / colour-filter have no local package, or the md5 is unknown) is
    counted in MIX_DEGRADED and composited normally - never silently guessed;
  - shadow blur uses U-03's diffuse*600 and panel-space distance, both pending pixel calibration.

Usage:
  python scripts/render_frame.py --model temp/playback-test/model.json --t 12.4 --out temp/playback-test/frame-12.4.png
  python scripts/render_frame.py --model ... --from 0 --to 36 --step 0.5 --out-dir temp/playback-test/frames
"""

from __future__ import annotations

import argparse
import json
import io
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from mixmode_blend import blend, resolve_mode   # 同目录
# Windows 控制台是 GBK：读数里带中文/箭头/替换符时 print 会在最后一步抛错，
# 把已经算完的结果整个吞掉（本轮自己的统计工具就栽过一次）。只改错误处理策略，不改编码。
try:
    sys.stdout.reconfigure(errors="replace")     # type: ignore[attr-defined]
    sys.stderr.reconfigure(errors="replace")     # type: ignore[attr-defined]
except Exception:                                 # noqa: BLE001
    pass

FF = r"D:\Program Files\JianyingPro\11.6.0.14552\ffmpeg.exe"
K_EM = 0.00574          # F-035/F-036 band 0.00574-0.00578; em_px = size * canvas_width * k
ROOT = Path(__file__).resolve().parents[1]

_MIX_MANIFEST: dict | None = None
_MPATH = ROOT / "temp" / "playback-test" / "mixmode" / "manifest.json"
if _MPATH.exists():
    _MIX_MANIFEST = json.loads(_MPATH.read_text(encoding="utf-8"))


def gtc(d, key, default):
    # JS's ?? in Python: 0.0 and False are values, not absence.
    v = d.get(key)
    return default if v is None else v


def rgb(color, default=(1.0, 1.0, 1.0)):
    if not color or len(color) < 3:
        return tuple(int(round(255 * c)) for c in default)
    return tuple(int(round(255 * max(0.0, min(1.0, c)))) for c in color[:3])


def decode_frame(path: str, at_s: float) -> Image.Image | None:
    """One frame at source seconds, as a PNG pipe.

    Letting ffmpeg emit an encoded image rather than rawvideo is deliberate: the container's
    display matrix rotates these clips (coded 1920x1080 -> display 1080x1920), and reading the
    size back off the picture removes a whole class of stride mismatch - the first version
    guessed 1920x1080 from ffmpeg's own log line and produced horizontal shearing.
    """
    if Path(path).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"):
        try:
            im = Image.open(path)
            # convert("RGB") here would flatten a transparent logo onto black and then the
            # layer, stretched to the canvas, hides everything under it.
            return im if im.mode in ("RGBA", "LA") else im.convert("RGBA")
        except OSError:
            return None
    cmd = [FF, "-hide_banner", "-loglevel", "error", "-ss", f"{at_s:.6f}", "-i", path,
           "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None
    if r.returncode != 0 or not r.stdout:
        return None
    try:
        return Image.open(io.BytesIO(r.stdout)).convert("RGB")
    except OSError:
        return None


MIX_DEGRADED: list[tuple[str, str | None]] = []

# 入场动画（P-29/F-078）：曲线从预设包内的 lua 读，不手抄（animation_curve.py 的模块文档写了边界）。
# 关掉它只为「实现前 vs 实现后」的对照测量，不是运行期开关。
APPLY_ANIMATIONS = True
_CURVES: dict[str, list] = {}


def curve_for(seg: dict) -> list:
    a = (seg.get("animations") or [None])[0]
    if not a or not a.get("path"):
        return []
    key = str(a["path"])
    if key not in _CURVES:
        from animation_curve import load_curve
        _CURVES[key] = load_curve(key)
    return _CURVES[key]


def anim_value(seg: dict, pos_us: int, out_h: int, texture_h: float | None) -> dict:
    """该段在 pos_us 处的动画值。没有曲线 / 预设不在我们实现的面上 => 恒等（并计入未覆盖）。

    求值时刻要从**该动画自己的窗口起点**算：`start` 给了就用它，缺席时 in 从段头起、
    out 从段尾倒推。一律从段头起会把出场动画画在入场的位置上（第一版就是这么错的）。
    """
    ident = {"alpha": 1.0, "scale_x": 1.0, "scale_y": 1.0, "dy_norm": 0.0}
    if not APPLY_ANIMATIONS:
        return ident
    tr = curve_for(seg)
    if not tr:
        return ident
    a = (seg.get("animations") or [{}])[0]
    seg_dur = seg["target"]["duration_us"]
    dur_us = a.get("duration_us") or 0
    start_us = a.get("start_us")
    if start_us is None:
        start_us = max(0, seg_dur - dur_us) if a.get("kind") == "out" else 0
    t = (pos_us - seg["target"]["start_us"] - start_us) / 1e6
    from animation_curve import value_at
    v = value_at(tr, t, (0, out_h or 1), texture_h=texture_h)
    out = dict(ident)
    for k in ident:
        out[k] = v.get(k, ident[k])
    return out


def apply_anim(img: Image.Image, av: dict, dy_base: float) -> tuple[Image.Image, int, int]:
    """把 alpha/scale 作用到已定位的图层上，返回新图与需要补加的 (dx, dy) 像素偏移。"""
    dx = dy = 0
    if av["scale_x"] != 1.0 or av["scale_y"] != 1.0:
        nw, nh = max(1, round(img.width * av["scale_x"])), max(1, round(img.height * av["scale_y"]))
        cx, cy = img.width / 2, img.height / 2
        img = img.resize((nw, nh), Image.LANCZOS)
        dx, dy = int(round(cx - nw / 2)), int(round(cy - nh / 2))
    if av["alpha"] < 1.0:
        a = av["alpha"]
        img = img.copy()
        img.putalpha(img.getchannel("A").point(lambda v, a=a: int(round(v * a))))
    dy -= int(round(av["dy_norm"] * dy_base))   # y 轴向上为正（F-035/U-08），所以画布坐标要减
    return img, dx, dy



def blend_over(canvas: Image.Image, layer: Image.Image, pos: tuple[int, int],
               mode: str, opacity: float = 1.0) -> None:
    """把 layer 按厂商预乘混合式叠到 canvas 上（不是 alpha_composite）。

    画布在本通道里始终不透明（alpha=1），所以 `fa + ba - fa*ba` 退化成 1，
    预乘输出就是最终像素，直接 paste、不再带 mask（带 mask 会把 alpha 用第二遍）。
    """
    cw, ch = canvas.size
    x0, y0 = max(0, pos[0]), max(0, pos[1])
    x1, y1 = min(cw, pos[0] + layer.width), min(ch, pos[1] + layer.height)
    if x1 <= x0 or y1 <= y0:
        return
    fg = np.asarray(layer.convert("RGBA").crop((x0 - pos[0], y0 - pos[1],
                                                x1 - pos[0], y1 - pos[1])),
                    dtype=np.float32) / 255.0
    a = fg[..., 3:4]
    fgp = np.concatenate([fg[..., :3] * a, a], axis=-1)          # straight -> premultiplied
    bg = np.asarray(canvas.crop((x0, y0, x1, y1)), dtype=np.float32) / 255.0
    ba = bg[..., 3:4]
    bgp = np.concatenate([bg[..., :3] * ba, ba], axis=-1)
    out = blend(mode, fgp, bgp, fg_alpha=opacity)
    px = np.clip(out[..., :3] / np.maximum(out[..., 3:4], 1e-6), 0.0, 1.0)
    canvas.paste(Image.fromarray((px * 255.0 + 0.5).astype("uint8"), "RGB"), (x0, y0))


def place(layer: Image.Image, canvas_size, clip, material_kind: str = "video") -> tuple[int, int, Image.Image]:
    cw, ch = canvas_size
    lw, lh = layer.size
    c = clip or {}
    # Nothing in the format says a still image should be distorted, and stretching a 1242x330
    # logo by ch/lh (4.4x here) visibly is not what JianYing's own cover shows. Uniform fit is
    # the defensible default; the anchor and the base scale remain UNCALIBRATED (see
    # docs/evidence/playback-log.md P-11 for the measured discrepancy against the cover).
    fit = min(cw / lw, ch / lh) if material_kind == "photo" else 1.0
    if material_kind == "photo":
        sx = gtc(c, "scale_x", 1) * fit
        sy = gtc(c, "scale_y", 1) * fit
    else:
        sx = gtc(c, "scale_x", 1) * cw / lw
        sy = gtc(c, "scale_y", 1) * ch / lh
    scaled = layer.resize((max(1, int(lw * sx)), max(1, int(lh * sy))), Image.LANCZOS)
    alpha = c.get("alpha")
    if alpha is not None and alpha < 1:
        mask = Image.new("L", scaled.size, int(255 * max(0.0, min(1.0, alpha))))
        scaled.putalpha(mask)
    cx = cw / 2 + (c.get("x") or 0) * cw / 2
    cy = ch / 2 - (c.get("y") or 0) * ch / 2
    rot = -gtc(c, "rotation", 0)
    if rot:
        scaled = scaled.rotate(rot, expand=True, resample=Image.BICUBIC)
    return int(cx - scaled.width / 2), int(cy - scaled.height / 2), scaled


def draw_text(canvas: Image.Image, seg, fonts_dir_cache, pos_us: int = 0) -> None:
    t = seg.get("text") or {}
    txt = (t.get("text") or "").replace("\n", " ")
    styles = t.get("styles") or [{}]
    cw, ch = canvas.size
    # segments[].clip is the geometry channel (P-13): normalised offsets where ±1 is half the
    # canvas and y points up. Without it every caption was drawn dead-centre.
    c = seg.get("clip") or {}
    ox = (c.get("x") or 0.0) * cw / 2
    oy = -(c.get("y") or 0.0) * ch / 2
    sc_x = c.get("scale_x") or 1.0
    pieces = []
    for st in styles:
        rng = st.get("range")
        piece = txt[rng[0]:rng[1]] if isinstance(rng, list) and len(rng) == 2 else (txt if st is styles[0] else "")
        if not piece:
            continue
        px = max(1, int(round(gtc(st, "size", 15) * cw * K_EM * sc_x)))
        pieces.append((piece, px, st))
    if not pieces:
        return
    fonts, widths, heights, tops = [], [], [], []
    for piece, px, st in pieces:
        f = load_font(st.get("font_path"), px, fonts_dir_cache)
        fonts.append(f)
        box = ImageDraw.Draw(canvas).textbbox((0, 0), piece, font=f)
        widths.append(box[2] - box[0])
        heights.append(box[3] - box[1])
        # PIL anchors on the ascender line, so the ink starts box[1] BELOW the y passed in.
        # Not subtracting it puts every caption ~15% of an em too low (12 px here: the mask
        # IoU against the cover is 0.27 unshifted and 0.72 once that offset is removed).
        tops.append(box[1])
    total = sum(widths)
    # 入场动画（F-078）：文字层走同一套曲线，textureH 取实测墨迹高——包里 lua 用的就是
    # sprite 的纹理高，不是画幅高。
    av = anim_value(seg, pos_us, ch, max(heights) if heights else ch)
    if av["dy_norm"]:
        oy = oy - int(round(av["dy_norm"] * ch / 2))
    alpha = av["alpha"]
    x = (cw - total) / 2 + ox
    rot = c.get("rotation") or 0.0
    for (piece, px, st), f, w, h, top in zip(pieces, fonts, widths, heights, tops):
        col = rgb(st.get("color")) + ((int(round(255 * alpha)),) if alpha < 1.0 else ())
        sh = st.get("shadow")

        def paint(dst, x=x, h=h, top=top, piece=piece, f=f, col=col, sh=sh):
            if sh:
                import math
                blur = max(0.0, (sh.get("diffuse") or 0) * 600 * cw / 1080)
                dist = (sh.get("distance") or 0) * cw / 1080
                rad = math.radians(sh.get("angle") or 0)
                shx, shy = math.cos(rad) * dist, -math.sin(rad) * dist
                # `x` already carries the clip offset; adding ox again pushed the shadow
                # 205 px away from its glyph on the rotated emphasis caption.
                sy = (ch - h) / 2 + oy - top + shy
                if blur > 0.4:
                    # PIL has no glyph shadow: draw onto a scratch layer, blur, then composite.
                    scratch = Image.new("RGBA", dst.size, (0, 0, 0, 0))
                    ImageDraw.Draw(scratch).text((x + shx, sy), piece,
                                                 fill=rgb(sh.get("color"), (0, 0, 0)) + (int(round(255 * (sh.get("alpha") or 1) * alpha)),),
                                                 font=f)
                    scratch = scratch.filter(ImageFilter.GaussianBlur(blur))
                    dst.alpha_composite(scratch)
                else:
                    ImageDraw.Draw(dst).text((x + shx, sy), piece,
                                             fill=rgb(sh.get("color"), (0, 0, 0)), font=f)
            ImageDraw.Draw(dst).text((x, (ch - h) / 2 + oy - top), piece, fill=col, font=f)

        if abs(rot) > 1e-6:
            # Rotate the layer about the piece's own ink centre, in canvas coordinates, so the
            # clip transform and the authoring rotation compose the same way Pixi does it.
            cx, cy = x + w / 2, (ch - h) / 2 + oy - top + h / 2
            layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            paint(layer)
            canvas.alpha_composite(layer.rotate(-rot, resample=Image.BICUBIC,
                                                center=(int(round(cx)), int(round(cy)))))
        else:
            paint(canvas)
        x += w


_font_cache: dict[tuple[str | None, int], ImageFont.FreeTypeFont] = {}


def load_font(path, px, _cache=None):
    key = (path, px)
    if key in _font_cache:
        return _font_cache[key]
    f = None
    if path and Path(path).is_file():
        try:
            f = ImageFont.truetype(str(path), px)
        except OSError:
            f = None
    if f is None:
        f = ImageFont.load_default()
    _font_cache[key] = f
    return f


def active_segment(track, pos_us):
    for s in track["segments"]:
        if s.get("visible") is False:
            continue
        t0 = s["target"]["start_us"]
        if t0 <= pos_us < t0 + s["target"]["duration_us"]:
            return s
    return None


def collect(canvas, model, pos_us, fonts_dir_cache, depth=0):
    """Paint every track at pos_us onto canvas, composites recursed (P-02)."""
    layers = []
    for ti, track in enumerate(model["tracks"]):
        if track["type"] == "audio":
            continue
        seg = active_segment(track, pos_us)
        if not seg:
            continue
        z = ti * 100000 + (seg.get("render_index") or 0)
        if track["type"] == "text":
            layers.append(("text", z, seg, None))
            continue
        mm = seg.get("media") or {}
        cache_ok = bool(mm.get("path")) and (mm.get("container") or {}).get("readable") is not False
        if not cache_ok:
            comp = seg.get("composite")
            if comp and depth < 2:
                child_pos = (pos_us - seg["target"]["start_us"]) * (seg.get("speed") or 1)
                # The child carries its own canvas (this draft: 1080x1440 inside a 1080x1920
                # timeline), so child coordinates must be resolved in the child's space.
                cc = (comp.get("canvas") or {})
                csize = (int(cc.get("width") or canvas.size[0]), int(cc.get("height") or canvas.size[1]))
                sub = Image.new("RGBA", csize, (0, 0, 0, 0))
                collect(sub, comp, child_pos, fonts_dir_cache, depth + 1)
                if sub.size != canvas.size:
                    # Fit by width and centre vertically - stretching 1080x1440 onto 1080x1920
                    # puts the child's caption at 0.843 of the height, while the cover measures
                    # 0.755 and the fitted law predicts 0.757 (P-14). Same law as the browser.
                    sc = canvas.size[0] / sub.size[0]
                    if sc != 1.0:
                        sub = sub.resize((round(sub.size[0] * sc), round(sub.size[1] * sc)),
                                         Image.LANCZOS)
                    pad = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
                    pad.paste(sub, ((canvas.size[0] - sub.size[0]) // 2,
                                    (canvas.size[1] - sub.size[1]) // 2), sub)
                    sub = pad
                layers.append(("image", z, seg, sub))
            continue
        if not mm.get("path") or not mm.get("exists"):
            continue
        src_s = (seg["source"]["start_us"] + (pos_us - seg["target"]["start_us"])
                 * (seg.get("speed") or 1)) / 1e6
        frame = decode_frame(mm["path"], src_s)
        if frame:
            layers.append(("image", z, seg, frame.convert("RGBA")))
    for kind, z, seg, payload in sorted(layers, key=lambda x: x[1]):
        if kind == "text":
            draw_text(canvas, seg, fonts_dir_cache, pos_us)
        else:
            x, y, img = place(payload, canvas.size, seg.get("clip"),
                                ((seg.get("material") or {}).get("type")) or "video")
            av = anim_value(seg, pos_us, canvas.size[1], img.height)
            if av != {"alpha": 1.0, "scale_x": 1.0, "scale_y": 1.0, "dy_norm": 0.0}:
                img, adx, ady = apply_anim(img, av, canvas.size[1] / 2)
                x, y = x + adx, y + ady
            mm = seg.get("mix_mode")
            mode = resolve_mode(mm, _MIX_MANIFEST) if mm else None
            if mm and not mode:
                MIX_DEGRADED.append((str(seg.get("id")), (mm or {}).get("package_md5")))
            if mode:
                blend_over(canvas, img, (x, y), mode,
                           opacity=float((seg.get("clip") or {}).get("alpha")
                                         if (seg.get("clip") or {}).get("alpha") is not None
                                         else 1.0))
            else:
                canvas.alpha_composite(img, (x, y))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True)
    ap.add_argument("--t", type=float, help="single timeline position in seconds")
    ap.add_argument("--from", dest="t0", type=float)
    ap.add_argument("--to", type=float)
    ap.add_argument("--step", type=float, default=0.5)
    ap.add_argument("--out")
    ap.add_argument("--out-dir")
    args = ap.parse_args()

    model = json.loads(Path(args.model).read_text(encoding="utf-8-sig"))
    cw, ch = int(model["canvas"]["width"]), int(model["canvas"]["height"])
    bg = (0, 0, 0, 255)
    canvas0 = Image.new("RGBA", (cw, ch), bg)

    times = [args.t] if args.t is not None else list(
        __import__("numpy").arange(args.t0, args.to + 1e-9, args.step))
    if args.out_dir:
        Path(args.out_dir).mkdir(parents=True, exist_ok=True)
    fonts_dir_cache: dict = {}
    for t in times:
        canvas = canvas0.copy()
        collect(canvas, model, int(t * 1e6), fonts_dir_cache)
        out = args.out if len(times) == 1 else str(Path(args.out_dir or ".") / f"frame-{t:.3f}.png")
        canvas.convert("RGB").save(out)
        print(f"{t:8.3f}s -> {out}", flush=True)
    if MIX_DEGRADED:
        print(f"mix_mode degraded (composited normally, NOT guessed): {len(MIX_DEGRADED)} "
              f"segments; e.g. {MIX_DEGRADED[:3]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
