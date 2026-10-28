"""U-93 的两段式探针：浏览器比通道 2 亮 ~1.8 码值，出在**解码**还是**上屏**。

L10 看到的是一个数（+1.8），但视频腿上有两个环节都能各自引入色彩偏移：
  ① WebCodecs / `createImageBitmap` 的 yuv→rgb 与 limited/full range 处理；
  ② Pixi 的 sRGB 纹理色彩空间（上屏那一跳）。
所以把两条腿分开量：

  段一 同一条素材的同一**源帧**：ffmpeg 解出来的 PNG 中心 256 框 luma 均值（Python 侧，通道 2 用的就是它）
        vs 浏览器解出来并画到画面上的那一帧的同一框均值。
        浏览器侧不需要新页面：造一个 **solo 模型**（只留一条视频轨、只留覆盖该时刻的那一段、
        丢掉文字轨与叠加轨），于是页面画出来的就是这条素材本身，`&shots=` 回传即得。
        差 ≈ +1.8 ⇒ 落在解码/色彩转换（①）；差 ≈ 0 ⇒ 解码没问题，进段二。
  段二 同一个 solo 模型：浏览器（Pixi 上屏）vs 通道 2（PIL 直接贴）——两者都读同一份代理文件，
        如果段一里 ffmpeg↔浏览器 已经差 1.8，那就是 ①；若只在这里差，就是 ②。
        （脚本一次跑完两段的三个数，避免分两次跑还要重新对齐源帧。）

口径纪律：
  - 均值取 luma（0.299/0.587/0.114）在**画面中心 256×256** 固定框内，避开边缘与黑边；
  - 比较的必须是**同一源帧**：ffmpeg 用段的 `source.start + (t - target.start)` 秒去 `-ss`，
    并额外解码 ±1 帧取各自的均值——报告把三个候选都列出，避免「取到相邻帧」冒充「色彩偏移」；
  - 素材绝对路径、时间线时刻、源时刻三样都进报告（本项目的读数规矩）。

用法:
    python scripts/colour_range_probe.py [--timeline-model temp/playback-test/model-proxy-a.json]
                                         [--t 12.0] [--track 0] [--port 8798]
                                         [--report temp/playback-test/colour-probe.json]
前置：机器空载（它会起一次浏览器）。它 **不** 改草稿，只写 temp/。
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

# Windows 控制台是 GBK：这台机器上已有 4 个工具在**算完之后**的 print 上崩掉、把读数吞了。
# 只改错误处理策略（替换不可编码字符），不改编码。
try:
    sys.stdout.reconfigure(errors="replace")     # type: ignore[attr-defined]
    sys.stderr.reconfigure(errors="replace")     # type: ignore[attr-defined]
except Exception:                                 # noqa: BLE001
    pass
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "temp" / "playback-test"
sys.path.insert(0, str(ROOT / "scripts"))
import jy_paths                                      # noqa: E402

FF = str(jy_paths.ffmpeg())


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_port(port: int, timeout: float = 25.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.2)
    return False


def luma_box(path: Path | str, frac: float = 0.237) -> float | None:
    """中心区均值 luma，**框按图像自身尺寸取比例**，不取固定像素。

    原来写死 `box=256` 像素：256/1080 = 24% 但 256/540 = 47%，于是浏览器腿（页面回传 540 宽）
    与 ffmpeg 腿（原生 1080 宽）**量的根本不是同一块画面**——上一轮那个"浏览器 +21 码值"
    就是这么来的（真值是 +1.1~+1.8 的均匀偏移）。按比例取框之后，三腿的相对区域一致。
    """
    try:
        im = Image.open(path).convert("RGB")
    except OSError:
        return None
    w, h = im.size
    bw, bh = max(1, round(w * frac)), max(1, round(h * frac))
    x0, y0 = (w - bw) // 2, (h - bh) // 2
    a = np.asarray(im.crop((x0, y0, x0 + bw, y0 + bh)), dtype=np.float32)
    v = a @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    return round(float(v.mean()), 2)


def shot_size(path: Path) -> list[int] | None:
    if not path.is_file():
        return None
    w, h = Image.open(path).size
    return [w, h]


def build_solo_model(src: Path, t: float, track_index: int, dest: Path) -> dict | None:
    """只留一条轨 + 覆盖 t 的那一段：页面画出来的就是这条素材本身。"""
    m = json.loads(src.read_text(encoding="utf-8-sig"))
    pos = int(round(t * 1e6))
    tracks = []
    for i, tr in enumerate(m["tracks"]):
        if i != track_index or tr["type"] == "audio":
            continue
        segs = [s for s in tr["segments"]
                if s["target"]["start_us"] <= pos < s["target"]["start_us"] + s["target"]["duration_us"]]
        if not segs:
            return None
        tr = dict(tr)
        tr["segments"] = segs
        tracks.append(tr)
    if not tracks:
        return None
    solo = {**m, "tracks": tracks}
    dest.write_text(json.dumps(solo, ensure_ascii=False), encoding="utf-8")
    return solo


def ffmpeg_frame(media: str, at_s: float, out: Path) -> float | None:
    cmd = [FF, "-hide_banner", "-loglevel", "error", "-ss", f"{at_s:.6f}", "-i", media,
           "-frames:v", "1", "-y", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not out.is_file():
        return None
    return luma_box(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--timeline-model", default=str(OUT / "model-proxy-a.json"))
    ap.add_argument("--t", type=float, default=12.0)
    ap.add_argument("--track", type=int, default=0)
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--player", default="player.html")
    ap.add_argument("--seconds", type=int, default=120)
    ap.add_argument("--report", default=str(OUT / "colour-probe.json"))
    args = ap.parse_args()

    solo_path = OUT / "model-solo.json"
    solo = build_solo_model(Path(args.timeline_model), args.t, args.track, solo_path)
    if not solo:
        print(f"track{args.track} 在 t={args.t} 没有活动段（换一个 --t / --track）", file=sys.stderr)
        return 2
    seg = solo["tracks"][0]["segments"][0]
    mm = seg.get("media") or {}
    media = mm.get("path")
    if not media or not os.path.isfile(media):
        print(f"该段没有可读素材: {media}", file=sys.stderr)
        return 2
    src_s = (seg["source"]["start_us"] + (int(args.t * 1e6) - seg["target"]["start_us"])
             * (seg.get("speed") or 1)) / 1e6

    # 通道 2：同一个 solo 模型渲染同一时刻
    c2 = OUT / "colour-channel2.png"
    subprocess.run([sys.executable, "scripts/render_frame.py", "--model", str(solo_path),
                    "--t", f"{args.t}", "--out", str(c2)], cwd=str(ROOT),
                   capture_output=True, text=True, encoding="utf-8", errors="replace")

    # ffmpeg：同一源时刻，并给 ±1 帧做对照（防止「差一帧」被当成「色彩偏移」）
    step = 1.0 / 30.0
    ff = {"center": ffmpeg_frame(media, src_s, OUT / "colour-ffmpeg.png"),
          "minus1": ffmpeg_frame(media, src_s - step, OUT / "colour-ffmpeg-m1.png"),
          "plus1": ffmpeg_frame(media, src_s + step, OUT / "colour-ffmpeg-p1.png")}

    # 浏览器：起网关 + 页面，用现成的 &shots= 回传（solo 模型下画面就是这条素材）
    port = args.port or free_port()
    # **过期截图防护**：页面写的名字是它自己格式化的（t=12.0 → `browser-shot-12.png`，
    # 不是 `browser-shot-12-0.png`），所以按字符串拼出来的那个 unlink **删不掉真正会被读的文件**——
    # 上一轮门留下的旧截图就会被当成本次 solo 结果读进来。改成「记下开始时刻 + 事后只认
    # mtime 晚于它、且解析出的时刻对得上的那张」，宁可报 None 也不读来历不明的图。
    t_start = time.time()
    shot = OUT / f"browser-shot-{str(args.t).replace('.', '-')}.png"
    shot.unlink(missing_ok=True)
    gw = subprocess.Popen([sys.executable, "scripts/preview_gateway.py", "--port", str(port),
                           "--serve-dir", "temp", "--model", str(solo_path)],
                          cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    browser = None
    shot_used: Path | None = None
    sizes: dict = {}
    try:
        if not wait_port(port):
            print("网关没起来", file=sys.stderr)
            return 2
        url = (f"http://127.0.0.1:{port}/playback-test/{args.player}"
               f"?model={solo_path.name}&seek={args.t}&shots={args.t}"
               f"&fps=30&qmax=4&pool=4&tag=shot")
        subprocess.run([sys.executable, "scripts/browser_soak.py", "--url", url,
                        "--seconds", str(args.seconds), "--report", "temp/playback-test/report-shot.jsonl",
                        "--tag", "shotprobe", "--timeout", str(args.seconds + 30)],
                       cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
        fresh = []
        for p in sorted(OUT.glob("browser-shot-*.png")):
            try:
                pt = float(p.stem.replace("browser-shot-", "").replace("-", "."))
            except ValueError:
                continue
            if abs(pt - args.t) < 1e-3 and p.stat().st_mtime >= t_start:
                fresh.append(p)
        shot_used = fresh[-1] if fresh else None
        browser = luma_box(shot_used) if shot_used else None
        sizes = {"ffmpeg": shot_size(OUT / "colour-ffmpeg.png"),
                 "channel2": shot_size(c2), "browser": shot_size(shot_used)}
    finally:
        gw.terminate()
        try:
            gw.wait(timeout=10)
        except subprocess.TimeoutExpired:
            gw.kill()

    rows = {"media": media, "t_timeline": args.t, "t_source": round(src_s, 4),
            "box_frac": 0.237, "sizes": sizes, "shot": shot_used.name if shot_used else None,
            "ffmpeg_luma": ff, "channel2_luma": luma_box(c2), "browser_luma": browser}
    # 三腿的相对区域只有在**宽高比一致**时才真的同一块；不一致就直接标出来（540×953 那种
    # 内容包围盒差异会把 0.7% 的拉伸伪装成色彩差）。
    asp = {k: round(v[0] / v[1], 4) for k, v in sizes.items() if v}
    rows["aspect_ratios"] = asp
    if len({round(a, 3) for a in asp.values()}) > 1:
        rows["geometry_mismatch"] = True
    if rows["channel2_luma"] is not None and ff["center"] is not None:
        rows["d_channel2_minus_ffmpeg"] = round(rows["channel2_luma"] - ff["center"], 2)
    if browser is not None and ff["center"] is not None:
        rows["d_browser_minus_ffmpeg"] = round(browser - ff["center"], 2)
    if browser is not None and rows["channel2_luma"] is not None:
        rows["d_browser_minus_channel2"] = round(browser - rows["channel2_luma"], 2)
    print(json.dumps(rows, ensure_ascii=False, indent=1))
    Path(args.report).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"report -> {args.report}")
    print("判读：d_browser_minus_ffmpeg≈0 且 d_browser_minus_channel2≈0 ⇒ 这次没复现（换时刻再测）；"
          "d_browser_minus_ffmpeg≈+1.8 ⇒ 解码/色彩转换侧（候选①）；"
          "只有 d_browser_minus_channel2 显著 ⇒ 上屏侧（候选②，Pixi 色彩空间）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
