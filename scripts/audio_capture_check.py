"""判**录下来的预览音频**，不判自报数字。

为什么要有这条：门里的 L5 全部来自页面自报（`peak_fs`/`rms_windows`/`clipped_windows`），
而那些数是用 analyser 在 JS 循环里**轮询**取的——循环一冻几百毫秒，缺席的正是这些采样。
用户说"音频听起来很奇怪"时，自报通道是**被怀疑对象的一部分**，不能当证人口述。
这里读的是浏览器录下来的连续波形（player.html 的 `startCapture` → 网关 `/wave`），
对照物是同一条时间线的原生成片音轨（`JY_ORACLE_MP4` 指向的成片）。

只报数不判绿：这些判据还没有负样本 fixture（同一台机器上把某段真做成静音再验仪器必须变红），
按规约「先造反例再接判据」，先出读数。

用法：
    python scripts/audio_capture_check.py                     # 取最新的 preview-audio-*.wav
    python scripts/audio_capture_check.py --wav temp/playback-test/preview-audio-preview-run.wav
"""
from __future__ import annotations

import argparse
import os
import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:                                 # noqa: BLE001
    pass

OUT = Path(__file__).resolve().parents[1] / "temp" / "playback-test"
MP4 = os.environ.get("JY_ORACLE_MP4", "")     # 成片 oracle：本机路径，不写死在源码里


def read_wav(p: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(p), "rb") as w:
        n, rate, ch = w.getnframes(), w.getframerate(), w.getnchannels()
        raw = np.frombuffer(w.readframes(n), dtype="<i2")
    x = raw.astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, rate


def decode_mp4_mono(p: str, rate: int) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error", "-i", p, "-ac", "1", "-ar", str(rate),
           "-f", "f32le", "-"]
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 解码失败: {r.stderr[-200:].decode('utf-8', 'replace')}")
    return np.frombuffer(r.stdout, dtype="<f4")


def rms_windows(x: np.ndarray, rate: int, win_ms: int) -> np.ndarray:
    w = max(1, int(rate * win_ms / 1000))
    n = len(x) // w
    seg = x[:n * w].reshape(n, w)
    return np.sqrt((seg ** 2).mean(axis=1))


def dbfs(v: float) -> float:
    return -999.0 if v <= 0 else 20.0 * np.log10(v)


def describe(name: str, x: np.ndarray, rate: int, win_ms: int) -> dict:
    wins = rms_windows(x, rate, win_ms)
    d = np.abs(np.diff(x))
    # 静音段：连续窗 RMS 低于 -80 dBFS。只在这里数"段"，不数窗，避免把淡入淡出读成掉线。
    quiet = wins < 10 ** (-80 / 20)
    runs, start = [], None
    for i, q in enumerate(quiet):
        if q and start is None:
            start = i
        elif not q and start is not None:
            runs.append((start * win_ms / 1000.0, (i - start) * win_ms / 1000.0))
            start = None
    if start is not None:
        runs.append((start * win_ms / 1000.0, (len(quiet) - start) * win_ms / 1000.0))
    jumps = np.nonzero(d > 0.5)[0]
    out = {"samples": int(len(x)), "seconds": round(len(x) / rate, 2), "rate": rate,
           "peak": round(float(np.abs(x).max()), 4),
           "peak_dbfs": round(dbfs(float(np.abs(x).max())), 2),
           "clipped_samples": int((np.abs(x) >= 0.9995).sum()),
           "win_dbfs": {"max": round(dbfs(float(wins.max())), 2),
                        "median": round(dbfs(float(np.median(wins))), 2)},
           "silent_runs": [[round(a, 2), round(b, 2)] for a, b in runs if b >= win_ms / 1000.0],
           "silent_total_s": round(sum(b for _, b in runs), 2),
           "jump_gt_0.5": int(len(jumps)),
           "jump_first_s": [round(int(i) / rate, 3) for i in jumps[:8]]}
    print(f"AUDIO {name}: " + json.dumps(out, ensure_ascii=False))
    return out


