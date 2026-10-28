"""动画**接线**验证（曲线值本身由包内 lua 读，见 `animation_curve.py` 的模块文档）。

为什么不能只看门的其他层：动画只在段的头 0.1 s 里有可见差（P-30 就地更正的口径：
tween 时长来自包内 lua 的 0.1 s，而 `material_animations[].duration` 是 0.5 s 的预设槽长），
所以 1 s 网格的 L2/L3 永远碰不到它。这里用**真草稿里真带覆盖预设的段**做三条判据：
  (1) 至少存在一个我们能求值的预设（否则这条路径是死代码，门应该吵）；
  (2) 动画期内同一时刻开/关求值必须**画出不一样**（证明接线活着，不是只进了模型）；
  (3) 动画期外必须**逐字节一样**（证明曲线只在它该生效的窗口里生效，不是常驻改动）；
  (4) 求不了值的预设必须被显式记为未覆盖（不许用恒等曲线冒充实现）。

用法：
    python scripts/animation_wiring_check.py [--model temp/playback-test/model-check.json]
                                             [--out-dir temp/playback-test/animwiring]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_frame as rf  # noqa: E402
from animation_curve import load_curve  # noqa: E402
# Windows 控制台是 GBK：读数里带中文/箭头/替换符时 print 会在最后一步抛错，
# 把已经算完的结果整个吞掉（本轮自己的统计工具就栽过一次）。只改错误处理策略，不改编码。
try:
    sys.stdout.reconfigure(errors="replace")     # type: ignore[attr-defined]
    sys.stderr.reconfigure(errors="replace")     # type: ignore[attr-defined]
except Exception:                                 # noqa: BLE001
    pass


def covered_segments(model: dict) -> list[tuple[dict, float, list]]:
    out = []
    for tr in model["tracks"]:
        if tr["type"] == "audio":
            continue
        for s in tr["segments"]:
            for a in (s.get("animations") or []):
                trks = load_curve(a.get("path") or "")
                if trks:
                    out.append((s, (a.get("duration_us") or 0) / 1e6, trks))
                    break
    return out


def render(model: dict, t: float) -> np.ndarray:
    cw, ch = int(model["canvas"]["width"]), int(model["canvas"]["height"])
    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 255))
    rf.collect(canvas, model, int(round(t * 1e6)), {})
    return np.asarray(canvas.convert("RGB"), dtype=np.int16)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default="temp/playback-test/model-check.json")
    ap.add_argument("--out-dir", default="temp/playback-test/animwiring")
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    model = json.loads(Path(args.model).read_text(encoding="utf-8-sig"))

    cov = covered_segments(model)
    n_anim_seg = sum(1 for tr in model["tracks"] if tr["type"] != "audio"
                     for s in tr["segments"] if s.get("animations"))
    names_cov = sorted({a["name"] for tr in model["tracks"] if tr["type"] != "audio"
                        for s in tr["segments"] for a in (s.get("animations") or [])
                        if load_curve(a.get("path") or "")})
    names_miss = sorted({a["name"] for tr in model["tracks"] if tr["type"] != "audio"
                         for s in tr["segments"] for a in (s.get("animations") or [])
                         if not load_curve(a.get("path") or "")})

    rows = []
    for seg, dur_s, trks in cov[:6]:
        t0 = seg["target"]["start_us"] / 1e6
        tween = max((t_["dur_s"] for t_ in trks), default=0.1)
        inside = t0 + tween / 2
        outside = t0 + tween * 2.5
        if outside >= t0 + seg["target"]["duration_us"] / 1e6:
            outside = t0 + tween * 1.6
        rf.APPLY_ANIMATIONS = True
        on_in = render(model, inside)
        rf.APPLY_ANIMATIONS = False
        off_in = render(model, inside)
        rf.APPLY_ANIMATIONS = True
        on_out = render(model, outside)
        off_out = render(model, outside)
        d_in = int(np.abs(on_in - off_in).max())
        cells_in = int((np.abs(on_in - off_in) > 2).sum())
        d_out = int(np.abs(on_out - off_out).max())
        Image.fromarray(on_in.astype("uint8")).save(out / f"inside-{inside:.3f}-on.png")
        Image.fromarray(off_in.astype("uint8")).save(out / f"inside-{inside:.3f}-off.png")
        rows.append({"t0": round(t0, 3), "tween_s": tween, "inside": round(inside, 4),
                     "outside": round(outside, 4), "max_abs_inside": d_in,
                     "cells_changed_inside": cells_in, "max_abs_outside": d_out,
                     "props": sorted({t_["prop"] for t_ in trks}),
                     "name": next(a["name"] for a in seg["animations"]
                                  if load_curve(a.get("path") or ""))})
        print(f"  t0={t0:6.2f} {rows[-1]['name']:<10} tween={tween:.2f}s "
              f"inside Δmax={d_in:3d} ({cells_in} px changed)  outside Δmax={d_out}")
    rf.APPLY_ANIMATIONS = True

    checks = [
        ("存在可求值的动画预设（否则这条路径是死代码）", len(cov) > 0,
         f"{len(cov)}/{n_anim_seg} 段命中；覆盖预设 {names_cov}"),
        ("未覆盖预设被显式记下而不是用恒等曲线冒充", bool(names_miss),
         f"未覆盖 {len(names_miss)} 个：{names_miss}"),
        ("动画期内开/关画出不同（接线活着）",
         bool(rows) and all(r["max_abs_inside"] > 0 for r in rows),
         f"{len(rows)} 条候选里 Δmax>0 的有 "
         f"{sum(1 for r in rows if r['max_abs_inside'] > 0)} 条"),
        ("动画期外逐字节相同（曲线不常驻）",
         bool(rows) and all(r["max_abs_outside"] == 0 for r in rows),
         f"outside Δmax 全为 0：{[r['max_abs_outside'] for r in rows]}"),
        ("变化量足够可见（不是浮点尾差）",
         bool(rows) and max(r["cells_changed_inside"] for r in rows) > 1000,
         f"最多改变 {max([r['cells_changed_inside'] for r in rows] or [0])} 个像素通道"),
    ]
    bad = [c for c in checks if not c[1]]
    print("-" * 64)
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<44} {detail}")
    print(f"{len(checks) - len(bad)} of {len(checks)} animation wiring checks passed")
    (out / "wiring.json").write_text(json.dumps(
        {"model": args.model, "covered_segments": len(cov), "animation_segments": n_anim_seg,
         "covered_names": names_cov, "uncovered_names": names_miss, "rows": rows,
         "checks": [{"name": n, "ok": bool(o), "detail": d} for n, o, d in checks]},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
