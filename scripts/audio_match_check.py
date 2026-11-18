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


def _seg_audible(seg: dict, track_off: bool) -> bool:
    """静音律（判别式抄自厂商模型层，落点与 scripts/playback_model.py、player.html 三处同一条）：
    轨道 `attribute & MuteFlag(1)`；主视频轨的喇叭写的是草稿级 `config.video_mute`；
    片段 volume≈0（剪映把静音前的值留在 last_nonzero_volume）；原声被提取走时
    `extra_type_option & 1` 置位。判据方向反过来用：这里给分母，页面向同一条件让路。"""
    if track_off or seg.get("separated_audio"):
        return False
    return (seg.get("volume") if seg.get("volume") is not None else 1.0) > 0.002


def _media_playable(media: dict | None) -> bool:
    """和影像腿同一条可读性判据：只有**明确读不出容器**（加密的组合缓存）才算不能播。
    写成 `not container.get('readable')` 会把代理模型（readable 记在 media 上）全挡掉——
    那正是 2026-11-05 用户报「视频内的音频又漏了」的那条：一次电池 40 个音频作业 0 个来自视频段。"""
    if not media or not media.get("path") or not media.get("exists"):
        return False
    c = media.get("container")
    if isinstance(c, dict) and c.get("readable") is False:
        return False
    return True


def audio_segments(model_path: Path, min_len: float) -> list[tuple[str, float, float]]:
    """模型里**应当出声**的段时间窗（秒）：音频轨 + 视频段自带声（含组合子段，平移到父窗口）。

    原来只收「音频轨或有 `audio` 对象的段」，而视频自带声在模型里既没有 `audio` 对象也没有
    has_audio 字段 ⇒ 22 条素材段与 5 条组合子段从没进过分母，"成片有声段 19/19，我方缺 0 段"
    这句话当时并不覆盖口播（P-157）。
    """
    m = json.loads(model_path.read_text(encoding="utf-8-sig"))
    vmute = bool(m.get("video_mute"))
    out: list[tuple[str, float, float]] = []
    for tr in m.get("tracks") or []:
        kind = tr.get("type") or ""
        if kind not in ("audio", "video"):
            continue
        track_off = bool(tr.get("muted")) or (kind == "video" and bool(tr.get("is_main_video")) and vmute)
        for s in tr.get("segments") or []:
            tgt = s.get("target") or {}
            t0 = float(tgt.get("start_us", 0)) / 1e6
            t1 = t0 + float(tgt.get("duration_us", 0)) / 1e6
            sid = str(s.get("id") or "?")[:8]
            if not _seg_audible(s, track_off):
                continue
            if t1 - t0 >= min_len and (kind == "audio" or _media_playable(s.get("media"))):
                out.append((f"{'a' if kind == 'audio' else 'v'}:{sid}", t0, t1))
            comp = s.get("composite")
            if not comp or kind != "video":
                continue
            # 组合缓存自己读不出容器，声音来自子时间线的拍摄段——页面也是这么排的，
            # 所以分母必须一起收，否则口播缺了没人报（就是 P-157 的形状）。
            pv = s.get("volume") if s.get("volume") is not None else 1.0
            if pv <= 0.002:
                continue
            cvm = bool(comp.get("video_mute"))
            for ct in comp.get("tracks") or []:
                ckind = ct.get("type") or ""
                if ckind not in ("audio", "video"):
                    continue
                coff = bool(ct.get("muted")) or (ckind == "video" and bool(ct.get("is_main_video")) and cvm)
                for cs in ct.get("segments") or []:
                    if ckind == "video" and (cs.get("media") or {}).get("material_type") != "video":
                        continue          # 子时间线里的 .png 段不是音源
                    st = cs.get("target") or {}
                    c0 = float(st.get("start_us", 0)) / 1e6 + t0
                    c1 = c0 + float(st.get("duration_us", 0)) / 1e6
                    cv = cs.get("volume") if cs.get("volume") is not None else 1.0
                    if cv * pv <= 0.002:
                        continue
                    if c1 - c0 >= min_len and _seg_audible(cs, coff):
                        out.append((f"c:{str(cs.get('id') or '?')[:8]}@{sid}", c0, c1))
    return out


