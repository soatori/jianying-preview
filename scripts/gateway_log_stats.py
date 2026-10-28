"""从网关日志算闭区间取块的**复用率**与每请求耗时，给 SP-04 一个可复跑的读数。

为什么需要它：F-054 把「keep-alive / 多端口」从优化项升级成自建管线的**前置条件**（SP-04），
但 P-08 的对照只有**单源**，而且结论是反的——5.2 GB 的 NAS 片上 keep-alive 反而比每请求新建连接
慢 7.90 ms/请求（20.87 vs 12.96），本地片差 ≤0.21 ms。所以「前置条件」这句话现在既没在
**真草稿的播放负载**上验过，也没和网关实际的复用行为对过号。
网关每条请求都记了 `reused=yes/no`，这就够算复用率了 —— 不用新加仪器。

口径纪律：
  - 只数**播放期**的日志行（时间戳落在给定窗口内），否则会把别的跑数混进来；
  - 复用率按请求数计，不按字节；每请求耗时要分「复用 / 新建」两组分别报，
    因为 P-08 说的就是这个差；
  - NAS 与本地要分开：P-08 的结论方向完全取决于文件在哪。日志里没有挂载点信息，
    所以按 media id 的路径前缀判（`X:/` 视为 NAS）。

用法:
    python scripts/gateway_log_stats.py [--log temp/playback-test/gateway.log]
                                        [--since-minutes 12] [--top 8]
"""
from __future__ import annotations

import argparse
import re
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
# Windows 控制台是 GBK：读数里带中文/箭头/替换符时 print 会在最后一步抛错，
# 把已经算完的结果整个吞掉（本轮自己的统计工具就栽过一次）。只改错误处理策略，不改编码。
try:
    sys.stdout.reconfigure(errors="replace")     # type: ignore[attr-defined]
    sys.stderr.reconfigure(errors="replace")     # type: ignore[attr-defined]
except Exception:                                 # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parents[1]
# 网关的 `_note` 只写 `HH:MM:SS ...`（无日期），所以窗口是按**当天时刻**回推的。
LINE_RE = re.compile(r"^(?P<ts>\d{2}:\d{2}:\d{2})\s+(?P<rest>.*)$")
REQ_RE = re.compile(
    r"(?P<status>\d{3})\s+(?P<verb>GET|HEAD)\s+id=(?P<id>[^\s]+)\s+range=(?P<range>\S+)"
    r".*?file=(?P<file>[^\s]+)\s+reused=(?P<reused>yes|no)"
    r"(?:\s+ms=(?P<ms>[\d.]+))?")
DUR_RE = re.compile(r"dur_ms=(?P<ms>[\d.]+)")
NAS_RE = re.compile(r"^(X:|Z:|x:|z:)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--log", default=str(ROOT / "temp/playback-test/gateway.log"))
    ap.add_argument("--since-minutes", type=float, default=12.0,
                    help="只统计最近这段时间内的行（0 = 全量）")
    ap.add_argument("--top", type=int, default=8)
    args = ap.parse_args()

    log = Path(args.log)
    if not log.is_file():
        print(f"没有日志 {log}", file=sys.stderr)
        return 2
    cutoff = None
    if args.since_minutes:
        cutoff = time.time() - args.since_minutes * 60
    per_media = defaultdict(lambda: {"n": 0, "reused": 0, "bytes": 0, "ms_re": [], "ms_new": []})
    total = {"n": 0, "reused": 0, "matched": 0, "ms_re": [], "ms_new": [], "lines": 0}
    src_of = {}

    with log.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            total["lines"] += 1
            m = LINE_RE.match(line)
            if not m:
                continue
            if cutoff:
                try:
                    st = time.strptime(m.group("ts"), "%H:%M:%S")
                except ValueError:
                    continue
                now = time.localtime()
                ts = time.mktime((now.tm_year, now.tm_mon, now.tm_mday,
                                  st.tm_hour, st.tm_min, st.tm_sec, 0, 0, -1))
                if ts > time.time() + 3600:      # 跨到昨天的时间戳
                    ts -= 86400
                if ts < cutoff:
                    continue
            rest = m.group("rest")
            r = REQ_RE.search(rest)
            if not r:
                continue
            total["matched"] += 1
            mid = r.group("file") or r.group("id")
            entry = per_media[mid]
            entry["n"] += 1
            reused = r.group("reused") == "yes"
            entry["reused"] += 1 if reused else 0
            total["reused"] += 1 if reused else 0
            dm = DUR_RE.search(rest) or (
                re.search(r"ms=([\d.]+)", rest) if 'ms=' in rest else None)
            if dm:
                (entry["ms_re"] if reused else entry["ms_new"]).append(float(dm.group("ms")))
                (total["ms_re"] if reused else total["ms_new"]).append(float(dm.group("ms")))

    if not total["matched"]:
        print("窗口内没有匹配到请求行（检查 --since-minutes 与日志格式）")
        return 2
    n = total["matched"]
    print(f"扫描 {total['lines']} 行，匹配请求 {n} 条"
          f"（窗口 = 最近 {args.since_minutes or '全量'} 分钟）")
    print(f"复用率 {100.0 * total['reused'] / n:.1f}%  "
          f"每请求耗时中位：复用 {statistics.median(total['ms_re']) if total['ms_re'] else float('nan'):.2f} ms "
          f"vs 新建 {statistics.median(total['ms_new']) if total['ms_new'] else float('nan'):.2f} ms")
    print(f"按 media 前 {args.top}（n / 复用率 / 两组耗时中位）:")
    rows = sorted(per_media.items(), key=lambda kv: -kv[1]["n"])[:args.top]
    for mid, e in rows:
        re_ms = statistics.median(e["ms_re"]) if e["ms_re"] else float("nan")
        nw_ms = statistics.median(e["ms_new"]) if e["ms_new"] else float("nan")
        tag = "NAS" if NAS_RE.match(mid or "") else "本地/代理"
        print(f"  {tag:<6} {str(mid)[:38]:<40} n={e['n']:>6} reuse={100.0*e['reused']/e['n']:5.1f}% "
              f"复用={re_ms:6.2f}ms 新建={nw_ms:6.2f}ms")
    print("注：media id 是不透明摘要，路径前缀不在 id 里 ⇒ NAS/本地要由 media-manifest.json 回查，"
          "别把这里的 local? 当成结论。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
