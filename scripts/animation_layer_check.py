"""字幕动画的**图层级**判据：我们的字幕中心 vs 成片字幕中心，动画开/关谁更近。

为什么不用整帧相关判：F-072 测过，删掉全部字幕轨整帧只掉 0.005~0.024 ——
整帧判据对字幕几乎瞎。所以这里沿用门里 L2 的度量（`playback_check.layer_metrics`：
单色层的质心 + 1-99 百分位包围盒，归一化画幅单位），直接问一件事：
**动画接上以后，字幕在画面里的位置是不是更接近成片**。

颜色不硬编：从该片段的 `text.styles[].color` 里取，取第一个在成片帧上能匹配到 >=50 像素的色。
判读：`Δcy_on < Δcy_off` 就是方向对；反过来就是**我们把方向做反了**（负结果也要落档，
不许只报变好的那一半）。`dy` 的符号约定来自 F-035/U-08（y 轴向上为正，画布坐标要减）。

用法：
    python scripts/animation_layer_check.py [--model ...] [--frames-dir ...]
        [--head-steps 4] [--scale-colour-tol 46] [--report temp/playback-test/anim-layer.json]
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
from playback_check import layer_metrics  # noqa: E402
# Windows 控制台是 GBK：读数里带中文/箭头/替换符时 print 会在最后一步抛错，
# 把已经算完的结果整个吞掉（本轮自己的统计工具就栽过一次）。只改错误处理策略，不改编码。
try:
    sys.stdout.reconfigure(errors="replace")     # type: ignore[attr-defined]
    sys.stderr.reconfigure(errors="replace")     # type: ignore[attr-defined]
except Exception:                                 # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parents[1]


def rgb255(color) -> tuple[int, int, int] | None:
    if not color or len(color) < 3:
        return None
    return tuple(int(round(255 * max(0.0, min(1.0, c)))) for c in color[:3])   # type: ignore[return-value]


def seg_colours(seg: dict) -> list[tuple[int, int, int]]:
    out = []
    for st in ((seg.get("text") or {}).get("styles") or []):
        c = rgb255(st.get("color"))
        if c and c not in out:
            out.append(c)
    return out or [(255, 255, 255)]


def render_png(model: dict, t: float, apply_anim: bool, path: Path) -> None:
    cw, ch = int(model["canvas"]["width"]), int(model["canvas"]["height"])
    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 255))
    rf.APPLY_ANIMATIONS = apply_anim
    rf.collect(canvas, model, int(round(t * 1e6)), {})
    rf.APPLY_ANIMATIONS = True
    canvas.convert("RGB").save(path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default="temp/playback-test/model-check.json")
    ap.add_argument("--frames-dir", default="temp/playback-test/oracle/dense216")
    ap.add_argument("--curves", default="temp/playback-test/animation-curves.json")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--lead", type=int, default=3)
    ap.add_argument("--head-steps", type=int, default=4)
    ap.add_argument("--report", default="temp/playback-test/anim-layer.json")
    args = ap.parse_args()

    frames = sorted(Path(args.frames_dir).glob("*.png"))
    model = json.loads(Path(args.model).read_text(encoding="utf-8-sig"))
    curves = json.loads(Path(args.curves).read_text(encoding="utf-8-sig"))["presets"]
    out_dir = ROOT / "temp" / "playback-test" / "animlayer"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    skipped: list[dict] = []
    for tr in model["tracks"]:
        if tr["type"] != "text":
            continue
        for s in tr["segments"]:
            an = (s.get("animations") or [{}])[0]
            key = str(an.get("resource_id") or "")
            if key not in curves:
                continue
            pre = curves[key]
            dur = max((t_["dur_s"] for t_ in pre["tracks"]), default=0.1)
            t0 = s["target"]["start_us"] / 1e6
            ts = [t0 + dur * k / max(args.head_steps - 1, 1) for k in range(args.head_steps)]
            ts.append(t0 + dur * 3)
            for t in ts:
                idx = int(round(t * args.fps)) + args.lead
                if not (0 <= idx < len(frames)):
                    continue
                rp_on = out_dir / f"on-{t:.3f}.png"
                rp_off = out_dir / f"off-{t:.3f}.png"
                render_png(model, t, True, rp_on)
                render_png(model, t, False, rp_off)
                best = None
                for col in seg_colours(s):
                    m_on = layer_metrics(rp_on, frames[idx], col)
                    m_off = layer_metrics(rp_off, frames[idx], col)
                    if m_on.get("n_cover", 0) < 50:
                        continue          # 成片侧匹配不到这个色 => 换下一个色
                    if m_on.get("n_render", 0) < 50 or m_off.get("n_render", 0) < 50:
                        # 我们这侧没出图。动画期里淡到 0 是正常的，但**只有一侧没出图**时必须记下来：
                        # 那意味着成片看得见而我们看不见（或反之），不是「无差」。
                        skipped.append({"t": round(t, 4), "name": pre["name"],
                                        "colour": list(col),
                                        "n_render_on": m_on.get("n_render", 0),
                                        "n_render_off": m_off.get("n_render", 0),
                                        "n_cover": m_on.get("n_cover", 0)})
                        continue
                    best = {"t": round(t, 4), "name": pre["name"], "colour": list(col),
                            "cy_oracle": m_on["cover"]["cy"],
                            "cy_on": m_on["render"]["cy"], "cy_off": m_off["render"]["cy"],
                            "dcy_on": m_on["delta"]["cy"], "dcy_off": m_off["delta"]["cy"],
                            "ok_on": m_on["ok"], "ok_off": m_off["ok"]}
                    break
                if best:
                    rows.append(best)
                    print(f"  t={best['t']:8.4f} {best['name']:<10} "
                          f"oracle cy={best['cy_oracle']:.3f} 动画关 Δ={best['dcy_off']:.3f} "
                          f"动画开 Δ={best['dcy_on']:.3f}")
    if not rows:
        print("没有可比对的字幕动画帧（颜色在成片侧匹配不到，或该时间线没有覆盖预设）")
        return 2
    better = sum(1 for r in rows if r["dcy_on"] < r["dcy_off"] - 1e-6)
    worse = sum(1 for r in rows if r["dcy_on"] > r["dcy_off"] + 1e-6)
    same = len(rows) - better - worse
    print("-" * 62)
    print(f"{len(rows)} 帧：动画开更近 {better} / 更遠 {worse} / 不变 {same}")
    print(f"Δcy 中位：关 {sorted(r['dcy_off'] for r in rows)[len(rows)//2]:.3f}  "
          f"开 {sorted(r['dcy_on'] for r in rows)[len(rows)//2]:.3f}")
    if skipped:
        print(f"另有 {len(skipped)} 帧只有一侧出图（动画把字幕淡到 0 或成片侧看不见），"
              f"不计入上面分布：{skipped[:3]}")
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(
        {"rows": rows, "better": better, "worse": worse, "same": same,
         "skipped_one_side_only": skipped},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"report -> {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
