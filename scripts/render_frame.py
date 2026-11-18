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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jy_paths                                      # noqa: E402

FF = str(jy_paths.ffmpeg())
K_EM = 0.00574          # F-035/F-036 band 0.00574-0.00578; em_px = size * canvas_width * k
ROOT = Path(__file__).resolve().parents[1]

# 草稿记的是**绝对路径**的字体，缓存被清掉就不存在了（本例 42 条字幕样式全指向
# Cache/effect/7080096967543493150/...，该目录已没了）。原来这里落到
# `ImageFont.load_default()`：约 10 px 的点阵字，中文全是豆腐块——字号差 4 倍，
# 而 L2 的质心判据只看位置，于是整条时间线的字幕被量成「位置对」而没人看见它小。
# 回退必须仍是**能画中文的真字体、且用请求的 px**，并且要**计数报出去**。
# 顺序是**量出来的**，不是审美选择（`caption_ink_check --sweep-fallbacks`，t=1.0 字幕带对成片）：
#   雅黑粗体 墨 3961 / corr 0.777 / MAD 20.5   ← 成片 3476，浏览器 3544
#   黑体      墨 1962 / corr 0.765 / MAD 20.3
#   雅黑常规  墨 2295 / corr 0.715 / MAD 22.6
#   Noto VF   墨  721 / corr 0.605 / MAD 27.0
# 缺的那款是 HelloFont_ID_JianSong_95（95 = 重宋），所以默认先落到**重**字面；
# 常规体把笔画量差到 1/5，判据端就会把「字幕没画出来」读成「字幕位置没问题」。
FALLBACK_FONTS = [r"C:\Windows\Fonts\msyhbd.ttc",           # 雅黑粗体：标定后最贴近成片
                  r"C:\Windows\Fonts\simhei.ttf",           # 黑体
                  r"C:\Windows\Fonts\msyh.ttc",
                  r"C:\Windows\Fonts\NotoSansSC-VF.ttf"]
FONT_FALLBACKS: dict = {}     # 请求路径 -> 实际用的回退（None = 连回退都没有）

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


def kf_eval(track: dict, local_us: float) -> float:
    """关键帧求值：线性插值，端点外钳到端点值（U-35 未实测首末钳制；骨架同步律下与
    「用 clip 标量」一致）。控制柄（curveType/左右手柄）v1 **不**插值——没有 y 手柄的
    单位语义前按线性走，宁要缓动形状错也不要发明错缓动（手柄数由模型 stats.kf_curve_handles 报）。"""
    pts = track["points"]
    if local_us <= pts[0]["t_us"]:
        return pts[0]["v"]
    if local_us >= pts[-1]["t_us"]:
        return pts[-1]["v"]
    for a, b in zip(pts, pts[1:]):
        if local_us <= b["t_us"]:
            span = (b["t_us"] - a["t_us"]) or 1
            return a["v"] + (b["v"] - a["v"]) * ((local_us - a["t_us"]) / span)
    return pts[-1]["v"]


def kf_clip(seg: dict, pos_us: int) -> dict:
    """关键帧覆盖量并进 clip 副本（无关键帧段原样返回，零开销）。

    多点轨道取**绝对值**覆盖 clip 标量：首点通常等于原值（骨架同步律 F-027），所以覆盖
    与"从当前值开始动画"两种解释在首点重合，歧义只出现在中段——那是动画语义本身。
    Alpha 是 0..1 不透明度，与 clip.alpha 相乘；单位与 clip.* 同族（F-027）。
    """
    kfs = seg.get("keyframes")
    anim = ae_in_clip(seg, pos_us)
    if not kfs:
        base = dict(seg.get("clip") or {})
        if anim is not None:
            base["x"] = (base.get("x") or 0.0) + anim["x"]
        return base
    c = dict(seg.get("clip") or {})
    local = pos_us - ((seg.get("target") or {}).get("start_us") or 0)
    for t in kfs:
        v = kf_eval(t, local)
        p = t["property"]
        if p == "PositionX":
            c["x"] = v
        elif p == "PositionY":
            c["y"] = v
        elif p == "ScaleX":
            c["scale_x"] = v
        elif p == "ScaleY":
            c["scale_y"] = v
        elif p == "Rotation":
            c["rotation"] = v
        elif p in ("Alpha", "GlobalAlpha"):
            base = c.get("alpha") if c.get("alpha") is not None else 1.0
            c["alpha"] = base * max(0.0, min(1.0, v))
    if anim is not None:
        c["x"] = (c.get("x") or 0.0) + anim["x"]
    return c


