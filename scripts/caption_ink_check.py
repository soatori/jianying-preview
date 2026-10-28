"""字幕带到底谁偏离成片：三条腿（浏览器 / 通道 2 / 原生导出）在同一条**由成片自己定出**的带里比。

为什么需要它（本脚本是对 F-083 的一次自我纠正）：
L10 首轮把跨通道崩口按**固定分带网格**定位，我说「字幕带两边一致、差在素材画面」。
那个网格的 y 范围是我**按字幕大概位置猜的**，不是量出来的——同类错误在 t=7.0 那回
直接把一个 540×953 居中盒的产物读成了 +21 个码值。所以这里把比较区改成
**由成片腿自己的亮墨包围盒**定出：先问「成片在这条时间线上到底把字画在哪」，
再问三条腿各自在那儿有多少墨、形状对不对。

三腿与口径：
  - 浏览器 = 页面 `app.renderer.extract.pixels(app.stage)` 自己回传的帧（540 宽）。
  - 通道 2 = `render_frame.collect`，**默认用代理模型**（浏览器播的是代理，媒体不同就不是
    同一条素材；F-083 附表里 0.910→0.948 那个差就是这条混淆）。
  - 成片 = `--export-mp4` 按 `select=eq(n,round(t*fps)+lead)` 取的那一帧（1080×1920）。
  - 三条腿一律降到同一 540×960（BOX，面积平均，不引入插值锐化），所以**同一相对框 = 同一整数框**，
    裁出来的三张小图逐像素对齐，不需要再搜位移（跨通道判据本来就不该搜，见 L10 的两条判据分离）。
  - 墨量阈值用绝对码值（200/220）：三腿同尺度时「>200 的像素数」就是笔画质量本身。
    注意它只在该带**确实有字**时才有意义，所以墨量必须和包围盒一起报，不能只报计数。

用法:
    python scripts/caption_ink_check.py [--timestamps 1.0,7.0] [--width 540] \
        [--model temp/playback-test/model-proxy.json] \
        [--export-mp4 "<你的成片 mp4，或设 JY_ORACLE_MP4>"] \
        [--report temp/playback-test/caption-ink.json]
前置：先跑一次带 `&shots=` 的页面（对应时刻要有 browser-shot-*.png）。
"""
from __future__ import annotations

import argparse
import os
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_frame as rf  # noqa: E402

try:
    sys.stdout.reconfigure(errors="replace")     # type: ignore[attr-defined]
    sys.stderr.reconfigure(errors="replace")     # type: ignore[attr-defined]
except Exception:                                 # noqa: BLE001
    pass

FFMPEG = r"D:\Program Files\JianyingPro\11.6.0.14552\ffmpeg.exe"
LUMA = np.array([0.299, 0.587, 0.114], dtype=np.float32)


def luma2d(path: Path, w: int, h: int) -> np.ndarray:
    im = Image.open(path).convert("RGB").resize((w, h), Image.BOX)
    return (np.asarray(im, dtype=np.float32) @ LUMA).reshape(h, w)


def export_frame(mp4: str, idx: int, out: Path) -> Path:
    if not out.is_file():
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-i", mp4,
                        "-vf", f"select=eq(n\\,{idx})", "-fps_mode", "passthrough",
                        "-frames:v", "1", "-y", str(out)], check=False)
    return out if out.is_file() else None


def ink_stats(v: np.ndarray, thr: float) -> dict:
    """亮墨计数 + 归一化包围盒（x0,x1,y0,y1）。空带时 bbox=None，别用 0 蒙。"""
    m = v > thr
    n = int(m.sum())
    if not n:
        return {"ink": 0, "bbox": None}
    ys, xs = np.nonzero(m)
    h, w = v.shape
    return {"ink": n,
            "bbox": [round(xs.min() / w, 4), round((xs.max() + 1) / w, 4),
                     round(ys.min() / h, 4), round((ys.max() + 1) / h, 4)]}


def cc(a: np.ndarray, b: np.ndarray) -> float:
    x, y = a.ravel() - a.mean(), b.ravel() - b.mean()
    return float(x @ y / (np.linalg.norm(x) * np.linalg.norm(y) + 1e-9))


