"""关键帧（common_keyframes）接线的门禁判据：证明这条律**真的在画面上起作用**。

背景（用户 2026-11-05 定的顺序）：先不管素材动画预设，先把「所有东西正常显示」保住，
而关键帧是显示语义的一部分——带位置/缩放/不透明度关键帧的段，渲染器不读就画在错的地方。
律在 spec/keyframes.yaml：记录挂 segment.common_keyframes[]，time_offset 相对片段起点（µs），
values 与 clip.* 同单位（骨架帧 values==clip 标量，F-027），线性或控制柄贝塞尔。

四条断言，A3 是牙齿（负样本）：
  A1 提取律：`keyframe_tracks()` 只收**多点**画面类轨道；单点骨架（=clip 标量）与非画面类
     （调色/音量等）都不进渲染分母。
  A2 通道 2 生效：给真模型的一条字幕注入 PositionX 轨道，段首→段末字墨质心必须按律平移
     （Δx × cw/2 像素）；再注入 Alpha 轨道，墨量必须按比例掉。
  A3 牙齿：同一 fixture 拆掉关键帧重跑 A2 的两次渲染——质心/墨量必须**不动**（背景为空，
     不动的只能是我们自己）。若拆掉后仍动，判据在量别的东西，作废。
  A4 端点钳制 + 浏览器接线：kf_eval 段外取端点值；player.html 的全部 clip 消费点必须走
     `kfClip()`（源级断言，页面侧没有更便宜的实时判据）。

口径：只读模型 + 离线渲染（通道 2），与 typewriter_wiring_check 同一族。

用法:
    python scripts/keyframe_wiring_check.py [--model temp/playback-test/model-check-p157.json]
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_frame as rf  # noqa: E402
import playback_model as pm  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str) -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}")
    if not ok:
        FAILS.append(name)


def ink_stats(img: Image.Image, rows) -> tuple[float, int]:
    """字幕行带内 >235 亮墨的 x 质心（像素）与总量。rows=(y0,y1) 全分辨率坐标。"""
    a = np.asarray(img.convert("L"), dtype=np.uint8)[rows[0]:rows[1], :]
    ys, xs = np.where(a > 235)
    if not len(xs):
        return float("nan"), 0
    return float(xs.mean()), int(len(xs))


def text_seg(model: dict) -> dict:
    for tr in model["tracks"]:
        if tr["type"] == "text":
            for s in tr["segments"]:
                if s.get("text", {}).get("text"):
                    return s
    raise SystemExit("fixture model has no text segment")


def only_text(model: dict) -> dict:
    """背景清空的 fixture：只留 text 轨 ⇒ 带内亮墨只可能来自字幕自己。"""
    m = copy.deepcopy(model)
    m["tracks"] = [tr for tr in m["tracks"] if tr["type"] == "text"]
    return m


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="temp/playback-test/model-check-p157.json")
    args = ap.parse_args()
    model_path = Path(args.model)
    if not model_path.is_file():
        raise SystemExit(f"model not found: {model_path}（temp 产物缺席时先跑 playback_model.py）")
    model = json.loads(model_path.read_text(encoding="utf-8-sig"))

    print("A1 提取律")
    raw = {"common_keyframes": [
        {"property_type": "KFTypePositionX", "keyframe_list": [
            {"time_offset": 0, "values": [0.0], "left_control": {}, "right_control": {}},
            {"time_offset": 1000000, "values": [0.4], "left_control": {}, "right_control": {}}]},
        {"property_type": "KFTypeScaleX", "keyframe_list": [
            {"time_offset": 0, "values": [1.0]}]},                       # 单点骨架 ⇒ 不进
        {"property_type": "KFTypeVolume", "keyframe_list": [             # 非画面类 ⇒ 不进
            {"time_offset": 0, "values": [1.0]}, {"time_offset": 5, "values": [0.5]}]},
    ]}
    tr = pm.keyframe_tracks(raw)
    check("多点画面类轨道被收进", len(tr) == 1 and tr[0]["property"] == "PositionX"
          and [p["t_us"] for p in tr[0]["points"]] == [0, 1000000], str(tr)[:90])

    seg = text_seg(model)
    t0, dur = seg["target"]["start_us"], seg["target"]["duration_us"]
    cw, ch = model["canvas"]["width"], model["canvas"]["height"]
    base_clip = seg.get("clip") or {}
    x0 = base_clip.get("x") or 0.0
    # 字幕行的行窗：以 clip.y 与字号估计太绕，直接用渲染自身标定——先渲染一次基线，
    # 在下半屏找 >235 的行集合（背景已清空，唯一亮源就是字幕）。
    base = only_text(model)
    fonts_cache: dict = {}
    cv = Image.new("RGBA", (cw, ch), (0, 0, 0, 255))
    rf.collect(cv, base, t0 + 200000, fonts_cache)
    a = np.asarray(cv.convert("L"), dtype=np.uint8)
    ys = np.where((a > 235).sum(axis=1) >= 5)[0]
    if not len(ys):
        raise SystemExit("基线渲染没有字墨——fixture 段在该时刻不可见，换段或换时刻")
    rows = (int(ys[0]) - 8, int(ys[-1]) + 8)

    print("A2 通道 2 生效（位置 + 不透明度）")
    kf = copy.deepcopy(base)
    kfseg = text_seg(kf)
    move = 0.2                                   # 归一化 x：×cw/2 = 108 px @1080；取小值避免把字推出画框（裁边会吃掉位移）
    kfseg["keyframes"] = [{"property": "PositionX", "points": [
        {"t_us": 0, "v": x0, "lc": {}, "rc": {}, "curve": "Line"},
        {"t_us": dur, "v": x0 + move, "lc": {}, "rc": {}, "curve": "Line"}]}]
    cx0, n0 = ink_stats(rf.render_frame_at(kf, t0 + 200000, cw, ch), rows)
    cx1, n1 = ink_stats(rf.render_frame_at(kf, t0 + dur - 200000, cw, ch), rows)
    # 两次采样都不在关键帧端点上：线性律下期望位移 = move × cw/2 × (末采样-首采样)/dur。
    off0, off1 = 200000, dur - 200000
    want = move * cw / 2 * (off1 - off0) / dur
    got = cx1 - cx0
    check("位置质心按律平移", abs(got - want) <= 8, f"Δ={got:.1f}px 期望 {want:.1f}px（容差 8）")

    kfa = copy.deepcopy(base)
    kfas = text_seg(kfa)
    kfas["keyframes"] = [{"property": "Alpha", "points": [
        {"t_us": 0, "v": 1.0, "lc": {}, "rc": {}, "curve": "Line"},
        {"t_us": dur, "v": 0.2, "lc": {}, "rc": {}, "curve": "Line"}]}]
    def gray_mean(pos_us):
        a = np.asarray(rf.render_frame_at(kfa, pos_us, cw, ch).convert("L"), dtype=np.uint8)[rows[0]:rows[1], :]
        return float(a.mean())
    # 阈值计数对半透明墨不合适（alpha 0.91×255=232 恰在 >235 之下）——用行带灰度均值，
    # 它随 alpha 单调且无阈值悬崖。期望比值 ≈ (1-0.8·off1/dur)/(1-0.8·off0/dur)。
    m0, m1 = gray_mean(t0 + off0), gray_mean(t0 + off1)
    want_ratio = (1 - 0.8 * off1 / dur) / (1 - 0.8 * off0 / dur)
    check("不透明度按律衰减", abs(m1 / m0 - want_ratio) < 0.08,
          f"末/首 = {m1:.1f}/{m0:.1f} = {m1 / m0:.3f}（律 {want_ratio:.3f}，容差 0.08）")

    print("A3 牙齿（拆掉关键帧必须不动）")
    cx0b, n0b = ink_stats(rf.render_frame_at(base, t0 + 200000, cw, ch), rows)
    cx1b, n1b = ink_stats(rf.render_frame_at(base, t0 + dur - 200000, cw, ch), rows)
    check("无关键帧 ⇒ 质心不动", abs(cx1b - cx0b) <= 2, f"Δ={cx1b - cx0b:.1f}px（容差 2）")
    check("无关键帧 ⇒ 墨量不变", abs(n1b - n0b) <= max(20, n0b * 0.05),
          f"{n0b} → {n1b}")

    print("A4 端点钳制 + 浏览器接线")
    trk = {"property": "PositionX", "points": [
        {"t_us": 0, "v": 0.0, "lc": {}, "rc": {}, "curve": "Line"},
        {"t_us": 1000000, "v": 0.4, "lc": {}, "rc": {}, "curve": "Line"}]}
    check("段前取首值、段后取末值",
          rf.kf_eval(trk, -5) == 0.0 and rf.kf_eval(trk, 2_000_000) == 0.4
          and abs(rf.kf_eval(trk, 500_000) - 0.2) < 1e-9,
          f"-5→{rf.kf_eval(trk, -5)} 2e6→{rf.kf_eval(trk, 2_000_000)} 0.5e6→{rf.kf_eval(trk, 500_000):.3f}")
    page = (Path(__file__).resolve().parents[1] / "player" / "player.html").read_text(encoding="utf-8")
    naked = page.count("placeGroup(comp, seg.clip") + page.count("placeImage(sp, seg.clip") \
        + page.count("place(sp, seg.clip") + page.count("const c = seg.clip")
    check("页面 clip 消费点全部走 kfClip", naked == 0 and "function kfClip(" in page,
          f"裸 seg.clip 消费点 {naked}（须 0），kfClip 在场={('function kfClip(' in page)}")

    print(f"\n{'SELFTEST PASS' if not FAILS else 'SELFTEST FAIL: ' + ', '.join(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    # render_frame 没有单时刻入口函数，这里补一个不留副作用的包装。
    def _render_at(m, pos_us, cw, ch):
        cv = Image.new("RGBA", (cw, ch), (0, 0, 0, 255))
        rf.collect(cv, m, pos_us, {})
        return cv
    rf.render_frame_at = _render_at
    raise SystemExit(main())