AE_XOFF_ON = False
"""「侧滑」x 偏移开关（P-187 全量逐帧判错，与页面 `AE_XOFF_ON` 同批闸回）。

1105 帧、corr≥0.90 这条预登记线未动：加上后 20.267…20.500 全变差，红帧 9→13（4 帧绿翻红）；
表里 xoff[0]=−0.556 与 +0.144→0 的平滑段不同族 ⇒ 轨迹解析还没修对，先不许当修复用。
"""


def ae_in_clip(seg: dict, pos_us: int) -> dict | None:
    if not AE_XOFF_ON:
        return None
    """入场动画（`侧滑` 这一族）→ clip 的 x 偏移增量。

    走的是**既有那条路**（`_ae_pkg` = `ae_keyframe`，与 L8/L11、页面 `ae-curves.json` 同一个解析器），
    不再引第二份实现——P-181③ 立的规矩：两通道要读同一份导出/同一个解析器，
    不是"两份代码今天算出同样数字"。
    只动 x；缩放/曝光/模糊这一轮不进（不许一次上四支再回头找是谁坏的，P-179）。
    """
    for a in seg.get("animations") or []:
        if not isinstance(a, dict) or a.get("kind") != "in" or not a.get("path"):
            continue
        lua = Path(a["path"]) / "AmazingFeature" / "lua" / "SeekModeScript.lua"
        if not lua.exists():
            continue
        pkg = _ae_pkg(str(lua))
        if pkg[0] == "ERR":
            AE_LOG.append(("degraded-clip", str(seg.get("id")), pkg[1]))
            continue
        aek, tools, cons, _expo = pkg
        name = "ADBE Position_23"
        if name not in tools.attrs:
            continue                                   # 这包没有位移轨道（或只有别的通道）⇒ 不加偏移
        dur = (a.get("duration_us") or 0) / 1e6
        if dur <= 0:
            continue
        start = (seg.get("target") or {}).get("start_us") or 0
        el = max(0.0, (pos_us - start) / 1e6)
        if el >= dur:
            return {"x": 0.0}                          # 落位后不留小数（P-179 实测就是 0）
        cf = aek.frame_of_clamped(el, dur, cons, tools.all_frame)
        v = tools.get_val(name, max(0.0, min(cf, tools.all_frame)) / tools.all_frame)
        x = float(v[0] if isinstance(v, list) else v)
        design = cons.get("design_size") or 1080.0
        AE_LOG.append(("ae-x", str(seg.get("id")), round(el, 4), round(x, 2)))
        return {"x": (x - design / 2.0) / (design / 2.0)}
    return None


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


_TW_CACHE: dict = {}


def typewriter_truncate(seg, txt: str, pos_us: int) -> str:
    """「打字光标」= 只画可见前缀（F-087）。

    包内 lua 的 `checkDirty` 把每个字的 alpha 设成 `getCharPt(i, 1.2·t/dur)`，而后者是
    `tt > 0.9 ? 1 : 0` —— 对字序**单调**，所以可见集合永远是一个前缀，画前 k 个字与逐字
    设 alpha 等价，且不需要跑包内 GLSL（`onUpdate`/`getcuralpha` 在包里都是空函数，
    `curalpha` 是光标 sprite 的透明度，不是文字的）。节奏表是**写死的常量**，不是随机数。
    """
    for a in seg.get("animations") or []:
        if a.get("name") != "打字光标":
            continue
        if not APPLY_ANIMATIONS:
            # 「开/关动画」的对照判据（animation_region_check）要求这条路径也受同一个开关管，
            # 否则两臂画的完全一样，读数会变成假的「无差别」。
            return txt
        path = a.get("path") or ""
        if not path:
            return txt
        if path not in _TW_CACHE:
            import animation_curve as ac
            _TW_CACHE[path] = ac.load_typewriter(path)
        tw = _TW_CACHE[path]
        if not tw:
            return txt
        import animation_curve as ac
        tg = seg.get("target") or {}
        # 时间轴是**动画自己的** 0.2 s，不是片段时长（本时间线 14 段全是 0.20 s，片段却 0.47–0.93 s）。
        # 用片段时长会把揭示拉慢 2–5 倍 ⇒ `animation_region_check` 里成片已满、我们还在画前两个字，
        # 那 35 条「更远」就是这个轴错，不是仪器坏（F-087 的初判已就地更正）。
        dur_s = (a.get("duration_us") or 0) / 1e6 or (tg.get("duration_us", 0) / 1e6)
        t_in = (pos_us - tg.get("start_us", 0) - (a.get("start_us") or 0)) / 1e6
        k = ac.typewriter_prefix(tw, max(0.0, t_in), dur_s, len(txt))
        return txt[:k]
    return txt


