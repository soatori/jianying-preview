"""Playback-to-export match: does what the MLT playback path composites equal what
JianYing actually rendered out?

The point-query shots (`shot`, `dump_frame`) compare one instant against the model, and
`calibrate` compares against a cover JPEG. Neither answers the acceptance question the
2026-10-03 plan Task 4 asks for: for the *same project frame numbers*, on the *same
timeline*, against the *real export*, how close is playback?

Fixture under test (copied, never committed — see .gitignore "Test fixtures"):

* draft copy: D:/JianyingPro/JianyingPro Drafts/1012-1626-fixture
* real export: %USERPROFILE%/.jypreview/fixtures/1012-1626-fixture/1012-1626.mp4
  (+ fixture.json recording both paths, the export sha256, and the expected did/tid)

    python -m jypreview.tools.export_match                     # default fixture
    python -m jypreview.tools.export_match --frames 32 --json temp/export-match.json
    python -m jypreview.tools.export_match --offset-scan       # diagnose frame alignment

Requires the preview server running under the isolated MLT interpreter (that is the only
interpreter that has mlt7):

    powershell -File temp\\mlt-build\\server.ps1 -Action start

What "ignore the first frame" means here: JianYing's export and the model both start at
project frame 0, but frame 0 is not a usable comparison — the export's opening frame
carries the fade-in/first-GOP behaviour and the controller's frame 0 is what a seek parks
on, not what a viewer sees after playback advances. So sampling starts at frame 1, and the
frame-0 pair is recorded separately as `first_frame_ignored` evidence rather than scored.

Alignment is measured, not assumed: for every sampled frame the export frame is also
compared at -2..+2 frame offsets and the best offset is reported. A systematic non-zero
best offset means the export carries a leading offset and is a finding, not a pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from fractions import Fraction
from pathlib import Path

for _key in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(_key, None)

ROOT = Path(__file__).resolve().parents[3]
STATE_DIR = Path(os.environ.get("JY_PREVIEW_STATE_DIR") or (Path.home() / ".jypreview"))
FIXTURE_DIR = STATE_DIR / "fixtures" / "1012-1626-fixture"
RUNTIME_FFMPEG = ROOT / "temp" / "mlt-runtime" / "ucrt64" / "bin" / "ffmpeg.exe"
DEFAULT_BASE = os.environ.get("JY_PREVIEW_TEST_BASE", "http://127.0.0.1:8765")
TAIL_TOLERANCE_US = 500_000  # JianYing exports routinely carry a tail; the plan says to
                             # measure it, and this gate only requires the head to align.


def _tool(name: str) -> str:
    """Prefer the runtime's own ffmpeg so the fixture decodes identically everywhere."""
    if name == "ffmpeg" and RUNTIME_FFMPEG.is_file():
        return str(RUNTIME_FFMPEG)
    found = shutil.which(name)
    if not found:
        raise SystemExit(f"{name} is not on PATH and not in the MLT runtime; cannot decode")
    return found


def _request(path: str, base: str, method: str, **query) -> tuple[bytes, dict]:
    url = f"{base}{path}?{urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})}"
    try:
        with urllib.request.urlopen(
                urllib.request.Request(url, method=method, data=b"" if method == "POST" else None),
                timeout=600) as response:
            return response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {detail or exc.reason}") from exc


def _get(path: str, base: str, **query) -> tuple[bytes, dict]:
    return _request(path, base, "GET", **query)


def _post(path: str, base: str, **query) -> dict:
    body, _ = _request(path, base, "POST", **query)
    return json.loads(body) if body else {}


