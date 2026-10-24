"""生成「我们真正出厂的」混合模式着色器与 JS/Python 两套实现，并留可核对的来源证明。

为什么不誊写公式：F-077 的判据是「与剪映包内 `*BlendPreMul` 数值等价」。等价的对象如果是
我们自己重写的一份 GLSL，就得先证明重写没走样——那是第二轮证据。所以本脚本**切片而不改写**：
从包内 `.frag` 原文里取出「文件头 + 到该模式 `vec4 XBlendPreMul(...)` 结束的右括号」这一段，
逐字节保留，然后接上我们自己的 `main()`（我们的 uniform 装载方式、固定走预乘分支）。
出厂件与包内数学同源，sha256 可核对；差异只剩「谁给 baseTex/_MainTex、alpha 状态怎么给」，
而那正是 `mixmode_equivalence.py` 要在 GPU 上逐 texel 判的东西。

同时产一份 numpy 实现（`scripts/mixmode_blend.py` 消费的形状表），给通道 2 用；
那份是**手抄**，所以必须由同一个比对台验，不能自证。

用法：
    python scripts/mixmode_shaders.py [--frags temp/playback-test/mixmode]
输出：temp/playback-test/mixmode/frags-shipped/<nameId>.frag
      temp/playback-test/mixmode-blend.mjs         （浏览器出厂件）
      docs/evidence/tables/mixmode_shipped.csv     （包内 sha ↔ 出厂件 sha ↔ 保留的字节数）
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path
# Windows 控制台是 GBK：读数里带中文/箭头/替换符时 print 会在最后一步抛错，
# 把已经算完的结果整个吞掉（本轮自己的统计工具就栽过一次）。只改错误处理策略，不改编码。
try:
    sys.stdout.reconfigure(errors="replace")     # type: ignore[attr-defined]
    sys.stderr.reconfigure(errors="replace")     # type: ignore[attr-defined]
except Exception:                                 # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent

# 我们的 main：只做「取两层预乘纹理、按 _alpha 缩前景、交给包内函数」。
# 与包内 main() 预乘支的差别是刻意的：不读 blendAlphaState/fgAlphaState/bgAlphaState
# （引擎侧的 alpha 状态归属未判，见 U-90），因为我们自己保证送进去的是预乘值。
OUR_MAIN = """
// ---- our packaging: premultiplied inputs only, no engine alpha-state uniforms ----
void main(void) {
    vec2 fuv = uv0.xy / max(uv0.z, 1e-6);
    vec4 bg = texture2D(baseTex, uv1);
    vec4 fg = texture2D(_MainTex, fuv) * min(_alpha, 1.0);
    gl_FragColor = %s(fg, bg);
}
"""


def slice_premul(text: str, fn: str) -> str:
    """返回 text[0 : 该函数右括号之后]，不改写任何字符。"""
    m = re.search(rf"vec4\s+{re.escape(fn)}\s*\([^)]*\)\s*\{{", text)
    if not m:
        raise SystemExit(f"cannot locate vec4 {fn}")
    i = text.index("{", m.start())
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[: j + 1]
    raise SystemExit(f"unbalanced braces in {fn}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frags", default=str(ROOT / "temp" / "playback-test" / "mixmode"))
    args = ap.parse_args()
    src = Path(args.frags)
    manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    shipped = src / "frags-shipped"
    shipped.mkdir(parents=True, exist_ok=True)

    entries, rows = {}, []
    for pkg in manifest["packages"]:
        text = (src / "frags" / f"{pkg['nameId']}.frag").read_text(encoding="utf-8")
        head = slice_premul(text, pkg["premul_fn"])
        frag = head + "\n" + (OUR_MAIN % pkg["premul_fn"])
        dest = shipped / f"{pkg['nameId']}.frag"
        dest.write_text(frag, encoding="utf-8")
        entries[pkg["package_md5"]] = {
            "name_id": pkg["nameId"],
            "draft_name_zh": pkg.get("draft_name_zh") or "",
            "premul_fn": pkg["premul_fn"],
            "vendor_sha256": pkg["frag_sha256"],
            "shipped_sha256": hashlib.sha256(frag.encode("utf-8")).hexdigest(),
            "kept_bytes": len(head.encode("utf-8")),
            "frag": frag,
        }
        rows.append([pkg["nameId"], pkg["package_md5"], pkg.get("draft_name_zh") or "",
                     pkg["premul_fn"], pkg["frag_sha256"][:16],
                     hashlib.sha256(frag.encode("utf-8")).hexdigest()[:16],
                     len(head.encode("utf-8")), len(frag.encode("utf-8"))])

    mjs = Path(ROOT) / "temp" / "playback-test" / "mixmode-blend.mjs"
    mjs.write_text(
        "// 出厂混合模式表：由 scripts/mixmode_shaders.py 从剪映 MixMode 包内 GLSL 切片生成，\n"
        "// 不要手改。键是草稿 materials.effects[].path 尾段的包 md5（F-049 的直连键）。\n"
        "// vendor_sha256 对得上 temp/playback-test/mixmode/manifest.json 里的原文哈希。\n"
        "export const MIXMODE = " + json.dumps(
            {k: {kk: vv for kk, vv in v.items() if kk != "frag"} for k, v in entries.items()},
            ensure_ascii=False, indent=2) + ";\n"
        "export const MIXMODE_FRAGMENTS = " + json.dumps(
            {k: v["frag"] for k, v in entries.items()}, ensure_ascii=False, indent=2) + ";\n"
        "export function mixmodeFor(pkgMd5) {\n"
        "  return MIXMODE[pkgMd5] ? { ...MIXMODE[pkgMd5], frag: MIXMODE_FRAGMENTS[pkgMd5] } : null;\n"
        "}\n", encoding="utf-8")

    tbl = ROOT / "docs" / "evidence" / "tables" / "mixmode_shipped.csv"
    with tbl.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["name_id", "package_md5", "draft_name_zh", "premul_fn", "vendor_sha16",
                    "shipped_sha16", "kept_bytes", "shipped_bytes"])
        w.writerows(rows)

    print(f"{len(entries)} shipped fragments -> {shipped}")
    print(f"js module -> {mjs}")
    print(f"table     -> {tbl}")
    for r in rows:
        print(f"  {r[0]:<20} {r[3]:<26} kept={r[6]:>5}B shipped={r[7]:>5}B vendor={r[4]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
