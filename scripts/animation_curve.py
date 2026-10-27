"""从预设包内的 lua 里读出入场动画的 tween 声明，并求某一局部时刻的值。

为什么不手抄数字：曲线值（0.1 s、1.5 倍、`2.66 * textureH / screenH`、`quadOut`）都在包内明文 lua 的
`tween:fromTo(target, {from}, {to}, dur, Amaz.Ease.x, ...)` 里。手抄一遍就等于把「与剪映一致」
这句话降级成「我以为一致」。本模块只做**读取与求值**，真正的裁判是成片：
`scripts/animation_gap.py` 在实现前后各测一遍，窗内分布不动就是没做对。

已知的三条边界（都必须写清楚，不然会被当成普适能力）：
  1. **只覆盖用 `fromTo` 声明的预设**。本时间线 14 个预设里只有 3 个命中
     （向下滑动/缩小/渐显），其余 11 个走 AE 导出脚本或 `onUpdate` 里的显式数学，
     本模块对它们返回空 —— 调用方必须按「未实现」处理，不许拿近似曲线顶上。
  2. **tween 时长 ≠ 素材的 `duration`**。包内是 0.1 s（=3 帧 @30fps），
     而 `material_animations[].duration` 是 0.5 s（面板给的预设槽长）。P-30 用 0.5 s 窗量，
     等于把 3 帧的差摊到 15 帧上，中位数当然不动。
  3. **`Amaz.Ease.quadOut` 的函数式按标准二次缓出实现**（`t*(2-t)`），这是假设而不是取证：
     引擎的 Ease 表不在包内。方向与量纲（`localPosition` 的 y 用 ±1=半画幅解释）同样由成片判。

用法：
    from animation_curve import load_curve, value_at
    c = load_curve(pathlib.Path(pkg_path), name="向下滑动")
    v = value_at(c, t_in_segment=0.04, out_px=(1080, 1920), texture_h=1080)
"""
from __future__ import annotations

import pathlib
import re

FT_RE = re.compile(
    r"fromTo\(\s*(?P<tgt>[A-Za-z_][\w.\[\]]*)\s*,\s*\{(?P<fr>[^}]*)\}\s*,\s*\{(?P<to>[^}]*)\}"
    r"\s*,\s*(?P<dur>[0-9.]+)\s*,\s*Amaz\.Ease\.(?P<ease>[A-Za-z]+)", re.S)
PROP_RE = re.compile(r"\[\"([^\"]+)\"\]")   # lua 写成 {["_alpha"] = 0.0}：键在中括号里的双引号中
NUM_RE = re.compile(r'-?\d+(?:\.\d+)?')
VEC_RE = re.compile(r'Vector3f\(\s*([^)]*)\)')

TARGET_ALIAS = {
    "_alpha": "alpha", "alpha": "alpha",
    "localScale": "scale", "localPosition": "position",
}

# 二次缓出：0→1，前快后慢。见模块文档第 3 条——这是假设，由成片判。
EASE = {
    "quadOut": lambda t: t * (2.0 - t),
    "quadIn": lambda t: t * t,
    "linear": lambda t: t,
}


def _num(text: str, default: float = 1.0) -> float:
    m = NUM_RE.search(text)
    return float(m.group(0)) if m else default


def _vec(text: str) -> list[float]:
    m = VEC_RE.search(text)
    if not m:
        return [_num(text), _num(text), _num(text)]
    parts = [p.strip() for p in m.group(1).split(",")]
    out = []
    for p in parts:
        v = NUM_RE.search(p)
        out.append(float(v.group(0)) if v else 0.0)
    while len(out) < 3:
        out.append(0.0)
    return out[:3]


def _expr_value(text: str) -> tuple[float, str | None]:
    """返回 (字面常量, 待求表达式)。

    `localPosition` 的分量**按用途取**：位移用 y（第二个分量，lua 里 `Vector3f(0.0, 2.66 *
    textureH / screenH, 0.0)` 就是「从上方 2.66 个单位处滑下」），缩放/透明度用第一个分量。
    取第一个分量当位移是第一版的错——它恒为 0.0，于是位移动画看起来「实现了」其实一动不动。
    """
    m = re.search(r'=\s*Amaz\.Vector3f\(([^)]*)\)', text)
    if not m:
        mm = re.search(r'=\s*(-?[0-9.]+)', text)
        return (float(mm.group(1)) if mm else 1.0), None
    parts = [s.strip() for s in m.group(1).split(",")]
    # 判断用途：看属性名（调用方传的 fr 里带键名）
    use_y = bool(re.search(r'localPosition|position', text))
    pick = parts[1] if (use_y and len(parts) > 1) else (parts[0] if parts else "0")
    if re.fullmatch(r'-?\d+(?:\.\d+)?', pick):
        return float(pick), None
    return 0.0, pick


