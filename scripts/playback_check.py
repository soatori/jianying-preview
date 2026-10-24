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
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
# Windows 控制台是 GBK：读数里带中文/箭头/替换符时 print 会在最后一步抛错，
# 把已经算完的结果整个吞掉（本轮自己的统计工具就栽过一次）。只改错误处理策略，不改编码。
try:
    sys.stdout.reconfigure(errors="replace")     # type: ignore[attr-defined]
    sys.stderr.reconfigure(errors="replace")     # type: ignore[attr-defined]
except Exception:                                 # noqa: BLE001
    pass

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


def run(cmd: list[str], cwd: Path = ROOT, timeout: int = 0) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout or None)


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
    ap.add_argument("--skip-animations", action="store_true",
                    help="skip the L8 animation layers")
    ap.add_argument("--skip-browser-shots", action="store_true",
                    help="skip the L10 layer where the browser returns its own frames")
    ap.add_argument("--shot-times", default="1.0,6.633,20.23",
                    help="逗号分隔的时刻；浏览器会在这些时刻把画出来的帧回传")
    ap.add_argument("--shot-seconds", type=int, default=90)
    ap.add_argument("--oracle-frames", default="temp/playback-test/oracle/dense216",
                    help="一次解出的成片帧目录（L10 用，不重新解码）")
    ap.add_argument("--skip-mixmode", action="store_true",
                    help="skip the L7 mix-mode layers (they need no browser by default)")
    ap.add_argument("--mixmode-gpu", action="store_true",
                    help="also run the GPU three-way equivalence (starts its own browser)")
    ap.add_argument("--mixmode-seconds", type=int, default=240)
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

        # ---- 10. L10: 浏览器自己画出来的帧，对通道 2 与对成片同刻 ------------------------
        # 门的 L2/L3 一直用通道 2 出图，等于让另一条通道代答「预览看起来对不对」。
        # 这一层把交互内核本体放到像素判据下：两条判据分开阈值（跨通道 / 对成片），
        # 合并成一个数就会把「两条通路不一致」读成「成片本来就这样」。
        if not args.skip_browser_shots:
            times = args.shot_times
            for x in [s.strip() for s in times.split(",") if s.strip()]:
                (OUT / f"browser-shot-{x.replace('.', '-')}.png").unlink(missing_ok=True)
            url = (f"http://127.0.0.1:{port}/playback-test/{args.player}"
                   f"?model={Path(media_model).name}&seek=1.0&shots={times}"
                   f"&fps=30&qmax=4&pool=4")
            run([PY, "scripts/browser_soak.py", "--url", url,
                 "--seconds", str(args.shot_seconds), "--report", str(report.relative_to(ROOT)),
                 "--tag", "shot", "--timeout", str(args.shot_seconds + 25)])
            sh = run([PY, "scripts/browser_shot_check.py", "--timestamps", times,
                      "--model", args.model, "--frames-dir", args.oracle_frames,
                      "--report", str((OUT / "browser-shots.json").relative_to(ROOT))])
            js = OUT / "browser-shots.json"
            n = problems = 0
            if js.is_file():
                rep = json.loads(js.read_text(encoding="utf-8"))
                n = len([r for r in rep.get("rows", []) if "browser_vs_channel2" in r])
                problems = len(rep.get("problems", []))
            verdict("L10 browser pixels (vs channel 2 and vs export, same frame)",
                    sh.returncode == 0 and n >= 3 and problems == 0,
                    f"{n} timestamps compared, {problems} problems"
                    + (" | " + "; ".join((sh.stdout or "").strip().splitlines()[-4:])
                       if sh.returncode else ""))

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

    # ---- 9. L9: 跨通道曲线一致性 —— 浏览器自报的动画值 == 通道 2 算出的值 ------------------
    # 为什么不等像素先判：`ANIM_STATS.last` 带的是浏览器那一侧真正算出来的 alpha/scale/dy 与
    # 相对段起点的时刻，通道 2 用同一个模型重算同一时刻即可对数。像素级的通道一致另说
    # （浏览器还有解码与字体度量差异），这里判的是「两条通道吃的是不是同一条曲线」。
    # 口径：alpha/scale 严格比（与纹理高无关）；dy 只报差不判——JS 用节点高、Python 用墨迹高，
    # 两者的定义本来就不同（P-16 的 PIL 升部陷阱同类），拿它当判据会假报警。
    if not args.skip_animations:
        try:
            import render_frame as _rf
            seg_by_id = {s["id"]: s for tr in m["tracks"] for s in tr["segments"]}
            for tr in m["tracks"]:
                for s in tr["segments"]:
                    seg_by_id[s["id"]] = s
            recs: dict[str, dict] = {}
            for d in (runs or []):
                for r_ in ((d.get("anim") or {}).get("last") or []):
                    recs[r_["id"]] = r_
            anim_loaded = any((d.get("anim") or {}).get("loaded") for d in (runs or []))
            bad = []
            for sid, r_ in recs.items():
                s = seg_by_id.get(sid)
                if not s:
                    bad.append(f"{sid[:8]}: 段不在模型里")
                    continue
                pos_us = s["target"]["start_us"] + int(r_["t_us"])
                v = _rf.anim_value(s, pos_us, int(m["canvas"]["height"]), None)
                if abs(v["alpha"] - r_["alpha"]) > 0.02 or abs(v["scale_x"] - r_["s"]) > 0.02:
                    bad.append(f"{s.get('text',{}).get('text','')[:8] or sid[:8]}: "
                               f"浏览器 a/s={r_['alpha']}/{r_['s']} vs 通道2 "
                               f"{v['alpha']:.3f}/{v['scale_x']:.3f}")
            verdict("L9 cross-channel curve parity (browser == channel 2)",
                    anim_loaded and bool(recs) and not bad,
                    f"curves loaded={anim_loaded}, browser 报了 {len(recs)} 段, "
                    f"不一致 {len(bad)}" + (": " + "; ".join(bad[:3]) if bad else ""))
        except Exception as e:  # noqa: BLE001
            verdict("L9 cross-channel curve parity (browser == channel 2)", False, f"crashed: {e}")

    # ---- 7. L7: 混合模式（同源切片 GLSL + 构造样本接线）----------------------------------
    # 本草稿 0 个 mix_mode 引用 ⇒ L1~L6 永远不会经过这条路径；「写了」不等于「生效」，
    # 也不等于「下次改坏了还有人记得跑」。数学侧的 GPU 三方对照默认不跑（要起浏览器，
    # 且它测的是常量而非常规回归），要跑用 --mixmode-gpu，判据读表不读 stdout。
    if not args.skip_mixmode:
        ex = run([PY, "scripts/mixmode_shaders.py"])
        last = (ex.stdout.strip().splitlines() or ["no output"])[-1]
        verdict("L7 mixmode shipped GLSL", ex.returncode == 0, last[:150])
        wr = run([PY, "scripts/mixmode_wiring_check.py", "--model", args.model])
        tail = [ln for ln in wr.stdout.splitlines() if "wiring checks" in ln]
        verdict("L7 mixmode wiring (constructed fixture)", wr.returncode == 0,
                (tail[-1] if tail else (wr.stdout or wr.stderr)[-150:]))
        if args.mixmode_gpu:
            eq = run([PY, "scripts/mixmode_equivalence.py"], timeout=args.mixmode_seconds)
            tp = ROOT / "docs" / "evidence" / "tables" / "mixmode_equivalence.csv"
            bad: list[str] = []
            n_rows = 0
            if tp.exists():
                import csv as _csv
                with tp.open(encoding="utf-8-sig") as fh:
                    for row in _csv.DictReader(fh):
                        n_rows += 1
                        ship = int(row["shipped_vs_vendor_max_abs_255"])
                        npx = int(row["numpy_vs_vendor_max_abs_255"])
                        over = int(row["numpy_cells_over_tolerance"])
                        if ship > 1 or npx > 1 or over > 0:
                            bad.append(f"{row['name_id']} ship={ship} numpy={npx} over={over}")
            verdict("L7 mixmode GPU three-way (vendor GLSL = oracle)",
                    eq.returncode == 0 and n_rows == 10 and not bad,
                    f"{n_rows} modes read from the table, {len(bad)} out of tolerance"
                    + (": " + "; ".join(bad[:3]) if bad else ""))

    # ---- 8. L8: 入场动画的载体与接线（曲线值来自包内 lua，不手抄）--------------------------
    # 动画只在段头 0.1 s 有可见差，1 s 网格的 L2/L3 碰不到（P-30 就地更正的口径），
    # 所以要单独一层；判据含「动画期外必须逐字节相同」，用来抓「曲线常驻」这类错。
    if not args.skip_animations:
        # 曲线表是浏览器腿的依赖，手工导出就会悄悄过期（与 P-33 记的「代理模型缺字段」同一类：
        # 依赖不重建，浏览器静默按旧形状跑而门全绿）。所以每次门都重导一次并断言计数。
        rc = run([PY, "scripts/animation_curve.py", "--dump-table", args.model,
                  "--out", "temp/playback-test/animation-curves.json"])
        # 断言只看**计数**，不看中文：子进程 stdout 在 GBK 控制台上是被替换过的，
        # 拿中文子串匹配会把一次成功的重导判成失败（本层第一版就这么假红过一次）。
        # 两个计数各核各的，别混：`N presets` 对表里的预设条数，`覆盖 X/Y 段` 的 Y
        # 必须等于模型的 stats.animation_segments（口径：带**真条目**的段数，不是引用段数）。
        allout = "\n".join((rc.stdout or "").splitlines())
        mp = re.search(r"(\d+)\s*presets", allout)
        mc = re.search(r"(\d+)/(\d+)", allout)
        table = OUT / "animation-curves.json"
        try:
            tab = json.loads(table.read_text(encoding="utf-8")) if table.is_file() else {}
        except (OSError, ValueError):
            tab = {}
        n_pre = len(tab.get("presets") or {})
        seg_all = (m.get("stats") or {}).get("animation_segments")
        ok = (rc.returncode == 0 and mp and mc and n_pre == int(mp.group(1))
              and tab.get("segments_covered") == int(mc.group(1))
              and seg_all is not None and int(mc.group(2)) == seg_all)
        verdict("L8 curves table rebuilt from the model", ok,
                f"表内预设 {n_pre}（导出的说 {mp.group(1) if mp else '?'}），"
                f"覆盖 {mc.group(0) if mc else '?'} 段（模型 animation_segments={seg_all}）"
                + ("" if ok else f" | stdout={allout[-160:]!r}"))
        aw = run([PY, "scripts/animation_wiring_check.py", "--model", args.model])
        tail = [ln for ln in aw.stdout.splitlines() if "animation wiring checks" in ln]
        verdict("L8 animation wiring (real draft, covered presets)", aw.returncode == 0,
                (tail[-1] if tail else (aw.stdout or aw.stderr)[-160:]))

    width = max(len(name) for name, _, _ in checks) + 2
    # 控制台编码是 GBK：detail 里带中文（脚本 stdout 尾巴、预设名）时 print() 会在**最后一步**
    # 抛 UnicodeEncodeError，把已经跑完的 17 层结果全部吞掉。改成按字节写并替换不可编码字符。
    def emit(s: str) -> None:
        try:
            print(s)
        except UnicodeEncodeError:
            sys.stdout.buffer.write((s + "\n").encode("utf-8", "replace"))
    for name, state, detail in checks:
        emit(f"{state:<5} {name:<{width}} {detail}")
    failed = [c for c in checks if c[1] == "FAIL"]
    print(f"\n{len(checks) - len(failed)} of {len(checks)} checks passed"
          + (f", {len(failed)} FAILED" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
