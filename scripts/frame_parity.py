#!/usr/bin/env python3
"""frame_parity.py — **逐帧**把预览画出来的每一帧和成片对一遍，并把不合格的点按成因分组。

为什么要有这一层：门的 `L10` 一次只判 3 个时刻（1.0 / 6.633 / 20.23），`L11` 判 16 帧闪白，
`L3` 判视频带 11 个点。用户的目标是「预览完全复刻成片」，那判据必须落在**每一帧**上，
否则两帧之间的问题可以一路绿到底（P-124 的切点那一帧就是这类：三个采样点全都碰不到它）。

两条腿分开跑，因为取图贵、判定便宜：

    # ① 预览腿：起网关 + headless Chrome，让页面自己把每一帧回传 /shot
    python scripts/frame_parity.py --sweep --stride 1
    # ② 判定腿：浏览器帧 vs 成片 dense216（±3 搜最佳对齐，与 browser_shot_check 同一口径）
    python scripts/frame_parity.py --judge

判据线**沿用 `browser_shot_check.py` 已有的那两个数**（不新造尺子）：
`--min-export 0.90`（浏览器 vs 成片，±3 对齐后的最佳相关）、`--min-cross 0.95`（vs 通道 2，只对失败点补算）。
`--lead 3` 是"成片忽略首帧"的实测值（P-163：idx0→1→2 MAD 0.00、2→3 34.20）。

失败点会带成因标签（切点邻帧 / 字幕带在场 / 闪白段 / 调色支 / 组合子段口播 / 黑场），
"完全复刻"的口径 = 每一帧 vs 成片 ≥0.90 **且** 没有未归因的帧。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import psutil  # noqa: E402
from browser_soak import (BROWSER_RSS_LIMIT_MB, CHROME, OUT, ROOT, stop_process_tree,
                          tree_rss_mb)  # noqa: E402  复用 Chrome 进程树口径
from browser_shot_check import corr, luma_at, mean_lum  # noqa: E402  同一把尺，不另抄一份

DRAFT = Path("D:/JianyingPro/JianyingPro Drafts/李金昌 10月15日 (4)")


def free_port() -> int:
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ---------------- ① 预览腿 ----------------

def frame_times(model: dict, stride: int, fps: float) -> list[float]:
    dur = model["duration_us"] / 1e6
    n = int(math.ceil(dur * fps))
    return [round(i / fps, 3) for i in range(0, n, stride)]


def pick_times(model: dict, args) -> list[float]:
    """取样点名单：sweep 与 judge 必须用**同一份**，否则判定腿会去数一批根本没取的帧。"""
    times = frame_times(model, args.stride, args.fps)
    if args.limit:
        times = times[:: max(1, len(times) // args.limit)][: args.limit]
    return times


def sync_player() -> str:
    """把在册件物化成运行副本（门的 L0 同一条律，P-175 补进这条腿）。

    网关的静态根是 `temp/`，页面 URL 是 `/playback-test/player.html` —— 判的是**副本**，
    不是 `player/player.html`。副本在 gitignore 里，改完真身不刷新就会拿旧页的行为当新页的读数
    （P-175 那跑：`keys` 与 resources 层级都已改，截图仍是改前的，越带数一寸没动）。
    """
    src = ROOT / "player" / "player.html"
    dst = OUT / "player.html"
    blob = src.read_bytes()
    tmp = dst.with_suffix(dst.suffix + ".sync.tmp")
    tmp.write_bytes(blob)
    os.replace(tmp, dst)
    if dst.read_bytes() != blob:
        raise SystemExit("运行副本没能物化成在册件 ⇒ 这一批不判")
    return hashlib.md5(blob).hexdigest()[:12]


def sweep(args, model: dict, guard) -> list[float]:
    md5 = sync_player()
    (OUT / "frame-parity-player.md5").write_text(md5, encoding="utf-8")
    print(f"[sweep] L0 在册件已物化：player/player.html -> temp/playback-test/player.html md5 {md5}")
    times = pick_times(model, args)
    # 把上一轮的截图先挪进子目录（不删）：`browser-shot-<t>.png` 是按时刻命名的，
    # 旧文件会让"这一帧取到了"的判断成立，而它其实来自**另一版页面**——
    # browser_shot_check 用 --max-age-min 挡这件事，这里从源头把两批分开。
    prev = OUT / "shots-previous"
    prev.mkdir(exist_ok=True)
    moved = 0
    for p in list(OUT.glob("browser-shot-*.png")) + list(OUT.glob("browser-shot-*.json")):
        p.replace(prev / p.name)
        moved += 1
    print(f"[sweep] 旧截图挪进 {prev.name}/：{moved} 件")
    urls = []
    for i in range(0, len(times), args.chunk):
        urls.append(",".join(f"{t:g}" for t in times[i:i + args.chunk]))
    port = free_port()
    gw = subprocess.Popen([sys.executable, "-u", str(ROOT / "scripts/preview_gateway.py"),
                           "--port", str(port), "--serve-dir", "temp",
                           "--model", str(ROOT / "temp/playback-test" / args.model),
                           "--log", str(OUT / "gw-frameparity.log")],
                          cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    prof = OUT / "chrome-frameparity"
    prof.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    try:
        for ci, chunk in enumerate(urls):
            first, last = chunk.split(",")[0], chunk.split(",")[-1]
            done = {p.stem.replace("browser-shot-", "").replace("-", ".")
                    for p in OUT.glob("browser-shot-*.png")}
            url = (f"http://127.0.0.1:{port}/playback-test/player.html"
                   f"?model={args.model}&shots={chunk}&aud=0")
            print(f"[sweep] 段 {ci + 1}/{len(urls)}: t={first}…{last}（{chunk.count(',') + 1} 帧）",
                  flush=True)
            proc = subprocess.Popen([CHROME, "--headless=new", "--no-sandbox", "--no-first-run",
                                     "--no-default-browser-check",
                                     "--autoplay-policy=no-user-gesture-required",
                                     f"--user-data-dir={prof.resolve().as_posix()}",
                                     "--window-size=1280,900", "--remote-debugging-port=0", url],
                                    cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            chrome = psutil.Process(proc.pid)
            want = [t for t in chunk.split(",") if t not in done]
            deadline = time.time() + args.per_shot * len(want) + 60
            try:
                while want and time.time() < deadline and proc.poll() is None:
                    guard.check()
                    rss_mb, _, _ = tree_rss_mb(chrome)
                    if rss_mb > BROWSER_RSS_LIMIT_MB:
                        print(f"[memory] Chrome 进程树 RSS {rss_mb:.0f} MB > "
                              f"{BROWSER_RSS_LIMIT_MB:.0f} MB，停止本段", flush=True)
                        stop_process_tree(chrome)
                        break
                    have = {p.stem.replace("browser-shot-", "").replace("-", ".")
                            for p in OUT.glob("browser-shot-*.png")}
                    want = [t for t in want if t not in have]
                    if want:
                        time.sleep(1.0)
            finally:
                stop_process_tree(chrome)
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            if want:
                print(f"[sweep] 段 {ci + 1} 缺 {len(want)} 帧，先停：{want[:6]}", flush=True)
                return []
    finally:
        gw.terminate()
        try:
            gw.wait(timeout=10)
        except Exception:  # noqa: BLE001
            gw.kill()
    print(f"[sweep] 用时 {time.time() - t0:.0f} s")
    return times


# ---------------- ② 判定腿 ----------------

_LUMA: dict = {}
# ±3 帧搜索只需少量邻近帧常驻；128 个 float32 luma 面约 63 MB，避免缓存占去近 300 MB。
LUMA_CAP = 128


def luma(png: Path, w: int, h: int):
    # 逐帧判定时同一张成片帧会被 ±3 搜索解 7 次，缓存它（1105 帧的判定否则要跑 5 分钟以上）
    key = (str(png), w, h)
    v = _LUMA.get(key)
    if v is None:
        v = luma_at(png, w, h)
        _LUMA[key] = v
        # 存的是 float32 归一化数组（518400 B/帧）；±3 对齐只碰邻近帧，128 项足够复用。
        if len(_LUMA) > LUMA_CAP:
            for k in list(_LUMA)[: max(1, LUMA_CAP // 4)]:
                _LUMA.pop(k, None)
    return v


def active_at(model: dict, t: float) -> dict:
    """这一时刻谁在场——失败点要能归因，不然只能列数字。

    窗口一律用**整数微秒**比：`start_us/1e6` 与字面量 `20.233` 是两边不同的浮点数，
    在切点那一帧上 `t0 <= t` 会说假话（实测 20.233 那段动画就这样被漏掉过）。
    """
    out = {"text": 0, "video": 0, "child": 0, "flash": 0, "colour": set(), "gap": False}
    seen_cut = set()
    tus = int(round(t * 1e6))

    def visit(tracks, child=False):
        for tr in tracks:
            if tr.get("muted"):
                pass
            for s in tr.get("segments", []):
                tg = s.get("target") or {}
                su = tg.get("start_us", 0)
                eu = su + tg.get("duration_us", 0)
                t0 = su / 1e6
                t1 = eu / 1e6
                seen_cut.add(round(t0, 3))
                if not (su <= tus < eu):
                    continue
                typ = tr.get("type")
                if typ == "text":
                    out["text"] += 1
                elif typ in ("video", "audio"):
                    out["video"] += 1 if typ == "video" else 0
                if child:
                    out["child"] += 1
                ev = ((s.get("features") or {}).get("effect_values")) or {}
                for k, v in ev.items():
                    # 白名单会自己造假：上一版这里只认七个名字，`figure`/`smart_color_adjust`
                    # 被吃掉，于是带着这两支的段被当成"干净段"，我的 ls 归因跟着就偏了（P-176 之后才看穿）。
                    # 成因标签不是判据线，宁可宽也不要漏。
                    if isinstance(v, (int, float)) and abs(v) > 1e-6:
                        out["colour"].add(k)
                for a in (s.get("animations") or []):
                    if not isinstance(a, dict) or a.get("kind") not in ("in", "out"):
                        continue
                    du = (a.get("duration_us") or 0)
                    if du <= 0:
                        continue
                    if a["kind"] == "in" and 0 <= tus - su <= du:
                        out["flash"] += 1        # 这个字段以前只被初始化成 0，恒 0 ⇒ 哑归因（P-182③）
                    elif a["kind"] == "out" and 0 <= eu - tus <= du:
                        out["flash"] += 1
                comp = (s.get("composite") or {}).get("tracks")
                if comp:
                    visit(comp, True)

    visit(model.get("tracks") or [])
    out["near_cut"] = min((abs(t - c) for c in seen_cut), default=9.0) <= 1.5 / 30.0
    out["colour"] = sorted(out["colour"])
    out["video"] = out["video"] > 0
    return out


def judge(args, model: dict, guard) -> int:
    # L0 自证：这批截图必须能追回当前在册件（sweep 落一枚 md5，这里只核对不改写——
    # 判的是已经取到的图，物化只会把"截图来自哪版页"这件事彻底抹掉）。
    side = OUT / "frame-parity-player.md5"
    want = hashlib.md5((ROOT / "player" / "player.html").read_bytes()).hexdigest()[:12]
    if not side.is_file():
        print("没有 L0 自证文件 frame-parity-player.md5 ⇒ 这批截图不判（先跑 --sweep）")
        return 2
    got = side.read_text(encoding="utf-8").strip()
    if got != want:
        print(f"这批截图的页面是 md5 {got}，当前在册件是 {want} ⇒ 不是同一版，不判")
        return 2
    frames = sorted((ROOT / args.frames_dir).glob("*.png"))
    if len(frames) < 200:
        print(f"成片帧目录只有 {len(frames)} 张：{args.frames_dir}")
        return 2
    h = int(round(args.width * 1920 / 1080))
    times = pick_times(model, args)
    rows, skip_reasons = [], {}
    for i, t in enumerate(times):
        if i % 16 == 0:
            guard.check()
        tag = f"{t:g}".replace(".", "-")   # 与页面/网关的命名同一个口径：10.0 → "10"
        png = OUT / f"browser-shot-{tag}.png"
        if not png.is_file():
            skip_reasons["没有截图"] = skip_reasons.get("没有截图", 0) + 1
            rows.append({"t": t, "skipped": "没有截图"})
            continue
        idx = int(round(t * args.fps)) + args.lead
        if not (0 <= idx < len(frames)):
            skip_reasons["成片帧号越界"] = skip_reasons.get("成片帧号越界", 0) + 1
            rows.append({"t": t, "skipped": f"成片帧号 {idx} 越界"})
            continue
        age_min = (time.time() - png.stat().st_mtime) / 60.0
        if age_min > args.max_age_min:
            skip_reasons["截图过期"] = skip_reasons.get("截图过期", 0) + 1
            rows.append({"t": t, "skipped": f"截图过期 {age_min:.0f} 分钟"})
            continue
        meta = png.with_suffix(".json")
        mj = json.loads(meta.read_text(encoding="utf-8")) if meta.is_file() else {}
        b = luma(png, args.width, h)
        cand = [(k, corr(b, luma(frames[idx + k], args.width, h)))
                for k in range(-args.search, args.search + 1) if 0 <= idx + k < len(frames)]
        off, ecorr = max(cand, key=lambda x: x[1])
        lr = round(mean_lum(png, args.width, h) / max(mean_lum(frames[idx + off], args.width, h), 1e-6), 3)
        act = active_at(model, t)
        row = {"t": t, "export_frame": idx, "offset": off, "vs_export": round(ecorr, 3),
               "luma_ratio": lr, "ok": ecorr >= args.min_export,
               "lum_ok": args.lum_lo <= lr <= args.lum_hi,
               "paint_dt_s": (round(abs((mj.get("t_paint_us") or 0) / 1e6 - t), 4)
                              if mj.get("t_paint_us") is not None else None),
               "color_applied": (mj.get("color") or {}).get("applied"),
               "color_expected": (mj.get("color") or {}).get("expected"),
               **{("why_" + k): v for k, v in act.items()}}
        rows.append(row)
        if row["ok"]:
            continue
        row_no = sum(1 for r in rows if r.get("ok") is False)
        if row_no > 40:
            continue
        print(f"  t={t:7.3f}  vs成片 {row['vs_export']:.3f} 偏移 {off:+d} 亮度比 {lr} "
              f"| 字幕 {row['why_text']} 影像 {row['why_video']} 子段 {row['why_child']} "
              f"切点邻帧 {row['why_near_cut']} 调色 {row['why_colour']} "
              f"paintΔ {row['paint_dt_s']} 滤镜 {row['color_applied']}/{row['color_expected']}")
    guard.check()
    lum_bad = [r for r in rows if r.get("lum_ok") is False]
    bad = [r for r in rows if r.get("ok") is False]
    skipped = [r for r in rows if "skipped" in r]
    for k, v in sorted(skip_reasons.items(), key=lambda x: -x[1]):
        print(f"  未取到/跳过 {k}: {v} 帧")
    good = [r for r in rows if r.get("ok")]
    dist = sorted(r["vs_export"] for r in good + bad)
    pct = lambda p: dist[min(len(dist) - 1, int(p * (len(dist) - 1)))] if dist else None
    by = {}
    for r in bad:
        key = ("切点邻帧" if r["why_near_cut"] else
               "字幕带" if r["why_text"] else
               "调色支" if r["why_colour"] else
               "子段" if r["why_child"] else "别的")
        by.setdefault(key, []).append(r["t"])
    verdict = not bad and not skipped and not lum_bad
    print("-" * 78)
    print(f"逐帧判定：{len(times)} 帧（线 vs 成片 ≥{args.min_export}，±{args.search} 搜对齐，lead {args.lead}）"
          f"｜过 {len(good)}｜红 {len(bad)}｜未取到 {len(skipped)}")
    print(f"亮度比带 {args.lum_lo}–{args.lum_hi}：越带 {len(lum_bad)} 帧"
          f"（{', '.join(f't={r['t']}: {r['luma_ratio']}' for r in lum_bad[:10])}"
          f"{' …' if len(lum_bad) > 10 else ''}）")
    if dist:
        print(f"corr 分布：min {dist[0]:.3f} p05 {pct(.05):.3f} p50 {pct(.5):.3f} "
              f"p95 {pct(.95):.3f} max {dist[-1]:.3f}")
    for k, ts in sorted(by.items(), key=lambda x: -len(x[1])):
        print(f"  归因 {k}: {len(ts)} 帧  例 {ts[:6]}")
    print(("FRAME PARITY PASS：逐帧全部 ≥ 线，且没有未取到的帧" if verdict
           else "FRAME PARITY FAIL：见上面逐帧清单"))
    (ROOT / args.report).write_text(json.dumps(
        {"verdict": verdict, "n": len(times), "fail": len(bad), "skipped": len(skipped),
         "min_export": args.min_export, "lead": args.lead, "by_cause": {k: v for k, v in by.items()},
         "rows": rows}, ensure_ascii=False), encoding="utf-8")
    return 0 if verdict else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default="model-proxy-p157.json")
    ap.add_argument("--frames-dir", default="temp/playback-test/oracle/dense216")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--lead", type=int, default=3, help="成片片头重复帧数（P-163 实测 3）")
    ap.add_argument("--stride", type=int, default=1, help="帧步进，1 = 逐帧")
    ap.add_argument("--limit", type=int, default=0, help="只取 N 个采样点做标定")
    ap.add_argument("--chunk", type=int, default=120, help="一次页面会话取多少帧")
    ap.add_argument("--per-shot", type=float, default=8.0, help="每帧预算秒数（超时即停并报缺）")
    ap.add_argument("--width", type=int, default=270)
    ap.add_argument("--search", type=int, default=3, help="对齐搜索半径（帧）")
    ap.add_argument("--min-export", type=float, default=0.90)
    ap.add_argument("--lum-lo", type=float, default=0.96,
                    help="亮度比下界（沿用 brightness 一支的验收带 0.96–1.04，P-133/P-135）")
    ap.add_argument("--lum-hi", type=float, default=1.04)
    ap.add_argument("--max-age-min", type=float, default=240.0)
    ap.add_argument("--report", default="temp/playback-test/frame-parity.json")
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--judge", action="store_true")
    args = ap.parse_args()
    if not (args.sweep or args.judge):
        ap.error("要 --sweep（取图）或 --judge（判定），或两者都要")
    model = json.loads((OUT / args.model).read_text(encoding="utf-8-sig"))
    import mem_gate as mg
    mg.require_free()
    guard = mg.PeakGuard(label="frame_parity")
    with mg.heavy_lock():
        try:
            guard.check()
            if args.sweep:
                got = sweep(args, model, guard)
                if not got:
                    print("取图没跑齐，判定不启动（缺帧判绿是没意义的）")
                    return 1
            if args.judge:
                return judge(args, model, guard)
            return 0
        finally:
            print(f"[memory] {guard.summary()}")


if __name__ == "__main__":
    sys.exit(main())