def draw_text(canvas: Image.Image, seg, fonts_dir_cache, pos_us: int = 0) -> None:
    t = seg.get("text") or {}
    txt = typewriter_truncate(seg, (t.get("text") or "").replace("\n", " "), pos_us)
    styles = t.get("styles") or [{}]
    cw, ch = canvas.size
    # segments[].clip is the geometry channel (P-13): normalised offsets where ±1 is half the
    # canvas and y points up. Without it every caption was drawn dead-centre.
    c = kf_clip(seg, pos_us)
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
    # clip.alpha（与关键帧 Alpha，经 kf_clip 并进同一字段）原来对文字**不生效**——
    # alpha 只来自素材动画（anim_value），片段自己的不透明度被整个丢掉（A2 抓到的真缺陷）。
    calpha = c.get("alpha")
    if calpha is not None:
        alpha *= max(0.0, min(1.0, calpha))
    ga = t.get("global_alpha")
    if ga is not None:
        alpha *= max(0.0, min(1.0, ga))
    x = (cw - total) / 2 + ox
    rot = c.get("rotation") or 0.0
    for (piece, px, st), f, w, h, top in zip(pieces, fonts, widths, heights, tops):
        col = rgb(st.get("color"))
        sh = st.get("shadow")

        def paint(dst, x=x, h=h, top=top, piece=piece, f=f, col=col, sh=sh, alpha=alpha):
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
                    ImageDraw.Draw(dst, "RGBA").text((x + shx, sy), piece,
                                             fill=rgb(sh.get("color"), (0, 0, 0)), font=f)
            if alpha < 1.0:
                # PIL 的 ImageDraw.text **忽略填充的 alpha 字节**（RGBA 模式也一样，实测
                # 两种模式 max 都是 255）——半透明墨必须画到透明草稿层再 alpha_composite。
                scratch = Image.new("RGBA", dst.size, (0, 0, 0, 0))
                ImageDraw.Draw(scratch).text((x, (ch - h) / 2 + oy - top), piece,
                                             fill=col + (255,), font=f)
                scratch.putalpha(scratch.getchannel("A").point(lambda v: int(v * alpha)))
                dst.alpha_composite(scratch)
            else:
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
        # 缺字体≠没有字幕：换一条仍能画中文的真字体，**用同一个 px**，并把这次回退记下来。
        chosen = None
        for fb in FALLBACK_FONTS:
            try:
                if Path(fb).is_file():
                    f = ImageFont.truetype(fb, px)
                    chosen = fb
                    break
            except OSError:
                continue
        FONT_FALLBACKS.setdefault(path or "-", chosen)
    if f is None:
        f = ImageFont.load_default()
    _font_cache[key] = f
    return f


