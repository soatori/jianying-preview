"""Rebuild the timeline proxies the L4 battery plays, and the model that points at them.

Why this exists: the draft's video sources are 1080p59.94/50 at 57-70 Mbps on a
mapped drive (X:). Playing those straight through the browser gives ~7 fps and
seek >1 s, which is a storage/decode artifact and not a statement about the
player. Proxies move the variable being measured off the network.

Recipe is fixed by docs (h264_nvenc + yuv420p + faststart, source frame rate
preserved) plus the keyframe spacing measured in the gate: 1/6 s (P-110 — the
three-arm comparison against a same-recipe freshly-written control, so "the
file was just rewritten" is not what bought the improvement). Resolution is
deliberately NOT scaled: the pixel layers
(L2/L3/L10) compare against a native export at the same geometry, so a scaled
proxy would silently move that baseline.

Outputs land under temp/ only; sources are opened read-only and never rewritten.

Usage:
    python scripts/make_all_proxies.py --model temp/playback-test/model-check.json \
        --out-dir temp/playback-test/proxies --model-out temp/playback-test/model-proxy-a.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 门里三臂对照定下来的档位（P-110）：1/6 秒。改回 1.0 是合法的（`--gop-seconds 1.0`），
# 但那会把 first frame 从 128 ms 送回 388–431 ms、帧 max 中位从 187 送回 298–329。
DEFAULT_GOP_SECONDS = 1.0 / 6.0


def media_items(model: dict) -> list[dict]:
    media = model.get("media") or []
    return list(media.values()) if isinstance(media, dict) else list(media)


def swap_paths(node, proxy_map: dict) -> int:
    """把任何指向已代理源的 `path` 换成代理 —— **递归到底，含复合子时间线**。

    只换顶层 `media[]` 是不够的：播放器读的是 `segment.media.path`，而复合子画
    (`segments[].composite.tracks[].segments[].media` 与 `composite.media[]`) 各自带一份。
    漏掉子层的症状很阴：汇总行照报「25/49 media entries swapped」，子画却仍向网关要原路径
    （`! media X:/… not served [pump=none no-handle]`），L6 因此红。
    顶层条目上那些描述**源**的字段（exists/readable/container）一并按代理重算；`raw_path`
    是出处，留着不动。
    """
    swapped = 0
    if isinstance(node, dict):
        raw = node.get("path")
        if isinstance(raw, str):
            hit = proxy_map.get(Path(raw).resolve().as_posix())
            if hit:
                node["path_original"] = raw
                node["path"] = hit
                node["exists"] = Path(hit).is_file()
                node["readable"] = node["exists"]
                if "container" in node:
                    node["container"] = None     # 描述的是源，留着会让门的载体新鲜度判它过期
                swapped += 1
        for value in node.values():
            swapped += swap_paths(value, proxy_map)
    elif isinstance(node, list):
        for value in node:
            swapped += swap_paths(value, proxy_map)
    return swapped


def leftover_paths(node, proxy_map: dict) -> list:
    """写完重读后用：还指向「已代理源」的原路径清单（应为空）。"""
    found = []
    if isinstance(node, dict):
        raw = node.get("path")
        if isinstance(raw, str) and proxy_map.get(Path(raw).resolve().as_posix()):
            found.append(raw)
        for value in node.values():
            found.extend(leftover_paths(value, proxy_map))
    elif isinstance(node, list):
        for value in node:
            found.extend(leftover_paths(value, proxy_map))
    return found


def parse_fps(stream: dict) -> float:
    for key in ("avg_frame_rate", "r_frame_rate"):
        raw = stream.get(key) or ""
        num, _, den = raw.partition("/")
        try:
            value = float(num) / float(den or 1)   # "0/0" is ffprobe's "unknown"
        except (ValueError, ZeroDivisionError):
            continue
        if value > 0:
            return value
    return 0.0


def probe(ffprobe: str, path: str) -> dict:
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
        capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or "ffprobe failed").strip()[:200])
    return json.loads(out.stdout)


def target_name(src: Path, out_dir: Path, kind: str) -> Path:
    # Flat, collision-free and reversible: the source's own drive-less tail plus a
    # short hash, so two same-named files from different folders stay distinct.
    tail = "_".join(src.parts[-2:]).replace(":", "")
    digest = hashlib.sha1(src.as_posix().lower().encode("utf-8")).hexdigest()[:8]
    return out_dir / f"{tail[:60]}-{digest}.{kind}"


def gop_frames(fps: float, gop_seconds: float) -> int:
    return max(2, round((fps if fps > 0 else 60) * gop_seconds))


def transcode(ffmpeg: str, src: Path, dst: Path, fps: float,
              gop_seconds: float = DEFAULT_GOP_SECONDS, audio: str = "aac") -> None:
    gop = gop_frames(fps, gop_seconds)
    a_args = ["-c:a", "copy"] if audio == "copy" else ["-c:a", "aac", "-b:a", "160k"]
    tmp = dst.with_suffix(dst.suffix + ".part.mp4")
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
           "-map", "0:v:0", "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr",
           "-cq", "26", "-b:v", "0", "-pix_fmt", "yuv420p",
           "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0",
           "-map", "0:a:0?", *a_args,
           "-movflags", "+faststart", str(tmp)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError((res.stderr or "encode failed").strip()[:300])
    os.replace(tmp, dst)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", required=True)
    ap.add_argument("--gop-seconds", type=float, default=DEFAULT_GOP_SECONDS,
                    help=f"关键帧间隔（秒），按每只素材自己的 fps 换算成 -g；默认 {DEFAULT_GOP_SECONDS:.4f} = 1/6 秒。"
                         "档位由门里三臂对照定（P-110）：曲线谷底在 1/6 s（P-107），比它更密要付体积，"
                         "比它更稀则 first frame 与帧尾一起涨回 3 倍")
    ap.add_argument("--audio", choices=("aac", "copy"), default="aac",
                    help="从已有代理片派生时用 copy，音频就与被比的那套逐字节相同，"
                         "变量只剩 -g（P-105 ②的闸门）")
    ap.add_argument("--out-dir", default=str(ROOT / "temp/playback-test/proxies-g16-all"),
                    help="产物目录。**已存在的同名文件只复用、不重编** ⇒ 把新档位指到旧配率的目录"
                         "会得到旧配率（复用行会打印出来，别忽略它）")
    ap.add_argument("--model-out", default=str(ROOT / "temp/playback-test/model-proxy-g16.json"))
    ap.add_argument("--limit", type=int, default=0, help="stop after N files (smoke run)")
    args = ap.parse_args()

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        print("FAIL ffmpeg/ffprobe not on PATH", file=sys.stderr)
        return 1
    if "nvenc" not in subprocess.run([ffmpeg, "-hide_banner", "-encoders"],
                                     capture_output=True, text=True).stdout:
        print("FAIL this ffmpeg has no nvenc; pin one that does", file=sys.stderr)
        return 1

    model_path = Path(args.model)
    model = json.loads(model_path.read_text(encoding="utf-8-sig"))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    paths = sorted({m["path"] for m in media_items(model) if m.get("path") and m.get("type") == "video"})
    proxy_map: dict[str, str] = {}
    skipped, failed, silent = [], [], []
    done = 0
    for raw in paths:
        src = Path(raw)
        if not src.is_file():
            skipped.append((raw, "absent"))
            continue
        try:
            info = probe(ffprobe, raw)
        except RuntimeError as exc:
            skipped.append((raw, f"unprobeable: {exc}"))
            continue
        streams = info.get("streams") or []
        v = next((s for s in streams if s.get("codec_type") == "video"), None)
        if v is None:
            skipped.append((raw, "no video stream - served direct"))
            continue
        if (v.get("disposition") or {}).get("attached_pic") or int(v.get("width") or 0) < 256:
            # Cover art inside an .mp3 and sticker .png files also report a "video"
            # stream; nvenc rejects sub-minimum frames and the player reads stills
            # natively, so those stay pointed at the original.
            skipped.append((raw, "still image / attached picture - served direct"))
            continue
        if next((s for s in streams if s.get("codec_type") == "audio"), None) is None:
            silent.append(raw)
        fps = parse_fps(v)
        dst = target_name(src, out_dir, "mp4")
        if dst.is_file() and dst.stat().st_size > 0:
            proxy_map[src.resolve().as_posix()] = dst.resolve().as_posix()
            print(f"  [reuse] {src.name} -> {dst.name}（已存在，**没按本次 -g 重编**）", flush=True)
            continue
        try:
            transcode(ffmpeg, src, dst, fps, args.gop_seconds, args.audio)
            proxy_map[src.resolve().as_posix()] = dst.resolve().as_posix()
            done += 1
            print(f"  [{done}] {src.name}  {fps:.2f}fps -g {gop_frames(fps, args.gop_seconds)}"
                  f" -> {dst.name} ({dst.stat().st_size/1e6:.1f} MB)", flush=True)
        except (RuntimeError, OSError) as exc:
            failed.append((raw, str(exc)))
            print(f"  FAIL {src.name}: {exc}", file=sys.stderr, flush=True)
        if args.limit and done >= args.limit:
            print(f"  --limit {args.limit} reached", flush=True)
            break

    (out_dir / "proxy-map.json").write_text(json.dumps(proxy_map, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
    swapped = swap_paths(model, proxy_map)
    out_model = Path(args.model_out)
    tmp = out_model.with_suffix(out_model.suffix + ".tmp")
    tmp.write_text(json.dumps(model, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, out_model)

    # 自检：写完之后**重读一遍文件**，任何一层还留着已代理源的路径就是没换干净。
    # 不这么判的话，「swapped=25」这种数字本身可以完全自洽而子层是漏的（本轮就是这么红的 L6）。
    written = json.loads(out_model.read_text(encoding="utf-8-sig"))
    left = [raw_path for raw_path in leftover_paths(written, proxy_map)]
    if left:
        print(f"FAIL 模型里还有 {len(left)} 处指向已代理源的原路径（子层没换干净）：{left[:4]}",
              file=sys.stderr)
        return 1
    top = len(media_items(model))
    print(f"proxied {done} new, {len(proxy_map)} mapped, {swapped} path(s) swapped "
          f"(顶层 media {top} 条，含复合子画的分层条目)")
    print(f"proxy model -> {out_model}")
    for raw, why in skipped:
        print(f"  skipped: {Path(raw).name} ({why})")
    if silent:
        print(f"  {len(silent)} video source(s) carry no audio track: {[Path(p).name for p in silent][:6]}")
    if failed:
        print(f"FAILED {len(failed)} encode(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