def measure(ours: np.ndarray, our_rate: int, exp: np.ndarray, exp_rate: int,
            segs: list[tuple[str, float, float]], silent_db: float,
            our_shift: float = 0.0):
    """`our_shift` **只挪我方那一侧**。两边一起挪量的还是同窗对齐（P-139 第一次就栽在这里，
    P-141 又在自己新加的参数上重犯过一次）——那测的不是原点，是随便挑的时间。"""
    rows = []
    for sid, t0, t1 in segs:
        e, o = db(window(exp, exp_rate, t0, t1)), db(window(ours, our_rate, t0 + our_shift, t1 + our_shift))
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


def estimate_shift(ours: np.ndarray, exp: np.ndarray, rate: int, span: float = 4.0,
                   step_ms: float = 5.0) -> tuple[float, float, float]:
    """整段波形的互相关找"录音零点对时间线"的偏移（P-140 的教训：页内 `ctx0` 是**音频时钟坐标**，
    不是时间线坐标；不登记就会把每个窗都错配 ~1.8 s，把仪器误差报成通路缺陷）。

    返回 (滞后秒, 峰, 候选中位)。峰/中位 太接近 1 就是"这条尺子没有分辨力"，调用方必须报出来——
    当年包络相关就是这么被"同一条混音自比只有 0.344"否掉的（P-127），所以这里带自比对照与分辨力读数。
    """
    n = 1
    while n < ours.size + exp.size:
        n *= 2
    O = np.fft.rfft(ours - ours.mean(), n)
    X = np.fft.rfft(exp - exp.mean(), n)
    c = np.fft.irfft(O * np.conj(X), n)
    den = float(np.linalg.norm(ours - ours.mean()) * np.linalg.norm(exp - exp.mean())) + 1e-12
    lim = int(span * rate)
    step = max(1, int(rate * step_ms / 1000.0))
    cand = [(L / rate, abs(float(c[L if L >= 0 else n + L])) / den) for L in range(-lim, lim + 1, step)]
    best = max(cand, key=lambda z: z[1])
    med = float(np.median([v for _, v in cand]))
    return best[0], best[1], med


def shift_scan(args) -> int:
    """只挪我方那一侧，扫一遍录音原点：报表 (挪量, 参与段数, 相对散布, 中位Δ)。
    这条存在的理由：P-139/P-141 两次都把"两边一起挪"当成了原点检验，量到的其实是随便挑的时间。"""
    ours, our_rate = read_wav(Path(args.capture))
    exp, exp_rate = read_wav(Path(args.export_audio))
    segs = audio_segments(Path(args.media_model), args.min_seg)
    tol = args.tol if args.tol > 0 else SELF_Spread_DB
    lag, peak, med0 = estimate_shift(ours, exp, our_rate, span=args.search_span)
    print(f"整段互相关给出滞后 {lag:+.3f} s（峰 {peak:.4f}/中位 {med0:.4f}＝{(peak/med0 if med0 else 0):.1f} 倍分辨力）")
    # 可比性：每个挪量都判**同一批段**（所有挪量下窗都留在界内的那批），
    # 否则"越界丢窗"会让大挪量看起来更干净（P-141 第一版就差点把这当成登记后的绿）。
    dur = ours.size / our_rate
    keep = [(sid, t0, t1) for sid, t0, t1 in segs
            if t0 - args.search_span >= 0 and t1 + args.search_span <= dur]
    print("  可比段 %d/%d（±%.1f s 内窗都不出界），挪量只在这批上算" % (len(keep), len(segs), args.search_span))
    print("  挪量s  有效段  相对散布dB  中位ΔdB   缺段  对 %.2f dB 线" % tol)
    best = None
    for ms in range(-4000, 4001, 100):
        sh = ms / 1000.0
        _, live, missing, med, rel, _, _ = measure(ours, our_rate, exp, exp_rate, keep,
                                                   args.silent_db, our_shift=sh)
        if best is None or rel < best[1]:
            best = (sh, rel, med, len(live))
        if ms % 200 == 0:
            print("  %+6.2f  %5d/%d   %8.2f   %+7.2f   %3d   %s" % (
                sh, len(live), len(keep), rel, med, len(missing),
                "绿" if (rel <= tol and not missing) else "红"))
    print("BEST（只取窗全部在界的点）：挪量 %+.2f s ⇒ 相对散布 %.2f dB，中位Δ %+.2f dB，有效段 %d/%d" % (
        best[0], best[1], best[2], best[3], len(segs)) if best else "没有一个挪量能让所有窗留在界内")
    return 0


