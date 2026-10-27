"""打字光标接线的门禁判据：证明这条律**真的在画面上起作用**，而不是"代码在、没生效"。

为什么需要它（本项目规约：新渲染路径若本草稿会触发，就必须有一层判据）：
打字光是本轮新落地的路径，但门里没有任何一层会因为「打字静默失效」而变红——
`tw` 表从载体里丢了、`typewriter_truncate` 提前 return、样式 range 截断错位，
都会画成"整句一次出现"，而 L2/L3/L10 的整帧判据对这种差别**不敏感**（F-072/F-080 同族）。

三条断言，最后一条是**牙齿**（负样本）：
  A1 单调露出：动画窗口内取三个时刻，字幕墨的**右边缘**必须严格递增，且末刻 == 全文右边缘；
  A2 与律同解：每个时刻的右边缘必须落在 `typewriter_prefix` 算出的那个 k 的前缀边缘上
     （用 k=0..n 的纯文字层标定，不靠猜阈值）；
  A3 牙齿：把 `APPLY_ANIMATIONS` 关掉重跑 A1 —— 那时右边缘应当**恒定**（整句一次出现）。
     如果关掉动画后右边缘仍然递增，说明这条判据在量别的东西（素材运动），判据作废。

口径：只读模型 + 离线渲染（通道 2）。浏览器侧由 A4 的载体断言兜着：
     模型里每个打字段的 `animations[].tw` 必须真的带两张 14 项表——页面读不到包内 lua，
     表丢了它就画成静态，而这件事只有在这里能被发现。

用法:
    python scripts/typewriter_wiring_check.py [--model temp/playback-test/model-check.json]
        [--segments 3] [--tol 3]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import render_frame as rf                      # noqa: E402
import animation_curve as ac                   # noqa: E402
import typing_extent_check as tec              # noqa: E402

try:
    sys.stdout.reconfigure(errors="replace")    # type: ignore[attr-defined]
    sys.stderr.reconfigure(errors="replace")    # type: ignore[attr-defined]
except Exception:                                # noqa: BLE001
    pass


def solo_text_model(model: dict, seg_id: str, txt: str | None) -> dict:
    """只留被测文本段（**保留它的 animations**），去掉视频/音频轨与别的文字。

    不能直接用 `typing_extent_check.text_only_model`：那个为了做纯文字模板把
    `animations` 清空了 —— 拿来测打字路径就等于先把被测对象拆掉（第一版就是这么错的，
    A1 直接不单调）。这里 txt 给 None 表示"整句交给动画去截"，让 `typewriter_truncate` 自己决定。
    """
    tracks = []
    for tr in model["tracks"]:
        if tr["type"] != "text":
            continue
        for s in tr["segments"]:
            if s["id"] != seg_id:
                continue
            s2 = dict(s)
            if txt is not None:
                s2["text"] = dict(s.get("text") or {})
                s2["text"]["text"] = txt
            tracks.append({**tr, "segments": [s2]})
    return {**model, "tracks": tracks}


def text_layer_right_edge(model: dict, seg, txt: str, pos_us: int, apply_anim: bool,
                          rows: tuple[int, int]) -> tuple[int, list[int]]:
    """把**只有这一段文字**画到空白底上，返回行窗内墨的右边缘 + 每列是否有墨。"""
    cw, ch = int(model["canvas"]["width"]), int(model["canvas"]["height"])
    rf.APPLY_ANIMATIONS = apply_anim
    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    m2 = solo_text_model(model, seg["id"], txt)
    rf.collect(canvas, m2, int(pos_us), {})
    a = np.asarray(canvas.convert("RGB"), dtype=np.float32)
    lum = a[rows[0]:rows[1]] @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    cols = (lum.max(axis=0) > 40)
    xs = np.nonzero(cols)[0]
    return (int(xs.max()) if len(xs) else -1), cols.astype(np.int8).tolist()


def band(seg, ch: int) -> tuple[int, int]:
    t = seg.get("text") or {}
    styles = t.get("styles") or [{}]
    size = max([s.get("size") or 0 for s in styles] + [t.get("font_size") or 0])
    vc = 0.5 - ((seg.get("clip") or {}).get("y") or 0.0) / 2
    half = max(0.05, 0.8 * size * rf.K_EM * 1080 / 1920)
    return max(0, int((vc - half) * ch)), min(ch, int((vc + half) * ch))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default="temp/playback-test/model-check.json")
    ap.add_argument("--segments", type=int, default=3, help="抽查几段（每段要渲 2n+3 帧，别调太大）")
    ap.add_argument("--tol", type=int, default=3, help="右边缘与标定边缘的容差（像素，1080 宽尺度）")
    args = ap.parse_args()

    model = json.loads(pathlib.Path(args.model).read_text(encoding="utf-8-sig"))
    ch = int(model["canvas"]["height"])
    segs = []
    for tr in model["tracks"]:
        if tr["type"] != "text":
            continue
        for s in tr["segments"]:
            a = next((x for x in (s.get("animations") or []) if x.get("name") == "打字光标"), None)
            if a:
                segs.append((s, a))
    fails: list[str] = []

    # **非空判据**：没有打字段时下面的断言一条都不会跑，脚本会"0 问题 PASS"——
    # 那是最危险的假绿（判据没对象 ≠ 判据通过）。缺段通常是载体过期或 L1 没解出动画，
    # 正是要报出来的事。
    if not segs:
        print("TYPEWRITER_WIRING assertions=1 problems=1 segments=0 carrier_tables_ok=False")
        print("  ! A0 本模型里没有任何打字段 ⇒ 判据无对象，不能算通过（载体过期？L1 没解出动画？）")
        print("FAIL 打字接线 1 项断言，1 条问题")
        return 1

    n_tw = sum(1 for _, a in segs if a.get("tw"))
    if n_tw != len(segs):
        # 表是从**预设包**里读出来的，包在剪映的缓存目录里，会被剪映自己清掉
        # （F-084 那次是字体被清，这次是 19 个动画包被清：14 个打字光标 + 3 个生长 II + 侧滑 + 向上露出）。
        # 分不清"律坏了"和"包不在了"就会把环境问题读成产品回归——两种处置完全不同。
        gone = sum(1 for _, a in segs if not a.get("tw")
                   and a.get("path") and not pathlib.Path(a["path"]).is_dir())
        why = (f"其中 {gone} 段的预设包目录已不在机器上（剪映清了缓存）⇒ 律未被检验，不是律坏了"
               if gone == len(segs) - n_tw and gone else
               f"其中 {gone} 段是包不在，另 {len(segs) - n_tw - gone} 段是载体真的缺表")
        fails.append(f"A4 载体：{len(segs)} 个打字段里只有 {n_tw} 个带 tw 表 ⇒ {why}")
    for _, a in segs:
        tw = a.get("tw") or {}
        if any(len(tw.get(k) or []) != 14 for k in ("random_tween_time", "random_tween_time1")):
            fails.append(f"A4 载体：{a.get('path','')[-24:]} 的 tw 表长度不是 14")
            break
    print(f"A4 载体：{len(segs)} 个打字段，带表 {n_tw}，两表各 14 项")

    for s, a in segs[:args.segments]:
        txt = ((s.get("text") or {}).get("text") or "").replace("\n", " ")
        n = len(txt)
        t0 = s["target"]["start_us"]
        adur = (a.get("duration_us") or 0) / 1e6
        rows = band(s, ch)
        if adur <= 0 or n < 2:
            fails.append(f"段 {s['id'][:8]}：动画时长 {adur} 或字数 {n} 不足以构造露出")
            continue
        # 标定：k 个字的纯文字层右边缘
        r_k = [text_layer_right_edge(model, s, txt[:k], t0 + int(adur * 2e6), False, rows)[0]
               for k in range(n + 1)]
        fs = [text_layer_right_edge(model, s, txt, t0 + int(f * adur * 1e6), True, rows)[0]
              for f in (0.15, 0.5, 0.9)]
        print(f"  段 {s['id'][:8]} n={n} 动画 {adur*1e3:.0f}ms 标定 R_k={r_k} 开动画右边缘={fs}")
        if not (fs[0] < fs[1] < fs[2]):
            fails.append(f"A1 段 {s['id'][:8]}：露出不单调 {fs}")
        if abs(fs[2] - r_k[n]) > args.tol:
            fails.append(f"A1 段 {s['id'][:8]}：末刻右边缘 {fs[2]} != 全文 {r_k[n]}")
        for f, got in zip((0.15, 0.5, 0.9), fs):
            k = ac.typewriter_prefix(a["tw"], f * adur, adur, n)
            if abs(got - r_k[k]) > args.tol:
                fails.append(f"A2 段 {s['id'][:8]} f={f}：律说 k={k}（边缘 {r_k[k]}），画出来 {got}")
        const = [text_layer_right_edge(model, s, txt, t0 + int(f * adur * 1e6), False, rows)[0]
                 for f in (0.15, 0.5, 0.9)]
        if len(set(const)) > 1:
            fails.append(f"A3 牙齿失效 段 {s['id'][:8]}：关动画后右边缘仍在动 {const} ⇒ 判据在量素材，作废")
        else:
            print(f"      A3 牙齿：关动画右边缘恒定 {const[0]}（与全文 {r_k[n]} 同）⇒ 判据有牙")

    print("-" * 72)
    for x in fails:
        print("  !", x)
    # ASCII 标记行：门的 detail 是靠**匹配这行**取的。中文行在子进程管道里会被换成 "?"，
    # 于是失败时判据端只能回落到 stdout 尾巴（实测是个 `]`），等于把现场擦掉。
    print(f"TYPEWRITER_WIRING assertions={4 + args.segments * 5} problems={len(fails)} "
          f"segments={len(segs)} carrier_tables_ok={n_tw == len(segs)}")
    print(f"{'FAIL' if fails else 'PASS'} 打字接线 {4 + args.segments * 5} 项断言，{len(fails)} 条问题")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
