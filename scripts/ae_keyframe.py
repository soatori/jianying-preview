"""读 AE 导出动画包里的 `ae_attribute` 关键帧表，并**照 lua 原样**求值。

为什么要有这条：`animation_tiers.py` 把「向上闪入」判成 T3（≥3 lua / ≥2 frag / 有 .rt），
理由是「要脚本运行时」。但本包的 `SeekModeScript.lua` 里**时间律是明文表**
（`ADBE_Exposure2` 等 6 条，每条 = 贝塞尔控制点 + 帧区间 + 值区间），脚本自己只是
「把 curTime 折进 0..1，再查表」。所以这条族不是不可读，是**我们的读取器只认 fromTo**。
`spec/animations.yaml` 里那句「T3 要先证明移植与包内脚本输出一致」在这里怎么满足？
机器上没有 lua 解释器（`lua`/`luajit`/`lupa` 均无），所以本工具不执行 lua，而是：
  ①表名/常数/关键帧**全部机械解析**（不誊写：`ae_progress` 的 `21/49`、`mod` 的 `0.0001`
    都是从源码正则取出并断言存在）；
  ②`GetVal` 的贝塞尔与二分逐条对齐 lua 原文（`_remap01`/`_cubicBezier`/`_getBezier01X`/`_mix`）；
  ③**外部校验交给成片**：预测的亮度增益 2^E 与成片逐帧均值亮度比形状（见 flash_check）。
证据等级：②是「逐条对齐的手移植，未经执行验证」；③过了才升级为「与原生输出一致」。

用法：
    python scripts/ae_keyframe.py --t 0,0.033,0.1 --duration 0.3
    python scripts/ae_keyframe.py --dump-times        # 只报解析到的表与常数
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:                                      # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parents[1]
DEF_PKG = (Path.home() / "AppData/Local/JianyingPro/User Data/Cache/effect"
           / "7273389803532456504/ecaffca7c7e1d7744fa296a29f65b366"
           / "AmazingFeature/lua/SeekModeScript.lua")


# ---------------------------------------------------------------- lua 表解析
def lua_table(text: str, pos: int):
    """解析一个 `{...}`，返回 (value, 新位置)。值只有 数 / 字符串 / 表 三种。"""
    assert text[pos] == "{", f"期望 '{{' 于 {pos}: {text[pos:pos+20]!r}"
    pos += 1
    items: list = []
    while True:
        while pos < len(text) and text[pos] in " \t\r\n;,":
            pos += 1
        if pos >= len(text):
            raise ValueError("lua 表未闭合")
        if text[pos] == "}":
            return items, pos + 1
        if text[pos] == "[":                      # ["NAME"] = ...
            m = re.match(r'\["([^"]*)"\]\s*=', text[pos:])
            assert m, f"键语法不认识: {text[pos:pos+40]!r}"
            pos += m.end()
            while pos < len(text) and text[pos] in " \t\r\n":
                pos += 1
            v, pos = lua_table(text, pos)
            items.append((m.group(1), v))
            continue
        if text[pos] == "{":
            v, pos = lua_table(text, pos)
            items.append(v)
            continue
        if text[pos] in "\"'":
            q = text[pos]
            end = text.index(q, pos + 1)
            items.append(text[pos + 1:end])
            pos = end + 1
            continue
        m = re.match(r"[-+0-9.eE]+", text[pos:])
        assert m, f"值语法不认识: {text[pos:pos+40]!r}"
        items.append(float(m.group(0)))
        pos += m.end()


def strip_lua_comments(src: str) -> str:
    """去掉 `--[[ … ]]` 块注释与 `--` 行注释。不先去注释，解析器会把注释里的
    `--` 当数字（`could not convert string to float: '--'`），把好包误判成解析失败。"""
    src = re.sub(r"--\[(=*)\[[\s\S]*?\]\1\]", " ", src)
    return re.sub(r"--[^\n]*", "", src)


def parse_ae_attribute(src: str) -> dict:
    src = strip_lua_comments(src)
    i = src.index("local ae_attribute")
    j = src.index("{", i)
    tbl, _ = lua_table(src, j)
    out = {}
    for k, v in tbl:
        out[k] = v
    return out


def extract_constants(src: str) -> dict:
    """seek() 里的时间映射常数——从源码取，不写死在本文件里。"""
    src = strip_lua_comments(src)
    c: dict[str, object] = {}
    m = re.search(r"local\s+AEprogress\s*=\s*t\s*\*\s*([0-9.]+)\s*/\s*([0-9.]+)", src)
    assert m, "取不到 AEprogress = t * A / B"
    c["ae_mul"], c["ae_div"] = float(m.group(1)), float(m.group(2))
    m = re.search(r"local\s+t\s*=\s*math\.mod\(time,self?\.duration\s*\+\s*([0-9.e-]+)\)"
                  r"\s*/\s*\(\s*self?\.duration\s*\+\s*([0-9.e-]+)\)", src)
    if not m:
        m = re.search(r"math\.mod\(time,\s*self\.duration\s*\+\s*([0-9.e-]+)\)\s*/"
                      r"\s*\(\s*self\.duration\s*\+\s*([0-9.e-]+)\)", src)
    assert m, "取不到 t = mod(time, duration+eps)/(duration+eps)"
    assert m.group(1) == m.group(2), "mod 的两个 eps 不一致"
    c["mod_eps"] = float(m.group(1))
    m = re.search(r"self\.duration\s*=\s*([0-9.eE-]+)", src)
    assert m, "取不到 self.duration 默认值"
    c["default_duration"] = float(m.group(1))
    m = re.search(r"local\s+fps\s*=\s*AEprogress\s*\*\s*([0-9.]+)", src)
    c["fps_ref"] = float(m.group(1)) if m else None
    m = re.search(r"local\s+noiseIns\s*=[^\n]*?\*\s*([0-9.eE-]+)", src)
    c["noise_gain"] = float(m.group(1)) if m else None
    return c


# ------------------------------------------------- AETools 求值（对齐 lua 原文）
def remap01(a: float, b: float, x: float) -> float:
    if x < a:
        return 0.0
    if x > b:
        return 1.0
    return (x - a) / (b - a)


def cubic_bezier(p1, p2, p3, p4, t):
    return [
        p1[0] * (1 - t) ** 3 + 3 * p2[0] * (1 - t) ** 2 * t
        + 3 * p3[0] * (1 - t) * t * t + p4[0] * t * t * t,
        p1[1] * (1 - t) ** 3 + 3 * p2[1] * (1 - t) ** 2 * t
        + 3 * p3[1] * (1 - t) * t * t + p4[1] * t * t * t,
    ]


def get_bezier01_x(bz, x):
    ts, te = 0.0, 1.0
    while True:
        tm = (ts + te) * 0.5
        v = cubic_bezier([0, 0], [bz[0], bz[1]], [bz[2], bz[3]], [1, 1], tm)
        if v[0] > x:
            te = tm
        else:
            ts = tm
        if (te - ts) < 0.0001:
            break
    return (te + ts) * 0.5


def cubic_bezier01(bz, p):
    return cubic_bezier([0, 0], [bz[0], bz[1]], [bz[2], bz[3]], [1, 1],
                        get_bezier01_x(bz, p))[1]


def mix(a: float, b: float, x: float) -> float:
    return a * (1 - x) + b * x


class AETools:
    def __init__(self, attrs: dict):
        self.attrs = attrs
        mx = 0
        for content in attrs.values():
            for info in content:
                mx = max(mx, info[1][1])
        self.all_frame = mx

    def get_val(self, name: str, progress: float):
        content = self.attrs[name]
        cur_frame = progress * self.all_frame
        for info in content:
            bz, (start, end), vr = info[0], info[1], info[2]
            if cur_frame >= start and cur_frame < end:
                cp = remap01(start, end, cur_frame)
                if len(bz) > 4:
                    res = []
                    for k in range(3):
                        cb = [bz[k], bz[k + 3], bz[k + 6], bz[k + 9]]
                        res.append(mix(vr[0][k], vr[1][k], cubic_bezier01(cb, cp)))
                    return res
                p = cubic_bezier01(bz, cp)
                if isinstance(vr[0], list):
                    return [mix(vr[0][j], vr[1][j], p) for j in range(len(vr[0]))]
                return mix(vr[0], vr[1], p)
        f = content[0][1]
        if cur_frame < f[0]:
            v0 = content[0][2][0]
            return v0[0] if isinstance(v0, list) else v0
        l = content[-1][1]
        if cur_frame >= l[1]:
            v1 = content[-1][2][1]
            return v1[0] if isinstance(v1, list) else v1
        return None


def frame_of(time: float, duration: float, cons: dict, all_frame: float | None = None) -> float:
    """lua: t = mod(time, dur+eps)/(dur+eps); AEprogress = t*A/B; cur_frame = AEprogress*all_frame"""
    af = TOOLS.all_frame if all_frame is None else all_frame
    d = duration if duration else cons["default_duration"]
    t = (time % (d + cons["mod_eps"])) / (d + cons["mod_eps"])
    return t * cons["ae_mul"] / cons["ae_div"] * af


def frame_of_clamped(time: float, duration: float, cons: dict,
                     all_frame: float | None = None) -> float:
    """同 `frame_of`，但把 time 夹在 [0, duration]——成片证明入场动画**不循环**（F-095），
    这条才是渲染器该用的那条；保留 `frame_of` 只为了能把 lua 字面写法当假设去打。"""
    af = TOOLS.all_frame if all_frame is None else all_frame
    d = duration if duration else cons["default_duration"]
    t = min(max(time, 0.0), d) / (d + cons["mod_eps"])
    return t * cons["ae_mul"] / cons["ae_div"] * af


TOOLS: AETools | None = None


def main() -> int:
    global TOOLS
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkg", type=Path, default=DEF_PKG)
    ap.add_argument("--t", default="", help="相对该段起点的秒数，逗号分隔")
    ap.add_argument("--duration", type=float, default=0.3)
    ap.add_argument("--dump-times", action="store_true")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    src = args.pkg.read_text(encoding="utf-8", errors="replace")
    attrs = parse_ae_attribute(src)
    cons = extract_constants(src)
    TOOLS = AETools(attrs)
    report = {"pkg": str(args.pkg), "constants": cons, "all_frame": TOOLS.all_frame,
              "attrs": {k: [{"bezier": i[0], "frames": i[1], "values": i[2]} for i in v]
                        for k, v in attrs.items()}}
    # 覆盖率自证：解析到的属性数 + 每条关键帧数 + 帧区间是否首尾相接
    cov = []
    for k, v in attrs.items():
        spans = [(i[1][0], i[1][1]) for i in v]
        joined = all(spans[i][1] == spans[i + 1][0] for i in range(len(spans) - 1))
        cov.append((k, len(v), spans[0][0], spans[-1][1], joined))
    report["coverage"] = [{"attr": a, "keys": n, "from": s, "to": e,
                           "contiguous": bool(j)} for a, n, s, e, j in cov]
    print(f"AE 表属性数={len(attrs)} all_frame={TOOLS.all_frame} 常数={cons}")
    for a, n, s, e, j in cov:
        print(f"  {a:38s} 关键帧 {n} 段 帧区间 [{s:g},{e:g}) 首尾相接={j}")

    if not args.dump_times:
        vals = []
        for ts in [x for x in args.t.split(",") if x.strip() != ""]:
            time = float(ts)
            cf = frame_of(time, args.duration, cons)
            prog = cf / TOOLS.all_frame
            row = {"time": time, "cur_frame": cf}
            for k in attrs:
                v = TOOLS.get_val(k, prog)
                row[k] = v[0] if isinstance(v, list) and len(v) == 1 else v
            vals.append(row)
        report["samples"] = vals
        report["duration"] = args.duration
        for r in vals:
            print(json.dumps(r, ensure_ascii=False))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        tmp = args.json.with_suffix(args.json.suffix + ".tmp")
        tmp.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        bak = args.json.with_suffix(args.json.suffix + ".bak")
        if args.json.exists():
            bak.write_bytes(args.json.read_bytes())
        tmp.replace(args.json)
        print(f"写出 {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
