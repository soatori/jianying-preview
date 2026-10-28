"""判定「向上闪入」这一窗里**哪条律承重**：把成片逐帧的两个可观测量
（亮度、结构）与 AE 明文表逐帧的预测序列对齐，各自给 Pearson r、
模型残差，再加**置换对照**（打乱预测序列 200 次，报 |r|≥观测值的比例）。

为什么不能只看"加了像不像"：整帧相关对单层不敏感（F-072），而本窗的两个
可观测量分别对应两条不同的律——
  亮度  mean(frame)          ← `ADBE_Exposure2` 的 `u_Intensity`（乘性、线性光）
  结构  mean|ΔI_y|(垂直梯度)  ← `ADBE_Gaussian_Blur_2_0001_2_3` 的垂直强度
帧 201 的垂直梯度只有常帧的 4~5%（F-095），所以「模糊可后置」这条前提要由
结构的 r 来判，而不是由我读 lua 的印象来判。

顺带把两条时间映射假设放在一起打：**夹紧** `t=min(time,dur)` 与 **lua 字面循环**
`mod(time,dur)`。成片 211..227 全平（F-095）应当判循环败。

用法：
    python scripts/flash_attribution.py            # 默认本草稿这一窗
    python scripts/flash_attribution.py --report temp/playback-test/flash-attr.json
读数打印用 ASCII 标记 `FLASH_ATTR ...`，方便门层直接抓行。
"""
from __future__ import annotations

import argparse
import os
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_frame as rf                      # noqa: E402
import ae_keyframe as aek                      # noqa: E402

try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:                                # noqa: BLE001
    pass

MP4 = os.environ.get("JY_ORACLE_MP4", "")     # 成片 oracle：本机路径，不写死在源码里
PKG = (Path.home() / "AppData/Local/JianyingPro/User Data/Cache/effect"
       / "7273389803532456504/ecaffca7c7e1d7744fa296a29f65b366"
       / "AmazingFeature/lua/SeekModeScript.lua")
EXPO = "ADBE_Exposure2_0003_0_1"
VB = "ADBE_Gaussian_Blur_2_0001_2_3"
HB = "ADBE_Gaussian_Blur_2_0001_0_0"
POS = "ADBE_Position_2_4"


def pearson(x, y) -> float:
    a, b = np.asarray(x, float), np.asarray(y, float)
    a = a - a.mean()
    b = b - b.mean()
    d = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(a @ b / d) if d else float("nan")