def _simple_arith(expr: str, names: dict[str, float]) -> float | None:
    """只认 `k`、`k*NAME`、`k*NAME/NAME` 三种式子；别的返回 None（= 不猜）。

    不用 eval：表达式来自磁盘上的包内文件，把文件内容当代码执行不是本项目该有的一面
    （而且我们只需要这三形，见 TopIn.lua 的 `2.66 * textureH / screenH`）。
    """
    e = expr.replace(" ", "")
    for pat, keys in (
        (r"^([0-9.]+)\*([A-Za-z_]\w*)/([A-Za-z_]\w*)$", 3),
        (r"^([0-9.]+)\*([A-Za-z_]\w*)$", 2),
        (r"^([0-9.]+)$", 1),
    ):
        m = re.match(pat, e)
        if not m:
            continue
        g = m.groups()
        if keys == 1:
            return float(g[0])
        if keys == 2:
            v = names.get(g[1])
            return float(g[0]) * v if v is not None else None
        a, b = names.get(g[1]), names.get(g[2])
        if a is None or b is None or b == 0:
            return None
        return float(g[0]) * a / b
    return None


def load_typewriter(pkg_path: str | pathlib.Path) -> dict | None:
    """读「打字光标」那两张**写死在 lua 里**的节奏表（F-087）。

    它不是 `fromTo`，也不是随机数：`refreshrandomTime` 取
    `random_tween_time` / `random_tween_time1` 之一，按 `(i-1) % len` 循环铺到每个字上再归一化。
    表是常量 ⇒ **可以逐帧精确复现**，这点决定了这块欠口值不值得做。
    """
    p = pathlib.Path(pkg_path)
    d = p if p.is_dir() else p.parent
    if not d.is_dir():
        return None
    tables: dict[str, list[float]] = {}
    for f in sorted(d.glob("*.lua")):
        text = f.read_text(encoding="utf-8", errors="replace")
        for name, body in re.findall(r"\b(random_tween_time1?)\s*=\s*\{([^}]*)\}", text):
            vals = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", body)]
            if vals:
                tables[name] = vals
    if "random_tween_time" not in tables:
        return None
    return tables


def typewriter_prefix(tw: dict, t_in_seg: float, dur_s: float, n_chars: int) -> int:
    """这条时刻**可见的前缀字数**。

    口径（全部来自包内 lua 原文）：
      选表  `duration/oriCount >= 0.15` ⇒ `random_tween_time1`，否则 `random_tween_time`；
      铺表  第 i 个字取 `table[(i-1) % len]`，整条按 Σ=1 归一化；
      可见  `checkDirty` 把每个字的 alpha 设成 `getCharPt(i, 1.2*time/duration)`，
            而 `getCharPt` 返回 `tt > 0.9 and 1.0 or 0.0`，`tt` 是该字自己槽位内的进度
            ⇒ 第 i 字可见 ⇔ `1.2·t/dur >= Σ_{j<i} w_j + 0.9·w_i`。
      该式对 i **单调**，所以可见集合恰好是一个前缀 ⇒ 两通道都能用「只画前 k 个字」实现，
      不需要逐字 alpha、也不需要跑包内 GLSL（`getcuralpha`/`onUpdate` 在包里都是**空函数**，
      `curalpha` 是**光标 sprite** 的透明度，不是文字的）。
    """
    if n_chars <= 0 or dur_s <= 0:
        return 0
    table = tw["random_tween_time1"] if dur_s / n_chars >= 0.15 else tw["random_tween_time"]
    w = [table[i % len(table)] for i in range(n_chars)]
    total = sum(w)
    tau = 1.2 * t_in_seg / dur_s
    acc, k = 0.0, 0
    for wi in w:
        if tau >= acc + 0.9 * wi / total:
            k += 1
            acc += wi / total
        else:
            break
    return k


