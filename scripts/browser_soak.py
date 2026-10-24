"""Launch headless Chrome at a probe URL and sample its process-tree RSS while it runs.

Why this exists: the browser-side 判据 "10 分钟会话 ≤ 2 GB" has to be read from the OS, not from
performance.memory (JS heap is ~100 MB and says nothing about GPU/Skia/decoder allocations).
temp/px-probe/run_browser_probe.py did this for the old decode probe but had the URL, port and
report file baked in; this one takes them as arguments so the same measurement works on the
player page.

Chrome needs an **absolute** --user-data-dir: a relative one falls back to the user's real
profile and attaches to the running browser session.

Usage:
  python scripts/browser_soak.py --url http://127.0.0.1:8790/playback-test/player.html?autostart=1 \
      --seconds 600 --report temp/playback-test/report-playback.jsonl --tag soak-proxy
"""

from __future__ import annotations

import argparse
import subprocess
import threading
import time
from pathlib import Path

import psutil
import sys
# Windows 控制台是 GBK：读数里带中文/箭头/替换符时 print 会在最后一步抛错，
# 把已经算完的结果整个吞掉（本轮自己的统计工具就栽过一次）。只改错误处理策略，不改编码。
try:
    sys.stdout.reconfigure(errors="replace")     # type: ignore[attr-defined]
    sys.stderr.reconfigure(errors="replace")     # type: ignore[attr-defined]
except Exception:                                 # noqa: BLE001
    pass

CHROME = r"C:/Program Files/Google/Chrome/Application/chrome.exe"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "temp" / "playback-test"


def proc_role(cmdline: list[str]) -> str:
    """Chrome tags its child processes with --type=...; that is what makes a peak attributable."""
    for i, arg in enumerate(cmdline):
        if arg.startswith("--type="):
            return arg.split("=", 1)[1]
        if arg == "--type" and i + 1 < len(cmdline):
            return cmdline[i + 1]
    return "browser"


def tree_rss_mb(proc: psutil.Process) -> tuple[float, int, dict]:
    procs = [proc]
    try:
        procs += proc.children(True)
    except psutil.NoSuchProcess:
        pass
    total = 0
    by_role: dict[str, float] = {}
    for p in procs:
        try:
            rss = p.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        try:
            role = proc_role(p.cmdline())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            role = "unknown"
        total += rss
        by_role[role] = by_role.get(role, 0.0) + rss / 2**20
    return total / 2**20, len(procs), by_role


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", required=True)
    ap.add_argument("--seconds", type=int, default=120)
    ap.add_argument("--report", default="", help="jsonl the page self-posts to; waited on for growth")
    ap.add_argument("--tag", default="soak")
    ap.add_argument("--timeout", type=int, default=0, help="kill chrome after this many seconds regardless")
    args = ap.parse_args()

    profile = OUT / f"chrome-soak-{args.tag}"
    profile.mkdir(parents=True, exist_ok=True)
    report = Path(args.report) if args.report else None
    before = len(report.read_text(encoding="utf-8").splitlines()) if report and report.exists() else 0

    # No --disable-gpu here on purpose: the render-base decision is only valid with the hardware
    # path on (F-043/F-044), so the memory reading has to be taken in that configuration too.
    cmd = [CHROME, "--headless=new", "--no-sandbox", "--no-first-run",
           "--no-default-browser-check", "--autoplay-policy=no-user-gesture-required",
           f"--user-data-dir={profile.resolve().as_posix()}",
           "--window-size=1280,900", "--remote-debugging-port=0", args.url]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ps = psutil.Process(proc.pid)

    samples, stop = [], threading.Event()

    def sampler() -> None:
        while not stop.is_set():
            try:
                mb, n, roles = tree_rss_mb(ps)
            except psutil.NoSuchProcess:
                break
            samples.append((round(time.time() - t0, 1), mb, n, roles))
            time.sleep(1.0)

    t0 = time.time()
    th = threading.Thread(target=sampler, daemon=True)
    th.start()
    deadline = t0 + (args.timeout or args.seconds + 30)
    while time.time() - t0 < args.seconds:
        if proc.poll() is not None:
            break
        if report:
            try:
                if len(report.read_text(encoding="utf-8").splitlines()) > before:
                    break
            except OSError:
                pass
        if time.time() > deadline:
            break
    stop.set()
    th.join(timeout=3)
    wall = time.time() - t0
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    for p in psutil.process_iter(["ppid"]):
        try:
            if p.info["ppid"] == proc.pid:
                p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if not samples:
        print("no samples - chrome died immediately?", flush=True)
        return 1
    top = max(samples, key=lambda s: s[1])
    peak = top[1]
    mean = sum(s[1] for s in samples) / len(samples)
    last = samples[-1][1]
    first = samples[0][1]
    median = sorted(s[1] for s in samples)[len(samples) // 2]
    over = sum(1 for s in samples if s[1] > 2048)
    roles = ", ".join(f"{k}={v:.0f}MB" for k, v in sorted(top[3].items(), key=lambda kv: -kv[1])[:5])
    lines = [
        f"tag={args.tag} url={args.url}",
        f"wall_s={wall:.1f} samples={len(samples)} peak_procs={max(s[2] for s in samples)}",
        f"rss_first_mb={first:.0f} rss_mean_mb={mean:.0f} rss_peak_mb={peak:.0f} rss_last_mb={last:.0f}",
        f"rss_median_mb={median:.0f} seconds_over_2048={over}/{len(samples)}",
        f"peak_at_s={top[0]:.0f} by_role: {roles}",
        f"threshold_mb=2048 verdict={'PASS' if peak <= 2048 else 'FAIL'}",
        "growth_mb_over_window=%.0f" % (last - first),
        "per_second:" + ",".join(f"{t:.0f}s={mb:.0f}MB" for t, mb, _, _ in samples),
    ]
    (OUT / f"rss-{args.tag}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:5]), flush=True)
    print(f"-> {OUT / f'rss-{args.tag}.txt'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
