"""生成 `mixmode/a50-ref.json`：通道 2 在**图层不透明度**下的逐格参照表（P-62 的判据来源）。

为什么要有这个脚本而不是临时命令行：P-62 那条"浏览器 == 通道 2 的不透明度律"的结论，
判据是一张 17×17 参照表。表如果是一次性 `python -c` 敲出来的，下次没人能复现，
等价性就退化成了当时那一跑的口头断言。这张表**必须由通道 2 自己的 `blend()` 产出**——
第一轮我就是因为按公式手推了一个 `(fg+bg)/2` 的参照，把两条互斥假设"都验证成过"。

网格与 `temp/playback-test/mixmode-pixi.html` 里的生成式**必须一致**（改了那边要重跑这里）：
  LV[i] = round(i*255/16)，fg = (LV[x], LV[y], 128, 255)，bg = (LV[y], LV[x], 64, 255)

用法：
    python scripts/mixmode_opacity_reference.py [--opacity 0.5] [--out temp/playback-test/mixmode/a50-ref.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from mixmode_blend import SCALAR, blend  # noqa: E402

N = 17
# 与仪器页同一生成式：LV 是 0..255 的 17 级梯度
LV = [round(i * 255 / (N - 1)) for i in range(N)]
# 混合模式名 → mixmode_blend.SCALAR 的键（两边命名不同，这里只做显式映射，不猜）
MODES = {
    "multiply": "multiply", "screen": "screen", "overlay": "overlay",
    "softlight": "softlight", "colordodge": "colordodge", "colorburn": "colorburn",
    "darken": "darken", "lighten": "lighten", "hardlight": "hardlight",
    "linearburn": "linearburn",
}


def grids() -> tuple[np.ndarray, np.ndarray]:
    fg = np.zeros((N, N, 4), np.float32)
    bg = np.zeros((N, N, 4), np.float32)
    for y in range(N):
        for x in range(N):
            fg[y, x] = (LV[x], LV[y], 128, 255)
            bg[y, x] = (LV[y], LV[x], 64, 255)
    return fg / 255.0, bg / 255.0


def premul(a: np.ndarray) -> np.ndarray:
    return np.concatenate([a[..., :3] * a[..., 3:4], a[..., 3:4]], axis=-1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--opacity", type=float, default=0.5)
    ap.add_argument("--out", default="temp/playback-test/mixmode/a50-ref.json")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    fg, bg = grids()
    fgp, bgp = premul(fg), premul(bg)
    unknown = [v for v in MODES.values() if v not in SCALAR]
    if unknown:
        print(f"FAIL: mixmode_blend 缺少模式 {unknown}（命名漂移会被静默跳过，先撞死）")
        return 2
    out = {}
    for name, key in MODES.items():
        op = blend(key, fgp, bgp, fg_alpha=args.opacity)
        px = np.clip(op[..., :3] / np.maximum(op[..., 3:4], 1e-6), 0.0, 1.0)
        q = (px * 255.0 + 0.5).astype("uint8")
        a = np.clip(op[..., 3:4] * 255.0 + 0.5, 0, 255).astype("uint8")
        out[name] = np.concatenate([q, a], axis=-1).reshape(-1).tolist()
        print(f"{name:12s} opacity={args.opacity} first4={out[name][:4]}")
    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(out), encoding="utf-8")     # 原子写：读侧不会拿到半张表
    tmp.replace(p)
    print(f"modes={len(out)} -> {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
