"""P-28 的归因器：段边界后那 +2 帧到底是哪条轨、哪个变量。

为什么需要它：export_compare 的 `off` 是在 ±2 帧窗口里**搜**出来的最佳对齐，所以「off=+2」
只说明「对不上到 0.96」，不说明「整条时间线差两帧」——6.633 处即使取到最佳偏移也只有 0.880@64。
本脚本把两个自由度分开：
  (a) 成片侧的运动下限：corr(oracle[n], oracle[n±1])，画面本来就在动时 0.88 可能不是缺陷；
  (b) 每条轨**自己的素材取样时刻**平移 Δ 帧：只对单条轨改 `source.start_us`，
      其余轨冻结在同一帧，于是「谁错了、错几帧」是一矩阵而不是一句猜测。
对齐用**固定** oracle 帧号（round(t*30)+lead），不再搜偏移 —— 搜偏移会把平移实验的自由度吃掉。

口径：oracle 帧 = 一次解出的 dense216 全帧；我们的帧 = 通道 2（`render_frame.collect`）。
判读：某条轨在 Δ=k 处 corr 明显高于 Δ=0 ⇒ 我们对那条轨的素材起点算错了 k 帧（正 = 我们取早了）。
解码做了 memo：同一 (路径, 源秒) 只跑一次 ffmpeg，否则 105 帧会把时间全花在解码上。

用法：
    python scripts/cut_alignment.py --model temp/playback-test/model-check.json \
        --frames-dir temp/playback-test/oracle/dense216 \
        --times 6.600,6.633,6.666,6.700,6.800 --shifts -3,-2,-1,0,1,2,3 \
        [--track 1] [--drop 0] [--report temp/playback-test/l3/cut-6600.json]
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
from export_compare import luma  # noqa: E402
# Windows 控制台是 GBK：读数里带中文/箭头/替换符时 print 会在最后一步抛错，
# 把已经算完的结果整个吞掉（本轮自己的统计工具就栽过一次）。只改错误处理策略，不改编码。
try:
    sys.stdout.reconfigure(errors="replace")     # type: ignore[attr-defined]
    sys.stderr.reconfigure(errors="replace")     # type: ignore[attr-defined]
except Exception:                                 # noqa: BLE001
    pass

_DECODED: dict[tuple[str, int], object] = {}
_ORIG_DECODE = rf.decode_frame    # 绑之前先抓住原函数，否则 memo 会自己调自己（第一版就栽在这）


def memo_decode(path: str, at_s: float):
    key = (path, int(round(at_s * 1e6)))
    if key not in _DECODED:
        _DECODED[key] = _ORIG_DECODE(path, at_s)
    return _DECODED[key]


rf.decode_frame = memo_decode   # collect() 走这个名字，所以替换它就换到了取样缓存


def shifted_model(model: dict, track_index: int, frames: int, fps: float) -> dict:
    """深拷贝一条轨的 source.start_us 平移 frames 帧 —— 只动那一条轨。"""
    m = json.loads(json.dumps(model))
    d = int(round(frames * 1e6 / fps))
    idxs = [i for i, tr in enumerate(m["tracks"])
            if (track_index == -1 and tr["type"] != "audio") or i == track_index]
    for i in idxs:
        for s in m["tracks"][i]["segments"]:
            if s["source"]["duration_us"]:
                s["source"]["start_us"] = s["source"]["start_us"] + d
    return m


def render(model: dict, t: float, drop: set[int]) -> Image.Image:
    cw, ch = int(model["canvas"]["width"]), int(model["canvas"]["height"])
    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 255))
    if drop:
        keep = [tr for i, tr in enumerate(model["tracks"]) if i not in drop]
        model = {**model, "tracks": keep}
    rf.collect(canvas, model, int(round(t * 1e6)), {})
    return canvas.convert("RGB")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", required=True)
    ap.add_argument("--frames-dir", required=True)
    ap.add_argument("--times", default="6.600,6.633,6.666,6.700,6.800")
    ap.add_argument("--shifts", default="-3,-2,-1,0,1,2,3")
    ap.add_argument("--track", type=int, action="append", default=[],
                    help="track index to shift (repeatable; default = every non-audio track)")
    ap.add_argument("--drop", type=int, action="append", default=[],
                    help="track index to remove entirely (repeatable)")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--lead", type=int, default=3)
    ap.add_argument("--scale", type=int, default=64)
    ap.add_argument("--report", default="")
    args = ap.parse_args()

    frames = sorted(Path(args.frames_dir).glob("*.png"))
    if len(frames) < 10:
        sys.exit(f"oracle dir {args.frames_dir} has {len(frames)} pngs")
    model = json.loads(Path(args.model).read_text(encoding="utf-8-sig"))
    tracks = args.track or ([-1] + [i for i, tr in enumerate(model["tracks"])
                             if tr["type"] == "video" and any(s.get("media") for s in tr["segments"])])
    times = [float(x) for x in args.times.split(",")]
    shifts = [int(x) for x in args.shifts.split(",")]

    def oc(idx: int) -> np.ndarray:
        return luma(frames[idx], args.scale)

    print(f"oracle frames={len(frames)} scale={args.scale}px lead={args.lead} "
          f"tracks_shifted={tracks} drop={args.drop}")
    rows = []
    for t in times:
        base = int(round(t * args.fps)) + args.lead
        o = oc(base)
        floor = {k: round(float(oc(base + k) @ o), 3) for k in (-2, -1, 1, 2)
                 if 0 <= base + k < len(frames)}
        line = {"t": t, "export_frame": base, "native_floor": floor, "shift": {}}
        ours = {w: luma_from(render(model, t, set(args.drop)), w) for w in (args.scale,)}
        best0 = ours[args.scale]
        line["base_corr"] = round(float(o @ best0), 3)
        for ti in tracks:
            row = {}
            for k in shifts:
                m = shifted_model(model, ti, k, args.fps)
                c = float(o @ luma_from(render(m, t, set(args.drop)), args.scale))
                row[k] = round(c, 3)
            line["shift"][ti] = row
        for ti in range(len(model["tracks"])):
            if ti in tracks or ti == -1:
                continue
            c = float(o @ luma_from(render(model, t, {ti}), args.scale))
            line.setdefault("drop", {})[ti] = round(c, 3)
        rows.append(line)
        head = f"t={t:7.3f} frame={base:4d} base={line['base_corr']:.3f} " \
               f"native±1={floor.get(-1)}~{floor.get(1)} native±2={floor.get(-2)}~{floor.get(2)}"
        print(head)
        for ti, row in line["shift"].items():
            path = " ".join(f"{k:+d}:{v:.3f}" for k, v in sorted(row.items()))
            print(f"    track{ti} shift {path}")
        if "drop" in line:
            print("    drop " + " ".join(f"t{i}:{v:.3f}" for i, v in sorted(line["drop"].items())))

    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(
            {"model": args.model, "scale": args.scale, "lead": args.lead, "rows": rows},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"report -> {args.report}")
    return 0


def luma_from(img: Image.Image, w: int) -> np.ndarray:
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return luma_open(buf, w)


def luma_open(buf, w: int) -> np.ndarray:
    im = Image.open(buf).convert("RGB")
    im = im.resize((w, max(1, int(round(w * im.height / im.width)))), Image.BOX)
    a = np.asarray(im, dtype=np.float32)
    v = a @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    v = v.ravel()
    v = v - v.mean()
    return v / (np.linalg.norm(v) + 1e-9)


if __name__ == "__main__":
    sys.exit(main())
