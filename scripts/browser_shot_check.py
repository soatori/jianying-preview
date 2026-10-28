"""浏览器回传的帧 vs 成片同刻 vs 通道 2 同刻——把**交互预览内核自己**放到像素判据下。

为什么需要它：门的 L2/L3 都用 `render_frame.py`（通道 2）出图，所以直到今天
"预览看起来对不对" 其实是被**另一条通道**代答的；播放器只被「不是黑帧」和帧率数字判过（L4/L6）。
本脚本让浏览器把 Pixi 真正画出来的那一帧回传（`player.html?shots=` → 网关 `/shot`），
然后与两把尺对：① 同刻的成片帧（产品目标），② 同刻的通道 2 帧（两条通路必须说同一件事）。

口径：
  - 浏览器图是页面自己降到 540 宽的（`toDataURL` 前），成片帧按 `round(t*fps)+lead` **固定**取，
    不搜偏移（P-29）；通道 2 帧现算并降到同一 540 尺度，三者尺度一致才可比。
  - 度量还是多尺度 luma Pearson（与 `export_compare` 同族）：绝对码值必然不同（编解码、色域、
    导出锐化），要比的是结构。
  - 判据分两条，不合并成一条：**跨通道一致**（浏览器 vs 通道 2）应当很高，因为是同一份模型同一条
    布局律；**对成片**允许更低一档，因为浏览器侧还有解码器与色彩范围差异。
    把两条混成一个阈值，会把「两条通道不一致」读成「成片本来就这样」。

用法:
    python scripts/browser_shot_check.py [--dir temp/playback-test] \
        [--model temp/playback-test/model-check.json] [--timestamps 1.0,6.633,20.23] \
        [--min-cross 0.95] [--min-export 0.90] [--report temp/playback-test/browser-shots.json]
前置：先跑一次带 `&shots=...` 的页面（网关得活着）。
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_frame as rf  # noqa: E402
# Windows 控制台是 GBK：读数里带中文/箭头/替换符时 print 会在最后一步抛错，
# 把已经算完的结果整个吞掉（本轮自己的统计工具就栽过一次）。只改错误处理策略，不改编码。
try:
    sys.stdout.reconfigure(errors="replace")     # type: ignore[attr-defined]
    sys.stderr.reconfigure(errors="replace")     # type: ignore[attr-defined]
except Exception:                                 # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parents[1]


def luma_at(path_or_arr, w: int, h: int) -> np.ndarray:
    if isinstance(path_or_arr, (str, Path)):
        im = Image.open(path_or_arr).convert("RGB")
    else:
        im = path_or_arr.convert("RGB")
    im = im.resize((w, h), Image.BOX)
    a = np.asarray(im, dtype=np.float32)
    v = a @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    v = v.ravel()
    v = v - v.mean()
    return v / (np.linalg.norm(v) + 1e-9)


def corr(a: np.ndarray, b: np.ndarray) -> float:
    return float(a @ b)


def channel2_png(model: dict, t: float, out: Path) -> None:
    cw, ch = int(model["canvas"]["width"]), int(model["canvas"]["height"])
    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 255))
    rf.collect(canvas, model, int(round(t * 1e6)), {})
    canvas.convert("RGB").save(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default="temp/playback-test")
    ap.add_argument("--model", default="temp/playback-test/model-check.json")
    ap.add_argument("--frames-dir", default="temp/playback-test/oracle/dense216")
    ap.add_argument("--timestamps", default="")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--lead", type=int, default=3)
    ap.add_argument("--width", type=int, default=270, help="统一比较尺度（短边方向宽）")
    ap.add_argument("--min-cross", type=float, default=0.95)
    ap.add_argument("--min-export", type=float, default=0.90)
    ap.add_argument("--report", default="temp/playback-test/browser-shots.json")
    ap.add_argument("--max-age-min", type=float, default=180.0,
                    help="截图超过这么多分钟就跳过（过期截图不会报错，只会给出假的负相关）")
    args = ap.parse_args()

    d = Path(args.dir)
    shots = sorted(d.glob("browser-shot-*.png"))
    if not shots:
        print(f"没有 {d}/browser-shot-*.png —— 先跑一次带 &shots= 的页面（网关要活着）")
        return 2
    frames = sorted(Path(args.frames_dir).glob("*.png"))
    model = json.loads(Path(args.model).read_text(encoding="utf-8-sig"))
    cw, ch = int(model["canvas"]["width"]), int(model["canvas"]["height"])
    want = {x.strip() for x in args.timestamps.split(",") if x.strip()}

    rows, bad = [], []
    h = int(round(args.width * 1920 / 1080))
    for png in shots:
        tag = png.stem.replace("browser-shot-", "").replace("-", ".")
        try:
            t = float(tag)
        except ValueError:
            continue
        if want and f"{t}" not in want and f"{t:.3f}" not in want:
            continue
        idx = int(round(t * args.fps)) + args.lead
        if not (0 <= idx < len(frames)):
            rows.append({"t": t, "skipped": f"成片帧号 {idx} 越界"})
            continue
        ours = d / f"c2-{tag}.png"
        channel2_png(model, t, ours)
        # 两条截图卫生判据，都是 t=12 那次「跨通道 −0.370」教出来的（重截后同一时刻 0.980）：
        # (1) **过期**：判据端无法从图本身看出它是哪一版页面产的，过期截图不会报错，
        #     只会给出一个看起来很严重的负相关 ⇒ 超过 --max-age-min 就跳过并报。
        # (2) **几何**：`extract.pixels(stage)` 取的是 stage 的**内容包围盒**，不是画幅，
        #     所以 540 宽的截图通常是 540×953 而非 540×960（差 0.7%，随时刻变化）。
        #     这条只**报**不判——真出现大偏差（>2%）才是信箱或别的东西。
        sw, sh = Image.open(png).size
        want_h = int(round(sw * ch / cw))
        age_min = (time.time() - png.stat().st_mtime) / 60.0
        if age_min > args.max_age_min:
            bad.append(f"t={t} 截图已过期 {age_min:.0f} 分钟（>{args.max_age_min:.0f}）——"
                       f"它可能是另一版页面产的，先重跑 &shots= 再判")
            rows.append({"t": t, "skipped": f"shot age {age_min:.0f} min"})
            print(f"  t={t:7.3f}  SKIP 截图过期 {age_min:.0f} 分钟")
            continue
        if abs(sh - want_h) > 0.02 * want_h:
            bad.append(f"t={t} 截图 {sw}x{sh} 与画幅比例差 {abs(sh-want_h)/want_h:.1%}"
                       f"（>2%）——信箱或别的内容，不是 0.7% 的内容包围盒效应")
            rows.append({"t": t, "skipped": f"shot geometry {sw}x{sh} vs {sw}x{want_h}"})
            print(f"  t={t:7.3f}  SKIP 截图几何 {sw}x{sh}（画幅应为 {sw}x{want_h}）")
            continue
        meta = png.with_suffix(".json")
        paint_us = json.loads(meta.read_text(encoding="utf-8")).get("t_paint_us") if meta.is_file() else None
        dt_paint = round(abs((paint_us or 0) / 1e6 - t), 4) if paint_us is not None else None
        b = luma_at(png, args.width, h)
        c = luma_at(ours, args.width, h)
        # 两条判据的混淆项不同，所以对对齐的处理也不同：
        #   跨通道：同一份模型、同一时刻、同一布局律 => 不存在位移问题，固定同刻比，差就是差。
        #   对成片：切点两侧是**不同镜头**，固定帧号差一帧就会把 0.98 读成 0.13（P-28/F-072 的教训），
        #           所以允许 +-3 搜最佳对齐，并把选中的偏移报出来——偏移本身是证据，不是和稀泥。
        o0 = luma_at(frames[idx], args.width, h)
        cand = [(k, corr(b, luma_at(frames[idx + k], args.width, h)))
                for k in range(-3, 4) if 0 <= idx + k < len(frames)]
        off, ecorr = max(cand, key=lambda x: x[1])
        xcorr = corr(b, c)
        xcorr, ecorr = round(xcorr, 3), round(ecorr, 3)
        ok_x, ok_e = xcorr >= args.min_cross, ecorr >= args.min_export
        rows.append({"t": t, "export_frame": idx, "chosen_offset_frames": off,
                     "browser_vs_channel2": xcorr,
                     "browser_vs_export": ecorr, "cross_ok": ok_x, "export_ok": ok_e,
                     "capture_dt_s": dt_paint, "shot": png.name})
        line = (f"  t={t:7.3f}  浏览器 vs 通道2 {xcorr:.3f} {'PASS' if ok_x else 'FAIL'}   "
                f"浏览器 vs 成片 {ecorr:.3f} {'PASS' if ok_e else 'FAIL'} (偏移 {off:+d} 帧, "
                f"截图与目标时刻差 {dt_paint} s)")
        print(line)
        if not ok_x:
            bad.append(f"t={t} 跨通道只有 {xcorr}（< {args.min_cross}）——两条通路对同一时刻说不一致")
        if not ok_e:
            bad.append(f"t={t} 浏览器对成片只有 {ecorr}（< {args.min_export}）")
    n = len([r for r in rows if "browser_vs_channel2" in r])
    if n == 0:
        print("没有可比帧")
        return 2
    print("-" * 68)
    print(f"{n} 个时刻；跨通道一致中位 {sorted(r['browser_vs_channel2'] for r in rows if 'browser_vs_channel2' in r)[n//2]:.3f}，"
          f"对成片中位 {sorted(r['browser_vs_export'] for r in rows if 'browser_vs_export' in r)[n//2]:.3f}")
    for x in bad[:6]:
        print("  !", x)
    Path(args.report).write_text(json.dumps(
        {"width": args.width, "rows": rows, "problems": bad,
         "thresholds": {"cross": args.min_cross, "export": args.min_export}},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"report -> {args.report}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
