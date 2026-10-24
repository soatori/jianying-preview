"""内存判据的单变量 A/B：同一份播放器代码，只换模型（或只换一个开关），比 RSS 分布。

为什么要它：600 s 判据在新 build 上 median 从 **895 → 1166 MB**（peak 1674 → 1767，
`rss-gate.txt` vs `rss-anim-soak.txt`，两条都是 `playms=600000&seeks=0`）。
角色拆开看是 **gpu-process 1281→1018（降）而 renderer 285→496（升）**，
所以「我们的改动让内存涨了」这句不能直接说——旧读数与新读数的峰值时刻也不同（163 s vs 18 s），
两次跑的差别不止一个变量。要判就得一次只动一个东西，并且看**分布**而不是单点。

口径：
  - 中位数、p95、越线秒数一起报（峰值是单点，容易被一次 GPU 抖动带偏，U-79 争的就是这个）。
  - 每个 arm 独立起浏览器与 profile，跑完自己收（不留驻进程）。
  - 两 arm 之间不并行：同机 ffmpeg/GPU 争用会同时污染 RSS 与帧率读数（P-05 的教训）。

用法:
    python scripts/rss_ab.py --arms "旧模型=model-proxy-a.json.bak,新模型=model-proxy-a.json" \
        [--seconds 200] [--playms 240000] [--port 8793] [--report temp/playback-test/rss-ab.json]
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import statistics
import subprocess
import sys
import time
from pathlib import Path
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

ROLE_RE = re.compile(r"([a-z-]+)=(\d+)MB")


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_port(port: int, timeout: float = 25.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.2)
    return False


def run_arm(name: str, model: str, port: int, seconds: int, playms: int, tag: str) -> dict:
    extra = ""
    if "?" in model:
        model, extra = model.split("?", 1)
        extra = "&" + extra
    url = (f"http://127.0.0.1:{port}/playback-test/player.html?autostart=1&model={model}"
           f"&playms={playms}&seeks=0&fps=30&qmax=4&pool=4&loop=1&tag={tag}{extra}")
    rr = subprocess.run([PY, "scripts/browser_soak.py", "--url", url,
                         "--seconds", str(seconds), "--tag", tag,
                         "--report", str((OUT / f"report-{tag}.jsonl").relative_to(ROOT)),
                         "--timeout", str(seconds + 40)],
                        cwd=str(ROOT), capture_output=True, text=True,
                        encoding="utf-8", errors="replace")
    rss = OUT / f"rss-{tag}.txt"
    if not rss.is_file():
        return {"arm": name, "model": model, "error": f"{rss.name} 没写出来（soak 退出码 {rr.returncode}）",
                "stderr_tail": (rr.stderr or "")[-300:]}
    txt = rss.read_text(encoding="utf-8", errors="replace")
    # browser_soak 的逐秒行形如 `  12.4 1180 14 gpu-process=...,renderer=...`
    numbers = [int(m) for m in re.findall(r"^\s*[\d.]+\s+(\d+)\s+\d+", txt, re.M)]
    summary = {}
    for k in ("rss_first_mb", "rss_mean_mb", "rss_peak_mb", "rss_last_mb", "rss_median_mb"):
        m = re.search(rf"{k}=(\d+)", txt)
        if m:
            summary[k] = int(m.group(1))
    over = re.search(r"seconds_over_2048=(\S+)", txt)
    # 只看 by_role 那一行：整份文件里 `rss_peak_mb=1540` 也会被 ROLE_RE 误抓成角色 "s"
    roles = {}
    for line in txt.splitlines():
        if "by_role" not in line:
            continue
        for r, mb in ROLE_RE.findall(line):
            roles[r] = max(roles.get(r, 0), int(mb))
    return {"arm": name, "model": model, "samples": len(numbers),
            "median_from_samples": round(statistics.median(numbers), 1) if numbers else None,
            "p95_from_samples": round(statistics.quantiles(numbers, n=20)[18], 1) if len(numbers) > 20 else None,
            "max_from_samples": max(numbers) if numbers else None,
            "summary": summary, "seconds_over": over.group(1) if over else None,
            "roles_peak_seen": roles}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--arms", required=True,
                    help="逗号分隔的 name=model[?query]（model 相对 temp/playback-test，"
                         "query 用于 &anim=0 这类同模型不同行为的臂）")
    ap.add_argument("--seconds", type=int, default=200)
    ap.add_argument("--playms", type=int, default=240000)
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--report", default=str(OUT / "rss-ab.json"))
    args = ap.parse_args()

    port = args.port or free_port()
    gw = subprocess.Popen([PY, "scripts/preview_gateway.py", "--port", str(port),
                           "--serve-dir", "temp",
                           "--model", str(OUT / "model-proxy-a.json")],
                          cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = []
    try:
        if not wait_port(port):
            print("gateway 没起来", file=sys.stderr)
            return 2
        for spec in args.arms.split(","):
            name, model = [x.strip() for x in spec.split("=", 1)]
            tag = re.sub(r"[^a-z0-9]+", "-", name.lower())
            print(f"  arm {name} ({model}) {args.seconds}s ...", flush=True)
            out.append(run_arm(name, model, port, args.seconds, args.playms, tag))
    finally:
        gw.terminate()
        try:
            gw.wait(timeout=10)
        except subprocess.TimeoutExpired:
            gw.kill()

    print("-" * 70)
    for r in out:
        if r.get("error"):
            print(f"  {r['arm']:<14} ERROR {r['error']}")
            continue
        s = r["summary"]
        print(f"  {r['arm']:<14} 样本={r['samples']:>4} "
              f"median={r['median_from_samples'] or s.get('rss_median_mb')} "
              f"p95={r['p95_from_samples']} max={r['max_from_samples'] or s.get('rss_peak_mb')} "
              f"越线={r['seconds_over']} 角色峰值={r['roles_peak_seen']}")
    Path(args.report).write_text(json.dumps({"seconds": args.seconds, "playms": args.playms,
                                             "arms": out}, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    print(f"report -> {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
