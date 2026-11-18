"""读装机包内的 **AE 导出关键帧表**（`animation_curve.load_curve` 那一档覆盖不到的预设走这里）。

形状逐字取自包内明文 `Cache/effect/<id>/*/AmazingFeature/lua/SeekModeScript.lua`：

    ["ADBE Position_23"] = {
        ["spatial"] = true, ["d"] = 3,
        ["k"] = { {0, 240, 626, -204}, {0.1333…, 618, 555, -10}, {0.6, 540, 540, 0} },
        ["s"] = { {["o"] = {{x, y}}}, {["i"] = {{x, y}}}, … },
    }

`k` 的每行第一列是**秒**；`s` 是段间缓动，o=出切线、i=入切线，两分量都是**归一化**控制点
（横轴占时段比例、纵轴占值差比例）——与 Lottie 的 o/i 同一套语义，所以求值按三次贝塞尔解 x(s)=f 再取 y。

这一层**只读表**。单位与语义留在包内 lua 里由调用方自己去取（`DURATION = 18 / 30`、
`DESIGN_SIZE = 1080`、`DESIGN_CAMERA_Z = -(1080/2)/tan(fov/2)`、`GS_X_INTENSITY = 0.5`），
不在这里写死常量——写了就等于把「与剪映一致」降级成「我以为一致」。
`animation_curve` 的模块文档第 1 条说的「返回空 = 未实现」在这一档被补上；补不上的仍然返回空，
调用方必须按未实现处理，不许拿近似曲线顶上。
"""
from __future__ import annotations

import pathlib
import re

# 两种命名都在包里出现过：侧滑写 `["ADBE Position_23"]`，向上闪入写 `["ADBE_Position_2_4"]`
# ⇒ 只按 `ADBE` 前缀认，中间的空格/下划线与尾号都留给调用方自己配，不在这里归一化（归一化会造出第二种"方言"）。
_TRACK_RE = re.compile(r'\["(ADBE[^"]+)"\]\s*=\s*\{')
_FIELD_RE = re.compile(r'\["([^"]+)"\]\s*=')
_NUM_RE = re.compile(r'-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?')


def _skip_string(text: str, i: int) -> int:
    """text[i] 是引号时跳到引号结束后，否则原样返回。"""
    ch = text[i]
    if ch != '"' and ch != "'":
        return i
    j = i + 1
    while j < len(text):
        if text[j] == "\\":
            j += 2
            continue
        if text[j] == ch:
            return j + 1
        j += 1
    return j


def _block(text: str, open_at: int) -> tuple[str, int]:
    """从 `text[open_at] == '{'` 起配对，返回 (块内文本, 块尾下标)。"""
    depth, i = 0, open_at
    while i < len(text):
        j = _skip_string(text, i)
        if j != i:
            i = j
            continue
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_at + 1:i], i + 1
        i += 1
    return text[open_at + 1:], len(text)


def _fields(inner: str) -> dict[str, str]:
    """把块内 `["名字"] = <值文本>` 拆出来（值按配对截断，不递归）。"""
    out, i = {}, 0
    while i < len(inner):
        j = _skip_string(inner, i)
        if j != i:
            i = j
            continue
        m = _FIELD_RE.search(inner, i)
        if not m:
            break
        p = m.end()
        while p < len(inner) and inner[p].isspace():
            p += 1
        if p < len(inner) and inner[p] == "{":
            body, end = _block(inner, p)
            out[m.group(1)] = "{" + body + "}"
        else:
            end = p
            while end < len(inner) and inner[end] != ",":
                end += 1
            out[m.group(1)] = inner[p:end]
        i = end + 1
    return out


def _rows(raw: str) -> list[list[float]]:
    """`{ {0,240,626,-204}, {0.13,618,555,-10} }` → [[0.0,240.0,…], [0.13,…]]。

    先把**外层那对花括号剥掉**再逐个取直接子块——第一版没剥，把整张表吃成一行，
    于是每条 track 只剩一个"关键帧"，值退化成常量（端点断言当时照样通过，正是它骗过我）。
    """
    body = raw
    j = body.find("{")
    if j >= 0:
        inner, _ = _block(body, j)
        body = inner
    out, i = [], 0
    while i < len(body):
        if body[i] == "{":
            child, end = _block(body, i)
            nums = [float(x) for x in _NUM_RE.findall(child)]
            if nums and not re.search(r"[A-Za-z_\[]", child):
                out.append(nums)
            else:
                out.extend(_rows(child))       # 又嵌套一层（如 o={{x,y}}）
            i = end
        else:
            i += 1
    return out


