"""把「L1 丢了 33 段动画」量成一个可对成片比较的数：动画窗内 vs 窗外的整帧相关差。

为什么要单独量（而不是只报条数）：P-29 只用 6.6 s 一个时刻证明了白闪来自入场动画，但
「33 段没渲染动画」到底让预览偏离成片多少，是一个分布问题；不量就只能说「有缺口」，
没法说「先做哪个」。判据形态照 P-29 的教训：**固定 oracle 帧号**（`round(t*fps)+lead`），
不搜偏移 —— 对一段正在衰减的闪光搜偏移得到的数字没有含义。

口径：
  - 动画窗 = `[t0, t0+dur)`（kind=in）或 `[t0+seg_dur-dur, t0+seg_dur)`（kind=out）；
    dur 来自 `segments[].animations[].duration_us`（F-078 新增的字段）。
  - 对照窗 = 同一段里动画之外的位置，最多取 `--rest-cap` 秒，步长比窗内粗（窗外本来就该是稳态）。
  - corr = 64 px luma Pearson，成片帧与我们通道 2 的渲染同刻对同刻。
  - 「 attributable」= 窗内 < 阈值 且 窗外 >= 阈值 的时刻对数 —— 只有这种配法才把责任交给动画，
    窗外也低的时刻是别的成因（调色、行人运动），不计进来。

用法：
    python scripts/animation_gap.py --model temp/playback-test/model-check.json \
        --frames-dir temp/playback-test/oracle/dense216 \
        [--threshold 0.95] [--inside-step 0.1] [--rest-step 0.25] [--rest-cap 2.0] \
        [--report temp/playback-test/animation-gap.json]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_frame as rf  # noqa: E402
from export_compare import luma  # noqa: E402
# Windows 控制台是 GBK：读数里带中文/箭头/替换符时 print 会在最后一步抛错，
# 把已经算完的结果整个吞掉（本轮自己的统计工具就栽过一次）。只改错误处理策略，不改编码。
try:
    sys.stdout.reconfigure(errors="replace")     # type: ignore[attr-defined]
    sys.stderr.reconfigure(errors="replace")     # type: ignore[attr-defined]
except Exception:                                 # noqa: BLE001
    pass

_ORIG = rf.decode_frame
_CACHE: dict[tuple[str, int], object] = {}
_CAP = [64]   # 钳住解码缓存：一帧 1080x1920 约 8 MB。第一版没有上界，一次 A/B 吃到 4.2 GB 被停掉
              # ——工具自己的内存也要管，和门的 RSS 纪律同一条。用可变容器而不是 global：
              # `global X` 写在同名使用之后是 SyntaxError，两条腿当时就当场崩了。


def memo_decode(path: str, at_s: float):
    key = (path, int(round(at_s * 1e6)))
    if key not in _CACHE:
        _CACHE[key] = _ORIG(path, at_s)
        while len(_CACHE) > _CAP[0]:
            _CACHE.pop(next(iter(_CACHE)))
    return _CACHE[key]


rf.decode_frame = memo_decode


def corr_at(model: dict, frames: list[Path], t: float, lead: int, fps: float,
            scale: int, fonts: dict) -> tuple[float, str]:
    cw, ch = int(model["canvas"]["width"]), int(model["canvas"]["height"])
    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 255))
    rf.collect(canvas, model, int(round(t * 1e6)), fonts)
    idx = int(round(t * fps)) + lead
    if not (0 <= idx < len(frames)):
        return float("nan"), "outside"
    ours = luma_from(canvas, scale)
    return float(luma(frames[idx], scale) @ ours), "ok"


def luma_from(img: Image.Image, scale: int) -> np.ndarray:
    im = img.convert("RGB").resize((scale, max(1, int(round(scale * img.height / img.width)))), Image.BOX)
    a = np.asarray(im, dtype=np.float32)
    v = a @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    v = v.ravel()
    v = v - v.mean()
    return v / (np.linalg.norm(v) + 1e-9)


def windows(seg: dict) -> list[tuple[float, float, str, str]]:
    t0 = seg["target"]["start_us"] / 1e6
    dur = seg["target"]["duration_us"] / 1e6
    out = []
    for a in seg.get("animations") or []:
        d = (a.get("duration_us") or 0) / 1e6
        if not d:
            continue
        kind = a.get("kind")
        if kind == "out":
            out.append((t0 + max(0.0, dur - d), t0 + dur, kind, a.get("name") or ""))
        else:
            out.append((t0, min(t0 + dur, t0 + d), kind, a.get("name") or ""))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", required=True)
    ap.add_argument("--frames-dir", required=True)
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--lead", type=int, default=3)
    ap.add_argument("--scale", type=int, default=64)
    ap.add_argument("--threshold", type=float, default=0.95)
    ap.add_argument("--inside-step", type=float, default=0.1)
    ap.add_argument("--rest-step", type=float, default=0.25)
    ap.add_argument("--rest-cap", type=float, default=2.0)
    ap.add_argument("--report", default="")
    ap.add_argument("--cache-cap", type=int, default=_CAP[0],
                    help="解码缓存的帧数上限（每帧 ~8 MB）")
    ap.add_argument("--no-animations", action="store_true",
                    help="A/B 用：关掉通道 2 的动画求值，量同一批时刻的对照")
    ap.add_argument("--only-names", default="",
                    help="逗号分隔的动画名过滤（只量我们实现得动的那几个）")
    ap.add_argument("--head", type=float, default=0.12,
                    help="动画头几秒单独统计（tween 实测只有 0.1 s，摊到 0.5 s 窗里就看不见了）")
    args = ap.parse_args()

    frames = sorted(Path(args.frames_dir).glob("*.png"))
    if len(frames) < 10:
        sys.exit(f"oracle dir {args.frames_dir} has {len(frames)} pngs")
    model = json.loads(Path(args.model).read_text(encoding="utf-8-sig"))
    if args.no_animations:
        rf.APPLY_ANIMATIONS = False
    only = {x.strip() for x in args.only_names.split(",") if x.strip()}
    _CAP[0] = max(4, int(args.cache_cap))
    fonts: dict = {}
    inside: list[float] = []
    rest: list[float] = []
    rows = []
    per_name: dict[str, list[float]] = {}

    segs = [s for tr in model["tracks"] if tr["type"] != "audio" for s in tr["segments"]
            if s.get("animations") and (not only or any(a["name"] in only
                                                        for a in s["animations"]))]
    print(f"{len(segs)} segments carry animation entries; scale={args.scale}px "
          f"threshold={args.threshold} fixed-index (no shift search)")
    for seg in segs:
        ws = windows(seg)
        if not ws:
            continue
        t0 = seg["target"]["start_us"] / 1e6
        dur = seg["target"]["duration_us"] / 1e6
        ins_vals = []
        head_vals = []
        for (a, b, kind, name) in ws:
            t = a + args.inside_step / 2
            while t < b:
                c, _ = corr_at(model, frames, t, args.lead, args.fps, args.scale, fonts)
                if c == c:
                    ins_vals.append(c)
                    inside.append(c)
                    per_name.setdefault(name or kind, []).append(c)
                    if t - t0 <= args.head:
                        head_vals.append(c)
                t += args.inside_step
        rv = []
        span = min(dur, args.rest_cap)
        t = t0 + (ws[0][1] - t0) + args.rest_step / 2   # 动画结束后起量
        while t < t0 + span:
            c, _ = corr_at(model, frames, t, args.lead, args.fps, args.scale, fonts)
            if c == c:
                rv.append(c)
                rest.append(c)
            t += args.rest_step
        if head_vals:
            row_head = {"t0": round(t0, 3), "name": ws[0][3],
                        "head_med": round(statistics.median(head_vals), 3),
                        "head_min": round(min(head_vals), 3),
                        "rest_med": round(statistics.median(rv), 3) if rv else None}
            rows.append({**row_head, "inside_med": row_head["head_med"],
                         "inside_min": row_head["head_min"], "kind": ws[0][2],
                         "rest_min": min(rv) if rv else None, "attributable": False})
        if ins_vals:
            attributable = bool(sum(1 for c in ins_vals if c < args.threshold)) and bool(rv)                 and min(rv) >= args.threshold
            rows.append({"t0": round(t0, 3), "kind": ws[0][2], "name": ws[0][3],
                         "inside_med": round(statistics.median(ins_vals), 3),
                         "inside_min": round(min(ins_vals), 3),
                         "head_med": round(statistics.median(head_vals), 3) if head_vals else None,
                         "rest_med": round(statistics.median(rv), 3) if rv else None,
                         "rest_min": round(min(rv), 3) if rv else None,
                         "attributable": attributable})
            rest_txt = (f"rest {statistics.median(rv):.3f}" if rv else "rest n/a")
            head_txt = (f"head {statistics.median(head_vals):.3f}" if head_vals else "head n/a")
            print(f"  t0={t0:6.2f} {ws[0][3] or ws[0][2]:<10} inside {statistics.median(ins_vals):.3f}"
                  f" (min {min(ins_vals):.3f})  {head_txt}  {rest_txt}"
                  f"{'  <== 动画可归因' if attributable else ''}")

    if not inside:
        print("动画窗内一个可比时刻都没有（oracle 帧号越界？时刻数？先查这三样）")
        return 2
    print("-" * 68)
    print(f"samples: inside {len(inside)}  rest {len(rest)}   "
          f"animations_applied={rf.APPLY_ANIMATIONS} head={args.head}s")
    for label, xs in (("inside", inside), ("rest", rest)):
        if not xs:
            continue
        print(f"  {label:<7} median {statistics.median(xs):.3f}  p10 {np.percentile(xs,10):.3f} "
              f" min {min(xs):.3f}  below {args.threshold}: {sum(1 for x in xs if x < args.threshold)}/{len(xs)}")
    names = sorted(((n, statistics.median(v), len(v), min(v)) for n, v in per_name.items()),
                   key=lambda x: x[1])
    print("per animation (median corr inside, n, min):")
    for n, med, k, mn in names[:10]:
        print(f"  {n:<12} {med:.3f}  n={k:<3} min={mn:.3f}")
    if args.report:
        Path(args.report).write_text(json.dumps(
            {"model": args.model, "threshold": args.threshold, "scale": args.scale,
             "inside": {"n": len(inside), "median": statistics.median(inside),
                        "below": sum(1 for x in inside if x < args.threshold)},
             "rest": {"n": len(rest), "median": statistics.median(rest),
                      "below": sum(1 for x in rest if x < args.threshold)},
             "per_name": {n: {"median": statistics.median(v), "n": len(v), "min": min(v)}
                          for n, v in per_name.items()},
             "segments": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"report -> {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
