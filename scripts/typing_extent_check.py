"""成片这一刻「露出了几个字」——把打字光标的律换成它自己的单位来判。

为什么另起一台仪器（F-087 补记）：`animation_region_check` 比的是整块字幕区开/关动画谁 MAD 小，
它的横向基线来自**稳态全文**渲染，于是 ① 合法未画出的字被记成缺墨，② 就算翻正也只是「MAD 小一点」，
**不是**「第 k 个字在该出现时出现了」。本仪器直接量 k：
  - 用**我们自己的文字层**（空白底 + `render_frame.draw_text`，不解任何视频帧）画 k=0..n 个前缀，
    得到每个 k 的白墨**右边缘列** R_k —— 这就是标定；
  - 对每个时刻取成片同刻、同一行窗，量白墨右边缘 E（白 = 三通道最小值 > 190，比 luma 阈稳）；
  - `k_export = argmin_k |R_k − E|`，与 `typewriter_prefix` 的 `k_ours` 逐时刻对表。

口径与已知污染：
  - 行窗由模型几何定（v = 0.5 − clip.y/2 ± max(0.05, 0.8em)），列只在**该段全文的墨区**里量；
  - 成片帧号 = `round(t*fps)+lead` **固定**，不搜偏移（搜偏移会把时序问题读成对齐问题）；
  - 同一行窗里若有**别的**活着的字幕段，E 会被它抢走 ⇒ 该样本标 `other_text=True` 并**单独统计**，
    不混进总账（本时间线 3 条字幕轨同 y，这条不是杞人忧天）；
  - 成片里那根光标（`kiss.png`，未实现）会让 E 系统性偏右 1 个字以内 —— 读数里要带着这条解释。

用法:
    python scripts/typing_extent_check.py [--model temp/playback-test/model-tw.json]
        [--frames-dir temp/playback-test/oracle/dense216] [--samples 5] [--report ...]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import render_frame as rf                      # noqa: E402
import animation_curve as ac                   # noqa: E402

try:
    sys.stdout.reconfigure(errors="replace")    # type: ignore[attr-defined]
    sys.stderr.reconfigure(errors="replace")    # type: ignore[attr-defined]
except Exception:                                # noqa: BLE001
    pass


def band_luma(img: Image.Image, rows: tuple[int, int], size: tuple[int, int]) -> np.ndarray:
    """降到比较尺度后取行窗的 luma 面。"""
    a = np.asarray(img.convert("RGB").resize(size, Image.BOX), dtype=np.float32)
    return a[rows[0]:rows[1]] @ np.array([0.299, 0.587, 0.114], dtype=np.float32)


def model_without_text(model: dict, seg_id: str) -> dict:
    """同一份模型、只把被测那段的文字清空 ⇒ 得到**该时刻的背景**（视频/别的层都保留）。

    为什么非要减背景：第一版在**整行**上找最亮列的右边缘，于是字幕右侧任何亮素材
    （展会的白色展板）都会把 E 推到画幅边上，70 个样本里 59 个被判"脏"——
    仪器不是没信号，是被素材淹了。减掉我们自己的背景后，剩下的就是"这一层有没有字"。
    """
    tracks = []
    for tr in model["tracks"]:
        if tr["type"] != "text":
            tracks.append(tr)
            continue
        segs = []
        for s in tr["segments"]:
            if s["id"] == seg_id:
                s2 = dict(s)
                s2["text"] = dict(s.get("text") or {})
                s2["text"]["text"] = ""
                s2["animations"] = []
                segs.append(s2)
            else:
                segs.append(s)
        tracks.append({**tr, "segments": segs})
    return {**model, "tracks": tracks}


def white_cols(img: Image.Image, rows: tuple[int, int]) -> np.ndarray:
    """行窗内每列是否有**字幕墨**（降采样后 luma > 128）。

    一开始用的是「三通道最小值 > 190」的纯白判据，但成片参考只有 216 宽：
    5× 降采样把细笔画和背景平均掉，白字根本过不了 190 ⇒ 标定全空、14 段一律「无白墨」。
    两条腿**同样降采样 + 同一个 luma 阈**才可比，所以判据换成 luma>128（文字层背景是纯黑，
    成片那侧底是素材，但两边都只取「这一列有没有亮东西」的右边缘，平均效应同向）。
    """
    a = np.asarray(img.convert("RGB"), dtype=np.float32)
    lum = a[rows[0]:rows[1]] @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    return (lum > 128).any(axis=0)


def right_edge(cols: np.ndarray) -> int:
    xs = np.nonzero(cols)[0]
    return int(xs.max()) if len(xs) else -1


def text_only_model(model: dict, seg_id: str, new_text: str) -> dict:
    """只留被测文本段、其余文本段清空、视频/音频段全部去掉 ⇒ 画出来的是纯文字层。"""
    tracks = []
    for tr in model["tracks"]:
        if tr["type"] != "text":
            continue
        segs = []
        for s in tr["segments"]:
            if s["id"] == seg_id:
                s2 = dict(s)
                s2["text"] = dict(s.get("text") or {})
                s2["text"]["text"] = new_text
                s2["animations"] = []
                segs.append(s2)
        if segs:
            tracks.append({**tr, "segments": segs})
    return {**model, "tracks": tracks}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default="temp/playback-test/model-tw.json")
    ap.add_argument("--frames-dir", default="temp/playback-test/oracle/dense216")
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--lead", type=int, default=3)
    ap.add_argument("--report", default="temp/playback-test/typing-extent.json")
    ap.add_argument("--excess", type=float, default=60.0,
                    help="成片比我们的背景亮出这么多 luma 才算「这里有字」")
    args = ap.parse_args()

    model = json.loads(pathlib.Path(args.model).read_text(encoding="utf-8-sig"))
    frames = sorted(pathlib.Path(args.frames_dir).glob("*.png"))
    cw, ch = int(model["canvas"]["width"]), int(model["canvas"]["height"])
    sw, sh = Image.open(frames[0]).size
    scale_w, scale_h = sw, sh
    rf.APPLY_ANIMATIONS = False

    segs = []
    for tr in model["tracks"]:
        if tr["type"] != "text":
            continue
        for s in tr["segments"]:
            a = next((x for x in (s.get("animations") or []) if x.get("tw")), None)
            if a:
                segs.append((s, a))
    print(f"打字段 {len(segs)} 个；成片参考 {len(frames)} 张 {sw}x{sh}")

    agree = disagree = 0
    dirty = shared = 0
    unusable: list[dict] = []
    deltas = []
    rows = []
    for s, a in segs:
        txt = ((s.get("text") or {}).get("text") or "").replace("\n", " ")
        n = len(txt)
        t0 = s["target"]["start_us"] / 1e6
        adur = (a.get("duration_us") or 0) / 1e6 or (s["target"]["duration_us"] / 1e6)
        c = (s.get("clip") or {})
        styles = ((s.get("text") or {}).get("styles") or [{}])
        size = max([st.get("size") or 0 for st in styles] +
                   [((s.get("text") or {}).get("font_size")) or 0])
        vc = 0.5 - (c.get("y") or 0.0) / 2
        half = max(0.05, 0.8 * size * rf.K_EM * cw / ch)
        rows_px = (max(0, int((vc - half) * scale_h)), min(scale_h, int((vc + half) * scale_h)))

        # 标定 R_k：我们自己的纯文字层，k=0..n
        r_k = []
        for k in range(n + 1):
            canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            m2 = text_only_model(model, s["id"], txt[:k])
            if k > 0:
                rf.collect(canvas, m2, int((t0 + adur * 2) * 1e6), {})
            cols = white_cols(canvas.convert("RGB").resize((scale_w, scale_h)), rows_px) \
                if k > 0 else np.zeros(scale_w, dtype=bool)
            r_k.append(right_edge(cols))
        if r_k[n] < 0:
            print(f"  t0={t0:6.2f} n={n} 文字层无白墨，跳过")
            continue

        # 列窗：我们自己各前缀边缘所张成的区间（右端留光标余量）。E 只在窗内找。
        span = max(4, r_k[n] - r_k[0])
        win = (max(0, (r_k[1] if n >= 1 else r_k[n]) - 8),
               min(scale_w, r_k[n] + int(0.6 * span) + 8))

        # **有效性对照（F-089 的教训，写进仪器而不是只写进文档）**：
        # 在「这段还不在场」的时刻量同一个窗。若窗内仍有超出背景的亮墨，
        # 说明那墨属于我们背景没复现的别的层 ⇒ **这台仪器对这个段无效**，
        # 它的 k_export 全部作废。上一轮我没做这条对照，把 E=168（字幕右边缘才 144）
        # 读成了「成片已经画满 4 个字」，据此得出的「慢一个字」整条是假信号。
        ctrl = None
        for back in (1.0, 1.5, 2.0, 2.5):
            tc = t0 - back * adur
            if any(x["target"]["start_us"] <= int(tc * 1e6)
                   < x["target"]["start_us"] + x["target"]["duration_us"]
                   for tt in model["tracks"] if tt["type"] == "text" for x in tt["segments"]):
                continue                       # 这个对照时刻别的字幕在场，换更早的
            ci = int(round(tc * args.fps)) + args.lead
            if not (0 <= ci < len(frames)):
                continue
            rf.APPLY_ANIMATIONS = False
            cbbg = Image.new("RGBA", (cw, ch), (0, 0, 0, 255))
            rf.collect(cbbg, model_without_text(model, s["id"]), int(tc * 1e6), {})
            cd = (band_luma(Image.open(frames[ci]), rows_px, (scale_w, scale_h))
                  - band_luma(cbbg, rows_px, (scale_w, scale_h)))
            cc = cd.max(axis=0) > args.excess
            ctrl = (ci, int(np.nonzero(cc[win[0]:win[1]])[0].max()) + win[0]
                    if cc[win[0]:win[1]].any() else -1)
            break
        if ctrl is not None and ctrl[1] > r_k[n] + 0.25 * span:
            unusable.append({"t0": round(t0, 3), "ctrl_frame": ctrl[0], "ctrl_E": ctrl[1],
                             "R_full": r_k[n]})
            print(f"  t0={t0:6.2f} n={n} **无效**：该段不在场时窗内仍有亮墨 "
                  f"E={ctrl[1]} > 全文右边缘 {r_k[n]} ⇒ 这段的 k_export 不进总账")
            continue
        line = []
        for i in range(args.samples):
            f = (i + 0.5) / args.samples
            t = t0 + f * adur
            idx = int(round(t * args.fps)) + args.lead
            if not (0 <= idx < len(frames)):
                continue
            # 背景 = 同刻、同模型、只把**这一段**文字清空 ⇒ 减掉素材亮度之后再找右边缘。
            # 上一版直接在整行找最亮列，字幕右侧的白展板把 E 推到画幅边 ⇒ 59/70 判脏。
            rf.APPLY_ANIMATIONS = False
            bgc = Image.new("RGBA", (cw, ch), (0, 0, 0, 255))
            rf.collect(bgc, model_without_text(model, s["id"]), int(t * 1e6), {})
            diff = (band_luma(Image.open(frames[idx]), rows_px, (scale_w, scale_h))
                    - band_luma(bgc, rows_px, (scale_w, scale_h)))
            cols = diff.max(axis=0) > args.excess
            inside = np.nonzero(cols[win[0]:win[1]])[0]
            k_our = ac.typewriter_prefix(a["tw"], f * adur, adur, n)
            # **这一行的其它字幕层**：`k_export` 是从「墨的右边缘落在哪个前缀上」推出来的，
            # 不是认字认出来的。本时间线有 3 条字幕轨、clip.y 全是 -0.4427（同一行），
            # 所以只要别的段在这时刻活着，窗内的墨就可能是**它的**，k_export 就是假的。
            others = [x["id"] for tt in model["tracks"] if tt["type"] == "text"
                      for x in tt["segments"] if x["id"] != s["id"]
                      and x["target"]["start_us"] <= int(t * 1e6)
                      < x["target"]["start_us"] + x["target"]["duration_us"]]
            if others:
                shared += 1
                line.append({"f": round(f, 2), "skipped": "row_shared", "others": others,
                             "k_ours": k_our, "E": None, "k_export": None, "no_ink": 0})
                continue
            if len(inside):
                E = int(inside.max()) + win[0]
                k_exp = min(range(n + 1), key=lambda k: abs(r_k[k] - E))
                no_ink = 0
            else:
                # 窗内一点超出背景的墨都没有 ⇒ 这就是「还没出字」，k_export=0（不是脏）。
                # 但要单独计数：若我们的背景比成片还亮（解码/色彩范围差），这条会被误读成 0 字。
                E, k_exp, no_ink = -1, 0, 1
            line.append({"f": round(f, 2), "E": E, "k_export": k_exp, "k_ours": k_our,
                         "no_ink": no_ink})
            if k_exp == k_our:
                agree += 1
            else:
                disagree += 1
                deltas.append(k_our - k_exp)
        rows.append({"t0": round(t0, 3), "adur": round(adur, 3), "n": n, "window": list(win),
                    "rows_px": list(rows_px), "R_k": r_k, "control": ctrl, "samples": line})
        print(f"  t0={t0:6.2f} n={n} 列窗{win} R_k={r_k} "
              f"对照={'无(找不到该段不在场且无别的字幕的时刻)' if ctrl is None else f'帧{ctrl[0]} E={ctrl[1]}'}  "
              + " ".join(f"f{x['f']:.2f} 片{x['k_export']}{'(无墨)' if x['no_ink'] else ''}"
                         f"/我{x['k_ours']}{'✓' if x['k_export'] == x['k_ours'] else '✗'}"
                         for x in line))
    no_ink = sum(r["no_ink"] for row in rows for r in row["samples"])
    print("-" * 78)
    print(f"逐时刻字数对表：**一致 {agree} / 不一致 {disagree}**（样本 {agree + disagree}，"
          f"另有 {shared} 个样本该行被别的字幕段占 ⇒ 弃；"
          f"其中 {no_ink} 个窗内「比背景无超出」⇒ 判为 0 字）")
    if deltas:
        print(f"不一致时 k_ours − k_export：中位 {statistics.median(deltas):+.1f}，"
              f"范围 {min(deltas):+d}..{max(deltas):+d}（正=我们比成片多画，负=少画）")
    pathlib.Path(args.report).write_text(
        json.dumps({"rows": rows, "agree": agree, "disagree": disagree,
                    "dirty": dirty, "deltas": deltas}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"report -> {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
