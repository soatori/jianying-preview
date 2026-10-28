"""要求 1 的前半：把 MixMode 十个包的 GLSL 原文抽成可比对的清单。

为什么自研这一支：`mixmode_glsl.csv` 只记了「包 md5 ↔ 函数名 ↔ 文件路径」，没有把函数体本身
结构化出来，而数值等价比对需要的是**原文逐字**（转写成 JS 就是第二轮证据、会引入誊写误差）。
本脚本不改写、不重排 GLSL，只把 frag 原样复制到 temp/mixmode/frags/ 并记录 sha256，
比对脚本编译的是这份复制件，所以 oracle 与安装目录字节一致可查。

口径纪律：只读安装目录；每个包必须恰好一个 shaderGLES/*.frag，否则报错而不是取第一个。
`blendAlphaState/fgAlphaState/bgAlphaState` 三个 uniform 不在包内属性表里（属性表只有
inputWidth/inputHeight/_alpha/baseTex/_MainTex），所以走哪条 alpha 分支由引擎决定，不由包决定。

用法：
    python scripts/mixmode_extract.py [--install "<剪映安装目录>"]   # 缺省自动检测
                                      [--out-dir temp/mixmode]
输出：temp/mixmode/frags/<nameId>.frag + temp/mixmode/manifest.json
      docs/evidence/tables/mixmode_frag_manifest.csv
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
import jy_paths                                      # noqa: E402

FUNC_RE = re.compile(r"^\s*(?:float|vec4)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.M)
UNIFORM_RE = re.compile(r"^\s*uniform\s+\w+\s+(\w+)\s*;", re.M)
VARYING_RE = re.compile(r"^\s*varying\s+\w+\s+(\w+)\s*;", re.M)


def find_frag(pkg: Path) -> Path:
    frags = sorted(pkg.glob("Library/ShaderData/*/shaderGLES/*.frag"))
    if len(frags) != 1:
        raise SystemExit(f"{pkg.name}: expected exactly one shaderGLES frag, found {len(frags)}")
    return frags[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", default=None,
                    help="剪映安装目录（版本目录）；缺省由 scripts/jy_paths.py 自动检测")
    ap.add_argument("--out-dir", default=str(ROOT / "temp" / "mixmode"))
    ap.add_argument("--table", default=str(ROOT / "docs" / "evidence" / "tables" / "mixmode_frag_manifest.csv"))
    args = ap.parse_args()

    install = Path(args.install) if args.install else jy_paths.install_dir()
    mixdir = install / "Resources" / "MixMode"
    index = json.loads((mixdir / "MixMode.json").read_text(encoding="utf-8-sig"))
    out = Path(args.out_dir)
    (out / "frags").mkdir(parents=True, exist_ok=True)

    # 草稿侧中文名来自 F-049 的连接表（没有也不致命，只少一列）
    names: dict[str, str] = {}
    pkg_csv = ROOT / "docs" / "evidence" / "tables" / "mixmode_packages.csv"
    if pkg_csv.exists():
        with pkg_csv.open(encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                md5 = (row.get("package_md5") or row.get("path") or "").strip()
                zh = (row.get("draft_name_set") or "").strip()
                if md5 and zh:
                    names[md5] = zh

    records = []
    for item in index["resourceList"]:
        pkg = mixdir / item["path"]
        frag_path = find_frag(pkg)
        raw = frag_path.read_bytes()
        text = raw.decode("utf-8")
        cfg = json.loads((pkg / "config.json").read_text(encoding="utf-8-sig"))
        props = " ".join(re.findall(r"[ -~]{4,}", (pkg / "blend.material").read_bytes().decode("latin-1")))
        funcs = FUNC_RE.findall(text)
        # 一个包里可以有多个 *BlendPreMul（color_dodge 那包还带 NormalBlendPreMul），
        # 所以「本模式的函数」只能由 main() 里实际调用的那两条分支决定，不能按后缀取唯一。
        main_body = text[text.index("void main"):]
        called = [f for f in dict.fromkeys(funcs) if re.search(rf"\b{f}\s*\(", main_body)]
        premul = [f for f in called if f.endswith("BlendPreMul")]
        straight = [f for f in called if f.endswith("BlendStraight")]
        scalar = [f for f in funcs if not f.endswith("BlendPreMul") and not f.endswith("BlendStraight")]
        if len(premul) != 1 or len(straight) != 1:
            raise SystemExit(f"{item['nameId']}: main() should call one PreMul + one Straight, "
                             f"got premul={premul} straight={straight} (all funcs={funcs})")
        dest = out / "frags" / f"{item['nameId']}.frag"
        dest.write_bytes(raw)
        records.append({
            "nameId": item["nameId"],
            "effectId": item["effectId"],
            "resourceId": item["resourceId"],
            "package_md5": item["path"],
            "draft_name_zh": names.get(item["path"], ""),
            "frag_rel": str(frag_path.relative_to(pkg)).replace("\\", "/"),
            "frag_sha256": hashlib.sha256(raw).hexdigest(),
            "frag_bytes": len(raw),
            "config_alphaState": cfg.get("alphaState"),
            "config_version": cfg.get("version"),
            "material_props": props,
            "premul_fn": premul[0],
            "straight_fn": straight[0],
            "unused_premul_fns": [f for f in dict.fromkeys(funcs) if f.endswith("BlendPreMul") and f != premul[0]],
            "scalar_fns": scalar,
            "uniforms": re.findall(UNIFORM_RE, text),
            "varyings": re.findall(VARYING_RE, text),
            "has_branch_on_blendAlphaState": "blendAlphaState" in text,
            "frag_local": str(dest.relative_to(ROOT)).replace("\\", "/"),
        })

    manifest = {
        "install": str(install),
        "index_sha256": hashlib.sha256((mixdir / "MixMode.json").read_bytes()).hexdigest(),
        "packages": records,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    tbl = Path(args.table)
    with tbl.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["nameId", "effectId", "resourceId", "package_md5", "draft_name_zh", "premul_fn",
                    "straight_fn", "scalar_fns", "config_alphaState", "uniforms", "varyings",
                    "frag_sha256", "frag_bytes"])
        for r in records:
            w.writerow([r["nameId"], r["effectId"], r["resourceId"], r["package_md5"], r["draft_name_zh"],
                        r["premul_fn"], r["straight_fn"], "|".join(r["scalar_fns"]),
                        r["config_alphaState"], "|".join(r["uniforms"]), "|".join(r["varyings"]),
                        r["frag_sha256"], r["frag_bytes"]])

    print(f"{len(records)} packages from {install}")
    for r in records:
        print(f"  {r['nameId']:<12} {r['premul_fn']:<26} straight={str(r['straight_fn']):<26} "
              f"alphaState={r['config_alphaState']} sha={r['frag_sha256'][:8]} "
              f"uniforms={','.join(r['uniforms'])}")
    print(f"manifest -> {out / 'manifest.json'}")
    print(f"table    -> {tbl}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