# ---- 调色（**逐字取自装机包内明文 GLSL**，不猜律）-------------------------------------------
# `Cache/effect/7416258989467374091/9e1cfdca…/AmazingFeature_adjustColor/xshader/colorAdjust.frag`
# 的 brightness 支：p = 1+5B（B>0），否则 p = 1/(1−2.5B) 且先减 −B·0.01，再 `y = 1 − (1−x)^p`。
# 参数就是草稿 `materials.effects[type=brightness].value`——**成片判**过这个映射
# （P-130：0.645→0.967、0.815→0.997、1.111→1.025，滑杆全 null 的对照段不动）。
# 其余支（contrast 的 pivot/xFactor、black→slope/bias、light_sensation 的 17³ LUT）没有成片验过的
# 参数映射，未验不上；`COLOR["on"]=False` 是负样本开关（关掉必须逐位回到改前的像素）。
# **默认关**：浏览器那半还没接（要走 mixmode 那条"抽明文 frag → 出厂件 → 槽注入"的路，
# F-093④/F-094 已定形状）。一边调一边不调会让**跨通道**变差——那是我们半套实现造成的，
# 不是播放器坏了。律与成片验的参数映射都留着（P-130），两边同批打开才是完整一步。
# **两边都默认关**（P-131）：浏览器那半验证失败——`BlendModeFilter` 槽的形状是给
# **两张贴图**用的（F-094），一元律挂上去**没生效**（同一时刻比值仍是改前的 0.66/0.83/1.12，
# 而通道 2 已是 0.965/0.996/1.025），于是跨通道从 0.97 档掉到 0.908 ⇒ 只开一边是倒退。
# 律与参数映射都留着（成片验过，P-130），等浏览器侧形状修对再同批打开。
COLOR = {"on": True, "applied": 0, "skipped_lut": 0,
         # P-175 通路闭合验做出来了，不闭合的根因**不在律**：浏览器把 `resources` 挂在 `GlProgram.from`
         # 上，而 GlProgram 只解构 {fragment,vertex,layout,gpuLayout,name} ⇒ 被静默丢掉 ⇒ uLut 没有纹理
         # 单元，取样落回 unit 0——即拿查表坐标去采**画面自己**（不是"什么都不改"，是错一小格混回来，
         # 所以 corr 会掉到基线以下）。挂到 Filter 这一层后
         # 五段腿全绿（上传 0.0 / 公式 ±0.6 纹素 / W=1 max 2.0 / mix max 1.4 / 身份 max 0.5），
         # 线性空间的两条假设被否掉（max 84~183）⇒ 查表就在 sRGB 里，与通道 2 同一条。
         # P-176 重测过 black/white/shadow（P-167 那次「更差」是在 ls 还是空转时测的，值得重来）。
         # 结果：**方向对、带数不退**——被这三支改到的 157 帧 |ln 亮度比| 均值 0.0667→0.0620，
         # 但越带 318→325：14.633–14.8 六帧进带，13.6–13.7 四帧被推过顶（1.034→1.05，U-109 那块），
         # 15.0–15.433 九帧被推下沿（0.974→0.957）。⇒ 仍按预登记的带数口径一起闸回，
         # 记账：不是律错，是量与范围还差一点，15.x 那段（black+shadow+ls）是下一个落点。
         "branches": ("brightness", "light_sensation")}

# ---- 调色链：律与 uniform 映射**逐字**取自装机包内明文（F-103） -----------------------------
# frag：`AmazingFeature_adjustColor/xshader/colorAdjust.frag`（main() 的支顺序）
# 映射：同包 `lua/SeekModeScript.lua`（ContrastPivot=0.435、MinIntensity=-1、MaxIntensity=1、Eps=1e-5）
# brightness 保持 P-130/P-133 的**成片判过**口径：草稿原值直接进 shader 公式（不过 getBrightnessParam），
# 这条与 Lua 的差异记在 U-111，改哪一边都要成片重新判一次，不许在这里顺手换。
PIVOT = 0.435
BW_EPS = 0.005
_LUT_CACHE: dict[str, object] = {}


def _sig_xfactor(a: float) -> float:
    import math
    return math.exp(8.33 * a - 12.16) + 5.82 * a - 1.72


def _sig_yk(x: float, a: float, pivot: float) -> tuple[float, float]:
    import math
    af = _sig_xfactor(a)
    s = 1.0 / (1.0 + math.exp(-af * (x - pivot)))
    return s + pivot - 0.5, af * s * (1.0 - s)


def _contrast_uniforms(i: float):
    """getContrastParam 的逐字翻译：param≤1 走线性，否则走带边界校正的 sigmoid。"""
    param = i * 0.4 + 1.0 if i <= 0 else i * 0.6 + 1.0
    if param <= 1.0:
        return ("linear", param)
    lv, ls = _sig_yk(0.0, param, PIVOT)
    rv, rs = _sig_yk(1.0, param, PIVOT)
    pv, ps = _sig_yk(PIVOT, param, PIVOT)
    return ("sigmoid", {"xf": _sig_xfactor(param), "ld": 0.0 - lv, "rd": 1.0 - rv,
                        "lsd": ps - ls, "rsd": ps - rs, "ps": ps})