def load_registered(capture: str, report: str):
    """按页面实测轨迹把录音重采样到**时间线坐标**，返回 (数组, 采样率)。

    所有跑都走这一个函数，A/B 才可比（P-145 的错就是手写时把已登记的数组又减了一次原点）。
    只取播放头单调推进的前缀：`loop=1` 绕回之后的部分不能拿来重采样。
    """
    obj = None
    for line in open(report, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            j = json.loads(line)
        except Exception:
            continue
        ac = j.get("audio_capture") or {}
        if ac.get("trace"):
            obj = ac
    if not obj:
        raise SystemExit(f"旁证里没有实测轨迹（trace）：{report}")
    tr = obj["trace"]
    cs, ps = [float(tr[0][0])], [float(tr[0][1])]
    for c, v in tr[1:]:
        c, v = float(c), float(v)
        if v > ps[-1] - 0.05 and v - ps[-1] < 3.0:
            cs.append(c)
            ps.append(v)
        else:
            break                                   # 绕回：后面不参与
    cs = np.asarray(cs, dtype=np.float64)
    ps = np.asarray(ps, dtype=np.float64)
    with wave.open(capture, "rb") as w:
        rate, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        raw = np.frombuffer(w.readframes(n), dtype="<i2").reshape(-1, ch)
        raw = raw.mean(axis=1).astype(np.float64) / 32768.0
    upto = int(min(cs[-1], raw.size / rate) * rate)
    sample_ctx = np.arange(upto) / rate
    sample_pos = np.interp(sample_ctx, cs, ps)
    grid = np.arange(sample_pos[0], sample_pos[-1], 1.0 / rate)
    y = np.interp(grid, sample_pos, raw[:upto])
    # 数组下标必须等于**时间线秒**：录音从 timeline t0_pos 开始，前面补零，否则判据拿 (t0,t1) 取窗时
    # 会整体偏一个原点（P-151：洞被标成 2.07 而实际在 3.88）。
    pad = int(round(grid[0] * rate))
    return np.concatenate([np.zeros(pad, dtype=np.float64), y]), rate


def compare_captures(args) -> int:
    """同一批段、同一个登记函数下比较多次录音：谁更接近成片、彼此差多少。"""
    runs = []
    for spec in args.compare:
        label, _, rest = spec.partition("=")
        cap, _, rep = rest.partition(":")
        x, r = load_registered(cap, rep)
        runs.append((label, x, r))
        print(f"登记完成 {label}：{x.size / r:.2f} s @ {r} Hz（已换算到时间线坐标）")
    exp, er = read_wav(Path(args.export_audio))
    segs = audio_segments(Path(args.media_model), args.min_seg)
    tol = args.tol if args.tol > 0 else SELF_Spread_DB
    print("\n段         窗            成片     " + "  ".join("%9s" % l for l, _, _ in runs))
    per = {label: [] for label, _, _ in runs}
    for sid, t0, t1 in segs:
        e = db(window(exp, er, t0, t1))
        if e <= args.silent_db:
            continue
        vals = []
        for label, x, r in runs:
            v = db(window(x, r, t0, t1)) - e
            vals.append(v)
            per[label].append(v)
        print("%s  %6.2f-%6.2f  %7.2f   " % (sid, t0, t1, e)
              + "  ".join("%+8.2f" % v for v in vals))
    print("\n每次跑 vs 成片（逐段 Δ 的统计）：中位＝整体电平（只报数）；散布＝判定那条，线 %.2f dB" % tol)
    for label, _, _ in runs:
        a = np.asarray(per[label], dtype=np.float64)
        if a.size == 0:
            print("  %-10s 没有可比的段" % label)
            continue
        med = float(np.median(a))
        rel = float(np.max(np.abs(a - med)))
        print("  %-10s 有效段 %2d  中位 %+6.2f dB  散布 %6.2f dB  ⇒ %s"
              % (label, a.size, med, rel, "绿" if rel <= tol else "红"))
    base_label, base = runs[0][0], np.asarray(per[runs[0][0]], dtype=np.float64)
    for label, _, _ in runs[1:]:
        d = np.asarray(per[label], dtype=np.float64) - base
        print("  差值 %s−%s：中位 %+5.2f dB、区间 %+5.2f…%+5.2f ⇒ %s"
              % (label, base_label, float(np.median(d)), float(d.min()), float(d.max()),
                 "两次没有系统性差别" if abs(float(np.median(d))) < 1.0 else "有系统性差别"))
    return 0


def find_holes(ours: np.ndarray, our_rate: int, exp: np.ndarray, exp_rate: int,
               hole_s: float, our_db: float, exp_db: float,
               win_ms: float = 30.0) -> list[dict]:
    """我方连续静音而**成片同区不静音**的跨度 ⇒ 洞。

    只看我方会误报（成片本来也有静场），所以要求两侧同时成立：
    我方窗 < `our_db` 且 成片窗 > `exp_db`。跨度 ≥ `hole_s` 才计入。
    """
    w = max(1, int(our_rate * win_ms / 1000.0))
    flags = []
    for i in range(0, ours.size - w, w):
        t0 = i / our_rate
        t1 = t0 + w / our_rate
        o = db(ours[i:i + w])
        e = db(window(exp, exp_rate, t0, t1))
        flags.append((t0, o < our_db and e > exp_db))
    holes, cur = [], None
    for t0, bad in flags:
        if bad:
            cur = [t0, t0 + w / our_rate] if cur is None else [cur[0], t0 + w / our_rate]
        else:
            if cur and cur[1] - cur[0] >= hole_s:
                holes.append({"t0": round(cur[0], 3), "t1": round(cur[1], 3),
                              "seconds": round(cur[1] - cur[0], 3)})
            cur = None
    if cur and cur[1] - cur[0] >= hole_s:
        holes.append({"t0": round(cur[0], 3), "t1": round(cur[1], 3),
                      "seconds": round(cur[1] - cur[0], 3)})
    return holes


def delivery_ledger(report: str) -> tuple[str, int]:
    """把页内自己的交付账读出来贴在判定行旁边。

    为什么需要：`L29` 从音频推"有没有洞"，而**为什么**要看在跑时记下的账——
    P-154 就是靠它对上机制的：坏的那次 `0DB4E847` 与 BGM 的 `ctx0 == ctx1`（一段都没排进图）、
    `lost_s 10.95 s`，好的那次 `lost_s 0.174 s` 且区间正常。光看录音只能看到"有洞"，看不到"饿死"。
    """
    obj = None
    for line in open(report, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            j = json.loads(line)
        except Exception:
            continue
        if (j.get("play") or {}).get("audio"):
            obj = j["play"]["audio"]
    if not obj:
        return "交付账：没有旁证可读", 0
    ps = obj.get("per_seg") or []
    zero = [str(x.get("id"))[:8] for x in ps
            if x.get("ctx0") is not None and x.get("ctx1") is not None and x["ctx1"] <= x["ctx0"]]
    line = ("交付账：jobs_started=%s flushes=%s lost_s=%.2f s clamps=%s(%.0f ms) short_jobs=%s "
            "零排期段=%d%s" % (obj.get("jobs_started"), obj.get("flushes"), obj.get("lost_s") or 0,
                              obj.get("clamps"), obj.get("clamp_ms_total") or 0, obj.get("short_jobs"),
                              len(zero), ("：" + ",".join(zero[:6])) if zero else ""))
    return line, len(zero)


def judge(args) -> int:
    ours, our_rate = read_wav(Path(args.capture))
    exp, exp_rate = read_wav(Path(args.export_audio))
    segs = audio_segments(Path(args.media_model), args.min_seg)
    # 起播点之前的段既没机会播、也谈不上"我方比成片轻"，留在段统计里会造出 101 dB 这种假散布
    # （6B591400@0.0–0.567 在 start=1.81 之前，被我方读成 −120 ⇒ 整条判定被它一家扛走）。
    n_pre = sum(1 for s in segs if s[2] <= args.start_s + 1e-6)
    segs = [s for s in segs if s[2] > args.start_s + 1e-6]
    tol = args.tol if args.tol > 0 else SELF_Spread_DB
    if args.control:
        ctl, ctl_rate = read_wav(Path(args.control))
        _, _, _, _, ctl_rel, _, _ = measure(ctl, ctl_rate, ours, our_rate, segs, args.silent_db)
        tol = max(tol, ctl_rel)          # 容差不许低于"同一内容自己录两次"的散布
    shift = args.shift_ms / 1000.0
    note = "固定对齐"
    fitted = False            # 挪量若是拟合/手工来的，本行只作诊断（P-141）
    if args.shift_ms:
        note = f"手工挪量 {args.shift_ms:+.0f} ms"
    if args.auto_shift:
        lag, peak, med0 = estimate_shift(ours, exp, our_rate, span=args.search_span)
        shift = lag                                     # 符号由 --shift-scan 实测决定，不靠猜
        fitted = True
        note = (f"已按整段互相关登记原点：滞后 {lag:+.3f} s（峰 {peak:.4f}/中位 {med0:.4f}"
                f"＝{(peak/med0 if med0 else 0):.1f} 倍分辨力）")
    n_drop = sum(1 for _, t0, t1 in segs if t0 + shift < 0 or t1 + shift > ours.size / our_rate)
    rows, live, missing, med, rel, dexp, dour = measure(ours, our_rate, exp, exp_rate, segs,
                                                       args.silent_db, our_shift=shift)
    duty = (dour / dexp) if dexp else 1.0
    holes = find_holes(ours, our_rate, exp, exp_rate, args.hole_s,
                       args.hole_our_db, args.hole_exp_db)
    # 洞要分两类算（P-153）：跑从 `firstPlayable` 起播（这几次实测 1.81 s），**起点之前**没声音
    # 是首播边界、不是交付缺陷；只有起点之后的洞才是"该播而没播"。坐标不说清楚就会把边界算成故障。
    before = [h for h in holes if h["t1"] <= args.start_s + 1e-6]
    holes = [h for h in holes if h["t1"] > args.start_s + 1e-6]
    for h in holes:
        h["t0"] = round(max(h["t0"], args.start_s), 3)
        h["seconds"] = round(h["t1"] - h["t0"], 3)
    hole_s = sum(h["seconds"] for h in holes)
    before_s = sum(h["seconds"] for h in before)
    # 丢窗不许当成"过"：把录音挪出范围会让参与判定的段变少，散布自然变小（P-141 的坑）
    # P-141 的牙齿：拟合/手工挪量不给绿——同一批段上散布在 −2.6 s 与 +1.0/+1.2 s 都能压进线内，
    # 固定对齐却是 10.6 dB ⇒ 这条散布对"对齐"没有分辨力。判定只能按固定对齐做，
    # 原点必须由页面实测给出（t0_ctx/t0_wall/first_playable），不许本脚本自己凑。
    # 交付这一半不只判"整段没响"，还判**跨段的洞**（P-150：段级读数 0 缺段却有 2.9 s 掉落 ⇒ 失明）
    starved, ledger_line = 0, ""
    if args.report_jsonl:
        ledger_line, starved = delivery_ledger(args.report_jsonl)
    # 零排期段：作业起了却一段都没排进图（P-154：坏跑 4 条、lost_s 10.95 s，好跑 0 条 / 0.17 s）。
    # "起了却没排"本身就是失败，给它容差只会把失败摊成数值 ⇒ 这条不要阈值。
    ok = (not missing) and (rel <= tol) and (n_drop == 0) and not fitted and args.shift_ms == 0 \
        and hole_s <= args.hole_allow and starved == 0
    if fitted or args.shift_ms != 0:
        note += "（挪量＝拟合/手工 ⇒ 只作诊断，不判绿）"
    print(f"{'PASS' if ok else 'FAIL'}  L29 audio vs export (delivery + relative level)   {note}   "
          f"起播点前排除 {n_pre} 段；"
          f"成片有声段 {len(live)}/{len(rows)}，我方缺 {len(missing)} 段；"
          f"相对散布 max|Δ−中位| = {rel:.2f} dB（线 ≤{tol:.2f}，来自同内容自比；"
          f"窗被挪出录音范围的段 {n_drop}——不为 0 就不许判绿）；"
          f"整体偏移 {med:+.2f} dB（只报数，不判——律/增益侧，见 U-88）；"
          f"占空比 {duty:.3f}（我方/成片响窗比）；"
          f"我方静音而成片不静音的洞 {len(holes)} 处 / {hole_s:.2f} s（线 ≤{args.hole_allow:.2f} s，"
          f"单洞 ≥{args.hole_s:.2f} s 才计；起播点 {args.start_s:.2f} s 之前另有 "
          f"{len(before)} 处 / {before_s:.2f} s 算首播边界，不计入缺陷）")
    for h in holes[:8]:
        print(f"   洞：{h['t0']:.2f}–{h['t1']:.2f} s（{h['seconds']:.2f} s）")
    if missing:
        print("   缺的段：" + "; ".join(f"{r['id']}@{r['t0']}–{r['t1']} 成片 {r['export_db']} "
                                        f"我方 {r['ours_db']}" for r in missing[:6]))
    if rel > tol and live:
        worst = max(live, key=lambda r: abs(r["delta_db"] - med))
        print(f"   偏得最多的段：{worst['id']}@{worst['t0']}–{worst['t1']} Δ={worst['delta_db']} "
              f"（相对 {abs(worst['delta_db'] - med):.2f} dB）")
    if args.report_jsonl:
        print("   " + ledger_line)
    if args.dump:
        Path(args.dump).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if ok else 1


def selftest(args) -> int:
    """正例＝成片自己（Δ≡0）；反例＝把其中一段消音 ⇒ 两条判据都要红。"""
    exp, exp_rate = read_wav(Path(args.export_audio))
    segs = audio_segments(Path(args.media_model), args.min_seg)
    tol = args.tol if args.tol > 0 else SELF_Spread_DB
    bad = []
    pos = []
    if judge_of(exp, exp_rate, exp, exp_rate, segs, args.silent_db, tol)["fail_lines"]:
        bad.append("正例（同一份内容自比）竟然红 ⇒ 判据在没有误差时也报错")
    mut = exp.copy()
    pick = next((s for s in segs if s[2] - s[1] >= 1.0), segs[0])
    a, b = int(pick[1] * exp_rate), int(pick[2] * exp_rate)
    mut[a:b] = 0.0
    r = judge_of(mut, exp_rate, exp, exp_rate, segs, args.silent_db, tol)
    if not r["fail_lines"]:
        bad.append("反例（一段消音）还是绿的 ⇒ 守卫没牙")
    # 反例 2：只挖一个 0.4 s 的短洞（段级读数不会报"缺段"，洞检测必须抓到）
    mut2 = exp.copy()
    t0 = 6.6
    mut2[int(t0 * exp_rate):int((t0 + 0.4) * exp_rate)] = 0.0
    hl = find_holes(mut2, exp_rate, exp, exp_rate, 0.2, -60.0, -45.0)
    if not hl:
        bad.append("反例 2（挖 0.4 s 洞）洞检测没抓到 ⇒ 交付判据对跨段掉落失明")
    else:
        pos.append(f"洞检测抓到 {len(hl)} 处、首个在 {hl[0]['t0']:.2f} s")
    # 正例：原样（等于成片）不该有洞
    hl0 = find_holes(exp, exp_rate, exp, exp_rate, 0.2, -60.0, -45.0)
    if hl0:
        bad.append(f"正例（同一份自比）却有 {len(hl0)} 个洞 ⇒ 洞检测在自己身上就误报")
    print(("SELFTEST PASS：正例绿、一段消音转红（缺段 %d、相对散布 %.2f dB）；%s"
           % (len(r["missing"]), r["rel"], "；".join(pos) if pos else "洞检测未触发"))
           if not bad else "SELFTEST FAIL：" + "；".join(bad))
    return 0 if not bad else 2


def judge_of(ours, our_rate, exp, exp_rate, segs, silent_db, tol):
    _, live, missing, med, rel, dexp, dour = measure(ours, our_rate, exp, exp_rate, segs, silent_db)
    return {"missing": missing, "rel": rel, "med": med,
            "fail_lines": [k for k, v in (("缺段", missing), ("相对散布", rel > tol)) if v]}


def export_wav(mp4: Path, out: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp4),
                    "-vn", "-ac", "1", "-ar", "48000", str(out)], check=True)
    print(f"成片音轨已抽到 {out}（48 kHz 单声道）")