def load_curve(pkg_path: str | pathlib.Path, lua_names: tuple[str, ...] = ()) -> list[dict]:
    """读包内 lua，取出 `fromTo` 声明。找不到返回 []（= 该预设未实现，不是返回恒等曲线）。"""
    p = pathlib.Path(pkg_path)
    if not p.is_dir():
        return []
    luas = sorted(list(p.glob("*.lua")) + list(p.glob("lua/**/*.lua")))
    if lua_names:
        luas = [q for q in luas if q.name in lua_names]
    tracks = []
    for q in luas:
        text = q.read_text(encoding="utf-8", errors="replace")
        for m in FT_RE.finditer(text):
            fr, to = m.group("fr"), m.group("to")
            pm = PROP_RE.search(fr)
            prop = pm.group(1) if pm else None
            if prop not in TARGET_ALIAS:
                continue
            dur = float(m.group("dur"))
            f_const, f_expr = _expr_value(fr)
            t_const, _ = _expr_value(to)
            tracks.append({
                "prop": TARGET_ALIAS[prop],
                "lua_prop": prop,
                "from": f_const, "to": t_const,
                "from_expr": f_expr,
                "dur_s": dur,
                "delay_s": 0.0,
                "ease": m.group("ease"),
                "src": q.name,
            })
    return tracks


def value_at(tracks: list[dict], t_in_segment: float, out_px: tuple[int, int],
             texture_h: float | None = None) -> dict:
    """局部时刻 → {alpha, scale_x, scale_y, dy_norm}。dy_norm 用 ±1 = 半画幅解释（与 clip 同系）。"""
    v = {"alpha": 1.0, "scale_x": 1.0, "scale_y": 1.0, "dy_norm": 0.0, "applied": []}
    for tr in tracks:
        e = EASE.get(tr["ease"], EASE["linear"])
        t = (t_in_segment - tr["delay_s"]) / max(tr["dur_s"], 1e-6)
        if t <= 0.0:
            frac = 0.0
        elif t >= 1.0:
            frac = 1.0
        else:
            frac = e(t)
        if tr["prop"] == "alpha":
            a = tr["from"] + (tr["to"] - tr["from"]) * frac
            v["alpha"] = min(v["alpha"], max(0.0, min(1.0, a)))
        elif tr["prop"] == "scale":
            s = tr["from"] + (tr["to"] - tr["from"]) * frac
            v["scale_x"] = min(v["scale_x"], s)
            v["scale_y"] = min(v["scale_y"], s)
        elif tr["prop"] == "position":
            base = tr["from"]
            if tr["from_expr"]:
                got = _simple_arith(tr["from_expr"], {
                    "textureH": float(texture_h or 0.0),
                    "screenH": float(out_px[1] or 0.0),
                })
                if got is None:              # 式子超出我们认的三形 => 这条轨迹不猜
                    continue
                base = got
            y = base * (1.0 - frac) + tr["to"] * frac
            v["dy_norm"] = y
        v["applied"].append(f"{tr['prop']}:{tr['ease']}:{tr['dur_s']}s")
    return v


def covered(tracks: list[dict]) -> set[str]:
    return {t["prop"] for t in tracks}


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="读预设包内 lua 的 tween 声明（不手抄曲线值）")
    ap.add_argument("pkg", nargs="?", help="单个预设包目录：打印它的曲线")
    ap.add_argument("--dump-table", metavar="MODEL", help="从 L1 模型抽出全部曲线，导成浏览器可用的表")
    ap.add_argument("--out", default="temp/playback-test/animation-curves.json")
    args = ap.parse_args()

    if args.dump_table:
        model = json.loads(pathlib.Path(args.dump_table).read_text(encoding="utf-8-sig"))
        table: dict[str, dict] = {}
        n_all = n_cov = 0
        for tr in model["tracks"]:
            if tr["type"] == "audio":
                continue
            for s in tr["segments"]:
                an = s.get("animations") or []
                if not an:
                    continue
                n_all += 1
                a = an[0]
                trks = load_curve(a.get("path") or "")
                if not trks:
                    continue
                n_cov += 1
                key = str(a.get("resource_id") or a.get("path"))
                table[key] = {
                    "name": a.get("name"), "kind": a.get("kind"),
                    "duration_us": a.get("duration_us"), "start_us": a.get("start_us"),
                    "tracks": [{k: t[k] for k in ("prop", "from", "to", "from_expr", "dur_s", "ease")}
                               for t in trks],
                }
        out = pathlib.Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"presets": table, "segments_with_animations": n_all,
                                   "segments_covered": n_cov}, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        print(f"{len(table)} presets -> {out}  覆盖 {n_cov}/{n_all} 段"
              f"（未覆盖的段在浏览器里保持静态态，不猜）")
    elif args.pkg:
        tk = load_curve(args.pkg)
        print(json.dumps({"tracks": tk, "covered": sorted(covered(tk))}, ensure_ascii=False, indent=1))
    else:
        ap.print_help()
