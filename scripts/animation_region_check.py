"""字幕动画的区域判据：在同一条字幕自己的范围内，开动画是否比关动画更贴近成片。

为什么前两个判据都不够：
  - 整帧相关（`animation_gap.py`）对字幕近乎瞎——F-072 实测删掉全部字幕轨只掉 0.005~0.024；
    本轮 A/B 的 ON/OFF 读数逐段 Δ=0.000，就是这个瞎法的具体表现（接线本身是活的，
    `animation_wiring_check.py` 证明动画期内最多 255、期外逐字节相同）。
  - 全画面单色质心（`animation_layer_check.py`）也不够：淡出时字幕暗下去就掉出色彩掩膜，
    质心被同色的另一条字幕接管，于是 ON/OFF 读数一样。
  - 这里改成：先把**这一段自己**孤立出来（只留它，画到黑底）拿到它的横向占位范围，
    再在该列范围 + 全部纵向行程内，直接量 `|我们的帧 - 成片同帧|` 的平均值。
    开动画更小说明方向和量级对；更大说明方向反了——负结果同样要落档。

口径：差值在 0..255 的 RGB 平均绝对差；同刻对同刻，成片帧号固定 `round(t*fps)+lead`（P-29）。
用法：
    python scripts/animation_region_check.py [--model ...] [--frames-dir ...] [--curves ...]
                                             [--report temp/playback-test/anim-region.json]
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
# Windows 控制台是 GBK：读数里带中文/箭头/替换符时 print 会在最后一步抛错，
# 把已经算完的结果整个吞掉（本轮自己的统计工具就栽过一次）。只改错误处理策略，不改编码。
try:
    sys.stdout.reconfigure(errors="replace")     # type: ignore[attr-defined]
    sys.stderr.reconfigure(errors="replace")     # type: ignore[attr-defined]
except Exception:                                 # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parents[1]


def render(model: dict, t: float, apply_anim: bool, only_seg: str | None = None) -> np.ndarray:
    cw, ch = int(model["canvas"]["width"]), int(model["canvas"]["height"])
    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 255))
    m = model
    if only_seg is not None:
        keep = [{"type": tr["type"], "flag": tr["flag"], "attribute": tr.get("attribute"),
                 "segments": [s for s in tr["segments"] if s["id"] == only_seg]}
                for tr in model["tracks"] if any(s["id"] == only_seg for s in tr["segments"])]
        m = {**model, "tracks": [tr for tr in keep if tr["segments"]]}
    rf.APPLY_ANIMATIONS = apply_anim
    try:
        rf.collect(canvas, m, int(round(t * 1e6)), {})
    finally:
        rf.APPLY_ANIMATIONS = True
    return np.asarray(canvas.convert("RGB"), dtype=np.int16)


def luma(arr: np.ndarray) -> np.ndarray:
    return (arr @ np.array([0.299, 0.587, 0.114]))


def to_oracle_size(arr: np.ndarray, target_w: int) -> np.ndarray:
    """统一降到成片尺度再比：成片帧是 216 px 宽的降采样，全分辨率直接相减会广播失败。
    用 BOX（与 `export_compare.luma` 同一降采样口径），免得引入第二种尺度噪声。"""
    im = Image.fromarray(np.clip(arr, 0, 255).astype("uint8"))
    h = max(1, int(round(target_w * im.height / im.width)))
    return np.asarray(im.resize((target_w, h), Image.BOX), dtype=np.int16)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default="temp/playback-test/model-check.json")
    ap.add_argument("--frames-dir", default="temp/playback-test/oracle/dense216")
    ap.add_argument("--curves", default="temp/playback-test/animation-curves.json")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--lead", type=int, default=3)
    ap.add_argument("--report", default="temp/playback-test/anim-region.json")
    args = ap.parse_args()

    frames = sorted(Path(args.frames_dir).glob("*.png"))
    model = json.loads(Path(args.model).read_text(encoding="utf-8-sig"))
    curves = json.loads(Path(args.curves).read_text(encoding="utf-8-sig"))["presets"]

    rows, better, worse, same = [], 0, 0, 0
    for tr in model["tracks"]:
        for s in tr["segments"]:
            an = (s.get("animations") or [{}])[0]
            key = str(an.get("resource_id") or "")
            # 「打字光标」没有 fromTo 轨道，所以它**从来进不了这张表**（上一版 32 条比较里一条都没有）。
            # 现在把「带 tw 表」也算作可比较：判据仍然是**同一段开/关动画谁更贴近成片**，
            # 而 `render_frame.typewriter_truncate` 已挂在 `APPLY_ANIMATIONS` 上，两臂才真的不同。
            tw = bool(an.get("tw"))
            if key not in curves and not tw:
                continue
            pre = curves.get(key) or {"tracks": [], "name": an.get("name") or "?"}
            tween = max((t_["dur_s"] for t_ in pre["tracks"]), default=0.1)
            if tw and not pre["tracks"]:
                tween = (an.get("duration_us") or 0) / 1e6 or 0.1
            t0 = s["target"]["start_us"] / 1e6
            settled = t0 + tween * 2.0
            if settled >= t0 + s["target"]["duration_us"] / 1e6:
                settled = t0 + tween * 1.4
            # 该段自己的横向范围：孤立渲染（关动画，稳态）后取非黑列
            solo = render(model, settled, False, only_seg=s["id"])
            cols = (np.abs(solo).max(axis=(0, 2)) > 8)
            xs = np.nonzero(cols)[0]
            if xs.size < 8:
                rows.append({"t0": round(t0, 3), "name": pre.get("name") or an.get("name") or "?", "skipped": "该段孤立渲染几乎全黑"})
                continue
            x0, x1 = int(xs.min()), int(xs.max())
            for k in range(0, 4):
                t = t0 + tween * k / 3.0
                idx = int(round(t * args.fps)) + args.lead
                if not (0 <= idx < len(frames)):
                    continue
                orc_full = np.asarray(Image.open(frames[idx]).convert("RGB"), dtype=np.int16)
                ow = orc_full.shape[1]                    # 成片帧是 --oracle-width 的降采样
                sx = ow / float(model["canvas"]["width"])
                cx0, cx1 = max(0, int(x0 * sx)), min(ow, int(x1 * sx) + 1)
                if cx1 - cx0 < 4:
                    rows.append({"t0": round(t0, 3), "name": pre["name"],
                                 "skipped": f"降到成片尺度后列范围只剩 {cx1 - cx0} px"})
                    continue
                orc = orc_full[:, cx0:cx1]
                on = to_oracle_size(render(model, t, True), ow)[:, cx0:cx1]
                off = to_oracle_size(render(model, t, False), ow)[:, cx0:cx1]
                d_on = float(np.abs(on - orc).mean())
                d_off = float(np.abs(off - orc).mean())
                verdict = "更近" if d_on < d_off - 0.05 else ("更远" if d_on > d_off + 0.05 else "不变")
                better += verdict == "更近"
                worse += verdict == "更远"
                same += verdict == "不变"
                rows.append({"t0": round(t0, 3), "name": pre.get("name") or an.get("name") or "?", "t": round(t, 4),
                             "x_range": [x0, x1], "mad_on": round(d_on, 2),
                             "mad_off": round(d_off, 2), "verdict": verdict})
                print(f"  t={t:8.4f} {pre['name']:<10} x[{x0},{x1}]  "
                      f"关 MAD={d_off:6.2f}  开 MAD={d_on:6.2f}  {verdict}")
    n = better + worse + same
    if n == 0:
        print("没有可比帧")
        return 2
    print("-" * 64)
    print(f"{n} 个同刻比对：开动画更近 {better} / 更远 {worse} / 不变 {same}")
    med = lambda key: sorted(r[key] for r in rows if key in r)[len([r for r in rows if key in r]) // 2]
    print(f"MAD 中位：关 {med('mad_off'):.2f}  开 {med('mad_on'):.2f}")
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(
        {"rows": rows, "better": better, "worse": worse, "same": same,
         "skipped": [r for r in rows if "skipped" in r]}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"report -> {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