def _shadow_p(i: float) -> float:
    return 1.0 - 0.503 * i + 0.183 * i ** 2 - 0.147 * i ** 3 + 0.067 * i ** 4


def _highlight_p(i: float) -> float:
    return 1.0 + 0.503 * i + 0.183 * i ** 2 + 0.147 * i ** 3 + 0.067 * i ** 4


def _black_white(black: float, white: float) -> tuple[float, float]:
    xw = 1.0 - white * 0.5 if white >= 0 else 1.0
    yw = 1.0 if white >= 0 else 1.0 + white * 0.5
    xb = 0.0 if black >= 0 else -black * 0.5
    yb = black * 0.5 if black >= 0 else 0.0
    xw, yw = max(xw, BW_EPS), max(yw, BW_EPS)
    xb, yb = min(xb, xw - BW_EPS), min(yb, yw - BW_EPS)
    slope = (yw - yb) / (xw - xb)
    return slope, yb - slope * xb


def _lut(seg: dict, which: str):
    import pathlib
    name = f"lightSensation_{which}.png"
    # 首选建模时复制过来的那份（与浏览器读的是同一个文件，两边同批的同源性才算得清）
    staged = pathlib.Path(__file__).resolve().parents[1] / "temp/playback-test/lut" / name
    if not staged.is_file():
        paths = ((seg.get("features") or {}).get("effect_paths")) or {}
        pkg = paths.get("light_sensation") or paths.get("fade") or paths.get("contrast")
        if not pkg:
            return None
        root = pathlib.Path(pkg)
        cand = [root / "image" / name, *sorted(root.glob(f"*/image/{name}"))]
        staged = next((c for c in cand if c.is_file()), None)
        if staged is None:
            return None
    f = staged
    key = str(f)
    if key not in _LUT_CACHE:
        _LUT_CACHE[key] = np.asarray(Image.open(f).convert("RGB"), dtype=np.float32) / 255.0
    return _LUT_CACHE[key]


def _apply_lut(a, tex):
    """frag 的 applyLut3D（gridSample=17、gridNum=17×1）+ GL 的 LINEAR/CLAMP 取样。"""
    h, w = tex.shape[:2]
    gs = 17.0
    sx, sy = 1.0 / gs - 1.0 / w, 1.0 / 1.0 - 1.0 / h
    blue = a[..., 2] * (gs - 1.0)
    parts = []
    for fn in (np.floor, np.ceil):
        gi = fn(blue)
        gpy = np.floor(gi / gs)
        gpx = gi - gpy * gs
        u = gpx / gs + 0.5 / w + sx * a[..., 0]
        v = gpy * 1.0 + 0.5 / h + sy * a[..., 1]
        # GL 的 LINEAR 取样在纹素中心 `u*w − 0.5`（不是 `u*(w−1)`）：厂商 frag 的 uv
        # （gx/17 + 0.5/289 + (1/17−1/289)·r）正是按这个约定设计的，r=0/1 恰好落在整数纹素上。
        # 旧写法把整张 17³ 表挤了 0.35% ⇒ 大坐标处偏 0.5~1.5 格（P-173 往返验抓到）。
        x = np.clip(u * w - 0.5, 0, w - 1)
        y = np.clip(v * h - 0.5, 0, h - 1)
        x0 = np.floor(x).astype(int)
        y0 = np.floor(y).astype(int)
        x1 = np.minimum(x0 + 1, w - 1)
        y1 = np.minimum(y0 + 1, h - 1)
        fx = (x - x0)[..., None]
        fy = (y - y0)[..., None]
        parts.append(tex[y0, x0] * (1 - fx) * (1 - fy) + tex[y0, x1] * fx * (1 - fy)
                     + tex[y1, x0] * (1 - fx) * fy + tex[y1, x1] * fx * fy)
    wm = (blue - np.floor(blue))[..., None]
    return np.clip(parts[0] * (1 - wm) + parts[1] * wm, 0, 1)


