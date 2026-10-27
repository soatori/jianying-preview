"""把「还有 9 个动画预设没覆盖」变成一张**按段数加权的施工清单**。

为什么要它：U-91 记的是「9/12 不可求值」，但那是**预设个数**，不是**观众看得见的段数**。
本表按 `segments` 加权，并给出每个预设的**包内实物**（lua 数、shader pass 数、渲染目标数、贴图、
是否 AE/LightSpeed 导出件），据此定层级——决定「下一条该实现哪个」的是这个，不是名字。

层级口径（**写死在代码里，避免事后编故事**）：
  T0 已覆盖   `animation_curve.load_curve` 能解出轨道（当前只有纯 `fromTo` 那三个）。
  T1 只差求值 1 个 lua **且没有** `.frag`：曲线在 lua 里，解不出来是**读取器**的问题，
              本表会把「为什么解不出」一起报（没匹配到 fromTo / 属性名不在白名单 / 表达式不可求值）。
  T2 需要跑包内 shader 1 个 lua + ≥1 个 `.frag`：位移/透明度可以按曲线近似，
              但**画面效果**（模糊、曝光、遮罩）必须执行包内 GLSL，近似会静默失真。
  T3 需要脚本运行时 ≥3 个 lua，或 ≥2 个 `.frag`，或有 `.rt`（渲染目标链），
              或含 `.lsanim/.lsproj/.jsdat`（AE/LightSpeed 导出工程）——这类不是「补一条曲线」，
              是要么实现脚本 VM 语义、要么按包内 shader 重画，两者都超出曲线读取器。

口径：只读草稿与 `User Data/Cache/effect` 下的包目录，不写不回；`segments` 数的是**带该预设真条目**
的段数（与 L1 `stats.animation_segments` 同口径），不是引用数。

用法:
    python scripts/animation_tiers.py [--model temp/playback-test/model-check.json]
        [--table temp/playback-test/animation-curves.json]
        [--csv docs/evidence/tables/animation_tiers.csv]
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import animation_curve as ac  # noqa: E402

try:
    sys.stdout.reconfigure(errors="replace")     # type: ignore[attr-defined]
    sys.stderr.reconfigure(errors="replace")     # type: ignore[attr-defined]
except Exception:                                 # noqa: BLE001
    pass

SIGNS = ("fromTo", "onUpdate", "seek(", "checkDirty", "setTexture", "uniform", "Math.")
AE_MARKS = (".lsanim", ".lsproj", ".jsdat")

# 分层只看**包内实物**有个已知缺陷：`.frag` 的**数量**说明不了它**在做什么**。
# 实测（2026-10-24）向上露出的 frag 就一句 `texture2D(_MainTex,uv0) * step(uv.y, 1-(1-height_cut)*0.4)`
# —— 那是个**单均匀量驱动的行遮罩**，两条通道都能不跑 GLSL 直接实现（PIL 乘 alpha、Pixi 裁 alpha）。
# 所以再加一层**语义**判据：数 frag 里的采样次数、循环、邻域采样（模糊/卷积）、以及有没有 `.rt` 链。
# T2a = 只有 `texture2D` 一次且无循环 ⇒ 多半是 mask/混合类，**可移植到两通道**；
# T2b = 多次采样 / 有循环 / 有 `.rt` ⇒ 真要执行 GLSL（或接 offscreen GL）。
def frag_semantics(files: list[pathlib.Path]) -> dict:
    def read(f):
        return f.read_text(encoding="utf-8", errors="replace")
    frags = [f for f in files if f.suffix.lower() == ".frag"]
    verts = [f for f in files if f.suffix.lower() == ".vert"]
    ftext = [read(f) for f in frags]
    vtext = [read(f) for f in verts]
    joined = "\n".join(ftext + vtext)
    # **动画不一定在 frag 里**：向上露出 实测是 `.vert` 里 `uv0.y = (1.0-uv0.y) + eraseUV.y`
    # （贴图滚动）配 frag 里一条固定裁剪。只看 frag 的采样次数会把它归成「mask 类」——
    # 结论碰巧对，理由错，所以单独记一项：**uniform 有没有被用在顶点着色器的 uv 赋值里**。
    uv_assign = re.compile(r"uv0?\.\w\s*=[^;]*;", re.I)
    vert_scroll = 0
    for t in vtext:
        for stmt in uv_assign.findall(t):
            names = re.findall(r"uniform\s+\w+\s+(\w+)\s*;", t)
            if any(n in stmt for n in names):
                vert_scroll = 1
                break
    return {
        "tex_fetch": sum(t.count("texture2D(") for t in ftext),
        "loops": len(re.findall(r"\bfor\s*\(", joined)),
        "neighbor": len(re.findall(r"uv\s*[+\-]\s*[A-Za-z0-9_.]+\s*/", joined)),
        "passes": len(ftext) + len(vtext),
        "vert_scroll": vert_scroll,
    }


def why_not_evaluable(lua_text: str) -> str:
    """T1 的「差多少」要说清楚，否则下一轮又会重新猜一遍。"""
    if "fromTo" not in lua_text:
        return "lua 里没有 fromTo（不是 fromTo 族，得换读法）"
    props = sorted(set(re.findall(r"fromTo\s*\(\s*[A-Za-z_][\w.]*\s*,\s*([A-Za-z_.]+)", lua_text)))
    return "有 fromTo 但没解出轨道，目标属性=" + (",".join(props)[:70] or "未识别")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default="temp/playback-test/model-check.json")
    ap.add_argument("--table", default="temp/playback-test/animation-curves.json")
    ap.add_argument("--csv", default="docs/evidence/tables/animation_tiers.csv")
    args = ap.parse_args()

    model = json.loads(pathlib.Path(args.model).read_text(encoding="utf-8-sig"))
    table = {}
    tp = pathlib.Path(args.table)
    if tp.is_file():
        table = json.loads(tp.read_text(encoding="utf-8")).get("presets") or {}

    entries: dict[str, dict] = {}
    for tr in model["tracks"]:
        if tr["type"] == "audio":
            continue
        for s in tr["segments"]:
            for a in (s.get("animations") or []):
                key = str(a.get("resource_id") or a.get("path"))
                e = entries.setdefault(key, {"name": a.get("name"), "kinds": set(),
                                             "path": a.get("path") or "", "segments": 0,
                                             "dur_us": a.get("duration_us")})
                e["segments"] += 1
                if a.get("kind"):
                    e["kinds"].add(a["kind"])

    rows = []
    for key, e in entries.items():
        p = pathlib.Path(e["path"])
        d = p if p.is_dir() else p.parent
        files = [f for f in d.rglob("*") if f.is_file()] if d.is_dir() else []
        exts = collections.Counter(f.suffix.lower() for f in files)
        luas = sorted(f for f in files if f.suffix.lower() == ".lua")
        lua_text = "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in luas) \
            if luas else ""
        tracks = ac.load_curve(e["path"])
        props = sorted({t["prop"] for t in tracks}) if tracks else []
        sem = frag_semantics(files)
        if tracks:
            tier = "T0"
        elif exts.get(".frag", 0) == 0 and len(luas) <= 1:
            tier = "T1"
        elif len(luas) >= 3 or exts.get(".frag", 0) >= 2 or exts.get(".rt", 0) or \
                any(exts.get(m, 0) for m in AE_MARKS):
            tier = "T3"
        else:
            tier = "T2"
        # 语义细分：只有 T2 值得问「这个 shader 到底要不要真跑」
        if tier == "T2":
            tier = "T2a" if (sem["tex_fetch"] <= 1 and not sem["loops"] and not sem["neighbor"]) \
                else "T2b"
        rows.append({
            "name": e["name"], "tier": tier, "segments": e["segments"],
            "kinds": "+".join(sorted(e["kinds"])), "dur_ms": round((e["dur_us"] or 0) / 1000, 1),
            "lua": len(luas), "frag": exts.get(".frag", 0), "rt": exts.get(".rt", 0),
            "mesh": exts.get(".mesh", 0), "png": exts.get(".png", 0) + exts.get(".jpg", 0),
            "ae_export": int(any(exts.get(m, 0) for m in AE_MARKS)),
            "tex_fetch": sem["tex_fetch"], "loops": sem["loops"], "neighbor": sem["neighbor"],
            "vert_scroll": sem["vert_scroll"],
            "props": "|".join(props), "dir_exists": int(d.is_dir()),
            "signs": "+".join(f"{k}:{lua_text.count(k)}" for k in SIGNS if k in lua_text),
            "why": "" if tracks else why_not_evaluable(lua_text),
        })

    order = {"T0": 0, "T1": 1, "T2a": 2, "T2b": 3, "T3": 4}
    rows.sort(key=lambda r: (order[r["tier"]], -r["segments"], r["name"] or ""))
    tot = sum(r["segments"] for r in rows)
    print(f"预设 {len(rows)} 个 / 带动画的段 {tot} 段（口径：带真条目的段，非引用数）")
    by_t = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        by_t[r["tier"]][0] += 1
        by_t[r["tier"]][1] += r["segments"]
    for t in ("T0", "T1", "T2a", "T2b", "T3"):
        n, sg = by_t.get(t, (0, 0))
        print(f"  {t:3s}: {n:2d} 个预设 / {sg:3d} 段  ({sg * 100 // max(1, tot)}% 的动画段)")
    print("-" * 92)
    for r in rows:
        print(f'{r["tier"]:3s} {str(r["name"]):<11s} 段={r["segments"]:3d} {r["kinds"]:<3s} '
              f'{r["dur_ms"]:>6.1f}ms lua={r["lua"]} frag={r["frag"]:2d} rt={r["rt"]:2d} '
              f'png={r["png"]} AE={r["ae_export"]} 采样={r["tex_fetch"]:2d} 循环={r["loops"]} '
              f'邻域={r["neighbor"]} 顶点滚动={r["vert_scroll"]}')
        if r["props"]:
            print(f'      属性: {r["props"]}')
        if r["why"]:
            print(f'      未覆盖原因: {r["why"]}  签名={r["signs"] or "-"}')

    out = pathlib.Path(args.csv)
    if out.parent.is_dir():
        cols = ["tier", "name", "segments", "kinds", "dur_ms", "lua", "frag", "rt", "mesh",
                "png", "ae_export", "tex_fetch", "loops", "neighbor", "vert_scroll",
                "props", "signs", "why",
                "dir_exists"]
        tmp = out.with_suffix(".tmp")
        tmp.write_text(",".join(cols) + "\n" + "\n".join(
            ",".join('"' + str(r[c]).replace('"', "'") + '"' for c in cols) for r in rows),
            encoding="utf-8")
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp.replace(out)
        print(f"table -> {out}")
    else:
        print(f"（{out.parent} 不存在，跳过 CSV）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
