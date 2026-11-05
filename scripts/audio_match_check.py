"""音频侧的"匹配成片"判据层：**段落电平偏差（相对）+ 交付完整性**，判据线能被证伪。

为什么要这一层：`L5` 判的是页面自报的混音器健康，录音那条链（`audio_capture_check.py` →
网关 `/wave`）至今**只有读数、没有判据**。而 100 ms 包络相关已经被自己的对照否掉
（同一条混音录两次只有 0.344，`evidence/playback-log.md` P-127），所以不能拿相关度定线。

两条能落地的判据（口径来自 2026-10-28 定案：削顶照抄成片、不设 ≤0 dBFS 线、不写"电平已对齐"）：

1. **交付完整性**：成片里响着的段，我方也必须响（`> --silent-db`）。
   洞 = 成片有、我们没有 ⇒ 这是"音频匹配成片"最硬的一条，且与律/增益无关。
2. **段落电平偏差（只看相对）**：Δ_i = 我方 − 成片（dB），**判的是 `max|Δ_i − median Δ|`**，
   容差取"同一份内容自己录两次"散布的实测值（现读 4.41 dB，可用 `--tol` 覆盖）。
   那条整体偏移（现读约 −8.4 dB）**只报数不判**——它在律/增益侧（U-88），
   把它写进判据就等于用一条永远过不了或永远无意义线。

`--selftest` 用**造出来的负样本**证明这两条会转红（拿成片自己当"我方"⇒ Δ=0 必绿；
再把其中一段消音 ⇒ 两条都必须红）。守卫没牙就别声称有守卫。

用法：
  python scripts/audio_match_check.py --capture temp/playback-test/preview-audio-xxx.wav \
      --export-audio temp/playback-test/oracle-export.wav \
      --control temp/playback-test/preview-audio-yyy.wav \
      --media-model temp/playback-test/model-proxy-g16.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

try:                                            # Windows 控制台是 GBK，读数里带中文会在最后一步抛错
    sys.stdout.reconfigure(errors="replace")    # type: ignore[attr-defined]
except Exception:                               # noqa: BLE001
    pass

SELF_Spread_DB = 4.41           # P-127：同一条混音录两次，逐段 Δ 的自身散布 p95


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        rate, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        raw = np.frombuffer(w.readframes(n), dtype="<i2")
    x = raw.reshape(-1, ch).mean(axis=1) if ch > 1 else raw
    return x.astype(np.float64) / 32768.0, rate


def db(x: np.ndarray) -> float:
    if x.size == 0:
        return -120.0
    r = float(np.sqrt(np.mean(np.square(x, dtype=np.float64))) if x.size else 0.0)
    return -120.0 if r <= 0 else max(-120.0, 20.0 * np.log10(r))


def window(x: np.ndarray, rate: int, t0: float, t1: float) -> np.ndarray:
    a, b = max(0, int(t0 * rate)), min(x.size, int(t1 * rate))
    return x[a:b] if b > a else np.array([], dtype=np.float64)


def audio_segments(model_path: Path, min_len: float) -> list[tuple[str, float, float]]:
    """模型里带音频的段时间窗（秒）。音频轨 + 自带声的段都算。"""
    m = json.loads(model_path.read_text(encoding="utf-8"))
    out: list[tuple[str, float, float]] = []
    for tr in m.get("tracks") or []:
        for s in tr.get("segments") or []:
            tgt = s.get("target") or {}
            t0 = float(tgt.get("start_us", 0)) / 1e6
            t1 = t0 + float(tgt.get("duration_us", 0)) / 1e6
            if t1 - t0 < min_len:
                continue
            kind = tr.get("type") or ""
            # 模型里没有 has_audio 这个字段；段带不带声看 `audio` 对象（视频段自带声）或轨型。
            if (kind == "audio" or s.get("audio")) and not s.get("muted"):
                out.append((str(s.get("id") or "?")[:8], t0, t1))
    return out


def measure(ours: np.ndarray, our_rate: int, exp: np.ndarray, exp_rate: int,
            segs: list[tuple[str, float, float]], silent_db: float):
    rows = []
    for sid, t0, t1 in segs:
        e, o = db(window(exp, exp_rate, t0, t1)), db(window(ours, our_rate, t0, t1))
        rows.append({"id": sid, "t0": round(float(t0), 3), "t1": round(float(t1), 3),
                     "export_db": round(float(e), 2), "ours_db": round(float(o), 2),
                     "delta_db": round(float(o - e), 2),
                     "export_audible": bool(e > silent_db), "ours_audible": bool(o > silent_db)})
    live = [r for r in rows if r["export_audible"]]
    missing = [r for r in live if not r["ours_audible"]]
    deltas = np.array([r["delta_db"] for r in live], dtype=np.float64)
    med = float(np.median(deltas)) if deltas.size else 0.0
    rel = float(np.max(np.abs(deltas - med))) if deltas.size else 0.0
    duty_exp = sum(1 for i in range(0, exp.size - 1, exp_rate // 10)
                   if db(exp[i:i + exp_rate // 10]) > silent_db)
    duty_our = sum(1 for i in range(0, ours.size - 1, our_rate // 10)
                   if db(ours[i:i + our_rate // 10]) > silent_db)
    return rows, live, missing, med, rel, duty_exp, duty_our


def judge(args) -> int:
    ours, our_rate = read_wav(Path(args.capture))
    exp, exp_rate = read_wav(Path(args.export_audio))
    segs = audio_segments(Path(args.media_model), args.min_seg)
    tol = args.tol if args.tol > 0 else SELF_Spread_DB
    if args.control:
        ctl, ctl_rate = read_wav(Path(args.control))
        _, _, _, _, ctl_rel, _, _ = measure(ctl, ctl_rate, ours, our_rate, segs, args.silent_db)
        tol = max(tol, ctl_rel)          # 容差不许低于"同一内容自己录两次"的散布
    rows, live, missing, med, rel, dexp, dour = measure(ours, our_rate, exp, exp_rate, segs,
                                                       args.silent_db)
    duty = (dour / dexp) if dexp else 1.0
    ok = (not missing) and (rel <= tol)
    print(f"{'PASS' if ok else 'FAIL'}  L29 audio vs export (delivery + relative level)   "
          f"成片有声段 {len(live)}/{len(rows)}，我方缺 {len(missing)} 段；"
          f"相对散布 max|Δ−中位| = {rel:.2f} dB（线 ≤{tol:.2f}，来自同内容自比）；"
          f"整体偏移 {med:+.2f} dB（只报数，不判——律/增益侧，见 U-88）；"
          f"占空比 {duty:.3f}（我方/成片响窗比）")
    if missing:
        print("   缺的段：" + "; ".join(f"{r['id']}@{r['t0']}–{r['t1']} 成片 {r['export_db']} "
                                        f"我方 {r['ours_db']}" for r in missing[:6]))
    if rel > tol and live:
        worst = max(live, key=lambda r: abs(r["delta_db"] - med))
        print(f"   偏得最多的段：{worst['id']}@{worst['t0']}–{worst['t1']} Δ={worst['delta_db']} "
              f"（相对 {abs(worst['delta_db'] - med):.2f} dB）")
    if args.dump:
        Path(args.dump).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if ok else 1


def selftest(args) -> int:
    """正例＝成片自己（Δ≡0）；反例＝把其中一段消音 ⇒ 两条判据都要红。"""
    exp, exp_rate = read_wav(Path(args.export_audio))
    segs = audio_segments(Path(args.media_model), args.min_seg)
    tol = args.tol if args.tol > 0 else SELF_Spread_DB
    bad = []
    if judge_of(exp, exp_rate, exp, exp_rate, segs, args.silent_db, tol)["fail_lines"]:
        bad.append("正例（同一份内容自比）竟然红 ⇒ 判据在没有误差时也报错")
    mut = exp.copy()
    pick = next((s for s in segs if s[2] - s[1] >= 1.0), segs[0])
    a, b = int(pick[1] * exp_rate), int(pick[2] * exp_rate)
    mut[a:b] = 0.0
    r = judge_of(mut, exp_rate, exp, exp_rate, segs, args.silent_db, tol)
    if not r["fail_lines"]:
        bad.append("反例（一段消音）还是绿的 ⇒ 守卫没牙")
    print(("SELFTEST PASS：正例绿、一段消音转红（缺段 %d、相对散布 %.2f dB）"
           % (len(r["missing"]), r["rel"])) if not bad else
           "SELFTEST FAIL：" + "；".join(bad))
    return 0 if not bad else 2


def judge_of(ours, our_rate, exp, exp_rate, segs, silent_db, tol):
    _, live, missing, med, rel, dexp, dour = measure(ours, our_rate, exp, exp_rate, segs, silent_db)
    return {"missing": missing, "rel": rel, "med": med,
            "fail_lines": [k for k, v in (("缺段", missing), ("相对散布", rel > tol)) if v]}


def export_wav(mp4: Path, out: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp4),
                    "-vn", "-ac", "1", "-ar", "48000", str(out)], check=True)
    print(f"成片音轨已抽到 {out}（48 kHz 单声道）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", default="", help="页内录音（网关 /wave 落的那份）")
    ap.add_argument("--export-audio", default="temp/playback-test/oracle-export.wav")
    ap.add_argument("--export-mp4", default="", help="给这个就从成片抽音轨再判")
    ap.add_argument("--control", default="", help="同一条混音的第二份录音（用来定容差下限）")
    ap.add_argument("--media-model", default="temp/playback-test/model-proxy-g16.json")
    ap.add_argument("--tol", type=float, default=0.0, help="0＝用实测自身散布下限 4.41 dB")
    ap.add_argument("--silent-db", type=float, default=-60.0)
    ap.add_argument("--min-seg", type=float, default=0.5, help="短于此的段不参与（避免窗口边噪）")
    ap.add_argument("--dump", default="")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.export_mp4 and not Path(args.export_audio).is_file():
        export_wav(Path(args.export_mp4), Path(args.export_audio))
    if args.selftest:
        return selftest(args)
    if not (args.capture and Path(args.capture).is_file()):
        print("没有 --capture（先跑一次带音频录音的会话：audio_capture_check.py）")
        return 3
    return judge(args)


if __name__ == "__main__":
    sys.exit(main())
