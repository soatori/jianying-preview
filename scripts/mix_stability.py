"""U-86 的判决实验：同一模型**整条时间线确定性播放**（无 seek）重复 N 次，看混音读数稳不稳。

为什么必须设计实验而不是继续翻日志：54 个历史跑数里我能想到并检过的 14 个候选字段
（`chunks/nodes/loudness_applied/fades_applied/pool/requests/pump.dropped/pump.live/decoded/
composited_fps/realtime_factor/first_frame_ms/seek_n/seek_median_ms`）按「有满刻度窗 / 没有」
分组后**全部重叠**，连 `source_seconds_advanced` 两组中位都是 9.98 s —— 观察性数据判不了这条，
继续找相关只会在共同因上再错一次（上一轮 `loudness_applied` 就是这么翻车的）。

单变量在这里是什么：**测量窗口本身**。电池的 10 s + 12 次 seek 意味着每次跑实际覆盖的时间线
子集不同，所以 `peak_fs` 若随覆盖变化就是**采样口径问题**，不是混音竞态；
判据因此改成两条分支：
  - `playms >= 时间线长度` 且 `seeks=0` 时 `peak_fs` 重复间极差 <= 0.02 ⇒
    **离散来自 seek 覆盖**，U-86 结案，且混音判据必须按全时间线测（写进文档的口径）；
  - 仍然飘 ⇒ 真是混音侧竞态，转给 `streamFor`/节点归属那条线（P-18/P-22 同族）去查。

用法:
    python scripts/mix_stability.py [--repeats 3] [--media-model temp/playback-test/model-proxy-a.json]
                                    [--port 8792] [--report temp/playback-test/mix-stability.json]
"""
from __future__ import annotations

import argparse
import json
import socket
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

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "temp" / "playback-test"
PY = sys.executable


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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--model", default=str(OUT / "model-check.json"))
    ap.add_argument("--media-model", default=str(OUT / "model-proxy-a.json"))
    ap.add_argument("--player", default="player.html")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--report", default=str(OUT / "mix-stability.json"))
    args = ap.parse_args()

    media_model = Path(args.media_model)
    model = json.loads(Path(args.model).read_text(encoding="utf-8-sig"))
    dur_s = model["duration_us"] / 1e6
    playms = int((dur_s + 1.5) * 1000)          # 覆盖整条时间线并留收尾
    port = args.port or free_port()
    report = OUT / "report-mixstab.jsonl"
    if report.exists():
        report.unlink()

    gw = subprocess.Popen([PY, "scripts/preview_gateway.py", "--port", str(port),
                           "--serve-dir", "temp", "--model", str(media_model)],
                          cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rows = []
    try:
        if not wait_port(port):
            print("gateway 没起来", file=sys.stderr)
            return 2
        url = (f"http://127.0.0.1:{port}/playback-test/{args.player}"
               f"?autostart=1&model={media_model.name}&playms={playms}&seeks=0&fps=30"
               f"&qmax=4&pool=4&loop=0&tag=mixstab")
        for i in range(args.repeats):
            before = len(report.read_text(encoding="utf-8").splitlines()) if report.exists() else 0
            subprocess.run([PY, "scripts/browser_soak.py", "--url", url,
                            "--seconds", str(int(playms / 1000) + 30),
                            "--report", str(report.relative_to(ROOT)), "--tag", "mixstab",
                            "--timeout", str(int(playms / 1000) + 60)],
                           cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
            if not report.exists():
                # 网关按**请求体里的 tag** 决定落哪个文件，不是 --tag/--report；
                # 页面 tag 走 ?tag= 参数（本轮之前它硬编码 'playback'，所以这里永远等不到文件）。
                rows.append({"run": i, "error": f"{report.name} 不存在：页面 POST 的 tag 没对上"
                                                f"（检查 URL 里的 &tag= 与 player.html 的 tag 参数化）"})
                break
            lines = report.read_text(encoding="utf-8").splitlines()[before:]
            if not lines:
                rows.append({"run": i, "error": "报告文件在，但这次跑没追加新行（浏览器或网关没活到上报）"})
                continue
            r = json.loads(lines[-1])
            a = (r.get("play") or {}).get("audio") or {}
            pl = r.get("play") or {}
            rows.append({"run": i, "peak_fs": a.get("peak_fs"),
                         "clipped_windows": a.get("clipped_windows"),
                         "peak_rms": a.get("peak_rms"), "chunks": a.get("chunks"),
                         "nodes": a.get("nodes"), "loudness_applied": a.get("loudness_applied"),
                         "fades_applied": a.get("fades_applied"),
                         "sample_rate": a.get("sample_rate"),
                         "audio_errors": a.get("audio_errors"),
                         "rms_max": max(a.get("rms_windows") or [0]),
                         "rms_n": len(a.get("rms_windows") or []),
                         "sec_adv": pl.get("source_seconds_advanced"),
                         "fps": pl.get("composited_fps"), "rt": pl.get("realtime_factor"),
                         "dropped": (pl.get("pump") or {}).get("dropped"),
                         "requests": pl.get("requests"),
                         "black_streaks": len(r.get("black_streaks") or []),
                         "errors": len(r.get("errors") or [])})
            d = rows[-1]
            print(f"  run {i}: peak_fs={d['peak_fs']} clipped={d['clipped_windows']} "
                  f"chunks={d['chunks']} nodes={d['nodes']} sec_adv={d['sec_adv']} "
                  f"fps={d['fps']} rt={d['rt']} errors={d['errors']} black={d['black_streaks']}",
                  flush=True)
    finally:
        gw.terminate()
        try:
            gw.wait(timeout=10)
        except subprocess.TimeoutExpired:
            gw.kill()

    vals = [r["peak_fs"] for r in rows if isinstance(r.get("peak_fs"), (int, float))]
    if len(vals) < 2:
        print("有效读数不足 2 个，判不了")
        Path(args.report).write_text(json.dumps({"playms": playms, "rows": rows},
                                                 ensure_ascii=False, indent=1), encoding="utf-8")
        return 2
    spread = max(vals) - min(vals)
    deterministic = spread <= 0.02
    print("-" * 66)
    print(f"整条时间线（playms={playms} ms, seeks=0）{len(vals)} 次："
          f"peak_fs {sorted(round(v, 4) for v in vals)}  极差 {spread:.4f}")
    print(f"判定：{'确定性 —— 离散来自 seek 覆盖，混音判据必须按全时间线测' if deterministic else '仍然飘 —— 是混音侧竞态，转 P-18/P-22 那条线'}")
    Path(args.report).write_text(json.dumps(
        {"playms": playms, "duration_s": round(dur_s, 3), "repeats": len(rows),
         "peak_fs": vals, "spread": round(spread, 4), "deterministic": deterministic,
         "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"report -> {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
