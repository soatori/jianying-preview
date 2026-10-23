"""One command that re-answers "did the playback base actually work on this draft?".

Why this exists: on 2026-10-22 five separate defects shipped past checks that each looked green -
a black video layer while `composited_fps` stayed at 27 (P-12), a geometry channel that was null
for every segment (P-13), a caption 12 px too low (P-16), a mixer that never heard the camera
audio (P-18), and a first black-frame guard that could only report a false negative (P-21).
None of those are visible in a counter, and none were caught by an ad-hoc run. This script pins
the four layers together so the same class of miss needs only one command to surface:

  1. L1   model build + its own assertions (references, overlap, target==source/speed, geometry)
  2. L2   channel-2 frame render, compared against a native oracle by colour-layer metrics
  3. L4   headless browser battery: the six base criteria, read from the page's self-report
  4. L6   the silent-black-frame guard, both directions (it must be empty here, and the
          `--negative-model` fixture must make it non-empty)

Nothing here writes to the draft. Chrome is launched by scripts/browser_soak.py (hardware path on,
own user-data-dir) and the gateway it starts is stopped again on the way out.

Usage:
  python scripts/playback_check.py \
      --plain "temp/playback-test/plain/李金昌 10月15日 (4)__draft_content.json.dec.json" \
      --draft-root "D:\\JianyingPro\\JianyingPro Drafts\\李金昌 10月15日 (4)" \
      --timeline 017E2FEC-11D0-47d6-87C1-9709D2A2F18D \
      --model temp/playback-test/model-proxy-a.json \
      --oracle-mp4 "E:\\输出\\销售\\1015-1701\\1015-1701.mp4" \
      --pixel-t 1.0 --pixel-colour 255,255,255
  # --pixel-colour must name a layer that is actually live at --pixel-t: the default gold
  # caption only exists in the cover state, and against the export it reads "layer missing".
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "temp" / "playback-test"
PY = sys.executable
FFMPEG = r"D:\Program Files\JianyingPro\11.6.0.14552\ffmpeg.exe"

# The six base criteria, as thresholds. Values come from docs/spec (render-base decision) and the
# readings in docs/evidence/playback-log.md; a criterion with no agreed basis is reported INFO.
CRITERIA = {
    "composited_fps_min": 24.0,
    "seek_median_ms_max": 150.0,
    "first_frame_ms_max": 300.0,
    "session_peak_mb_max": 2048.0,
}


def run(cmd: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_port(port: int, timeout: float = 20.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), 0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def layer_metrics(render: Path, cover: Path, colour: tuple[int, int, int],
                  tol: int = 46) -> dict:
    """Centroid + 1-99th percentile box of one colour layer, in normalised canvas units.

    Basis: whole frame, every 2nd column, max-channel-diff < tol. Bounding box rather than IoU
    is deliberate - against a JPEG reference the thin-stroke IoU tops out near 0.5-0.8 because
    chroma subsampling drops the glyph edges from the mask (P-16).
    """
    target = np.array(colour, dtype=np.int16)

    def one(path: Path) -> np.ndarray:
        a = np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)
        return np.abs(a - target).max(axis=2) < tol

    def box(m: np.ndarray) -> dict:
        ys, xs = np.nonzero(m)
        h, w = m.shape
        n = len(xs)
        if n < 50:
            return {"n": int(n)}
        return {"n": int(n),
                "cx": round(float(xs.mean()) / w, 3), "cy": round(float(ys.mean()) / h, 3),
                "x0": round(float(np.percentile(xs, 1)) / w, 3),
                "x1": round(float(np.percentile(xs, 99)) / w, 3),
                "y0": round(float(np.percentile(ys, 1)) / h, 3),
                "y1": round(float(np.percentile(ys, 99)) / h, 3)}

    r, c = box(one(render)), box(one(cover))
    shared = {"n_render": r.get("n", 0), "n_cover": c.get("n", 0)}
    if "cx" not in r or "cx" not in c:
        return {**shared, "ok": False, "why": "layer missing on one side"}
    d = {k: round(abs(r[k] - c[k]), 3) for k in ("cx", "cy", "x0", "x1", "y0", "y1")}
    return {**shared, "delta": d, "max_delta": max(d.values()),
            "ok": max(d.values()) <= 0.02, "render": r, "cover": c}


def video_band(render: Path, cover: Path, y0: float, y1: float, x1: float,
               mask: list[tuple[float, float]], scales: list[int]) -> dict:
    """Structure agreement between a native cover frame and our render, inside a band both keep intact.

    Two properties of this measurement are load-bearing and were learned the hard way (F-065/F-066):
    a cover can only verify its own moment and records no timestamp, and luma RMSE alone misleads -
    two *native* covers about a second apart score negatively against each other in this footage,
    so the criterion is the correlation read against that cross-moment baseline, not the RMSE.
    """
    def band(path: Path, k: int, use_mask: bool):
        a = np.asarray(Image.open(path).convert("L"), dtype=np.float32)
        h, w = a.shape
        rows = np.zeros(h, dtype=bool)
        rows[int(h * y0):int(h * y1)] = True
        if use_mask:
            for lo, hi in mask:
                rows[int(h * lo):int(h * hi)] = False
        sub = a[rows, :int(w * x1)]
        hh, ww = sub.shape
        if hh < 4 or ww < 4:
            return None
        small = np.asarray(Image.fromarray(sub.astype(np.uint8)).resize(
            (max(1, ww // k), max(1, hh // k)), Image.BOX), dtype=np.float32)
        return small

    out: dict[str, float] = {}
    for k in scales:
        for tag, use_mask in (("", True), ("_unmasked", False)):
            a, b = band(cover, k, use_mask), band(render, k, use_mask)
            if a is None or b is None or a.shape != b.shape:
                continue
            d = float(np.sqrt(((a - b) ** 2).mean()))
            r = float(np.corrcoef(a.ravel(), b.ravel())[0, 1]) if a.std() and b.std() else 0.0
            out[f"corr{k}px{tag}"] = round(r, 3)
            out[f"rmse{k}px{tag}"] = round(d, 1)
    return out


def parse_ranges(spec: str) -> list[tuple[float, float]]:
    out = []
    for part in (spec or "").split(","):
        if "-" not in part:
            continue
        lo, hi = part.split("-", 1)
        out.append((float(lo), float(hi)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--plain", required=True)
    ap.add_argument("--draft-root", required=True)
    ap.add_argument("--timeline", required=True)
    ap.add_argument("--model", default=str(OUT / "model-check.json"),
                    help="where the freshly built playback model lands")
    ap.add_argument("--player", default="player.html")
    ap.add_argument("--media-model", default="",
                    help="gateway model + player model to play (defaults to --model; "
                         "pass the proxy build to keep the criteria run realistic)")
    ap.add_argument("--cover", default="", help="native oracle frame for the pixel layer")
    ap.add_argument("--oracle-mp4", default="",
                    help="the real JianYing export; its frame round(t*fps)+lead becomes the "
                         "pixel-layer oracle (preferred over --cover, which is not same-moment)")
    ap.add_argument("--oracle-fps", type=float, default=30.0)
    ap.add_argument("--oracle-lead", type=int, default=3,
                    help="duplicated cover stills at the head of the export (F-070). Oracle-side "
                         "alignment only - the preview deliberately does not reproduce them.")
    ap.add_argument("--pixel-t", type=float, default=0.5)
    ap.add_argument("--pixel-colour", default="255,222,0", help="RGB of the layer to compare")
    ap.add_argument("--negative-model", default=str(OUT / "model-blacktest.json"),
                    help="fixture whose video layer paints nothing; the guard must catch it")
    ap.add_argument("--battery-ms", type=int, default=10000)
    ap.add_argument("--seeks", type=int, default=12)
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--repeat", type=int, default=3,
                    help="battery runs per criterion; verdicts are medians")
    ap.add_argument("--cover-frame", default="",
                    help="native cover to score the VIDEO layer against (F-066 band metric)")
    ap.add_argument("--band", default="0.02-0.42", help="y range of the intact band, as a-b")
    ap.add_argument("--band-x1", type=float, default=0.5,
                    help="right edge of the usable band; the second cover's right half is flat 255")
    ap.add_argument("--band-mask", default="0.17-0.33",
                    help="y ranges to drop because an overlay sits in them (comma separated a-b)")
    ap.add_argument("--video-scan", default="",
                    help="scan t over a-b:step against --cover-frame instead of one timestamp")
    ap.add_argument("--video-corr-min", type=float, default=0.6,
                    help="PASS threshold on corr@32px with the overlay masked")
    ap.add_argument("--skip-negative", action="store_true")
    args = ap.parse_args()

    checks: list[tuple[str, str, str]] = []
    media_model = args.media_model or args.model
    report = OUT / "report-playback.jsonl"

    def verdict(name: str, ok: bool, detail: str) -> None:
        checks.append((name, "PASS" if ok else "FAIL", detail))

    # ---- 1. L1: build the model and read its own assertions -------------------------------
    r = run([PY, "scripts/playback_model.py", args.plain, "--draft-root", args.draft_root,
             "--out", args.model, "--timeline", args.timeline])
    if r.returncode != 0:
        print(r.stdout[-2000:], r.stderr[-2000:])
        return 2
    m = json.loads(Path(args.model).read_text(encoding="utf-8"))
    s = m["stats"]
    verdict("L1 errors/warnings", not m["errors"] and not m["warnings"],
            f"errors {len(m['errors'])} warnings {len(m['warnings'])}")
    verdict("L1 geometry channel", s["geometry_segments"] > 0,
            f"clip on {s['geometry_segments']}/{s['geometry_total']} segments, "
            f"{s['segment_count']} segments, {s['media_count']} media "
            f"(missing {s['media_missing']}, unreadable {s['media_unreadable']})")

    # ---- 2. L2: render a frame and compare one layer against the native oracle ------------
    # The export is the oracle now that we have one: `draft_cover.jpg` is an independently
    # rendered still, not a timeline frame (F-070), so scoring a layer against it can only ever
    # agree by coincidence - and it did, by hiding F-071 (the cover happens to show the state
    # with the two `visible:false` layers painted).
    oracle = None
    if args.oracle_mp4 and Path(args.oracle_mp4).is_file():
        idx = int(round(args.pixel_t * args.oracle_fps)) + args.oracle_lead
        oracle = OUT / f"oracle-frame-{idx}.png"
        if not oracle.is_file():
            run([FFMPEG, "-hide_banner", "-loglevel", "error", "-i", args.oracle_mp4,
                 "-vf", f"select=eq(n\\,{idx})", "-fps_mode", "passthrough",
                 "-frames:v", "1", "-y", str(oracle)])
        if not oracle.is_file():
            verdict("L2 pixel layer", False, f"could not extract export frame {idx}")
            oracle = None
    elif args.cover:
        oracle = Path(args.cover)

    if oracle is not None:
        png = OUT / f"check-{args.pixel_t:.2f}s.png"
        rr = run([PY, "scripts/render_frame.py", "--model", args.model,
                  "--t", f"{args.pixel_t}", "--out", str(png)])
        if rr.returncode != 0 or not png.is_file():
            verdict("L2 pixel layer", False, f"render failed: {rr.stderr[-200:]}")
        else:
            rgb = tuple(int(v) for v in args.pixel_colour.split(","))
            got = layer_metrics(png, oracle, rgb)
            verdict("L2 pixel layer", got.get("ok", False),
                    f"{png.name} vs {oracle.name}: max box/centroid delta "
                    f"{got.get('max_delta', 'n/a')} (<=0.02) over {got.get('n_render', 0)} px "
                    f"[{got.get('why', '')}]")
    else:
        checks.append(("L2 pixel layer", "SKIP", "no --oracle-mp4 / --cover given"))

    # ---- 2b. L3 video layer against a native cover frame (F-066 band metric) --------------
    if args.cover_frame and Path(args.cover_frame).is_file():
        lo, hi = (float(v) for v in args.band.split("-"))
        mask = parse_ranges(args.band_mask)
        cf = Path(args.cover_frame)

        def score(png: Path) -> dict:
            return video_band(png, cf, lo, hi, args.band_x1, mask, [1, 8, 32])

        if args.video_scan:
            a, b = args.video_scan.split(":")[:2]
            step = float(args.video_scan.split(":")[2]) if len(args.video_scan.split(":")) > 2 else 0.1
            best = None
            t = float(a)
            while t <= float(b) + 1e-9:
                png = OUT / f"bandscan-{t:.2f}.png"
                run([PY, "scripts/render_frame.py", "--model", args.model,
                     "--t", f"{t:.2f}", "--out", str(png)])
                if png.is_file():
                    got = score(png)
                    c32 = got.get("corr32px", 0.0)
                    if best is None or c32 > best[0]:
                        best = (c32, t, got)
                t += step
            if best:
                c32, bt, got = best
                verdict("L3 video band", c32 >= args.video_corr_min,
                        f"best at t={bt:.2f}s corr@32px {c32} (>= {args.video_corr_min}), "
                        f"corr@1px {got.get('corr1px')}, unmasked {got.get('corr32px_unmasked')}, "
                        f"rmse@32px {got.get('rmse32px')}, band {args.band} x<{args.band_x1} "
                        f"mask {args.band_mask or 'none'}")
        else:
            png = OUT / f"bandsingle-{args.pixel_t:.2f}s.png"
            run([PY, "scripts/render_frame.py", "--model", args.model,
                 "--t", f"{args.pixel_t}", "--out", str(png)])
            got = score(png) if png.is_file() else {}
            verdict("L3 video band", got.get("corr32px", 0) >= args.video_corr_min,
                    f"t={args.pixel_t} corr@32px {got.get('corr32px')} "
                    f"(>= {args.video_corr_min}), corr@1px {got.get('corr1px')}, "
                    f"unmasked {got.get('corr32px_unmasked')}, rmse@32px {got.get('rmse32px')}")
    elif args.cover_frame:
        checks.append(("L3 video band", "SKIP", f"--cover-frame not found: {args.cover_frame}"))

    # ---- 3+4. browser layers, against one gateway we own ----------------------------------
    port = args.port or free_port()
    gw = subprocess.Popen([PY, "scripts/preview_gateway.py", "--port", str(port),
                           "--serve-dir", "temp", "--model", media_model],
                          cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_port(port):
            verdict("gateway", False, f"port {port} never accepted connections")
            return 2

        def battery(url_model: str, tag: str) -> dict:
            before = len(report.read_text(encoding="utf-8").splitlines()) if report.exists() else 0
            url = (f"http://127.0.0.1:{port}/playback-test/{args.player}"
                   f"?autostart=1&model={url_model}&playms={args.battery_ms}&seeks={args.seeks}"
                   f"&fps=30&qmax=4&pool=4&loop=1")
            run([PY, "scripts/browser_soak.py", "--url", url, "--seconds", "90",
                 "--report", str(report.relative_to(ROOT)), "--tag", tag])
            lines = report.read_text(encoding="utf-8").splitlines()
            return json.loads(lines[-1]) if len(lines) > before else {}

        runs = [d for d in (battery(Path(media_model).name, f"check{i}")
                            for i in range(args.repeat)) if d]
        if runs and not any((d.get("play") or {}).get("composited_fps") for d in runs):
            verdict("L4 criteria", False,
                    f"no run reported a picture: {len(runs)} report(s) arrived but every one is "
                    f"empty inside `play` - the media behind --media-model is probably missing "
                    f"(regenerate with temp/playback-test/add_proxy_audio.py)")
        if not runs:
            verdict("L4 criteria", False, "the page never self-reported within 90 s")
        else:
            def series(fn):
                return sorted(v for v in (fn(d) for d in runs) if isinstance(v, (int, float)))

            def med(xs):
                return xs[len(xs) // 2] if xs else None

            play = lambda d: d.get("play") or {}
            aud_of = lambda d: play(d).get("audio") or {}
            fps = series(lambda d: play(d).get("composited_fps"))
            seek = series(lambda d: (d.get("seek") or {}).get("median_ms"))
            first = series(lambda d: d.get("first_frame_ms"))
            reqs = series(lambda d: play(d).get("requests"))
            peaks = series(lambda d: aud_of(d).get("peak_fs"))
            clips = series(lambda d: aud_of(d).get("clipped_windows"))
            # Every criterion is judged on the median across runs and printed with its tail. A
            # single reading is what let one 351 ms first frame and one zero-clip run each look
            # like "the answer" (Q-8, Q-9).
            verdict("L4 continuous playback",
                    (med(fps) or 0) >= CRITERIA["composited_fps_min"],
                    f"median {med(fps)} fps (>=24), min {fps[0] if fps else '-'}, n={len(runs)}")
            verdict("L4 seek", (med(seek) or 1e9) <= CRITERIA["seek_median_ms_max"],
                    f"median of per-run medians {med(seek)} ms (<=150), worst {max(seek) if seek else '-'}")
            over = sum(1 for v in first if v > CRITERIA["first_frame_ms_max"])
            verdict("L4 first frame", (med(first) or 1e9) <= CRITERIA["first_frame_ms_max"],
                    f"median {med(first)} ms (<=300), "
                    f"spread {f'{min(first)}-{max(first)}' if first else '-'} (n={len(first)}), "
                    f"{over}/{len(first)} runs over the line")
            verdict("L4 Range streaming", (med(reqs) or 0) > 0,
                    f"median {med(reqs)} ranged requests per {args.battery_ms} ms window")
            bad = [d for d in runs if d.get("black_streaks") or d.get("errors")]
            verdict("L6 no silent black frame", not bad,
                    f"{len(bad)}/{len(runs)} runs with black_streaks or errors"
                    + (f"; e.g. {bad[0].get('black_streaks')} {bad[0].get('errors')[:1]}" if bad else ""))
            aud = [aud_of(d) for d in runs]
            nerr = sum(1 for a in aud if a.get("audio_errors"))
            rates = sorted({r for d in runs for r in (play(d).get("audio_rates_seen") or [])})
            verdict("L5 mixer", nerr == 0 and all((a.get("chunks") or 0) > 0 for a in aud),
                    f"{nerr}/{len(runs)} runs with audio_errors, rates_seen {rates} "
                    f"(sample_rate is a last-writer field and proves nothing)")
            checks.append(("mix headroom (no agreed basis, Q-8)", "INFO",
                           f"peak_fs {peaks}; runs with >=1 clipped window "
                           f"{sum(1 for c in clips if c > 0)}/{len(clips)}"))
            rss = OUT / "rss-check0.txt"
            peak = ""
            if rss.is_file():
                for line in rss.read_text(encoding="utf-8").splitlines():
                    if "rss_peak_mb=" in line:
                        peak = line.strip()
                        break
            checks.append(("session memory (600 s criterion is separate)", "INFO",
                           peak or f"no rss_peak_mb line in {rss.name}"))

        if not args.skip_negative and Path(args.negative_model).is_file():
            n = battery(Path(args.negative_model).name, "check-neg")
            verdict("L6 guard has teeth", bool(n.get("black_streaks")),
                    f"fixture {Path(args.negative_model).name} -> "
                    f"black_streaks {n.get('black_streaks')} (must be non-empty), "
                    f"fps still {(n.get('play') or {}).get('composited_fps')}")
    finally:
        gw.terminate()
        try:
            gw.wait(timeout=10)
        except subprocess.TimeoutExpired:
            gw.kill()

    width = max(len(name) for name, _, _ in checks) + 2
    for name, state, detail in checks:
        print(f"{state:<5} {name:<{width}} {detail}")
    failed = [c for c in checks if c[1] == "FAIL"]
    print(f"\n{len(checks) - len(failed)} of {len(checks)} checks passed"
          + (f", {len(failed)} FAILED" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