def _eases(sraw: str) -> list[dict]:
    """一行的 o/i 是归一化切线（方言 B）；**多行**是每通道一对，且 y 给的是**绝对值**
    （`Scale` 的 o.y=217.185 就是该通道关键帧本身的值）——求值前要按段首末值把它归一化回 0~1。
    第一版只取 `r[0][:2]` 又把 y 当归一数用，于是 scale 解出 −2360 %。"""
    # 剥一层外层大括号后**直接在剩下的文本里**找子块；再把剥掉的内容重新包一层，
    # 下一次 find("{") 会命中那层刚包回去的括号——整表被当成一段、`_fields` 又按同名后写覆盖，
    # 于是每通道切线取到的是**最后一个关键帧**的（217.185 变 120.81）。
    body = sraw
    if body.lstrip().startswith("{"):
        body, _ = _block(body, body.index("{"))
    item, i = [], 0
    while True:
        j = body.find("{", i)
        if j < 0:
            break
        seg, i = _block(body, j)
        ff = _fields(seg)
        one = {}
        for side in ("o", "i"):
            r = _rows(ff.get(side, ""))
            if r:
                one[side] = r[0][:2]
                one[side + "_rows"] = [row[:2] for row in r]     # 每通道一组时按通道取
        if one:
            item.append(one)
    return item


def load_ae_from_text(text: str) -> list[dict]:
    """从一段 lua 正文取方言 A 的表——`ae_keyframe` 归一内联表时走的就是这条，不重复读文件逻辑。"""
    tracks = []
    for m in _TRACK_RE.finditer(text):
        inner, _ = _block(text, m.end() - 1)
        f = _fields(inner)
        keys = _rows(f.get("k", ""))
        if not keys:
            continue
        tracks.append({
            "name": m.group(1),
            "d": int(float(next(iter(_NUM_RE.findall(f.get("d", "")) or ["1"])))),
            "spatial": "spatial" in f,
            "keys": keys,
            "eases": _eases(f.get("s", "")),
        })
    return tracks


def load_ae(pkg_path, lua_names=("SeekModeScript.lua",)) -> list[dict]:
    """返回 [{"name","d","spatial","keys","eases","src"}…]；包不存在或表读不到 ⇒ []（=未实现）。"""
    p = pathlib.Path(pkg_path)
    if not p.is_dir():
        return []
    luas = sorted(set(list(p.glob("**/lua/*.lua")) + list(p.glob("**/*.lua"))))
    if lua_names:
        luas = [q for q in luas if q.name in lua_names]
    tracks = []
    for q in luas:
        for tr in load_ae_from_text(q.read_text(encoding="utf-8", errors="replace")):
            tracks.append({**tr, "src": q.name})
    return tracks


def _bez(s: float, p0: float, p1: float, p2: float, p3: float) -> float:
    u = 1.0 - s
    return u * u * u * p0 + 3 * u * u * s * p1 + 3 * u * s * s * p2 + s * s * s * p3


def ae_value(track: dict, t_sec: float) -> list[float]:
    """elapsed 秒处的各分量值：越界取端点值；没有缓动段就线性。"""
    ks = track["keys"]
    if t_sec <= ks[0][0]:
        return ks[0][1:]
    if t_sec >= ks[-1][0]:
        return ks[-1][1:]
    j = 0
    for j in range(len(ks) - 1):
        if ks[j][0] <= t_sec <= ks[j + 1][0]:
            break
    t0, t1 = ks[j][0], ks[j + 1][0]
    span = t1 - t0
    f = 0.0 if span <= 0 else (t_sec - t0) / span
    e = track["eases"][j] if j < len(track["eases"]) else {}
    v0, v1 = ks[j][1:], ks[j + 1][1:]
    n = min(len(v0), len(v1))
    if e.get("o_rows") and e.get("i_rows"):
        out = []
        for q in range(n):
            o = e["o_rows"][q] if q < len(e["o_rows"]) else e["o_rows"][0]
            i = e["i_rows"][q] if q < len(e["i_rows"]) else e["i_rows"][0]
            span = v1[q] - v0[q]
            oy = o[1] if abs(span) < 1e-9 else (o[1] - v0[q]) / span     # y 是绝对值 ⇒ 归一化
            iy = i[1] if abs(span) < 1e-9 else (i[1] - v0[q]) / span
            out.append(v0[q] + span * _ease01(f, o[0], oy, i[0], iy))
        return out
    if e.get("o") and e.get("i"):
        return [v0[q] + (v1[q] - v0[q]) * _ease01(f, e["o"][0], e["o"][1], e["i"][0], e["i"][1])
                for q in range(n)]
    return [v0[q] + (v1[q] - v0[q]) * f for q in range(n)]


def _ease01(f: float, ox: float, oy: float, ix: float, iy: float) -> float:
    """包内同一条三次贝塞尔：控制点 (0,0)-(ox,oy)-(1-ix,1-iy)-(1,1)，先解 x=f 再取 y。"""
    lo, hi = 0.0, 1.0
    for _ in range(48):
        mid = 0.5 * (lo + hi)
        if _bez(mid, 0.0, ox, 1.0 - ix, 1.0) < f:
            lo = mid
        else:
            hi = mid
    return _bez(0.5 * (lo + hi), 0.0, oy, 1.0 - iy, 1.0)