def apply_color_adjust(img, seg):
    """按厂商 frag 的支顺序作用**已验的**调色支；无调色的段逐位不变。"""
    if not COLOR["on"] or img is None:
        return img
    ev = ((seg.get("features") or {}).get("effect_values")) or {}
    nz = {k: float(v) for k, v in ev.items()
          if isinstance(v, (int, float)) and abs(v) > 1e-6 and k in COLOR["branches"]}
    if not nz:
        return img
    a = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    COLOR["applied"] += 1
    b = nz.get("brightness")
    if b:
        if b > 0:
            pw = 1.0 + b * 5.0
        else:
            pw = 1.0 / (1.0 - b * 2.5)
            a = np.maximum(a - (-b * 0.01), 0.0)
        a = np.clip(1.0 - np.power(1.0 - a, np.float32(pw)), 0.0, 1.0)
    c = nz.get("contrast")
    if c:
        kind, prm = _contrast_uniforms(c)
        if kind == "linear":
            a = np.clip(prm * (a - PIVOT) + PIVOT, 0.0, 1.0)
        else:
            xf, ld, rd, lsd, rsd, ps = (prm["xf"], prm["ld"], prm["rd"],
                                        prm["lsd"], prm["rsd"], prm["ps"])
            s = 1.0 / (1.0 + np.exp(-xf * (a - PIVOT)))
            y = s + PIVOT - 0.5
            k = xf * s * (1.0 - s)
            left = a <= PIVOT
            scale = np.where(left, ((ps - k) / lsd) ** 2, ((ps - k) / rsd) ** 2)
            a = np.clip(y + scale * np.where(left, ld, rd), 0.0, 1.0)
    st = nz.get("saturation")
    if st:
        sp = st + 1.0
        F = np.array([0.208540, 0.702086, 0.089374], dtype=np.float32)
        base = F * (1.0 - sp)
        out = np.empty_like(a)
        for i in range(3):
            vec = base.copy()
            vec[i] = vec[i] + sp
            out[..., i] = a @ vec
        a = np.clip(out, 0.0, 1.0)
    hb = nz.get("highlight")
    if hb:
        ph = np.float32(_highlight_p(hb))
        t = 1.0 - a
        a = np.clip(1.0 - np.power(t, ph) - (ph - 1.0) * (t * t - t * t * t), 0.0, 1.0)
    sh = nz.get("shadow")
    if sh:
        ps = np.float32(_shadow_p(sh))
        a = np.clip(np.power(a, ps) + (ps - 1.0) * (a * a - a * a * a), 0.0, 1.0)
    if nz.get("black") or nz.get("white"):
        slope, bias = _black_white(nz.get("black", 0.0), nz.get("white", 0.0))
        a = np.clip(slope * a + bias, 0.0, 1.0)
    ls = nz.get("light_sensation")
    if ls:
        tex = _lut(seg, "max" if ls > 0 else "min")
        if tex is None:
            COLOR["skipped_lut"] += 1     # 取不到 LUT 就不施加这一支，并且要能在读数里看见
        else:
            a = np.clip(a + (np.asarray(_apply_lut(a, tex), dtype=np.float32) - a) * abs(ls), 0.0, 1.0)
    return Image.fromarray((a * 255).astype(np.uint8)).convert("RGBA")


def active_segment(track, pos_us):
    for s in track["segments"]:
        if s.get("visible") is False:
            continue
        t0 = s["target"]["start_us"]
        if t0 <= pos_us < t0 + s["target"]["duration_us"]:
            return s
    return None