def perm_frac(x, y, n=200, seed=7) -> float:
    """置换对照：打乱 y 的顺序，看 |r|≥观测值 的比例（越小越不像巧合）。"""
    rng = np.random.default_rng(seed)
    obs = abs(pearson(x, y))
    hits = sum(1 for _ in range(n) if abs(pearson(x, rng.permutation(np.asarray(y, float)))) >= obs)
    return hits / n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mp4", default=MP4)
    ap.add_argument("--pkg", type=Path, default=PKG)
    ap.add_argument("--cut-t", type=float, default=6.6, help="段起点（秒，成片时间轴）")
    ap.add_argument("--lead", type=int, default=3, help="成片帧号 lead（P-29 固定值）")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--pre", type=int, default=3, help="切点前取几帧（当预闪对照用）")
    ap.add_argument("--post", type=int, default=30, help="切点后取几帧（要够到动画之外做基线）")
    ap.add_argument("--duration", type=float, default=0.3)
    ap.add_argument("--base-after", type=float, default=0.2,
                    help="动画结束后再隔多少秒才允许进基线（否则基线被衰减尾巴污染）")
    ap.add_argument("--gamma", type=float, default=2.2, help="Exposure.frag 的线性化指数")
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()

    src = args.pkg.read_text(encoding="utf-8", errors="replace")
    attrs = aek.parse_ae_attribute(src)
    cons = aek.extract_constants(src)
    tools = aek.AETools(attrs)
    print(f"表: 属性={len(attrs)} all_frame={tools.all_frame} 常数={cons}")

    # 成片帧号 = round(t*fps) + lead（P-29 固定的那条 lead；上一版解析了却没用上，
    # 于是把 198 当切点、把 198..200 三帧常亮帧当成"闪的开头"，r 直接被冲平）
    cut_frame = int(round(args.cut_t * args.fps)) + args.lead
    f_lo, f_hi = cut_frame - args.pre, cut_frame + args.post
    frames, means, grads_v, grads_h, stds = [], [], [], [], []
    for f in range(f_lo, f_hi + 1):
        im: Image.Image = rf.decode_frame(args.mp4, f / args.fps)
        if im is None:
            print(f"FLASH_ATTR decode_fail frame={f}")
            continue
        a = np.asarray(im.convert("L").resize((270, 480)), dtype=np.float64)
        frames.append(f)
        means.append(float(a.mean()))
        grads_v.append(float(np.mean(np.abs(np.diff(a, axis=0)))))
        grads_h.append(float(np.mean(np.abs(np.diff(a, axis=1)))))
        stds.append(float(a.std()))
    n = len(frames)
    # 基线只允许取「动画窗口 + base_after」之外的帧：上一版用末 6 帧，
    # 而末 6 帧还在衰减尾巴里（108.5 vs 干净基线 105.5），残差被系统性抬高。
    base_idx = [i for i, f in enumerate(frames)
                if (f - cut_frame) / args.fps >= args.duration + args.base_after]
    if len(base_idx) < 4:
        print(f"FLASH_ATTR WARN 基线帧不足: {len(base_idx)}（窗口外的帧没取够，--post 加大）")
    base = float(np.mean([means[i] for i in base_idx]))
    base_gv = float(np.mean([grads_v[i] for i in base_idx]))
    base_gh = float(np.mean([grads_h[i] for i in base_idx]))
    base_std = float(np.mean([stds[i] for i in base_idx]))
    print(f"解码 {n}/{f_hi-f_lo+1} 帧  帧号 {frames[0]}..{frames[-1]}  "
          f"基线（{len(base_idx)} 帧，t>={args.duration + args.base_after:.2f}s）"
          f" mean={base:.2f} gradV={base_gv:.2f} gradH={base_gh:.2f} std={base_std:.2f}")

    fit = [i for i, f in enumerate(frames)
           if cut_frame <= f and (f - cut_frame) / args.fps <= args.duration + 1e-6]
    ctrl = [i for i, f in enumerate(frames) if f < cut_frame]
    print(f"拟合帧 {len(fit)}（切点..切点+{args.duration}s）；预切点对照 {len(ctrl)} 帧")

    def sel(lst):
        return [lst[i] for i in fit]

    def curves(mode: str):
        out = {"E": [], "V": [], "H": [], "y": []}
        for f in frames:
            t = (f - cut_frame) / args.fps
            fn = aek.frame_of_clamped if mode == "clamp" else aek.frame_of
            cf = fn(t, args.duration, cons, tools.all_frame)
            prog = max(0.0, min(cf, tools.all_frame)) / tools.all_frame

            def g(k):
                v = tools.get_val(k, prog)
                return v[0] if isinstance(v, list) else v
            out["E"].append(g(EXPO))
            out["V"].append(g(VB))
            out["H"].append(g(HB))
            out["y"].append(tools.get_val(POS, prog)[1])
        return out

    obs_log2 = [math.log2(max(m / base, 1e-6)) for m in means]
    obs_gv = [g / base_gv for g in grads_v]
    res = {"frames": frames, "cut_frame": cut_frame, "base_mean": base, "base_gradV": base_gv,
          "means": means, "gradV": grads_v, "gradH": grads_h, "std": stds, "modes": {},
          "fit_frames": [frames[i] for i in fit],
          "precut_control": [{"frame": frames[i], "mean": means[i], "ratio": means[i] / base,
                              "gradV": grads_v[i]} for i in ctrl]}
    print("预切点对照（闪若提前，这里就该 >1.2）：" +
          "  ".join(f"f{frames[i]}={means[i]/base:.3f}/g{grads_v[i]/base_gv:.2f}" for i in ctrl))
    for mode in ("clamp", "mod"):
        c = curves(mode)
        # 亮度模型：Exposure.frag 是线性光乘 2^E，回到 gamma 域即 base*2^(E/gamma)
        pred_m = [base * 2.0 ** (e / args.gamma) for e in c["E"]]
        resid = [pred_m[i] - means[i] for i in fit]
        rb = pearson(sel(c["E"]), sel(obs_log2))
        rs = pearson(sel(c["V"]), sel(obs_gv))
        pf = perm_frac(sel(c["E"]), sel(obs_log2))
        ps = perm_frac(sel(c["V"]), sel(obs_gv))

        # 结构项不能只比"两条都单调下降"，那对量纲没有要求。改判**各向异性**：
        # 表里垂直强度 300→0、水平强度 8→0 是两条**不同形状**的曲线，
        # 若成片掉的是**垂直**梯度，则 `1/(1+k·X)` 用 X=V 应当明显比 X=H 拟合得好。
        def fit_inv(xs):
            ys = sel(obs_gv)
            best = (1e9, 0.0, None)
            for kk in np.arange(0.0, 0.5, 2e-4):
                pred = [1.0 / (1.0 + kk * v) for v in xs]
                rr = float(np.sqrt(np.mean((np.asarray(pred) - np.asarray(ys)) ** 2)))
                if rr < best[0]:
                    best = (rr, float(kk), pred)
            return best

        rms_v, k_v, pred_v = fit_inv(sel(c["V"]))
        rms_h, k_h, pred_h = fit_inv(sel(c["H"]))
        max_v = max(abs(p - y) for p, y in zip(pred_v, sel(obs_gv)))
        max_h = max(abs(p - y) for p, y in zip(pred_h, sel(obs_gv)))
        gh_ratio = float(np.mean([grads_h[i] for i in fit]) /
                         max(float(np.mean([grads_v[i] for i in fit])), 1e-9))
        # 夹紧 vs 循环的分歧**只出现在窗口之外**：`mod` 会在 t=dur 处折回 E=1.83 再闪一次。
        # 所以这条不能放进 fit（放进来会把两假设糊成同一个），要单独打。
        post = [i for i, f in enumerate(frames)
                if args.duration < (f - cut_frame) / args.fps <= args.duration + 0.3 + 1e-6]
        post_sse = float(np.sum([(pred_m[i] - means[i]) ** 2 for i in post])) / max(len(post), 1)
        post_max = max((abs(pred_m[i] - means[i]) for i in post), default=float("nan"))
        peak = max(fit, key=lambda i: means[i])
        res["modes"][mode] = {"expo": c["E"], "vblur": c["V"], "hblur": c["H"], "ypos": c["y"],
                              "pred_mean": pred_m, "resid": resid,
                              "r_expo_logbright": rb, "r_vblur_grad": rs,
                              "perm_expo": pf, "perm_vblur": ps,
                              "max_abs_resid": max(abs(x) for x in resid),
                              "resid_rms": float(np.sqrt(np.mean(np.square(resid)))),
                              "grad_k_v": k_v, "grad_rms_v": rms_v, "grad_max_v": max_v,
                              "grad_k_h": k_h, "grad_rms_h": rms_h, "grad_max_h": max_h,
                              "grad_h_over_v_in_fit": gh_ratio,
                              "post_frames": [frames[i] for i in post],
                              "post_mse": post_sse, "post_max_abs": post_max,
                              "peak_frame": frames[peak], "peak_obs_mean": means[peak],
                              "peak_pred_mean": pred_m[peak]}
        print(f"--- {mode}: 时长={args.duration}s  拟合帧数={len(fit)}（含峰值帧）---")
        print(f"  亮度 r(E, log2 mean/base) = {rb:+.4f}  置换|r|>=观测比例={pf:.3f}  "
              f"模型残差 max={max(abs(x) for x in resid):.1f} rms={np.sqrt(np.mean(np.square(resid))):.1f} 码值")
        print(f"  结构 r(Vblur, gradV/base) = {rs:+.4f}  置换比例={ps:.3f}")
        print(f"  各向异性拟合 1/(1+k·X) 对 gradV/base：X=V k={k_v:.4f} rms={rms_v:.4f} max={max_v:.4f} | "
              f"X=H k={k_h:.4f} rms={rms_h:.4f} max={max_h:.4f}  ⇒ {'垂直' if rms_v < rms_h else '水平'}"
              f"更合（窗内 gradH/gradV={gh_ratio:.2f}）")
        print(f"  峰值帧 f{frames[peak]} mean={means[peak]:.2f}（预测 {pred_m[peak]:.2f}）"
              f" std={stds[peak]:.2f} vs 常帧 std={float(np.mean(stds[-6:])):.2f}")

    a, b = res["modes"]["clamp"], res["modes"]["mod"]
    print(f"窗口外（夹紧/循环分歧处）拟合：夹紧 mse={a['post_mse']:.1f} max={a['post_max_abs']:.1f}"
          f" 码值 | 循环 mse={b['post_mse']:.1f} max={b['post_max_abs']:.1f} 码值"
          f"  （{len(a['post_frames'])} 帧 {a['post_frames'][:3]}…）")
    win = "clamp" if a["post_mse"] <= b["post_mse"] else "mod"
    print(f"FLASH_ATTR time_model={win} mse_clamp={a['post_mse']:.1f} mse_mod={b['post_mse']:.1f} "
          f"r_in_window clamp={a['r_expo_logbright']:+.4f} mod={b['r_expo_logbright']:+.4f} "
          f"resid_max_clamp={a['max_abs_resid']:.1f} resid_rms_clamp={a['resid_rms']:.1f}")
    print(f"FLASH_ATTR structure r_vblur={a['r_vblur_grad']:+.4f} perm={a['perm_vblur']:.3f} "
          f"k_v={a['grad_k_v']:.4f} rms_v={a['grad_rms_v']:.4f} "
          f"k_h={a['grad_k_h']:.4f} rms_h={a['grad_rms_h']:.4f}")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        tmp = args.report.with_suffix(args.report.suffix + ".tmp")
        tmp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        bak = args.report.with_suffix(args.report.suffix + ".bak")
        if args.report.exists():
            bak.write_bytes(args.report.read_bytes())
        tmp.replace(args.report)
        print(f"写出 {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