def active_texts(model: dict, t: float) -> list:
    """这条时刻活着的字幕段 + 它在画幅里的**行中心**（v = 0.5 - clip.y/2，y 轴向上）。

    窗口来自模型几何而不是「猜个带」，也不是从成片的亮墨反推——本例素材本身就有一片
    200 码值以上的亮区，第一次跑把「成片墨盒」量成了整幅（0..1），那条读数作废。
    """
    out = []
    for tr in model.get("tracks", []):
        if tr.get("type") != "text":
            continue
        for seg in tr.get("segments", []):
            tg = seg.get("target", {})
            s = tg.get("start_us", 0) / 1e6
            d = tg.get("duration_us", 0) / 1e6
            if d <= 0 or not (s <= t < s + d):
                continue
            tx = seg.get("text") or {}
            c = seg.get("clip") or {}
            styles = tx.get("styles") or [{}]
            size = max([st.get("size") or 0 for st in styles] + [tx.get("font_size") or 0])
            out.append({"content": (tx.get("text") or "")[:20], "t0": round(s, 3),
                        "dur": round(d, 3), "size": size, "align": tx.get("alignment"),
                        "color": tx.get("text_color"),
                        "x": round(c.get("x", 0.0), 4), "y": round(c.get("y", 0.0), 4),
                        "v_center": round(0.5 - c.get("y", 0.0) / 2, 4),
                        "anim": [a.get("kind") for a in seg.get("animations", []) if a.get("kind")]})
    return out


def sweep_fallbacks(legs_src: dict, t: float, model: dict, cw: int, ch: int,
                    W: int, H: int, box: list, candidates: list) -> None:
    """把通道 2 的回退字体逐个换一遍，看哪个**最贴近成片的墨量**。

    原字体（本例 HelloFont_ID_JianSong_95，一款重宋）在这台机器上已经不存在了，
    所以「换哪一款」不是审美选择，是一次标定：判据=字幕带里对成片的 corr 与墨量比。
    这里直接改模块属性再重画，属于实验台行为，不进渲染器的默认链。
    """
    j0, j1 = int(box[2] * H), int(box[3] * H)
    i0, i1 = int(box[0] * W), int(box[1] * W)
    exp = legs_src["export"][j0:j1, i0:i1]
    orig = list(rf.FALLBACK_FONTS)
    print(f"  回退标定 t={t} 带 {box}：成片墨 {int((exp>200).sum())} corr 1.0")
    for cand in candidates:
        rf.FALLBACK_FONTS[:] = [cand]
        rf._font_cache.clear()
        canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 255))
        rf.collect(canvas, model, int(round(t * 1e6)), {})
        v = luma2d_from(canvas, W, H)[j0:j1, i0:i1]
        s = ink_stats(v, 200)
        print(f"    {Path(cand).name:22s} 墨 {s['ink']:6d}  对成片 corr {cc(v, exp):.4f}  "
              f"MAD {float(np.abs(v-exp).mean()):6.2f}  墨盒 {s['bbox']}")
    rf.FALLBACK_FONTS[:] = orig
    rf._font_cache.clear()