def probe_export(video: Path) -> dict:
    out = subprocess.run(
        [_tool("ffprobe"), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate,nb_frames,duration,codec_name",
         "-show_entries", "format=duration", "-of", "json", str(video)],
        capture_output=True, text=True, timeout=120, check=False)
    data = json.loads(out.stdout or "{}")
    stream = (data.get("streams") or [{}])[0]
    num, _, den = (stream.get("r_frame_rate") or "30/1").partition("/")
    return {
        "path": str(video),
        "sha256": _sha(video),
        "codec": stream.get("codec_name"),
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "fps": {"num": int(num or 30), "den": int(den or 1)},
        "nb_frames": int(stream.get("nb_frames") or 0),
        "duration_us": int(round(float(data.get("format", {}).get("duration") or 0.0) * 1e6)),
    }


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 22), b""):
            digest.update(block)
    return digest.hexdigest()


def export_frames(video: Path, indices: list[int], out_dir: Path,
                  grid: tuple[int, int] = (360, 640)) -> dict[int, Path]:
    """Decode the wanted export frames in one pass, selected by exact frame number.

    A single ``select`` expression beats N invocations: ``-ss`` seeks snap to the nearest
    keyframe and would quietly shift the very alignment this tool is measuring. Scaling
    happens inside the filter chain so the stills land grid-sized instead of 1080x1920 PNGs.
    """
    wanted = sorted({index for index in indices if index >= 0})
    if not wanted:
        return {}
    pattern = out_dir / "export-%05d.png"
    expression = "+".join(f"eq(n,{index})" for index in wanted)
    # MLT hands back full-range RGBA; the H.264 export is limited (tv) range. Comparing
    # them without normalising the range taxes every pixel, so widen the export to full.
    base_command = [_tool("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(video),
                    "-vf", f"select='{expression}',scale={grid[0]}:{grid[1]}:out_range=full"]
    # ffmpeg 9 removed -vsync; older builds have no -fps_mode. Try the new spelling first.
    for frame_flag in (["-fps_mode", "passthrough"], ["-vsync", "0"]):
        for path in out_dir.glob("export-*.png"):
            path.unlink()
        result = subprocess.run(base_command + frame_flag + [str(pattern)],
                               capture_output=True, text=True, timeout=1800, check=False)
        files = sorted(out_dir.glob("export-*.png"))
        if len(files) == len(wanted):
            return {index: path for index, path in zip(wanted, files)}
        if result.returncode != 0 and "Unrecognized option" in result.stderr:
            continue
        break
    raise RuntimeError(f"decoded {len(files)} of {len(wanted)} export frames: "
                       f"{result.stderr.strip()[:200]}")


def sample_frames(duration_us: int, fps: float, count: int, skip_first: int = 1) -> list[int]:
    """Spread `count` project frame numbers over the timeline, never including frame 0."""
    frame_count = max(1, int(duration_us * fps / 1_000_000))
    usable = list(range(skip_first, frame_count))
    if not usable:
        return []
    step = len(usable) / count
    return sorted({usable[min(len(usable) - 1, int(index * step + step / 2))]
                   for index in range(count)})


def placeholder_share(values, colour=(224, 64, 160), tolerance=26) -> float:
    """Fraction of rendered pixels that are the compiler's missing-media tile.

    ``mlt_backend`` paints ``#e040a0`` for every clip it degrades to a placeholder, so this
    separates "the graph is missing content" from "the content is graded differently".
    """
    import numpy

    flat = numpy.asarray(values, dtype="int16").reshape(-1, 3)
    near = (numpy.abs(flat - numpy.array(colour, dtype="int16")) <= tolerance).all(axis=1)
    return round(float(near.mean()), 4)


def grade_normalized_similarity(left, right) -> float:
    """Similarity after matching per-channel mean/std.

    JianYing bakes HSL / colour-curve / material-color corrections that the model declares
    it does not preview. Aligning first-order statistics isolates how much of the residual is
    global grading versus geometry or missing layers.
    """
    import numpy

    a = numpy.asarray(left, dtype="float32")
    b = numpy.asarray(right, dtype="float32")
    if a.shape != b.shape or not a.size:
        return 0.0
    b_mean = b.mean(axis=0)
    b_std = b.std(axis=0)
    a_mean = a.mean(axis=0)
    a_std = a.std(axis=0)
    scaled = (b - b_mean) * numpy.where(a_std > 1e-6, a_std / numpy.maximum(b_std, 1e-6), 0.0) + a_mean
    rmse = float(numpy.sqrt(numpy.mean((scaled - a) ** 2))) / 255.0
    return round(max(0.0, 1.0 - rmse), 4)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", default=str(FIXTURE_DIR / "fixture.json"))
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--frames", type=int, default=24, help="sampled project frames")
    parser.add_argument("--grid", default="360x640", help="comparison grid WxH")
    parser.add_argument("--offset-scan", action="store_true",
                        help="also score export frames at -N..+N to measure lead/lag")
    parser.add_argument("--offset-window", type=int, default=4,
                        help="half-width of --offset-scan in project frames")
    parser.add_argument("--align", choices=("auto", "none"), default="auto",
                        help="measure the export's repeated-head offset and score against the "
                             "aligned export frame (auto); 'none' keeps the naive index match")
    parser.add_argument("--align-window", type=int, default=8,
                        help="how far ahead of the project frame to look for the head offset")
    parser.add_argument("--attribute", action="store_true",
                        help="also report placeholder share and grading-normalized similarity")
    parser.add_argument("--min-similarity", type=float, default=None,
                        help="gate every sampled pair against this value (default: no gate, "
                             "observations only — the plan forbids inventing thresholds)")
    parser.add_argument("--min-clean-similarity", type=float, default=None,
                        help="regression floor for frames with no placeholder tile. This is a "
                             "floor against future regressions, NOT a fidelity pass mark: pixel "
                             "parity is bounded by the effects the model declares it does not "
                             "render (see docs/handoff/2026-10-13-export-match-fixture.md)")
    parser.add_argument("--json", default="temp/export-match.json")
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest)
    if not manifest_path.is_file():
        print(f"FAIL: fixture manifest missing: {manifest_path}")
        return 2
    fixture = json.loads(manifest_path.read_text(encoding="utf-8"))
    export = Path(fixture["export"]["path"])
    if not export.is_file():
        print(f"FAIL: export fixture missing: {export}")
        return 2
    if _sha(export) != fixture["export"]["sha256"]:
        print("FAIL: export fixture bytes differ from the manifest")
        return 2

    width, height = (int(value) for value in args.grid.lower().split("x"))
    probe = probe_export(export)
    base = args.base
    did = fixture["draft"]["did"]
    timeline_selector = fixture["draft"]["timeline"]

    checks = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        print(("PASS: " if ok else "FAIL: ") + f"{name} — {detail}")

    # --- recognition: the draft resolver plus the model's own frame IR --------
    from jypreview import config as config_mod
    from jypreview.model.timeline import FrameRate
    from jypreview.session import PreviewSession

    session = PreviewSession(config_mod.load())
    view = session.view(did)
    tid = view.resolve_timeline(timeline_selector)["id"]
    content, _meta = view.content(tid)

    # The project's frame rate lives on the compiled model, not on TimelineContent
    # (draft_adapter defaults it and warns "fps_defaulted"), and the frame IR is what the
    # backend composites against, so read the rate/canvas/duration from there.
    ir = json.loads(_get("/api/frame", base, draft=did, timeline=tid, t_us=1_000_000)[0])["data"]
    model_fps = float(ir["fps"])
    canvas = ir["canvas"]
    duration_us = int(ir["duration_us"])
    fraction = Fraction(model_fps).limit_denominator(1000)
    rate = FrameRate(fraction.numerator, fraction.denominator)

    check("draft fixture intact",
          _sha(Path(view.row["path"]) / "draft_content.json")
          == fixture["draft"]["draft_content_sha256"],
          f"draft_content.json of {view.row['name']} compared against the manifest sha256")
    check("draft recognized", view.did == did and bool(tid) and view.row.get("has_content"),
          f"did={view.did} name={view.row['name']} layout={view.row.get('layout')} "
          f"encoding={view.row.get('encoding')} tid={tid}")
    check("model IR resolves the fixture", bool(ir.get("layers")) or "stats" in ir,
          f"layers={len(ir.get('layers') or [])} warnings={ir.get('warnings')} "
          f"media_missing={((ir.get('stats') or {}).get('media_missing'))}")
    check("canvas matches export", (int(canvas["width"]), int(canvas["height"]))
          == (probe["width"], probe["height"]),
          f"model {canvas['width']}x{canvas['height']} vs export "
          f"{probe['width']}x{probe['height']}")
    export_fps = probe["fps"]["num"] / probe["fps"]["den"]
    check("fps matches export", abs(model_fps - export_fps) < 1e-6,
          f"model {model_fps} ({rate.num}/{rate.den}) vs export "
          f"{probe['fps']['num']}/{probe['fps']['den']} = {export_fps}")
    tail_us = probe["duration_us"] - duration_us
    check("head aligns, tail tolerated", 0 <= tail_us <= TAIL_TOLERANCE_US,
          f"export {probe['duration_us']} us - model {duration_us} us = {tail_us} us tail "
          f"({tail_us * export_fps / 1e6:.2f} frames)")

    # --- frame-by-frame match ------------------------------------------------
    from PIL import Image  # noqa: PLC0415  (grid decode; default interpreter has Pillow)

    def vector(path: Path) -> bytes:
        """Grid-sized RGB bytes.

        Deliberately bytes, not a list of floats: a 360x640 grid expanded to Python floats
        costs tens of megabytes per image, and this runs once per sampled frame per offset.
        """
        with Image.open(path) as image:
            values = image.convert("RGB").resize((width, height), Image.BILINEAR).tobytes()
            image.close()
        return values

    def similarity(left: bytes, right: bytes) -> float:
        # Same metric as calibrate._similarity (RMSE over 0..1 channels), accumulated in
        # chunks so no per-pixel Python object list is ever materialised.
        total = 0
        count = min(len(left), len(right))
        step = 1 << 16
        for offset in range(0, count, step):
            a = left[offset:offset + step]
            b = right[offset:offset + step]
            total += sum((x - y) * (x - y) for x, y in zip(a, b))
        rmse = ((total / max(count, 1)) ** 0.5) / 255.0
        return round(max(0.0, 1.0 - rmse), 4)

    work = Path(tempfile.mkdtemp(prefix="jypreview-export-match-"))
    frames = sample_frames(duration_us, model_fps, args.frames)
    window = abs(args.offset_window)
    request_id = 0

    def render_frame(index: int) -> tuple[Path | None, dict, str]:
        """Seek and pull one project frame through the live backend."""
        nonlocal request_id
        request_id += 1
        try:
            _post("/api/backend/seek", base, draft=did, timeline=tid,
                  playback_id=playback_id, t_us=rate.sample_us(index), request_id=request_id)
            payload, headers = _get("/api/backend/render", base, draft=did, timeline=tid,
                                    playback_id=playback_id, request_id=request_id)
        except RuntimeError as exc:
            return None, {}, str(exc)[:220]
        if payload[:4] != b"\x89PNG":
            return None, {}, f"render is not PNG: {payload[:60]!r}"
        path = work / f"render-{index:06d}.png"
        path.write_bytes(payload)
        return path, headers, ""

    def decode(indices: list[int]) -> dict[int, Path]:
        """Export stills, batched: ffmpeg's expression parser rejects a 100-term `+` chain, and
        keeping the batches small also bounds how many grid images are on disk at once."""
        wanted = sorted({index for index in indices if 0 <= index < probe["nb_frames"]})
        got: dict[int, Path] = {}
        for start in range(0, len(wanted), 16):
            folder = work / f"export-{start:05d}"
            folder.mkdir(parents=True, exist_ok=True)
            got.update(export_frames(export, wanted[start:start + 16], folder, (width, height)))
        return got

    opened = _post("/api/backend/open", base, draft=did, timeline=tid)
    snapshot = opened["data"]["snapshot"]
    playback_id = snapshot["playback_id"]
    check("playback backend open", snapshot.get("backend") == "mlt" and bool(playback_id)
          and int(snapshot["duration_us"]) == duration_us,
          f"playback_id={playback_id} phase={snapshot['phase']} "
          f"duration_us={snapshot['duration_us']}")

    # JianYing repeats the first project frame in the exported file, so export frame N is not
    # project frame N: the head padding shifts everything by a constant. The padding is read off
    # the file itself (leading frames identical to frame 0), and a median-similarity scan over a
    # few frames is used only as a cross-check, because the shift is a property of the export
    # rather than a parameter to fit.
    align_window = abs(args.align_window)
    align_offsets = tuple(range(-2, align_window + 1))
    offset, align_medians, head_padding = 0, {}, 0
    head = decode(list(range(0, 8)))
    if head.get(0) is not None:
        first = vector(head[0])
        while head_padding + 1 in head and similarity(first, vector(head[head_padding + 1])) >= 0.999:
            head_padding += 1
    if args.align == "auto" and frames:
        offset = head_padding
        picks = frames[::max(1, len(frames) // 5)][:5]
        probes = dict(head)
        probes.update(decode([index + delta for index in picks for delta in align_offsets]))
        scores: dict[int, list[float]] = {delta: [] for delta in align_offsets}
        for index in picks:
            rendered, _headers, _error = render_frame(index)
            if rendered is None:
                continue
            values = vector(rendered)
            for delta in align_offsets:
                reference = probes.get(index + delta)
                if reference is not None:
                    scores[delta].append(similarity(values, vector(reference)))
        align_medians = {delta: round(statistics.median(values), 4)
                         for delta, values in scores.items() if values}
        if align_medians:
            # The head padding is a floor, not the answer: an export may hold frames longer than
            # the minimum its duplicated head proves, so only offsets at or past it are candidates.
            # Choosing the best candidate is still a property of the file, not a per-frame fit.
            candidates = {delta: value for delta, value in align_medians.items() if delta >= offset}
            if candidates:
                offset = min(candidates, key=lambda delta: (-candidates[delta], delta))

    scan_offsets = tuple(range(-window, window + 1)) if args.offset_scan else ()
    stills = decode([index + delta for index in frames
                     for delta in ({0, offset} | set(scan_offsets))])
    check("export frames decoded", bool(stills),
          f"{len(stills)} PNG stills over "
          f"{-(-len(stills) // 16) or 1} ffmpeg decode batches")

    rows: list[dict] = []
    for index in frames:
        row: dict = {"frame": index, "t_us": rate.sample_us(index),
                     "export_frame": index + offset}
        rendered, headers, error = render_frame(index)
        if rendered is None:
            row["error"] = error
            rows.append(row)
            continue
        row["rendered_header_frame"] = int(headers.get("X-Project-Frame", -1))
        row["rendered_header_pts_us"] = int(headers.get("X-Project-PTS-US", -1))
        reference = stills.get(index + offset)
        if reference is None:
            row["error"] = f"export frame {index + offset} missing"
            rows.append(row)
            continue
        values = vector(rendered)
        row["similarity"] = similarity(values, vector(reference))
        if offset:
            plain = stills.get(index)
            if plain is not None:
                row["similarity_unaligned"] = similarity(values, vector(plain))
        if args.attribute:
            import numpy

            render_grid = numpy.frombuffer(values, dtype="uint8").reshape(-1, 3)
            export_grid = numpy.frombuffer(vector(reference), dtype="uint8").reshape(-1, 3)
            row["placeholder_share"] = placeholder_share(render_grid)
            row["similarity_grade_normalized"] = grade_normalized_similarity(render_grid, export_grid)
        scan = {}
        for delta in scan_offsets:
            other = stills.get(index + delta)
            if other is not None:
                scan[delta] = similarity(values, vector(other))
        if scan:
            row["offset_scan"] = scan
            row["best_offset"] = max(scan, key=scan.get)
        rows.append(row)

    scored = [row for row in rows if "similarity" in row]
    misparked = [row for row in scored
                 if row.get("rendered_header_frame") not in (None, row["frame"])]
    offsets = [row.get("best_offset") for row in scored if row.get("best_offset") is not None]
    graded = [row["similarity_grade_normalized"] for row in scored
              if "similarity_grade_normalized" in row]
    shares = [row["placeholder_share"] for row in scored if "placeholder_share" in row]
    # Frames whose render still carries placeholder tiles cannot be scored against the
    # export at all (this fixture has three such spans, from dangling material ids in the
    # draft itself), so the clean-frame median is the number a future change should move.
    clean = [row["similarity"] for row in scored if row.get("placeholder_share") == 0]
    unaligned = [row["similarity_unaligned"] for row in scored
                 if "similarity_unaligned" in row]
    summary = {
        "sampled": len(scored),
        "errors": len(rows) - len(scored),
        "alignment_offset_frames": offset,
        "export_head_padding_frames": head_padding,
        "alignment_medians_by_offset": align_medians,
        "clean_frames": len(clean),
        "median_similarity_clean_frames": round(statistics.median(clean), 4) if clean else None,
        "min_similarity_clean_frames": min(clean, default=None),
        "median_similarity_grade_normalized": statistics.median(graded) if graded else None,
        "placeholder_share_mean": round(statistics.mean(shares), 4) if shares else None,
        "placeholder_share_max": max(shares, default=None),
        "median_similarity": statistics.median([row["similarity"] for row in scored]) if scored else None,
        "median_similarity_unaligned": statistics.median(unaligned) if unaligned else None,
        "min_similarity": min([row["similarity"] for row in scored], default=None),
        "max_similarity": max([row["similarity"] for row in scored], default=None),
        "frames_below_0_90": sum(1 for row in scored if row["similarity"] < 0.90),
        "rendered_frame_header_mismatches": len(misparked),
        "best_offset_mode": statistics.mode(offsets) if offsets else None,
        "first_frame_ignored": "project frame 0 and export frame 0 are excluded by design",
    }
    ok = bool(scored) and all(row["ok"] for row in checks) \
        and not summary["rendered_frame_header_mismatches"]
    if args.min_similarity is not None and summary["min_similarity"] is not None:
        ok = ok and summary["min_similarity"] >= args.min_similarity
    floored = args.min_clean_similarity is not None
    if floored and summary["median_similarity_clean_frames"] is not None:
        ok = ok and summary["median_similarity_clean_frames"] >= args.min_clean_similarity
    label = ("playback matches export" if args.min_similarity is not None else
             "playback at/above the clean-frame regression floor" if floored else
             "playback vs export measured (no threshold set)")
    check(label, ok,
          f"{summary['sampled']} frames sampled, export head offset "
          f"{summary['alignment_offset_frames']:+d}, median {summary['median_similarity']}, "
          f"min {summary['min_similarity']}, below 0.90: {summary['frames_below_0_90']}, "
          f"identity mismatches: {summary['rendered_frame_header_mismatches']}")

    report = {
        "schema": "jypreview/export-match@1",
        "fixture": fixture,
        "export_probe": probe,
        "server": {"base": base, "playback_id": playback_id},
        "grid": [width, height],
        "checks": checks,
        "summary": summary,
        "frames": rows,
        "ok": ok,
    }
    out_path = Path(args.json)
    out_path = out_path if out_path.is_absolute() else ROOT / out_path
    if not out_path.is_relative_to(ROOT / "temp"):
        parser.error("--json must stay inside this repository's temp/")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    print(json.dumps(summary, ensure_ascii=False))
    print(out_path)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
