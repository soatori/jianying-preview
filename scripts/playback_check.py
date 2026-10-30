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
      --plain "temp/playback-test/plain/<草稿名>__draft_content.json.dec.json" \
      --draft-root "<草稿根>/<草稿名>" \
      --timeline "<时间线 uuid>" \
      --model temp/playback-test/model-proxy-a.json \
      --oracle-mp4 "<你的成片 mp4>" \
      --pixel-t 1.0 --pixel-colour 255,255,255
  # --pixel-colour must name a layer that is actually live at --pixel-t: the default gold
  # caption only exists in the cover state, and against the export it reads "layer missing".
"""

from __future__ import annotations

import argparse
import json
import os
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import jy_paths                                      # noqa: E402

FFMPEG = str(jy_paths.ffmpeg())

# The six base criteria, as thresholds. Values come from docs/spec (render-base decision) and the
# readings in docs/evidence/playback-log.md; a criterion with no agreed basis is reported INFO.
CRITERIA = {
    "composited_fps_min": 24.0,
    "seek_median_ms_max": 150.0,
    "first_frame_ms_max": 300.0,
    "session_peak_mb_max": 2048.0,
    # 帧预算按 30 fps 的一帧（33.3 ms）定 p95，按四个帧周期定 max：这是"看不出顿"的口径，
    # 不是照着某一轮读数反推的阈值。
    "frame_cost_p95_ms_max": 33.4,
    "frame_cost_max_ms_max": 150.0,
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
            return {"n": int(n), "frac": 0.0}
        return {"n": int(n), "frac": round(n / (h * w), 6),
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
    # 试过把「墨量比」也做成判据，**它是空的**：F-084 的豆腐块负样本给 ink_ratio 0.865，
    # 稳稳落在任何合理带宽里——整帧白墨 mask 被素材的亮区主导，字幕只占其中百分之几。
    # 真正有牙的还是下面这条 bbox 判据：豆腐块时 y1 从 0.732 掉到 0.540（Δ0.192 ≫ 0.02），
    # 因为字幕是画面里**最低**的白东西，1–99 百分位盒的下边就是它定的。
    # 墨量只在**字幕带内**才有意义，那条判据在 `scripts/caption_ink_check.py`（带由模型几何定）。
    return {**shared, "delta": d, "max_delta": max(d.values()),
            "ink_ratio": round(r["frac"] / c["frac"], 3) if c["frac"] else float("inf"),
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
                    help="battery runs per criterion; verdicts are medians. "
                         "自 2026-10-29 起也覆盖 `L4 frame budget`：整条时间轴那层会跑 "
                         "repeat 个点（每点约 +1~2 分钟墙钟，含交界 settle）")
    ap.add_argument("--settle-seconds", type=float, default=12.0,
                    help="相邻**起浏览器的阶段**之间的空机等待，语义同 "
                         "temp/playback-test/s1_split_ab.py 的 S1_SETTLE（等上一轮 Chrome 连同 "
                         "gpu-process/renderer 彻底退出、profile 落盘结束）。0 = 关掉，回到 "
                         "P-97 那一跑的背靠背形态。生效交界见 settle_before() 的注释")
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
    ap.add_argument("--skip-flash", action="store_true",
                    help="skip the L11 向上闪入 in/out A/B layer")
    ap.add_argument("--skip-jank", action="store_true",
                    help="skip the whole-timeline frame-budget layer (~1 extra pass)")
    ap.add_argument("--flash-seconds", type=int, default=1500,
                    help="L11 budget: it renders 16 frames x 3 arms offline")
    args = ap.parse_args()

    checks: list[tuple[str, str, str]] = []
    media_model = args.media_model or args.model
    report = OUT / "report-playback.jsonl"

    def verdict(name: str, ok: bool, detail: str) -> None:
        checks.append((name, "PASS" if ok else "FAIL", detail))

    # ---- 阶段交界的空机等待（P-97 ④ 第 4 条钉出来的结构问题）------------------------------
    # 理由不是"慢一点更稳"，是**读数会互相纠缠**：browser_soak 返回时只保证它 terminate 了自己那个
    # Chrome 主进程（scripts/browser_soak.py:124-134），gpu-process / renderer / profile 落盘还在收尾，
    # 下一个 Chrome 就在这条尾巴里起跑 ⇒ 门里 `L4 live pacing`（n=662 帧、paint p50 1516 ms）、
    # `L6` 同跑那条 `['846DA305']`、RSS peak 6251 MB 三处红出自**同一条被污染的跑**，
    # 而空载 + 臂间 settle 的独立复测 5 次都不可复现（P-97 ③④）。
    # 生效交界 = 相邻两次"起 Chrome 的阶段"之间，按跑序：
    #   电池 check0 → check1 → …（每个 repeat 点各一次）
    #   → 整条时间轴帧预算 jank0 → jank1 → …
    #   → 直播节奏 livepacing → L10 浏览器截图 → 负样本 check-neg
    #   → L7 混合模式浏览器腿 → L7 GPU 三方
    # 不起浏览器的阶段（L1 建模、L2/L3 的 ffmpeg 出图、L8/L9/L11 离线判定）之间**不等**，
    # 第一个起浏览器的阶段也不等（那一刻还没有我们启动的 Chrome）。
    _browser_stage: list[str] = []

    def log(s: str) -> None:
        try:
            print(s, flush=True)
        except UnicodeEncodeError:
            sys.stdout.buffer.write((s + "\n").encode("utf-8", "replace"))

    def settle_before(stage: str) -> None:
        prev = _browser_stage[-1] if _browser_stage else ""
        if prev and args.settle_seconds > 0:
            log(f"[settle] {prev} -> {stage}: 空机 {args.settle_seconds:g} s"
                "（等上一轮 Chrome 彻底退出；--settle-seconds 0 可关）")
            time.sleep(args.settle_seconds)
        _browser_stage.append(stage)

    # ---- 0. L0: the player under test must be the tracked one -------------------------------
    # The runtime copy sits in temp/ because that is where the gateway's static root and the
    # `/playback-test/...` URLs point (it pulls pixi/mediabunny from /px-probe/node_modules too).
    # If that copy drifts from `player/player.html`, every browser layer below judges code that is
    # not in the repo -- so materialise it and assert the write landed byte-identical.
    src = ROOT / "player" / "player.html"
    dst = OUT / Path(args.player).name
    if not src.is_file():
        verdict("L0 tracked player present", False, f"{src} missing")
    else:
        blob = src.read_bytes()
        tmp = dst.with_suffix(dst.suffix + ".sync.tmp")
        tmp.write_bytes(blob)
        os.replace(tmp, dst)
        verdict("L0 tracked player in place", dst.read_bytes() == blob,
                f"player/player.html -> {dst.relative_to(ROOT)} ({len(blob)} B), 与在册副本逐字节相同")

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
    # 轨类型覆盖（U-98）：不判 PASS/FAIL —— 草稿里有 mixed/sticker 轨不是错误，
    # 但"没被任何一条腿路由的段数"必须出现在门面上，否则它又变成一个没人读的数。
    checks.append(("L1 track coverage", "INFO",
                   f"按类型段数 {s.get('track_type_segments')}, "
                   f"未路由段数 {s.get('unrouted_track_segments')} "
                   f"(画面只走 video/text，声音只走 audio/video)"))

    # ---- 1b. L1 carrier hygiene: the media model is a *snapshot* ---------------------------
    # `fonts[].exists` was computed when the carrier was built. JianYing can evict its effect-font
    # cache at any time (it did, mid-session, F-084), and then the browser goes and fetches a face
    # that is no longer on disk: the page reports "A network error occurred" and L6 goes red for an
    # environmental reason that looks exactly like a player regression. Say what it is instead.
    mm = json.loads(Path(media_model).read_text(encoding="utf-8-sig"))
    stale = [f.get("path", "-") for f in (mm.get("fonts") or [])
             if f.get("exists") and not Path(f.get("path", "")).is_file()]
    verdict("L1 carrier freshness", not stale,
            f"{len(mm.get('fonts') or [])} face(s) listed in {Path(media_model).name}, "
            f"stale exists=true on {len(stale)}"
            + (f" - rebuild the carrier before reading L6; e.g. {stale[0][-40:]}" if stale else ""))

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
                    f"{got.get('max_delta', 'n/a')} (<=0.02) over {got.get('n_render', 0)} px; "
                    f"ink ratio {got.get('ink_ratio', 'n/a')} (observed only, NOT judged — "
                    f"void on the F-084 fixture) [{got.get('why', '')}]")
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

        def battery(url_model: str, tag: str, playms: int | None = None,
                    seeks: int | None = None) -> dict:
            settle_before(f"电池 {tag}")
            before = len(report.read_text(encoding="utf-8").splitlines()) if report.exists() else 0
            url = (f"http://127.0.0.1:{port}/playback-test/{args.player}"
                   f"?autostart=1&model={url_model}"
                   f"&playms={playms if playms is not None else args.battery_ms}"
                   f"&seeks={seeks if seeks is not None else args.seeks}"
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

            # ---- 4b. L4 帧预算：整条时间轴跑 repeat 遍，判尾部而不是均值 -----------------------
            jd: list[dict] = []
            ld: dict = {}   # --skip-jank 时这两个不进 L6 的分母，但名字必须存在（L6 要引用）
            # 用户报"一顿一顿"而门全绿，有两条理由：①`composited_fps` 是帧数÷墙钟的**均值**，
            # 一帧 1.2 s 的停顿摊进均值只剩 0.03 fps；②电池只跑 10 s 还带 seek，实测最坏那十帧
            # 落在 5.7~16.4 s，从没被覆盖过。这层自己走完整条时间轴，判 p95/max，并把
            # "重复上一帧"的次数与新帧速率一起报出来——否则"不卡"可能只是"冻住了"。
            # 「把单点当分布」的更正（P-97 ② 第 2 条 / ⑦ 第 2 条）：这一层原先写在 repeat 循环
            # **之外**，所以 `--repeat 2` 也只产 1 个帧预算点，而 P-96/P-97 是按"分布"在读的
            # （靠事后另开 p97_jank_repeat.py 补到 4 点）。现在点数 = args.repeat。
            # **代价（明写）**：每个点多跑一条整条时间轴（本机 duration≈36.8 s + 交界 settle），
            # ≈ +1~2 分钟墙钟；`--repeat 3`（默认）比改前多约 2~4 分钟。
            # **判据一个数没动**：线仍是 p95<=33.4 / max<=150，且**每个点各自吃线、全部过才绿**
            # ——不取中位，取中位会让一个被污染的点被其余点平均掉，那是悄悄放宽。
            if not args.skip_jank:
                dur_ms = int(round(m["duration_us"] / 1000)) + 700
                for i in range(args.repeat):
                    d = battery(Path(media_model).name, f"jank{i}", playms=dur_ms, seeks=0)
                    if d:
                        jd.append(d)
                num = lambda v: isinstance(v, (int, float))  # noqa: E731
                pts = []
                for i, d in enumerate(jd):
                    pl_i = d.get("play") or {}
                    fc_i = pl_i.get("frame_cost_ms") or {}
                    p95_i, mx_i, n_i = fc_i.get("p95"), fc_i.get("max"), fc_i.get("n") or 0
                    pts.append({"i": i, "d": d, "pl": pl_i, "fc": fc_i, "n": n_i,
                                "p95": p95_i, "max": mx_i,
                                "ok": (n_i > 0 and num(p95_i) and num(mx_i)
                                       and p95_i <= CRITERIA["frame_cost_p95_ms_max"]
                                       and mx_i <= CRITERIA["frame_cost_max_ms_max"])})
                bad_pts = [p for p in pts if not p["ok"]]
                p95s = [p["p95"] for p in pts if num(p["p95"])]
                maxs = [p["max"] for p in pts if num(p["max"])]
                # 详字段（>33ms/重复帧/预热分母）钉在 **max 最大的那个点**上，与历史单点读数同框可比
                worst = max(pts, key=lambda p: p["max"] if num(p["max"]) else -1) if pts else None
                w = ((worst or {}).get("pl") or {}).get("warm") or {}
                ok = bool(pts) and not bad_pts
                verdict("L4 frame budget (whole timeline, tail not mean)", ok,
                        f"n={len(pts)} 个点（--repeat={args.repeat}；绿=**每个点**都过 "
                        f"p95<={CRITERIA['frame_cost_p95_ms_max']} / "
                        f"max<={CRITERIA['frame_cost_max_ms_max']}，不取中位）"
                        f"；p95 各点 {[p['p95'] for p in pts]} 中位 {med(p95s)}"
                        f"；max 各点 {[p['max'] for p in pts]} 中位 {med(maxs)}"
                        + (f"；点数缺 {args.repeat - len(pts)}（页面没自报）"
                           if len(pts) < args.repeat else "")
                        + ("" if not worst else
                           f" | 详读点#{worst['i']}（max 最大）n={worst['n']} "
                           f"p50={worst['fc'].get('p50')} p90={worst['fc'].get('p90')} "
                           f"p95={worst['p95']} max={worst['max']} ms；"
                           f">33ms {worst['fc'].get('over_33ms')} >100ms {worst['fc'].get('over_100ms')}；"
                           f"重复上一帧 {(worst['pl'].get('pump') or {}).get('stale_holds')} 次，"
                           f"新帧 {worst['pl'].get('fresh_track_frames_per_second')}/s"
                           # 预热这条腿的分母：max 过线也可能因为它根本没跑（页侧默认开，一旦被改坏
                           # 就退化成"别处巧合让 max 达标"）。used≠started 就是有白热的解码器。
                           f"；预热泵 {w.get('used')}/{w.get('started')} 被到点取用"
                           f"（开={w.get('on')} 白热={w.get('wasted')} 废={w.get('dropped')}）")
                        + ("" if ok else
                           f" | 未过线点 {[p['i'] for p in bad_pts]}"
                           + (f" worst={worst['fc'].get('worst', [])[:3]} "
                              f"fps={worst['pl'].get('composited_fps')}" if worst else "")))
            else:
                # 跳过时要留一行的理由：这层是"整条时间轴会不会冻住"的唯一判据，而末尾的绿色总数
                # 是按 checks 计数、SKIP 也计入"未失败"。不留行，`--skip-jank` 的一跑就会以
                # "N of N 全绿"的名义，宣称一个从没测过的判据通过了。
                checks.append(("L4 frame budget (whole timeline, tail not mean)", "SKIP",
                               f"--skip-jank：整条时间轴的 p95/max 未测（本应有 --repeat={args.repeat} "
                               "个点），本层的判据不在这一跑里"))
            # ---- 4c. L4 直播节奏（tick 那条真实通路，用 drive=timer 敲同一个函数体）--------------
            # 其余各腿都跑在 battery() 自己按墙钟补帧的循环上；本机 headless、Qoder 内置浏览器、
            # 我自己起的带头 Chrome 三处都实测 **rAF 0 帧**，真实 rAF 自动测不到。
            # 但 tick() 本来就是 rAF 不等返回的 fire-and-forget ⇒ 用同帧率的定时器去敲它，
            # `await paint()` 挡住下一拍的效应一样，于是"用户看到的那条路"终于有自动读数。
            # 读数口径写死是 timer 驱动，不许冒充真实 rAF（写进报告字段 driver）。
            if not args.skip_jank:
                live_ms = int(round(m["duration_us"] / 1000)) + 3000
                # 网关按 tag 分文件写（report-<tag>.jsonl）。这个坑本轮踩过三次：
                # 不显式带 &tag= 而依赖页面默认值，就会去读一个永远不增长的 `report-playback.jsonl`，
                # 症状是"页面什么都没回答"。所以 URL 里写死 tag，读的也就是那个文件。
                lrep = OUT / "report-livepacing.jsonl"
                before = len(lrep.read_text(encoding="utf-8").splitlines()) if lrep.exists() else 0
                settle_before("直播节奏 livepacing")
                run([PY, "scripts/browser_soak.py", "--url",
                     f"http://127.0.0.1:{port}/playback-test/{args.player}"
                     f"?liveplay={live_ms}&model={Path(media_model).name}"
                     f"&drive=timer&fps=30&tag=livepacing",
                     "--seconds", str(int(live_ms / 1000) + 25),
                     "--report", str(lrep.relative_to(ROOT)), "--tag", "livepacing"])
                lines = lrep.read_text(encoding="utf-8").splitlines() if lrep.exists() else []
                ld = json.loads(lines[-1]) if len(lines) > before else {}
                lv = ld.get("live") or {}
                # 音画残差：音频时钟走过的秒数与播放头走过的秒数之差。
                # 必须**截到播放头还在走的那段**——时间轴走完 pos 就钉在 DUR，
                # 而 ctx 继续跑到 liveplay 窗口结束，不截就会看到 +4.9 s 的假失步（本轮就差点报出去）。
                dur = m["duration_us"] / 1e6
                ctk = [x for x in (lv.get("clock_track") or []) if len(x) > 2 and x[2] is not None]
                playing_pts = [x for x in ctk if x[1] < dur - 0.05]
                avres: list[float] = []
                if len(playing_pts) > 5:
                    p0, c0 = playing_pts[0][1], playing_pts[0][2]
                    avres = [(x[2] - c0) / 1000.0 - (x[1] - p0) for x in playing_pts]
                av_max = max((abs(v) for v in avres), default=None)
                nfr, p95, mx = lv.get("frames"), lv.get("gap_p95_ms"), lv.get("gap_max_ms")
                okl = (isinstance(nfr, int) and nfr > 200
                       and isinstance(p95, (int, float)) and p95 <= 50.0
                       and isinstance(mx, (int, float)) and mx <= 150.0
                       and avres and av_max is not None and av_max <= 0.05)
                verdict("L4 live pacing + A/V residual (drive=timer, not real rAF)", okl,
                        f"n={nfr} 帧 gap p50={lv.get('gap_p50_ms')} p95={p95} max={mx} ms"
                        f"（p95<=50 / max<=150）；音画残差 max={None if av_max is None else round(1000*av_max)} ms"
                        f"（<=50，截到播放头走完为止）；paint p50={lv.get('paint_p50_ms')} "
                        f"p95={lv.get('paint_p95_ms')} "
                        f"driver={lv.get('driver')} avclk={lv.get('avclk')} 错误={len(ld.get('tick_errors') or [])}")
            else:
                checks.append(("L4 live pacing + A/V residual (drive=timer, not real rAF)", "SKIP",
                               "--skip-jank：直播节奏这条真实通路的 tick 未测"))

            # L6 的分母原本只有 10 s 电池那几条跑，于是**整条时间轴那跑里的黑屏从来没被 judge 过**。
            # P-85 就是这么一条：flag=2 叠层 `C7817`（窗口 10.733–12.467 s）在整条跑里连续 ≥5 帧没出图，
            # 同跑 L6 仍报 0/1。判"有没有静默黑屏"却不看用户实际会走完整条的那一遍，等于只在一小段
            # 采样里有牙齿。现在把整条跑（jank）与直播节奏跑（livepacing）一起纳入，并按路径标注，
            # 免得两个分母混成一个数。整条跑现在每 repeat 一个点，所以逐点列出（`整条时间轴#i`）。
            extra_runs = [(f"整条时间轴#{i}", d) for i, d in enumerate(jd)]
            if ld:
                extra_runs.append(("直播节奏", ld))
            # --skip-jank 时 jd/ld 是空。空 dict 的 black_streaks 是 falsy，原来会被当成
            # "0 条黑屏"计进 2 的分母 ⇒ 用没跑过的跑充数。只计真取到读数的跑，缺几条写进 detail。
            # 期望点数 = repeat 条整条 + 1 条直播（改前这个 2 是写死的）。
            expected_x = args.repeat + 1
            missing_x = expected_x - len(extra_runs)
            bad = [d for d in runs if d.get("black_streaks") or d.get("errors")]
            bad_x = [(name, d) for name, d in extra_runs
                     if isinstance(d, dict) and (d.get("black_streaks") or d.get("errors"))]
            verdict("L6 no silent black frame", not bad and not bad_x,
                    f"{len(bad)}/{len(runs)} 电池跑 + {len(bad_x)}/{len(extra_runs)} 整条/直播跑"
                    f" 有 black_streaks 或 errors"
                    + (f"；整条/直播跑缺 {missing_x} 条"
                       f"（{'--skip-jank' if args.skip_jank else '这些点没取到读数'}），"
                       f"期望 {expected_x} 条、分母随之缩小" if missing_x else "")
                    + (f"; e.g. {bad[0].get('black_streaks')} {bad[0].get('errors')[:1]}" if bad else "")
                    + "".join(f" | {n}: {d.get('black_streaks')} {(d.get('errors') or [''])[0][:70]}"
                              f" (max帧时 {(d.get('play') or {}).get('frame_cost_ms', {}).get('max')} ms"
                              f", 不成像素材 {(d.get('no_video_media') or {}).get('frames_skipped')} 帧)"
                              for n, d in bad_x))
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
            settle_before("L10 浏览器截图")
            run([PY, "scripts/browser_soak.py", "--url", url,
                 "--seconds", str(args.shot_seconds), "--report", str(report.relative_to(ROOT)),
                 "--tag", "shot", "--timeout", str(args.shot_seconds + 25)])
            # 通道 2 这一腿必须和浏览器**播同一批媒体**。浏览器播的是代理（`--media-model`），
            # 而这里一直传的是 `--model`（原片）——F-083 第③条量过这个混淆本身就有 0.04
            # （0.910 vs 0.948），拿它当「两条通道不一致」会把管线差异算到渲染账上。
            sh = run([PY, "scripts/browser_shot_check.py", "--timestamps", times,
                      "--model", media_model, "--frames-dir", args.oracle_frames,
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
        # 浏览器那条腿单独一层：本草稿 0 个 mix_mode 段，L1~L10 在真实模型上永远不会
        # 走到浏览器混合路径；这层拿注入件跑真浏览器，判"载体取到切片、滤镜建出来、
        # 挂在活节点上"，并且带**反 fixture**（未知包 md5 必须降级且不挂任何节点）。
        # 这两条浏览器腿也在 settle 交界里：上一段 Chrome（负样本跑）刚 terminate，
        # gpu/renderer 还在收尾时再起一个浏览器，测的就不是脚本而是"两个窗口叠加"的机器。
        settle_before("L7 mixmode 浏览器腿")
        bw = run([PY, "scripts/mixmode_browser_check.py",
                  "--carrier", args.media_model or args.model], timeout=300)
        btail = [ln for ln in bw.stdout.splitlines() if "MIXMODE_BROWSER_WIRING" in ln]
        verdict("L7 mixmode browser wiring (fixture + negative fixture)",
                bw.returncode == 0 and any("MIXMODE_BROWSER_WIRING ok" in ln for ln in btail),
                (btail[-1][:150] if btail else (bw.stdout or bw.stderr)[-150:]))
        if args.mixmode_gpu:
            settle_before("L7 mixmode GPU 三方")
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
                    # 判据不看 stdout，只看 rc + 表。所以子进程一旦非零，**表可能是上一跑的**
                    # （本轮就撞上一次：门里这层红、行里却写"10 modes / 0 out of tolerance"，
                    # 读起来像"全对却 FAIL"）。把 rc 与尾巴、表的 mtime 一起打出来，下次能归因。
                    + (f" | rc={eq.returncode} 表 mtime="
                       f"{time.strftime('%m-%d %H:%M:%S', time.localtime(tp.stat().st_mtime)) if tp.exists() else '无表'}"
                       f" 本次没重导表"
                       + " tail=" + ((eq.stdout or "") + (eq.stderr or ""))[-260:].replace("\n", " / ")
                       if eq.returncode else "")
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
        # 打字光标是**新落地的渲染路径**，而整帧类判据对「字幕是整句出现还是逐字露出」不敏感
        # （F-072/F-080 同族）⇒ 表从载体里丢了、或 truncate 提前 return，都不会让任何一层变红。
        # 规约「本草稿会触发的新渲染路径必须有自己的门层」，这条就是补上的那层。
        tw = run([PY, "scripts/typewriter_wiring_check.py", "--model", args.model, "--segments", "2"])
        twl = [ln for ln in tw.stdout.splitlines() if "TYPEWRITER_WIRING" in ln]
        verdict("L8 typewriter wiring (prefix law live on channel 2 + carrier)", tw.returncode == 0,
                (twl[-1].strip() if twl else (tw.stdout or tw.stderr)[-160:]))

    # ---- 11. L11: 「向上闪入」曝光+垂直模糊的同刻开/关 A/B（对成片同帧号）--------------------
    # 这条族是 L10 在 t=6.633 判红的成因（F-095/F-096），而整帧相关对「只有一层在动」不敏感
    # （F-072/F-080）⇒ 两项各自都要能证明"生效了"。判据形态：窗内每帧 MAD 不变坏、窗外逐字节
    # 相同、阴性对照（预切点）不动、降级 0 且分母报出来。窗内必须**同时**见到曝光项和模糊项，
    # 否则表里那条 ADBE_Gaussian_Blur_2_0001_2_3 丢了也不会变红（空判据）。
    if not args.skip_flash:
        if args.oracle_mp4:
            rep = OUT / "flash-ab-gate.json"
            fr = run([PY, "scripts/flash_channel2_ab.py", "--model", media_model,
                      "--mp4", args.oracle_mp4, "--lead", str(args.oracle_lead),
                      "--fps", str(args.oracle_fps), "--report", str(rep)],
                     timeout=args.flash_seconds)
            try:
                rows = json.loads(rep.read_text(encoding="utf-8")) if rep.is_file() else []
            except (OSError, ValueError):
                rows = []
            live_of = lambda r: (r["exposure_E"] or 0) > 1e-4 or (r["vblur_V"] or 0) > 1e-4
            live = [r for r in rows if live_of(r)]
            idle = [r for r in rows if not live_of(r)]
            expo_live = [r for r in live if (r["exposure_E"] or 0) > 1e-4]
            blur_live = [r for r in live if (r["vblur_V"] or 0) > 1e-4]
            # 两项各自单变量：曝光看 off→expo，模糊看 expo→both。只看 off→both 会漏掉
            # 「曝光赚的被模糊亏回去」（206 帧那版过糊就是这么躲过去的）。
            worse = [r["frame"] for r in live if r["mad_expo"] > r["mad_off"] + 0.05]
            blur_worse = [r["frame"] for r in blur_live if r["mad_both"] > r["mad_expo"] + 0.05]
            flat = [r["frame"] for r in live if abs(r["mad_both"] - r["mad_off"]) <= 0.05]
            moved = [r["frame"] for r in idle if abs(r["mad_both"] - r["mad_off"]) > 1e-9]
            degrades = [x for r in rows for x in (r.get("log") or []) if x[0] == "degraded"]
            ok = (fr.returncode == 0 and rows and expo_live and blur_live
                  and not worse and not blur_worse and not moved and not degrades)
            verdict("L11 flash in/out A/B (channel 2 vs export, same frame index)", ok,
                    f"{len(rows)} 帧：窗内 {len(live)}（曝光 {len(expo_live)} / 模糊 {len(blur_live)}）、"
                    f"窗外 {len(idle)}；曝光变坏 {len(worse)} 模糊变坏 {len(blur_worse)} "
                    f"合计持平 {len(flat)}，窗外位移 {len(moved)}，降级 {len(degrades)}/{len(rows)}"
                    + (f" worse={worse[:4]} blur_worse={blur_worse[:4]}"
                       if (worse or blur_worse) else "")
                    + ("" if ok else f" | rc={fr.returncode} err={(fr.stderr or '')[-120:]}"))
        else:
            checks.append(("L11 flash in/out A/B", "SKIP", "no --oracle-mp4 given"))

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