def luma2d_from(im: Image.Image, w: int, h: int) -> np.ndarray:
    a = np.asarray(im.convert("RGB").resize((w, h), Image.BOX), dtype=np.float32)
    return (a @ LUMA).reshape(h, w)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default="temp/playback-test")
    ap.add_argument("--model", default="temp/playback-test/model-proxy.json",
                    help="通道 2 用哪份模型：默认代理，与浏览器播的同一批媒体")
    ap.add_argument("--export-mp4", default=os.environ.get("JY_ORACLE_MP4", ""))
    ap.add_argument("--timestamps", default="1.0")
    ap.add_argument("--width", type=int, default=540)
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--lead", type=int, default=3)
    ap.add_argument("--thr", type=float, default=200.0, help="亮墨阈（绝对码值，三腿同尺度才可比）")
    ap.add_argument("--band-half", type=float, default=0.05,
                    help="行中心上下各取多少画幅高（宁大勿小：小了会把两行字幕切掉）")
    ap.add_argument("--report", default="temp/playback-test/caption-ink.json")
    ap.add_argument("--sweep-fallbacks", action="store_true",
                    help="把通道 2 的回退字体逐个标定一遍（缺字体时用，判据=对成片墨量与 corr）")
    ap.add_argument("--candidates", default=",".join([
        r"C:\Windows\Fonts\NotoSansSC-VF.ttf", r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\simhei.ttf"]))
    args = ap.parse_args()

    d = Path(args.dir)
    model = json.loads(Path(args.model).read_text(encoding="utf-8-sig"))
    cw, ch = int(model["canvas"]["width"]), int(model["canvas"]["height"])
    # 截图文件名里的时刻是页面写出来的（1.0 -> "1"，6.633 -> "6-633"），所以**按解析出的浮点**
    # 配，别拿字符串去拼——`colour_range_probe` 那轮就因为拼名把一张已存在的截图当成缺失。
    shots = {}
    for p in d.glob("browser-shot-*.png"):
        try:
            shots[float(p.stem.replace("browser-shot-", "").replace("-", "."))] = p
        except ValueError:
            pass
    W = args.width
    H = int(round(W * ch / cw))
    rows = []
    for tag in [x.strip() for x in args.timestamps.split(",") if x.strip()]:
        t = float(tag)
        hit = [p for tt, p in shots.items() if abs(tt - t) < 1e-3]
        if not hit:
            print(f"t={t}: 没有对应截图（现有 {sorted(shots)}）")
            continue
        shot = hit[0]
        key = tag.replace(".", "-")
        idx = int(round(t * args.fps)) + args.lead
        exp = export_frame(args.export_mp4, idx, d / f"export-frame-{idx}.png")
        if exp is None:
            print(f"t={t}: 取不到成片帧 {idx}")
            continue
        c2 = d / f"c2ink-{key}.png"
        canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 255))
        rf.collect(canvas, model, int(round(t * 1e6)), {})
        canvas.convert("RGB").save(c2)

        legs = {"browser": luma2d(shot, W, H), "channel2": luma2d(c2, W, H),
                "export": luma2d(exp, W, H)}
        # 对齐核验：不核验就重演 t=7.0 的居中盒假读数。整帧 corr 低 ⇒ 先别解读分带。
        whole = {k: round(cc(v, legs["export"]), 4) for k, v in legs.items()}
        texts = active_texts(model, t)
        row = {"t": t, "export_frame": idx, "shot": shot.name, "model": Path(args.model).name,
               "scale": [W, H], "whole_frame_corr_vs_export": whole,
               "texts": texts, "legs": {}}
        if not texts:
            row["note"] = "这一帧模型里没有活动字幕段：没有可比的字幕，换时刻"
            rows.append(row)
            print(f"t={t:6.3f}  无活动字幕段（跳过）")
            continue
        # 带 = 各活动字幕行中心的并集，上下各放半个行高（行高按 em 估，宁大勿小）
        vc = [x["v_center"] for x in texts]
        em = max(x["size"] for x in texts) * rf.K_EM * cw / ch     # 字号换算到画幅高占比
        half = max(args.band_half, 0.8 * em)
        y0 = max(0.0, min(vc) - half)
        y1 = min(1.0, max(vc) + half)
        j0, j1 = int(y0 * H), int(y1 * H)
        row["band_rows"] = [round(y0, 4), round(y1, 4), j0, j1]
        band = {k: v[j0:j1, :] for k, v in legs.items()}
        # 带内**成片的墨盒**才定横向范围：素材再亮也只占几行，白字在带里通常是主导亮区。
        eb = ink_stats(band["export"], args.thr)["bbox"]
        if eb is None:
            row["note"] = f"带内成片在 {args.thr} 阈值下无亮墨：这条时刻的字幕不是亮色，判据不适用"
            rows.append(row)
            print(f"t={t:6.3f}  带内成片无亮墨（跳过，见 note）")
            continue
        i0, i1 = int(eb[0] * W), int(eb[1] * W)
        crops = {k: v[:, i0:i1] for k, v in band.items()}
        row["box"] = [round(eb[0], 4), round(eb[1], 4), round(y0, 4), round(y1, 4)]
        for k, v in crops.items():
            s = ink_stats(v, args.thr)
            row["legs"][k] = {"mean": round(float(v.mean()), 2),
                              "p99": round(float(np.percentile(v, 99)), 1),
                              "ink": s["ink"], "ink220": ink_stats(v, 220)["ink"],
                              "bbox": s["bbox"],
                              "corr_vs_export": round(cc(v, crops["export"]), 4),
                              "mad_vs_export": round(float(np.abs(v - crops["export"]).mean()), 2)}
        row["ink_ratio_browser_over_c2"] = round(
            row["legs"]["browser"]["ink"] / max(1, row["legs"]["channel2"]["ink"]), 2)
        rows.append(row)
        if args.sweep_fallbacks:
            sweep_fallbacks(legs, t, model, cw, ch, W, H,
                            [row["box"][0], row["box"][1], row["band_rows"][0], row["band_rows"][1]],
                            [c.strip() for c in args.candidates.split(",") if c.strip()])
        print(f"t={t:6.3f}  帧 {idx}  整帧corr 浏览器 {whole['browser']} / 通道2 {whole['channel2']}")
        b, c, x = row["legs"]["browser"], row["legs"]["channel2"], row["legs"]["export"]
        print(f"          带 {row['box']}  均值 浏览 {b['mean']}  通道2 {c['mean']}  成片 {x['mean']}")
        print(f"          >{args.thr} 墨 浏览 {b['ink']}  通道2 {c['ink']}  成片 {x['ink']}"
              f"   >220 浏览 {b['ink220']} 通道2 {c['ink220']} 成片 {x['ink220']}")
        print(f"          对成片 corr 浏览 {b['corr_vs_export']}  通道2 {c['corr_vs_export']}   "
              f"MAD 浏览 {b['mad_vs_export']}  通道2 {c['mad_vs_export']}")
        print(f"          墨盒 浏览 {b['bbox']}  通道2 {c['bbox']}  成片 {x['bbox']}")
        for tx in texts:
            print(f"          活动字幕 {tx}")
    Path(args.report).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"report -> {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