# ---------------------------------------------------------------- 入场动画的曝光项
# 包内 `SeekModeScript.lua` 带明文 `ae_attribute` 关键帧表（F-095），其中
# `ADBE_Exposure*` 是**全画面**的乘性曝光。走哪一支由**成片判**（F-096）：
# 线性光（`use_linear_light=0`，与 `Exposure.material` 默认一致）残差 rms 19.1 码值，
# gamma 空间直乘（`exposure_script` 的 `no_use_linear_light=true` 会写 1.0）rms 100.6 ⇒ 取前者。
# 时间映射**夹紧、不循环**：`mod` 写法在窗口外 mse=2040 vs 夹紧 0.3（F-096）。
AE_FLASH = {"off": False, "blur": True}
AE_LOG: list = []
_AE_CACHE: dict = {}
# 结构项的律是**对成片拟合出来的经验式**（F-096）：`gradV/基线 = 1/(1 + K·V)`，
# K=0.0552 由垂直强度 V 拟合（rms 0.0404），用水平强度拟合只有 rms 0.0917 ⇒ 各向异性。
# `GaussianBlur.frag` **仍未读**，所以这里不猜 `u_Strength` 的量纲：改成**在我们自己这一帧上**
# 试一组半径、量同一口径（270×480 灰度垂直梯度，与 K 的拟合口径一致）的梯度，
# 取第一个达到目标比值的半径。内容自适应、无需存表。
AE_BLUR_K = 0.0552
AE_VBLUR_ATTR = "ADBE_Gaussian_Blur_2_0001_2_3"
AE_BLUR_RADII = (0, 1, 2, 3, 4, 6, 8, 11, 14, 18, 24)
# 峰值帧 V=300 要 17× 梯度抑制，单趟半径 24 到不了；重复同一半径即 sigma 合成。
AE_BLUR_MAX_PASSES = 8


def _grad_v_small(img: Image.Image) -> float:
    a = np.asarray(img.convert("L").resize((270, 480)), dtype=np.float64)
    return float(np.mean(np.abs(np.diff(a, axis=0))))


def apply_vertical_blur(canvas: Image.Image, strength: float) -> float:
    """把整画布的垂直梯度压到 `1/(1+K·V)` 预测的比例；返回实际达到的比值。

    阶梯是单调的，所以取**第一档达到目标**的半径（就地停手，宁可略欠不可过糊）；
    整条阶梯都够不到目标时——峰值帧 V=300 要 17× 抑制，单趟上限只有 ~3.5×——
    重复叠加最强一档（即 sigma 合成）直到达到或触顶。
    早退式"够不到就一档不动"是原缺陷：恰恰在最该糊的帧上不糊（201..203 实测比值 1.000）。
    """
    base = _grad_v_small(canvas)
    if base <= 0:
        return 1.0
    want = base / (1.0 + AE_BLUR_K * strength)
    top = ImageFilter.GaussianBlur(radius=(0, AE_BLUR_RADII[-1]))
    chosen, got = canvas, base
    for r in AE_BLUR_RADII:
        if r == 0:
            continue
        cand = canvas.filter(ImageFilter.GaussianBlur(radius=(0, r)))
        g = _grad_v_small(cand)
        if g <= want:
            chosen, got = cand, g
            break
    passes = 1
    while got > want and passes < AE_BLUR_MAX_PASSES:
        cand = chosen.filter(top)
        g = _grad_v_small(cand)
        if g >= got:
            break
        chosen, got, passes = cand, g, passes + 1
    canvas.paste(chosen)
    return got / base


def _ae_track(seg: dict, pos_us: int, attr: str | None, tag: str) -> float:
    """从段的 `in` 动画所指的包里取某条 AE 轨道在此刻的值（夹紧、不循环）。"""
    if AE_FLASH["off"]:
        return 0.0
    for a in seg.get("animations") or []:
        if a.get("kind") != "in" or not a.get("path"):
            continue
        lua = Path(a["path"]) / "AmazingFeature" / "lua" / "SeekModeScript.lua"
        if not lua.exists():
            continue
        pkg = _ae_pkg(str(lua))
        if pkg[0] == "ERR":
            AE_LOG.append(("degraded", str(seg.get("id")), pkg[1]))
            continue
        aek, tools, cons, expo = pkg
        key = expo if attr is None else attr
        if key not in tools.attrs:
            return 0.0
        dur = (a.get("duration_us") or 0) / 1e6
        if dur <= 0:
            continue
        t = (pos_us - seg["target"]["start_us"]) / 1e6
        cf = aek.frame_of_clamped(t, dur, cons, tools.all_frame)
        v = tools.get_val(key, max(0.0, min(cf, tools.all_frame)) / tools.all_frame)
        val = float(v[0] if isinstance(v, list) else v)
        AE_LOG.append((tag, str(seg.get("id")), round(t, 4), round(val, 4)))
        return val
    return 0.0


