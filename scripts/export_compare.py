"""L3 whole-frame baseline: our channel-2 render vs a real JianYing export, frame by frame.

Why this exists: every pixel check before this one had only the draft's cover jpg as an oracle,
which is a single unlabelled frame - F-062 measured that a missing layer does not move a
whole-frame RMSE on it. An export is a same-moment oracle for the entire timeline, so this
script renders the draft at chosen positions, aligns to the export, and reports multi-scale luma
correlation per position plus a verdict.

Alignment: the exporter writes `--lead` duplicated copies of the cover still at the head of the
video stream (F-070: 1108 frames for a 1105-frame timeline), so export frame = round(t*fps)+lead.
That pre-roll is an export-side artifact and the preview deliberately does not reproduce it - the
user ruled this on 2026-10-23 - so `--lead` is only ever an oracle alignment offset and never a
change to what the player paints at t=0. A +-window search is still run, because the residual
+-1 frame is above the resolution of any correlation here and would otherwise read as a defect.

The metric is multi-scale Pearson correlation of the luma plane, not RMSE: the two sides differ
in codec, colour range and export sharpening, so absolute code values must not agree - the
structure (where bright and dark regions sit) is what has to.

Usage:
  python scripts/export_compare.py --model temp/playback-test/model-check.json \
      --export "<你的成片 mp4>" --from 0 --to 36 --step 1 \
      --work-dir temp/playback-test/l3
  # reuse the extracted oracle (skips ffmpeg):
  ... --frames-dir temp/playback-test/l3/oracle
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_frame import FF, collect  # noqa: E402
# Windows 控制台是 GBK：读数里带中文/箭头/替换符时 print 会在最后一步抛错，
# 把已经算完的结果整个吞掉（本轮自己的统计工具就栽过一次）。只改错误处理策略，不改编码。
try:
    sys.stdout.reconfigure(errors="replace")     # type: ignore[attr-defined]
    sys.stderr.reconfigure(errors="replace")     # type: ignore[attr-defined]
except Exception:                                 # noqa: BLE001
    pass


def extract_oracle(export: str, fps: float, out_dir: Path, width: int) -> None:
    """Decode the whole export once at `width` px - 163 MB for a 37 s 1080x1920 clip, and it is
    reused by every later run."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if len(list(out_dir.glob("*.png"))) > 10:
        return
    cmd = [FF, "-hide_banner", "-loglevel", "error", "-i", export,
           "-vf", f"scale={width}:-2", "-fps_mode", "passthrough", "-y",
           str(out_dir / "f-%05d.png")]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"ffmpeg failed extracting the oracle:\n{r.stderr[-1200:]}")


