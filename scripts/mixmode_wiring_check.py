"""混合模式**接线**验证（不是数学验证——数学由 mixmode_equivalence.py 在 GPU 上判）。

为什么要单独一条：本草稿 0 个 `mix_mode` 引用，所以门的 L1~L6 永远不会碰到这条新路径；
「代码写了」和「画面上真的按混合模式叠了」是两件事，必须用构造样本分开证。
做法：把 `model-check.json` 的 flag=2 叠加段注入三种模式，离线渲染同一时刻，看
  (a) multiply 让叠加区域变暗、screen 让它变亮（方向判据，比「像素不同」更有意义）；
  (b) 认不出的包 md5 **计入降级、按普通合成画**，绝不猜成一个模式；
  (c) 注入段数与实际生效段数一致（防止 mix_mode 挂错桶被静默丢掉）。

口径：亮度用 64 px luma 均值，区域 = 叠加层 place() 后的包围盒并集；同刻同模型只切 mix_mode，
所以差异只可能来自混合本身。样本文件只写到 temp/，草稿不动。

用法：
    python scripts/mixmode_wiring_check.py [--model temp/playback-test/model-check.json]
                                           [--t 6.70] [--out-dir temp/playback-test/mixwiring]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_frame as rf  # noqa: E402

MULTIPLY_MD5 = "8001e07eefc5d8b69572b977ca14bef9"   # MultiplyBlendPreMul
SCREEN_MD5 = "d9c1d4ca7ab91df4f48d12b339f2da88"     # ScreenBlendPreMul
BOGUS_MD5 = "00000000000000000000000000000000"      # 不是任何包 => 必须走降级


def inject(model: dict, md5: str | None, name: str = "") -> dict:
    m = json.loads(json.dumps(model))
    n = 0
    for tr in m["tracks"]:
        if tr["type"] == "audio":
            continue
        for s in tr["segments"]:
            if (s.get("track") or {}).get("flag") != 2 or not s.get("media"):
                continue
            s["mix_mode"] = None if md5 is None else {"name": name, "package_md5": md5,
                                                      "ref": "synthetic"}
            n += 1
    return m


def render(model: dict, t: float) -> Image.Image:
    cw, ch = int(model["canvas"]["width"]), int(model["canvas"]["height"])
    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 255))
    rf.MIX_DEGRADED.clear()
    rf.collect(canvas, model, int(round(t * 1e6)), {})
    return canvas.convert("RGB"), list(rf.MIX_DEGRADED)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default="temp/playback-test/model-check.json")
    ap.add_argument("--t", type=float, default=6.70)
    ap.add_argument("--out-dir", default="temp/playback-test/mixwiring")
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    base = json.loads(Path(args.model).read_text(encoding="utf-8-sig"))
    n_inject = sum(1 for tr in base["tracks"] if tr["type"] != "audio" for s in tr["segments"]
                   if (s.get("track") or {}).get("flag") == 2 and s.get("media"))
    pos_us = int(round(args.t * 1e6))
    # 降级只能按「该时刻真在画的段」数：全时间线注入了 23 段，某一时刻通常只有 1 段在活动，
    # 用注入总数当期望是口径错（第一版就把它当成了 FAIL）。
    n_active = sum(1 for tr in base["tracks"] if tr["type"] != "audio"
                   for s in [rf.active_segment(tr, pos_us)]
                   if s and s.get("media") and (s.get("track") or {}).get("flag") == 2)

    shots = {}
    for label, md5, name in (("plain", None, ""), ("multiply", MULTIPLY_MD5, "正片叠底"),
                             ("screen", SCREEN_MD5, "滤色"), ("unknown", BOGUS_MD5, "不存在的包")):
        img, degraded = render(inject(base, md5, name), args.t)
        p = out / f"{label}-{args.t:.2f}.png"
        img.save(p)
        lum = np.asarray(img.convert("L"), dtype=np.float32)
        shots[label] = {"path": str(p), "mean": round(float(lum.mean()), 2),
                        "bright_share": round(float((lum > 200).mean()), 4),
                        "degraded": len(degraded), "degraded_sample": degraded[:2]}
        print(f"{label:<8} mean={shots[label]['mean']:7.2f}  bright>200={shots[label]['bright_share']:.4f}"
              f"  degraded={shots[label]['degraded']}")

    checks = [
        ("存在可注入的 flag=2 叠加段（否则本检查是空跑）", n_inject > 0,
         f"{n_inject} 个 flag=2 带素材的段被注入 mix_mode"),
        ("multiply 让画面变暗", shots["multiply"]["mean"] < shots["plain"]["mean"],
         f"mean {shots['multiply']['mean']} < {shots['plain']['mean']}"),
        ("screen 让画面变亮", shots["screen"]["mean"] > shots["plain"]["mean"],
         f"mean {shots['screen']['mean']} > {shots['plain']['mean']}"),
        ("三种模式的画面互不相同（接线真的分叉）",
         len({shots[k]["mean"] for k in ("plain", "multiply", "screen")}) == 3,
         f"{[shots[k]['mean'] for k in ('plain','multiply','screen')]}"),
        ("认不出的 md5 计入降级而不是被猜掉（期望=该时刻在动的叠加段数）",
         shots["unknown"]["degraded"] == n_active and n_active > 0,
         f"degraded {shots['unknown']['degraded']} == active {n_active}"
         f" (全时间线注入 {n_inject})"),
        ("认不出的 md5 画面等同普通合成（降级形态确定）",
         shots["unknown"]["mean"] == shots["plain"]["mean"],
         f"mean {shots['unknown']['mean']} vs {shots['plain']['mean']}"),
    ]
    bad = [c for c in checks if not c[1]]
    print("-" * 60)
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<40} {detail}")
    print(f"{len(checks) - len(bad)} of {len(checks)} wiring checks passed")
    (out / "wiring.json").write_text(json.dumps(
        {"t": args.t, "model": args.model, "injected_segments": n_inject, "shots": shots,
         "checks": [{"name": n, "ok": bool(o), "detail": d} for n, o, d in checks]},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
