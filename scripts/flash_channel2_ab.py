"""通道 2 的**开/关 A/B**：加了「向上闪入」的曝光项之后，逐帧是否真的更像成片。

判据不是"看起来像"，而是三条同时看（F-096 的口径）：
  ① 与成片同帧号的 MAD（越小越像）；
  ② 我们自己的 mean 与成片 mean 的差；
  ③ 我们自己的垂直梯度 gradV 与成片的差（曝光管不了结构，这条应当**仍然差**——
     如果它也变好了，说明我把别的东西误当成曝光生效了）。
预切点帧（切点前 3 帧）是**阴性对照**：曝光项不该让它们变亮。

用法：
    python scripts/flash_channel2_ab.py --model temp/playback-test/model-proxy-a.json
"""
from __future__ import annotations

import argparse
import os
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_frame as rf                       # noqa: E402

try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:                                 # noqa: BLE001
    pass

MP4 = os.environ.get("JY_ORACLE_MP4", "")     # 成片 oracle：本机路径，不写死在源码里


def obs(img: Image.Image, size=(270, 480)):
    a = np.asarray(img.convert("L").resize(size), dtype=np.float64)
    return float(a.mean()), float(np.mean(np.abs(np.diff(a, axis=0))))


def render(model, t_s: float, mode: str):
    """mode: off=完全不开入场动画项；expo=只开曝光；both=曝光+垂直模糊。"""
    w = int(model["canvas"]["width"])
    h = int(model["canvas"]["height"])
    rf.AE_FLASH["off"] = (mode == "off")
    rf.AE_FLASH["blur"] = (mode == "both")
    rf.AE_LOG.clear()
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    rf.collect(canvas, model, int(round(t_s * 1e6)), {})
    log = list(rf.AE_LOG)
    rf.AE_LOG.clear()
    return canvas, log


def arms_of(model, t_s: float):
    out = {}
    for mode in ("off", "expo", "both"):
        img, log = render(model, t_s, mode)
        out[mode] = (img, log)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--mp4", default=MP4)
    ap.add_argument("--cut-t", type=float, default=6.6)
    ap.add_argument("--lead", type=int, default=3)
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--pre", type=int, default=3)
    ap.add_argument("--post", type=int, default=12)
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()

    model = json.loads(Path(args.model).read_text(encoding="utf-8"))
    cut_src = int(round(args.cut_t * args.fps)) + args.lead       # 成片帧号
    rows, better, worse, same, blur_better, blur_worse = [], 0, 0, 0, 0, 0
    print(f"切点成片帧={cut_src}（timeline {args.cut_t}s，lead={args.lead}）")
    print("帧号    t(s)   MAD关  MAD曝光  MAD曝+糊   成片mean  关    曝光  曝+糊   "
          "成片gV  曝+糊gV  判定")
    for k in range(-args.pre, args.post + 1):
        f = cut_src + k
        t = (f - args.lead) / args.fps
        exp = rf.decode_frame(args.mp4, f / args.fps)
        if exp is None:
            print(f"{f:6d}  解码失败")
            continue
        em, eg = obs(exp)
        arms = arms_of(model, t)
        m_img, m_log = arms["off"]
        x_img, x_log = arms["expo"]
        b_img, b_log = arms["both"]
        mad_off = float(np.mean(np.abs(obs_arr(m_img) - obs_arr(exp))))
        mad_expo = float(np.mean(np.abs(obs_arr(x_img) - obs_arr(exp))))
        mad_both = float(np.mean(np.abs(obs_arr(b_img) - obs_arr(exp))))
        om, og = obs(m_img)
        xm, xg = obs(x_img)
        bm, bg = obs(b_img)
        d_expo = mad_expo - mad_off
        d_both = mad_both - mad_expo
        verdict = ("曝光改好" if d_expo < -0.5 else ("曝光改坏" if d_expo > 0.5 else "曝光持平"))
        verdict += ("/糊改好" if d_both < -0.5 else ("/糊改坏" if d_both > 0.5 else "/糊持平"))
        better += d_expo < -0.5
        worse += d_expo > 0.5
        same += abs(d_expo) <= 0.5
        blur_better += d_both < -0.5
        blur_worse += d_both > 0.5
        e_now = max([x[3] for x in x_log if x[0] == "applied"], default=0.0)
        v_now = max([x[3] for x in b_log if x[0] == "vblur"], default=0.0)
        g_ratio = max([x[3] for x in b_log if x[0] == "grad_ratio"], default=1.0)
        rows.append({"frame": f, "t": t, "exp_mean": em, "exp_gradV": eg,
                     "mad_off": mad_off, "mad_expo": mad_expo, "mad_both": mad_both,
                     "mean_off": om, "mean_expo": xm, "mean_both": bm,
                     "gradV_off": og, "gradV_expo": xg, "gradV_both": bg,
                     "exposure_E": e_now, "vblur_V": v_now, "achieved_grad_ratio": g_ratio,
                     "expo_pred_ratio": 1.0 / (1.0 + 0.0552 * v_now) if v_now else 1.0,
                     "log": b_log})
        tag = "预切点" if k < 0 else ("窗内" if t <= args.cut_t + 0.3 + 1e-6 else "窗外")
        print(f"{f:6d} {t:6.3f} {mad_off:6.2f} {mad_expo:6.2f} {mad_both:7.2f}  "
              f"{em:7.1f} {om:5.1f} {xm:5.1f} {bm:5.1f}  {eg:5.2f} {bg:6.2f}  "
              f"{verdict} E={e_now:.3f} V={v_now:.1f} 比值实测{g_ratio:.3f}/预测"
              f"{rows[-1]['expo_pred_ratio']:.3f} [{tag}]")
    print(f"FLASH_AB frames={len(rows)} 曝光：改好={better} 改坏={worse} 持平={same}；"
          f"模糊：改好={blur_better} 改坏={blur_worse}；"
          f"平均MAD off={np.mean([r['mad_off'] for r in rows]):.2f} "
          f"expo={np.mean([r['mad_expo'] for r in rows]):.2f} "
          f"both={np.mean([r['mad_both'] for r in rows]):.2f}")
    pre = [r for r in rows if r["t"] < args.cut_t]
    drift = max((abs(r["mean_both"] - r["mean_off"]) for r in pre), default=0.0)
    gdrift = max((abs(r["gradV_both"] - r["gradV_off"]) for r in pre), default=0.0)
    print(f"FLASH_AB 阴性对照（预切点 {len(pre)} 帧）最大 mean 位移={drift:.3f} "
          f"gradV 位移={gdrift:.3f} 码值 ⇒ "
          f"{'通过：两项都没提前生效' if drift < 0.5 and gdrift < 0.05 else '失败：项漏到切点前'}")
    degrades = [x for r in rows for x in r["log"] if x[0] == "degraded"]
    print(f"FLASH_AB 降级计数={len(degrades)}（分母：渲染帧数 {len(rows)}）"
          f" 首个={degrades[:1]}")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        tmp = args.report.with_suffix(args.report.suffix + ".tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        bak = args.report.with_suffix(args.report.suffix + ".bak")
        if args.report.exists():
            bak.write_bytes(args.report.read_bytes())
        tmp.replace(args.report)
        print(f"写出 {args.report}")
    return 0


def obs_arr(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("RGB").resize((270, 480)), dtype=np.float64)


if __name__ == "__main__":
    sys.exit(main())
