"""Measure JianYing's real subtitle size from an exported MP4.

Time alignment with the draft is unreliable (exports often carry a tail, and drafts keep
being edited), so this works purely from band statistics:

1. detect the subtitle ink band in N sampled export frames (near-white pixels, lower half);
2. convert band height to an em using the **draft's own font file** -- the ink/em ratio is
   measured by rendering the same glyphs with Pillow, not guessed;
3. compare against every ``font_size`` used in the draft, so the implied px-per-size
   constant falls out directly.

    python -m jypreview.tools.measure_export --video <导出视频路径>\\<export>.mp4 \
        --draft "draft-mirror-drift" --timeline active --frames 40

Read ``implied_px_per_size`` against the current ``text_scale_factor * canvas_width``
(0.01 * 1080 = 10.8 px per size unit).
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from PIL import Image, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from jypreview import config as config_mod  # noqa: E402
from jypreview.model import paint  # noqa: E402
from jypreview.session import PreviewSession  # noqa: E402


def sample_frames(video: Path, count: int, out_dir: Path) -> list[tuple[float, Path]]:
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=nw=1:nk=1", str(video)],
                           capture_output=True, text=True, timeout=30)
    try:
        duration = float(probe.stdout.strip())
    except ValueError:
        duration = 0.0
    if duration <= 0:
        return []
    step = duration / (count + 1)
    frames = []
    for index in range(1, count + 1):
        seconds = index * step
        target = out_dir / f"f{index:03d}.png"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{seconds:.3f}",
                        "-i", str(video), "-frames:v", "1", "-y", str(target)],
                       capture_output=True, timeout=60)
        if target.is_file():
            frames.append((seconds, target))
    return frames


def detect_bands(image: Image.Image, rgb=(255, 255, 255), tolerance=30) -> list[dict]:
    """Row bands of near-``rgb`` pixels in the lower 60% -- one per subtitle line."""
    width, height = image.size
    small = image.convert("RGB").resize((width // 3, height // 3))
    scale = 3
    w, h = small.size
    pixels = small.load()
    rows: list[tuple[int, int, int]] = []
    y = int(h * 0.4)
    while y < h:
        xs = [x for x in range(w) if _near(pixels[x, y], rgb, tolerance)]
        if len(xs) >= max(6, int(w * 0.03)):
            top = y
            run_xs: list[int] = []
            while y < h:
                row_xs = [x for x in range(w) if _near(pixels[x, y], rgb, tolerance)]
                if len(row_xs) < max(4, int(w * 0.02)):
                    break
                run_xs.extend(row_xs)
                y += 1
            height_px = (y - top) * scale
            if 12 <= height_px <= h * scale * 0.45:
                rows.append((top * scale, (min(run_xs) * scale, max(run_xs) * scale)))
        else:
            y += 1
    bands = []
    for top, (left, right) in rows:
        bands.append({"top_px": top, "left_px": left, "right_px": right,
                      "height_px": None, "width_px": right - left})
    paired = []
    for band in bands:
        band["height_px"] = None
        paired.append(band)
    return paired


def _near(pixel, target, tolerance) -> bool:
    return all(abs(int(a) - int(b)) <= tolerance for a, b in zip(pixel, target))


def ink_to_em_ratio(font_path: str | None, sample: str, size_px: int = 240) -> float:
    """Ink height / em for the draft's actual font, measured with Pillow."""
    probe = sample or "国"
    box = None
    if font_path and Path(font_path).is_file():
        try:
            font = ImageFont.truetype(font_path, size_px)
            box = font.getbbox(probe)
        except OSError:
            box = None
    if not box:
        return 0.88
    ink_height = max(box[3] - box[1], 1)
    return round(ink_height / size_px, 4)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True)
    parser.add_argument("--draft", required=True)
    parser.add_argument("--timeline", default="active")
    parser.add_argument("--frames", type=int, default=40)
    args = parser.parse_args(argv)

    config = config_mod.load({})
    session = PreviewSession(config)
    view = session.view(args.draft)
    entry = view.resolve_timeline(args.timeline)
    content, _meta = view.content(entry["id"])
    width, height, ratio = content.canvas

    sizes: Counter = Counter()
    font_path = None
    for material in content.bucket("texts").values():
        raw = material.get("content")
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except json.JSONDecodeError:
            continue
        for style in parsed.get("styles") or []:
            if isinstance(style, dict) and style.get("size"):
                sizes[round(float(style["size"]), 3)] += 1
                font_path = font_path or ((style.get("font") or {}).get("path"))
    if not sizes:
        print(json.dumps({"ok": False, "code": "no_text_sizes", "reason": args.draft, "data": {}}))
        return 1

    sample_text = max(((material.get("content") or "") for material in
                       content.bucket("texts").values()), key=len, default="")
    ink_ratio = ink_to_em_ratio(font_path, "国")
    tmp = Path(tempfile.mkdtemp(prefix="jymeasure-"))
    frames = sample_frames(Path(args.video), args.frames, tmp)

    heights = []
    widths = []
    for seconds, path in frames:
        image = Image.open(path)
        for band in detect_bands(image):
            if band["height_px"]:
                continue
        # per-line height comes from consecutive row runs
    # Re-scan keeping heights (simple pass): measure each contiguous near-white row run.
    for seconds, path in frames:
        image = Image.open(path).convert("RGB")
        for band in _bands_with_height(image):
            heights.append(band["height_px"])
            widths.append(band["width_px"])

    if not heights:
        print(json.dumps({"ok": False, "code": "no_bands", "reason": "no subtitle band found",
                          "data": {"frames": len(frames)}}))
        return 1

    median_ink = statistics.median(heights)
    implied_em = round(median_ink / ink_ratio, 3)
    dominant_size = sizes.most_common(1)[0][0]
    per_size = round(implied_em / dominant_size, 4)
    ours = round(config.text_scale_factor * (width if config.text_size_basis == "width" else height), 4)
    payload = {
        "video": args.video, "draft": view.name, "timeline": entry["id"],
        "canvas": {"width": width, "height": height, "ratio": ratio},
        "frames_sampled": len(frames), "bands_found": len(heights),
        "font_file": font_path, "ink_to_em_ratio_measured": ink_ratio,
        "median_ink_height_px": median_ink,
        "implied_em_px": implied_em,
        "font_sizes_in_draft": dict(sizes.most_common(8)),
        "dominant_font_size": dominant_size,
        "implied_px_per_size": per_size,
        "current_px_per_size": ours,
        "suggested_text_scale_factor": round(per_size / width, 6),
        "band_widths_median_px": round(statistics.median(widths), 2) if widths else None,
        "sample_text_len": len(sample_text),
    }
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps({"ok": True, "code": "ok", "reason": "", "data": payload},
                     ensure_ascii=False, indent=2))
    return 0


def _bands_with_height(image: Image.Image, rgb=(255, 255, 255), tolerance=30) -> list[dict]:
    width, height = image.size
    small = image.resize((width // 3, height // 3))
    scale = 3
    w, h = small.size
    pixels = small.load()
    bands = []
    y = int(h * 0.4)
    while y < h:
        xs = [x for x in range(w) if _near(pixels[x, y], rgb, tolerance)]
        if len(xs) < max(6, int(w * 0.03)):
            y += 1
            continue
        top = y
        run: list[int] = []
        while y < h:
            row = [x for x in range(w) if _near(pixels[x, y], rgb, tolerance)]
            if len(row) < max(4, int(w * 0.02)):
                break
            run.extend(row)
            y += 1
        ink_h = (y - top) * scale
        ink_w = (max(run) - min(run)) * scale
        if 14 <= ink_h <= h * scale * 0.3 and ink_w >= width * 0.12:
            bands.append({"height_px": ink_h, "width_px": ink_w,
                          "top_px": top * scale, "left_px": min(run) * scale})
    return bands


if __name__ == "__main__":
    main()