def missing_holes(x: np.ndarray, e: np.ndarray, rate: int, win_ms: int = 100) -> dict:
    """成片有声、我方静音的区间。这就是"听起来一顿一顿"的音频侧定量口径。

    注意单位：窗数 ≠ 秒。上一版把 `Σ秒 / 窗数` 当百分比打印，把 61.8% 印成 6.2%——
    分母必须乘回窗长。
    """
    n = int(rate * win_ms / 1000)
    def env(a):
        k = len(a) // n
        s = np.sqrt((a[:k * n].reshape(k, n) ** 2).mean(axis=1))
        return 20 * np.log10(np.maximum(s, 1e-9))
    E, C = env(e), env(x)
    m = min(len(E), len(C))
    E, C = E[:m], C[:m]
    miss = (E > -40) & (C < -50)
    runs, s0 = [], None
    for i, h in enumerate(miss):
        if h and s0 is None:
            s0 = i
        elif not h and s0 is not None:
            runs.append((s0 * win_ms / 1000.0, (i - s0) * win_ms / 1000.0))
            s0 = None
    if s0 is not None:
        runs.append((s0 * win_ms / 1000.0, (m - s0) * win_ms / 1000.0))
    total = sum(b for _, b in runs)
    span = m * win_ms / 1000.0
    out = {"holes": len(runs), "hole_seconds": round(total, 2), "timeline_seconds": round(span, 2),
           "hole_share_pct": round(100.0 * total / max(span, 1e-9), 1),
           "audible_duty_pct": round(100.0 * float((C > -40).mean()), 1),
           "hist_len_s": sorted({round(b, 1) for _, b in runs})[:12],
           "first": [[round(a, 1), round(b, 1)] for a, b in runs[:12]]}
    print(f"AUDIO HOLES export_audible_we_silent n={out['holes']} "
          f"seconds={out['hole_seconds']}/{out['timeline_seconds']} "
          f"share={out['hole_share_pct']}% duty={out['audible_duty_pct']}%")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--wav", default="")
    ap.add_argument("--mp4", default=MP4)
    ap.add_argument("--window-ms", type=int, default=500)
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()

    p = Path(args.wav) if args.wav else max(OUT.glob("preview-audio-*.wav"), default=None)
    if not p or not p.is_file():
        print("AUDIO no capture wav found (run the player with the tap; gateway writes "
              "temp/playback-test/preview-audio-<name>.wav)")
        return 2
    x, rate = read_wav(p)
    ours = describe("browser_capture", x, rate, args.window_ms)
    res = {"wav": str(p), "capture": ours, "export": None}
    try:
        e = decode_mp4_mono(args.mp4, rate)
        res["export"] = describe("native_export", e, rate, args.window_ms)
        res["holes"] = missing_holes(x, e, rate)
        n = min(len(x), len(e))
        c = float(np.corrcoef(x[:n], e[:n])[0, 1])
        # 逐样本相关在这里是**错的仪器**：预览与成片是两条独立编码的 AAC/PCM 链（不同编解码、
        # 不同起始偏移），样本对不上是常态，读 0.005 不能说"内容不对"。能说的是"响度轮廓像不像"，
        # 所以把两边都压成 100 ms 的 RMS 包络，再在 ±10 s 里搜滞后——包络相关 + 最佳滞后才是
        # "预览的音频跟着成片走吗"这个问题该有的量。
        env_ms = 100
        ew, cw = rms_windows(e, rate, env_ms), rms_windows(x, rate, env_ms)
        el = 20 * np.log10(np.maximum(ew, 1e-6))          # dBFS 域比较，不受个别峰值支配
        cl = 20 * np.log10(np.maximum(cw, 1e-6))
        lags, best = {}, None
        for ms in range(-10000, 10001, 500):
            k = int(ms * rate / 1000 / (rate * env_ms / 1000))   # 以包络窗为单位
            if k >= 0:
                a, b = cl[k:], el[:len(cl) - k] if k else el
            else:
                a, b = cl[:k], el[-k:]
            m = min(len(a), len(b))
            if m < 50:
                continue
            cc = float(np.corrcoef(a[:m], b[:m])[0, 1])
            lags[ms] = round(cc, 4)
            if best is None or cc > best[1]:
                best = (ms, cc)
        res["sample_corr"] = round(c, 4)
        res["envelope_corr_at_lag_ms"] = lags
        res["envelope_best_lag_ms"], res["envelope_best_corr"] = best[0], round(best[1], 4)
        print(f"AUDIO 包络相关(100 ms 窗，dBFS 域) 最佳滞后 {best[0]}ms corr={best[1]:.4f}"
              f"；逐样本 corr={c:.4f}（只作观测，这条链不同编码，不能当判据）")
        # 削顶要指名口径：ffmpeg 解 AAC 到 f32 **不夹取**，成片在浮点域本来就超满刻度；
        # 解到 s16 才永远读不到 >1.0。F-073 那句"成片 |x|≥0.9995 的样本 = 0"是后一口径，
        # 两口径都要报，否则会把解码器的夹取当成剪映的常态。
        i16 = np.abs(e) >= 0.99995
        print(f"AUDIO 成片削顶口径：float 域 |x|>=0.9995 共 {int((np.abs(e) >= 0.9995).sum())} 个，"
              f"夹取到 1.0 的 s16 边界 |x|>=0.99995 共 {int(i16.sum())} 个；"
              f"预览 float 峰 {round(float(np.abs(x).max()), 4)}")
        d1 = np.abs(np.diff(x))
        print(f"AUDIO 预览每跳 {round(len(np.nonzero(d1 > 0.3)[0]) / max(1, len(x) / rate), 2)} 处"
              f"（|Δ|>0.3），成片每跳 "
              f"{round(len(np.nonzero(np.abs(np.diff(e)) > 0.3)[0]) / max(1, len(e) / rate), 2)} 处")
    except Exception as ex:                       # noqa: BLE001
        print(f"AUDIO 成片侧没读到（不影响预览侧读数）: {ex}")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        tmp = args.report.with_suffix(args.report.suffix + ".tmp")
        tmp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(args.report)
        print(f"写出 {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
