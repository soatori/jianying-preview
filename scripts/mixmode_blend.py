"""通道 2（无浏览器）的混合模式实现：按剪映包内 `*BlendPreMul` 的**预乘支**逐式实现。

来源与验证口径（重要）：本文件是**手抄**，抄的是
`Resources/MixMode/<包 md5>/Library/ShaderData/*/shaderGLES/*.frag` 里的预乘分支
（原文切片在 `temp/playback-test/mixmode/frags/`，sha256 记在
`docs/evidence/tables/mixmode_frag_manifest.csv`；出厂 GLSL 由 `scripts/mixmode_shaders.py` 生成）。
手抄不能自证，所以判据是 `scripts/mixmode_equivalence.py`：同一批 8-bit 输入同时喂
「包内原文在 GPU 上执行」与「本文件的 numpy 结果」，逐通道比 8-bit 差，阈值 1/255。
浏览器分支的归属仍未判（U-90）：我们固定走预乘支，因为我们的纹理自己保证是预乘的。

口径：所有数组都是 **premultiplied** RGBA，float32 0..1；`alpha` 用包内同一式
`fa + ba - fa*ba`。`fg_alpha`（面板不透明度）按包内 `fg *= min(_alpha,1.0)` 整支缩放，
即前景的颜色与 alpha 一起乘。
"""
from __future__ import annotations

import numpy as np

EPS = 1e-6

# 包 md5 -> 厂商函数名（切片生成器与清单共用同一键，见 mixmode_frag_manifest.csv）
MODE_BY_FUNCTION = {
    "MultiplyBlendPreMul": "multiply",
    "ScreenBlendPreMul": "screen",
    "DarkenBlendPreMul": "darken",
    "LightenBlendPreMul": "lighten",
    "OverlayBlendPreMul": "overlay",       # 注意：包内按**背景**分支，等于 CSS hard-light（F-077）
    "HardLightBlendPreMul": "hardlight",   # 包内按**前景**分支，等于 CSS overlay（F-077）
    "SoftLightBlendPreMul": "softlight",
    "ColorDodgeBlendPreMul": "colordodge",
    "ColorBurnBlendPreMul": "colorburn",
    "LinearBurnBlendPreMul": "linearburn",
}


def _over(f, b, fa, ba):
    """包里三条公共项：fg 独占 + bg 独占 + 两者共有的混合项基底。"""
    return f * (1.0 - ba) + b * (1.0 - fa)


def _screen(f, b, fa, ba):
    return f + b - f * b


def _multiply(f, b, fa, ba):
    return _over(f, b, fa, ba) + f * b


def _darken(f, b, fa, ba):
    return _over(f, b, fa, ba) + np.minimum(f * ba, b * fa)


def _lighten(f, b, fa, ba):
    return _over(f, b, fa, ba) + np.maximum(f * ba, b * fa)


def _linearburn(f, b, fa, ba):
    return _over(f, b, fa, ba) + np.maximum(f * ba + b * fa - fa * ba, 0.0)


def _overlay(f, b, fa, ba):
    # 包内 OverlayPreMul：分支条件 2.0*bc < ba（看背景）
    lo = f * (1.0 - ba) + b * (1.0 - fa) + 2.0 * f * b
    hi = f * (1.0 + ba) + b * (1.0 + fa) - 2.0 * f * b - fa * ba
    return np.where(2.0 * b < ba, lo, hi)


def _hardlight(f, b, fa, ba):
    # 包内 HardLightPreMul：分支条件 2.0*fc < fa（看前景），体与 Overlay 同
    lo = f * (1.0 - ba) + b * (1.0 - fa) + 2.0 * f * b
    hi = f * (1.0 + ba) + b * (1.0 + fa) - 2.0 * f * b - fa * ba
    return np.where(2.0 * f < fa, lo, hi)


def _softlight(f, b, fa, ba):
    t = b / np.maximum(ba, EPS)
    lo = f * (1.0 - ba) + b * (1.0 - fa) + b * (fa + (2.0 * f - fa) * (1.0 - t))
    hi = (f * (1.0 - ba) + b * (1.0 + fa)
          + np.sqrt(np.maximum(t, 0.0)) * (2.0 * f * ba - fa * ba) - 2.0 * f * b)
    return np.where(2.0 * f <= fa, lo, hi)


def _colordodge(f, b, fa, ba):
    t = np.maximum(ba * (fa - f), EPS)
    general = f * (1.0 - ba) + b * (1.0 - fa) + fa * ba * np.minimum(1.0, b * fa / t)
    both = np.where(b == 0.0, f * (1.0 - ba) + fa * ba,
                    f * (1.0 - ba) + b * (1.0 - fa) + fa * ba)
    return np.where(f == fa, both, general)


def _colorburn(f, b, fa, ba):
    t = np.maximum(f * ba, EPS)
    general = (f * (1.0 - ba) + b * (1.0 - fa)
               + fa * ba * (1.0 - np.minimum(1.0, (ba - b) * fa / t)))
    both = np.where(b == ba, b * (1.0 - fa) + fa * ba, b * (1.0 - fa))
    return np.where(f == 0.0, both, general)


SCALAR = {
    "multiply": _multiply, "screen": _screen, "darken": _darken, "lighten": _lighten,
    "overlay": _overlay, "hardlight": _hardlight, "softlight": _softlight,
    "colordodge": _colordodge, "colorburn": _colorburn, "linearburn": _linearburn,
}


def blend(mode: str, fg: np.ndarray, bg: np.ndarray, fg_alpha: float = 1.0) -> np.ndarray:
    """fg 按 mode 叠在 bg 上。两者都是 (..., 4) float32 预乘 RGBA，返回同形状预乘。

    `fg_alpha` 是面板不透明度：包内预乘支是 `fg *= min(_alpha,1.0)`，颜色和 alpha 一起缩。
    """
    fn = SCALAR.get(mode)
    if fn is None:
        raise KeyError(f"unknown mix mode {mode!r}; have {sorted(SCALAR)}")
    f = np.asarray(fg, dtype=np.float32) * np.float32(min(max(fg_alpha, 0.0), 1.0))
    b = np.asarray(bg, dtype=np.float32)
    fa, ba = f[..., 3:4], b[..., 3:4]
    out = np.empty_like(f)
    for k in range(3):
        out[..., k] = fn(f[..., k], b[..., k], fa[..., 0], ba[..., 0])
    out[..., 3] = (fa + ba - fa * ba)[..., 0]
    return np.clip(out, 0.0, 1.0)


def resolve_mode(mix_mode: dict | None, manifest: dict | None = None) -> str | None:
    """把 L1 的 `segments[].mix_mode` 解成本文件的模式名。

    直连键是包 md5（F-049：`effects[].path` 尾段 ↔ `MixMode.json` 的 `path`）。
    解析不出来（比如那两种无本地包的模式：差值/颜色滤镜）就返回 None —— 调用方必须显式降级，
    不许静默当正常层画。
    """
    if not mix_mode:
        return None
    md5 = mix_mode.get("package_md5")
    if manifest is not None:
        for pkg in manifest.get("packages") or []:
            if pkg.get("package_md5") == md5:
                return MODE_BY_FUNCTION.get(pkg.get("premul_fn"))
    fn = (mix_mode.get("premul_fn") or "")
    return MODE_BY_FUNCTION.get(fn)