def _ae_pkg(lua_path: str):
    """解析并 memoize 一个包的 AE 表。解不出就返回 ("ERR", 原因) —— 降级要数得出来。"""
    if lua_path in _AE_CACHE:
        return _AE_CACHE[lua_path]
    val = None
    try:
        import ae_keyframe as aek
        src = Path(lua_path).read_text(encoding="utf-8", errors="replace")
        attrs = aek.parse_ae_attribute(src)
        expo = next((k for k in attrs if k.startswith("ADBE_Exposure")), None)
        if not attrs:
            val = ("ERR", "no-ae-table")
        else:
            # 没有曝光轨道不算"降级"：`侧滑` 这一族就是只有位移/缩放/旋转/模糊（P-176 解出来的 7 条里没曝光）。
            # 老版本在这里直接 ERR no-exposure-attr，把整包判死，连带让位移那条也进不来。
            val = (aek, aek.AETools(attrs), aek.extract_constants(src), expo)
    except Exception as e:                         # noqa: BLE001
        val = ("ERR", f"{type(e).__name__}: {e}")
    _AE_CACHE[lua_path] = val
    return val


def ae_exposure_at(seg: dict, pos_us: int) -> float:
    """该段入场动画在此时刻的曝光 E（0 表示不适用/已结束）。只认带表的 `in` 动画。"""
    return _ae_track(seg, pos_us, None, "applied")


def ae_vblur_at(seg: dict, pos_us: int) -> float:
    """同一段入场动画的**垂直**模糊强度 `u_Strength`（包里的轨道名是固定的）。"""
    return _ae_track(seg, pos_us, AE_VBLUR_ATTR, "vblur")


def apply_exposure(canvas: Image.Image, e: float) -> None:
    """逐字照 `Exposure.frag`：pow 2.2 → ×2^E → +u_Offset(0) → pow(1/gsc=1) → pow 0.454545454545。"""
    a = np.asarray(canvas).astype(np.float64)
    rgb = np.power(np.clip(a[..., :3] / 255.0, 0.0, 1.0), 2.2) * (2.0 ** e)
    a[..., :3] = np.clip(np.power(rgb, 0.454545454545) * 255.0, 0.0, 255.0)
    canvas.paste(Image.fromarray(a.astype(np.uint8), "RGBA"))


def collect(canvas, model, pos_us, fonts_dir_cache, depth=0):
    """Paint every track at pos_us onto canvas, composites recursed (P-02)."""
    layers = []
    actives = []
    for ti, track in enumerate(model["tracks"]):
        if track["type"] == "audio":
            continue
        seg = active_segment(track, pos_us)
        if not seg:
            continue
        actives.append(seg)
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
            frame = apply_color_adjust(frame, seg)
            layers.append(("image", z, seg, frame.convert("RGBA")))
    for kind, z, seg, payload in sorted(layers, key=lambda x: x[1]):
        if kind == "text":
            draw_text(canvas, seg, fonts_dir_cache, pos_us)
        else:
            c = kf_clip(seg, pos_us)
            x, y, img = place(payload, canvas.size, c,
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
                           opacity=float(c.get("alpha") if c.get("alpha") is not None else 1.0))
            else:
                canvas.alpha_composite(img, (x, y))
    if depth == 0 and actives:
        e = 0.0
        v = 0.0
        for seg in actives:
            e = max(e, ae_exposure_at(seg, pos_us))
            if AE_FLASH["blur"]:
                v = max(v, ae_vblur_at(seg, pos_us))
        if v > 0:                       # 包内顺序：模糊在前、曝光是最后一趟
            ratio = apply_vertical_blur(canvas, v)
            AE_LOG.append(("grad_ratio", round(v, 2), None, round(ratio, 4)))
        if e > 1e-4:
            apply_exposure(canvas, e)


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
    if FONT_FALLBACKS:
        # 报出来而不是悄悄画：这条时间线的字幕全用回退字体画，像素判据要按这个口径读（F-084）。
        print(f"font fallback used for {len(FONT_FALLBACKS)} requested face(s): "
              f"{sorted(set(map(str, FONT_FALLBACKS.values())))}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