def shift_samples(x: np.ndarray, rate: int, ms: float) -> np.ndarray:
    """把录音整体挪 ms（正数＝往后），零填充——用来分清"窗内电平差是错位还是真缺内容"。"""
    k = int(round(ms / 1000.0 * rate))
    out = np.zeros_like(x)
    if k == 0:
        return x.copy()
    if k > 0:
        if k < x.size:
            out[k:] = x[:-k]
    else:
        if -k < x.size:
            out[:k] = x[-k:]
    return out


def shift_sweep(args) -> int:
    """扫一遍原点：若某个位移能把相对散布压进线内 ⇒ 红是**错位**；压不进去 ⇒ 是**分段缺内容**。
    这条不代替判据（线不动），只回答"红该归给谁"。"""
    ours, our_rate = read_wav(Path(args.capture))
    exp, exp_rate = read_wav(Path(args.export_audio))
    segs = audio_segments(Path(args.media_model), args.min_seg)
    tol = args.tol if args.tol > 0 else SELF_Spread_DB
    best = None
    print(f"sweep  位移ms   相对散布dB   中位ΔdB   缺段   （线 ≤{tol:.2f}）")
    for ms in range(-800, 801, 100):
        r = judge_of(shift_samples(ours, our_rate, ms), our_rate, exp, exp_rate, segs,
                     args.silent_db, tol)
        rel, med, miss = r["rel"], r["med"], len(r["missing"])
        print(f"       {ms:+5d}   {rel:9.2f}   {med:+8.2f}   {miss:3d}")
        if best is None or rel < best[1]:
            best = (ms, rel, med, miss)
    verdict = ("错位可解释：某位移能把散布压进线内 ⇒ 红归给原点/延迟"
               if best[1] <= tol else
               "任何 ±800 ms 位移都压不进线 ⇒ 红归给分段缺内容，不是错位")
    print(f"BEST 位移 {best[0]:+d} ms：相对散布 {best[1]:.2f} dB，中位Δ {best[2]:+.2f} dB，缺段 {best[3]} ⇒ {verdict}")
    return 0



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
    ap.add_argument("--start-s", type=float, default=0.0,
                    help="起播点（秒，时间线坐标）：这之前的静音算首播边界，不算交付缺陷")
    ap.add_argument("--hole-s", type=float, default=0.2,
                    help="连续这么久才算一个洞（秒）")
    ap.add_argument("--hole-allow", type=float, default=0.5,
                    help="允许的洞总时长（秒）——超过即转红")
    ap.add_argument("--hole-our-db", type=float, default=-60.0, help="我方视为静音的门限")
    ap.add_argument("--hole-exp-db", type=float, default=-45.0, help="成片视为有声的门限")
    ap.add_argument("--report-jsonl", default="", help="该次跑的页内旁证，用来贴出交付账（lost_s/零排期段等）")
    ap.add_argument("--dump", default="")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--shift-sweep", action="store_true", help="扫原点，分清错位与缺内容（不改判据线）")
    ap.add_argument("--shift-ms", type=float, default=0.0, help="手工登记录音原点（毫秒，窗往前挪）")
    ap.add_argument("--compare", action="append", default=[],
                    help="label=录音.wav:旁证.jsonl，可重复；同一登记函数下比多次录音")
    ap.add_argument("--shift-scan", action="store_true", help="只挪我方扫录音原点，报表给判定提供依据")
    ap.add_argument("--auto-shift", action="store_true",
                    help="用整段波形互相关自己找录音原点，判之前先登记")
    ap.add_argument("--search-span", type=float, default=4.0, help="--auto-shift 的搜索半径（秒）")
    args = ap.parse_args()
    if args.export_mp4 and not Path(args.export_audio).is_file():
        export_wav(Path(args.export_mp4), Path(args.export_audio))
    if args.selftest:
        return selftest(args)
    if args.shift_sweep:
        return shift_sweep(args)
    if args.compare:
        return compare_captures(args)
    if args.shift_scan:
        return shift_scan(args)
    if not (args.capture and Path(args.capture).is_file()):
        print("没有 --capture（先跑一次带音频录音的会话：audio_capture_check.py）")
        return 3
    return judge(args)


if __name__ == "__main__":
    sys.exit(main())