# ---- 方言 B：AETools（`向上闪入` 那类，包内自带解释器 `AETools:GetVal`）--------------------
# 形状：`["ADBE_Position_2_4"] = { {bezier, {start_frame, end_frame}, {from_values, to_values}}, … }`，
# `bezier` 是 4 个数（每个通道一组时是 12 个，第 k 通道取 b[k], b[k+3], b[k+6], b[k+9]）。
# **轴不一样**：`all_frame = max(end_frame)`，求值用 `cur_frame = progress * all_frame`
# （progress 是这一支动画自己的 0→1，实际时长来自草稿的 `duration_us`）
# ⇒ 这里的帧号只是**分辨率**，不是秒。方言 A（`侧滑`）的 `k` 第一列是**秒**，且包内写死
# `DURATION = 18 / 30`。两者混用会把 0.3 s 的动画按 1.63 s 来做——所以入口分叉，不猜。

_SEG_RE = re.compile(r'\["(ADBE[^"]+)"\]\s*=\s*\{')   # 只吃到表的开括号：多吃一个就只剩第一段


def _segments(raw: str) -> list[dict]:
    """一段一行：`{bezier…}, {start,end}, {{from…},{to…}}`。

    第三项**必须保持成行**（from/to 两行），第一版把它 findall 拍平成一个六数列表，
    于是 lo==hi，值恒等——不报错，只是动画不动。
    """
    body, _ = _block(raw, raw.index("{")) if raw.lstrip().startswith("{") else (raw, len(raw))
    out, i = [], 0
    while True:
        j = body.find("{", i)
        if j < 0:
            break
        inner, i = _block(body, j)
        parts, k = [], 0
        while k < len(inner):
            if inner[k] == "{":
                sub, k = _block(inner, k)
                parts.append(sub)
            else:
                k += 1
        if len(parts) >= 3:
            bez = [float(x) for x in _NUM_RE.findall(parts[0])]
            frm = [float(x) for x in _NUM_RE.findall(parts[1])]
            vals = _rows("{" + parts[2] + "}")
            if bez and frm and vals:
                out.append({"bezier": bez, "frames": frm, "values": vals})
    return out


def load_ae_tools(pkg_path, lua_names=("SeekModeScript.lua",)) -> dict:
    """返回 {track_name: {"dialect":"B","segments":[…]},"all_frame":N}；读不到返回 {}。"""
    p = pathlib.Path(pkg_path)
    if not p.is_dir():
        return {}
    res: dict = {}
    for q in [x for x in sorted(p.glob("**/lua/*.lua")) if not lua_names or x.name in lua_names]:
        text = q.read_text(encoding="utf-8", errors="replace")
        if "AETools" not in text:
            continue
        for m in _SEG_RE.finditer(text):
            inner, _ = _block(text, text.index("{", m.end() - 1))
            segs = _segments("{" + inner + "}")
            if segs:
                res[m.group(1)] = {"name": m.group(1), "dialect": "B", "segments": segs, "src": q.name}
    top = max([max(s["frames"][1] for s in t["segments"]) for t in res.values()], default=0)
    for t in res.values():
        t["all_frame"] = float(top)
    return res


def _cubic01(b: list[float], p: float) -> float:
    """包内 `_cubicBezier01`：控制点 (0,0)-(b1,b2)-(b3,b4)-(1,1)，先解 x 再取 y。"""
    if len(b) < 4:
        return p
    x0, y0, x1, y1 = b[0], b[1], b[2], b[3]
    lo, hi = 0.0, 1.0
    for _ in range(48):
        mid = 0.5 * (lo + hi)
        if _bez(mid, 0.0, x0, x1, 1.0) < p:
            lo = mid
        else:
            hi = mid
    return _bez(0.5 * (lo + hi), 0.0, y0, y1, 1.0)


def ae_tools_value(track: dict, progress: float, channel: int = 0) -> list[float]:
    """按 `AETools:GetVal` 求值：cur_frame = progress * all_frame，落在哪段就用那段的缓动插 from→to。"""
    segs = track["segments"]
    cur = progress * track.get("all_frame", 1.0)
    for sg in segs:
        a, b = sg["frames"][0], sg["frames"][1]
        if a <= cur < b or (b <= a and cur >= b):
            f = 0.0 if b <= a else min(max((cur - a) / (b - a), 0.0), 1.0)
            bb = sg["bezier"]
            if len(bb) > 4:                       # 每通道一组（scale 那种）
                k = min(channel, 2)
                bb = [bb[k], bb[k + 3], bb[k + 6], bb[k + 9]] if len(bb) >= 12 else bb[:4]
            prog = _cubic01(bb, f)
            lo, hi = sg["values"][0], sg["values"][-1]
            n = min(len(lo), len(hi))
            return [lo[q] + (hi[q] - lo[q]) * prog for q in range(n)]
    lo = segs[0]["values"][0] if cur < 0 else segs[-1]["values"][-1]
    return list(lo)


def track_by_name(tracks: list[dict], name: str) -> dict | None:
    for t in tracks:
        if t["name"] == name:
            return t
    return None


if __name__ == "__main__":
    import json
    import sys
    pkg = sys.argv[1]
    print(json.dumps(load_ae(pkg), ensure_ascii=False, indent=1)[:2600])
