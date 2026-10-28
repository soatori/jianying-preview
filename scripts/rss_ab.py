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


def drift_from(txt: str) -> dict | None:
    """末 60 s 中位 − 首 60 s 中位。soak 自带的 `growth_mb_over_window` 不能用：
    它是「末值 − 首值」，而首值永远是 Chrome 还没起 renderer 时的 5 MB ⇒ 每条臂都"增长 ~1000 MB"。"""
    ps = re.search(r"per_second:(.+)", txt)
    if not ps:
        return None
    by_sec: dict[int, int] = {}
    for s, v in re.findall(r"(\d+)s=(\d+)MB", ps.group(1)):
        by_sec[int(s)] = int(v)                      # 采样器一秒可能取两次，后者覆盖
    secs = sorted(by_sec)
    if len(secs) < 120:
        return None
    head = [by_sec[s] for s in secs if s < 60]
    tail = [by_sec[s] for s in secs if s >= secs[-1] - 59]
    vals = [by_sec[s] for s in secs]
    return {"n": len(vals), "span_s": secs[-1],
            "first60_median": statistics.median(head),
            "last60_median": statistics.median(tail),
            "drift_mb": statistics.median(tail) - statistics.median(head),
            "p95_mb": statistics.quantiles(vals, n=20)[18]}


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
    # browser_soak 现在只往这个文件里写**汇总行**（`wall_s=… samples=…` + rss_* + by_role），
    # 不再写逐秒序列 ⇒ 老的逐秒正则永远匹配不到东西，于是 `samples=0` 而 median 悄悄回退到
    # 汇总值——**读数看起来正常，其实没人检查过这轮跑了多久**。改成直接读汇总字段并**核对时长**：
    # 上一版就是这样把一次 38 s 的跑当成 600 s 报出来的（`--playms` 小于 `--seconds` 时，
    # 页面放完一遍就结束，soak 跟着结束，而 `--seconds` 只是上限不是下限）。
    got = {}
    for k in ("wall_s", "samples"):
        m = re.search(rf"{k}=(\d+(?:\.\d+)?)", txt)
        if m:
            got[k] = float(m.group(1))
    summary = {}
    for k in ("rss_first_mb", "rss_mean_mb", "rss_peak_mb", "rss_last_mb", "rss_median_mb"):
        m = re.search(rf"{k}=(\d+)", txt)
        if m:
            summary[k] = int(m.group(1))
    over = re.search(r"seconds_over_2048=(\S+)", txt)
    wall = got.get("wall_s", 0.0)
    short = wall < 0.8 * seconds
    # 漂移才是 600 s 这一档真正要量的东西。soak 自带的 `growth_mb_over_window` **不能用**：
    # 它是「末值 − 首值」，而首值永远是 Chrome 还没起 renderer 时的 5 MB，于是每条臂都"增长 ~1000 MB"。
    # 这里改成**末 60 s 中位 − 首 60 s 中位**（都取稳定窗口），并一并报 p95。
    drift = drift_from(txt)
    # 只看 by_role 那一行：整份文件里 `rss_peak_mb=1540` 也会被 ROLE_RE 误抓成角色 "s"
    roles = {}
    for line in txt.splitlines():
        if "by_role" not in line:
            continue
        for r, mb in ROLE_RE.findall(line):
            roles[r] = max(roles.get(r, 0), int(mb))
    return {"arm": name, "model": model, "samples": int(got.get("samples", 0)),
            "wall_s": wall, "short": short, "drift": drift,
            "median_from_samples": None, "p95_from_samples": None, "max_from_samples": None,
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
    bad = []
    for r in out:
        if r.get("error"):
            print(f"  {r['arm']:<14} ERROR {r['error']}")
            bad.append(r["arm"])
            continue
        s = r["summary"]
        flag = "  <-- 时长不足，这条臂作废" if r.get("short") else ""
        dr = r.get("drift") or {}
        print(f"  {r['arm']:<14} 样本={r['samples']:>4} 实跑={r.get('wall_s', 0):.0f}s"
              f"/{args.seconds}s median={s.get('rss_median_mb')} mean={s.get('rss_mean_mb')} "
              f"peak={s.get('rss_peak_mb')} last={s.get('rss_last_mb')} "
              f"漂移={dr.get('drift_mb', '?')}MB(首60s {dr.get('first60_median','?')}→末60s "
              f"{dr.get('last60_median','?')}) p95={dr.get('p95_mb','?')} "
              f"越线={r['seconds_over']} 角色峰值={r['roles_peak_seen']}{flag}")
        if r.get("short"):
            bad.append(r["arm"])
    if bad:
        # 上一版就是这里没喊：`--playms` 比 `--seconds` 小时页面放完一遍就收工，
        # 38 s 的数据被当成 600 s 报出来，median/peak 全都像真的。
        print(f"  ! 无效臂：{bad} —— 需要 --playms >= --seconds*1000（或让页面真循环）")
    Path(args.report).write_text(json.dumps({"seconds": args.seconds, "playms": args.playms,
                                             "arms": out}, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    print(f"report -> {args.report}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