def luma(path: Path, w: int) -> np.ndarray:
    im = Image.open(path).convert("RGB")
    im = im.resize((w, max(1, int(round(w * im.height / im.width)))), Image.BOX)
    a = np.asarray(im, dtype=np.float32)
    v = a @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    v = v.ravel()
    v = v - v.mean()
    return v / (np.linalg.norm(v) + 1e-9)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", required=True)
    ap.add_argument("--export", help="the native mp4 to compare against")
    ap.add_argument("--frames-dir", help="pre-extracted oracle frames (one png per export frame)")
    ap.add_argument("--work-dir", default="temp/playback-test/l3")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--lead", type=int, default=3, help="duplicated leading frames (F-070)")
    ap.add_argument("--window", type=int, default=2, help="+- frames to search for alignment")
    ap.add_argument("--search-width", type=int, default=64, help="scale used to pick the offset")
    ap.add_argument("--oracle-width", type=int, default=216)
    ap.add_argument("--from", dest="t0", type=float, default=0.0)
    ap.add_argument("--to", type=float, default=None)
    ap.add_argument("--step", type=float, default=1.0)
    ap.add_argument("--widths", default="16,32,64,128")
    ap.add_argument("--min-median", type=float, default=0.95)
    ap.add_argument("--min-frame", type=float, default=0.80)
    ap.add_argument("--report", default="", help="write the per-position rows here as json")
    args = ap.parse_args()

    work = Path(args.work_dir)
    oracle = Path(args.frames_dir) if args.frames_dir else work / "oracle"
    if not args.frames_dir:
        if not args.export:
            sys.exit("need --export (to extract) or --frames-dir (already extracted)")
        extract_oracle(args.export, args.fps, oracle, args.oracle_width)
    frames = sorted(oracle.glob("*.png"))
    if len(frames) < 10:
        sys.exit(f"oracle frame dir {oracle} has {len(frames)} pngs")

    model = json.loads(Path(args.model).read_text(encoding="utf-8-sig"))
    cw, ch = int(model["canvas"]["width"]), int(model["canvas"]["height"])
    widths = [int(x) for x in args.widths.split(",")]
    if args.search_width not in widths:
        widths.append(args.search_width)
        widths.sort()
    to = args.to if args.to is not None else model["duration_us"] / 1e6
    times = list(np.arange(args.t0, to + 1e-9, args.step))

    render_dir = work / "render"
    render_dir.mkdir(parents=True, exist_ok=True)
    ocache: dict[int, dict[int, np.ndarray]] = {}

    def oluma(idx: int, w: int) -> np.ndarray:
        slot = ocache.setdefault(idx, {})
        if w not in slot:
            slot[w] = luma(frames[idx], w)
        return slot[w]

    rows, fonts = [], {}
    print(f"{'t':>7} {'off':>4} " + " ".join(f"{w:>6}" for w in widths))
    for t in times:
        canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 255))
        collect(canvas, model, int(round(t * 1e6)), fonts)
        rp = render_dir / f"frame-{t:.3f}.png"
        canvas.convert("RGB").save(rp)
        ours = {w: luma(rp, w) for w in widths}

        base = int(round(t * args.fps)) + args.lead
        lo, hi = max(0, base - args.window), min(len(frames), base + args.window + 1)
        cand = list(range(lo, hi))
        if not cand:
            rows.append({"t": t, "skipped": "outside export"})
            continue
        off = max(cand, key=lambda i: float(oluma(i, args.search_width) @ ours[args.search_width]))
        cs = {w: round(float(oluma(off, w) @ ours[w]), 3) for w in widths}
        rows.append({"t": round(t, 3), "export_frame": off, "offset": off - base, "corr": cs})
        print(f"{t:7.3f} {off - base:+4d} " + " ".join(f"{cs[w]:6.3f}" for w in widths))

    if not rows:
        print("no positions compared")
        return 2
    ref = args.search_width
    vals = [r["corr"][ref] for r in rows if "corr" in r]
    meds = {w: round(statistics.median([r["corr"][w] for r in rows if "corr" in r]), 3)
            for w in widths}
    offs = [r["offset"] for r in rows if "corr" in r]
    ok_med = statistics.median(vals) >= args.min_median
    worst = min(rows, key=lambda r: r.get("corr", {}).get(ref, 9))
    ok_min = min(vals) >= args.min_frame
    print("-" * 46)
    for w in widths:
        print(f"  median @{w:4d}px {meds[w]:.3f}")
    print(f"  offset histogram {json.dumps({str(k): offs.count(k) for k in sorted(set(offs))})}")
    print(f"  worst t={worst.get('t')} @{ref}px {worst.get('corr', {}).get(ref)} "
          f"(offset {worst.get('offset')})")
    print(f"  verdict: median {'PASS' if ok_med else 'FAIL'} (>= {args.min_median}), "
          f"min {'PASS' if ok_min else 'FAIL'} (>= {args.min_frame})")
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(
            {"model": str(args.model), "export": args.export or str(args.frames_dir),
             "lead": args.lead, "window": args.window, "ref_scale": ref,
             "median": meds, "ok": ok_med and ok_min, "rows": rows}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"  report -> {args.report}")
    return 0 if (ok_med and ok_min) else 1


if __name__ == "__main__":
    sys.exit(main())
