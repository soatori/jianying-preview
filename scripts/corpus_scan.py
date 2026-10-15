"""Read-only corpus scan: what JianYing drafts actually contain, and how often.

Never writes inside a draft. Encrypted content is decrypted through the
subprocess worker into temp/corpus-scan/plain/. Aggregation is incremental so
only one draft is in memory at a time.

Outputs (all under temp/):
  manifest.json         layout + encryption classification for every draft
  stats.json            aggregated frequency tables
  csv/*.csv             the same tables, flat, for the spec docs

Usage:
  python scripts/corpus_scan.py --limit 0 --batch 40
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS / "jy_crypto"))

from cache import assert_scratch_target, draft_roots, scratch_dir  # noqa: E402
from client import call  # noqa: E402

INTERESTING_KEY = re.compile(r"blend|mix|composit|opaque|alpha_mode|render_index|group|z_order|zorder", re.I)
PROOF_SAMPLE = 20


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classify(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            head = handle.read(1)
    except OSError:
        return "unreadable"
    if not head:
        return "empty"
    return "plain" if head == b"{" else "cipher"


def enumerate_corpus(limit: int) -> list[dict]:
    entries: list[dict] = []
    for root in draft_roots():
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            timelines = entry / "Timelines"
            if timelines.is_dir():
                for sub in sorted(timelines.iterdir()):
                    candidate = sub / "draft_content.json"
                    if candidate.is_file():
                        entries.append({"draft": entry.name, "layout": "hybrid", "path": candidate})
                if (entry / "draft_content.json").is_file():
                    entries.append({"draft": entry.name, "layout": "hybrid-root-mirror", "path": entry / "draft_content.json"})
            else:
                candidate = entry / "draft_content.json"
                if candidate.is_file():
                    entries.append({"draft": entry.name, "layout": "legacy", "path": candidate})
                elif (entry / "draft_info.json").is_file():
                    entries.append({"draft": entry.name, "layout": "draft-info-only", "path": entry / "draft_info.json"})
                else:
                    entries.append({"draft": entry.name, "layout": "no-content", "path": None})
            if limit and len(entries) >= limit:
                return entries
    return entries


def decrypt_batch(items: list[dict], plain_dir: Path) -> dict[str, Path]:
    """One worker process per batch; returns sha-key -> plaintext path."""
    ops, mapping = [], {}
    for item in items:
        key = item["key"]
        dst = assert_scratch_target(plain_dir / f"{key}.json")
        if dst.exists() and dst.stat().st_size:
            mapping[key] = dst
            continue
        ops.append({"op": "decrypt_bytes", "src": item["path"], "dst": str(dst)})
        mapping[key] = dst
    if ops:
        payload = call(ops, tag=f"scan-{len(ops)}", timeout=1800)
        if payload.get("errors"):
            for err in payload["errors"]:
                print(f"  decrypt error: {err.get('op')} {err.get('error')} {err.get('message')}", file=sys.stderr)
    return mapping


class Aggregator:
    def __init__(self) -> None:
        self.layouts = collections.Counter()
        self.encodings = collections.Counter()
        self.track_types = collections.Counter()
        self.track_field_keys = collections.defaultdict(collections.Counter)
        self.segment_keys = collections.defaultdict(collections.Counter)
        self.buckets = collections.Counter()
        self.bucket_keys = collections.defaultdict(collections.Counter)
        self.bucket_enum_values = collections.defaultdict(collections.Counter)
        self.interesting = collections.defaultdict(collections.Counter)
        self.animations = collections.Counter()
        self.transitions = collections.Counter()
        self.effects = collections.Counter()
        self.stickers = collections.Counter()
        self.keyframe_types = collections.Counter()
        self.keyframe_curve = collections.Counter()
        self.clip_fields = collections.Counter()
        self.canvas_ratios = collections.Counter()
        self.text_style_keys = collections.Counter()
        self.text_flat_keys = collections.Counter()
        self.text_fill_types = collections.Counter()
        self.check_flags = collections.Counter()
        self.top_level_keys = collections.Counter()
        self.speed_values = collections.Counter()
        self.drafts_parsed = 0
        self.drafts_failed = 0

    ENUM_FIELDS = {
        "blend_mode", "mix_mode", "render_index", "render_index_track_mode_on", "free_render_index_mode_on",
        "render_uniform_index", "mode", "type", "mask_type", "curveType", "property_type", "category_name",
        "fill_type", "render_type", "alignment", "vertical_alignment", "font_source_platform", "add_type",
        "draft_type", "color_space", "alpha", "visible", "is_group", "source_platform",
    }

    def walk(self, node, path: tuple, ctx: dict) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                child = path + (key,)
                if INTERESTING_KEY.search(str(key)):
                    flat = ".".join(str(p) for p in child)
                    self.interesting[flat][json.dumps(value, ensure_ascii=False)[:80] if not isinstance(value, (int, float, str, bool, type(None))) else str(value)] += 1
                if isinstance(value, (dict, list)):
                    self.walk(value, child, ctx)
                elif key in self.ENUM_FIELDS:
                    self.bucket_enum_values[f"{ctx.get('bucket','?')}.{key}"][str(value)] += 1
        elif isinstance(node, list):
            for index, value in enumerate(node):
                self.walk(value, path + (f"[{index}]",), ctx)

    def add_draft(self, content: dict, layout: str, encoding: str) -> None:
        self.drafts_parsed += 1
        self.layouts[layout] += 1
        self.encodings[encoding] += 1
        for key in content:
            self.top_level_keys[key] += 1

        canvas = content.get("canvas_config") or {}
        if isinstance(canvas, dict):
            ratio = canvas.get("ratio")
            if ratio:
                self.canvas_ratios[str(ratio)] += 1
        for flag in ("render_index_track_mode_on", "free_render_index_mode_on", "render_uniform_index", "group_container"):
            if flag in content:
                self.interesting[f"<root>.{flag}"][str(type(content[flag]).__name__)] += 1

        for track in content.get("tracks") or []:
            if not isinstance(track, dict):
                continue
            ttype = str(track.get("type"))
            self.track_types[ttype] += 1
            for key in track:
                self.track_field_keys[ttype][key] += 1
            segments = track.get("segments") or []
            for segment in segments:
                if not isinstance(segment, dict):
                    continue
                for key in segment:
                    self.segment_keys[ttype][key] += 1
                clip = segment.get("clip")
                if isinstance(clip, dict):
                    for key in clip:
                        self.clip_fields[key] += 1
                    transform = clip.get("transform")
                    if isinstance(transform, dict):
                        self.clip_fields["transform." + ",".join(sorted(transform))] += 1
                speed = segment.get("speed")
                if speed is not None:
                    self.speed_values[str(speed)] += 1
                for kf in segment.get("common_keyframes") or []:
                    if isinstance(kf, dict):
                        self.keyframe_types[str(kf.get("property_type"))] += 1
                        curve = kf.get("keyframe_curve") or kf.get("curve") or {}
                        if isinstance(curve, dict):
                            self.keyframe_curve[str(curve.get("type") or curve.get("curveType"))] += 1
                self.walk(segment, ("segment",), {"bucket": f"segment:{ttype}"})

        materials = content.get("materials") or {}
        if isinstance(materials, dict):
            for bucket, items in materials.items():
                if not isinstance(items, list) or not items:
                    continue
                self.buckets[bucket] += 1
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    for key in item:
                        self.bucket_keys[bucket][key] += 1
                    self.walk(item, (bucket,), {"bucket": bucket})
                if bucket == "material_animations":
                    for item in items:
                        for anim in (item or {}).get("animations") or []:
                            if isinstance(anim, dict):
                                self.animations[(str(anim.get("type")), str(anim.get("name")), str(anim.get("id")))] += 1
                elif bucket == "transitions":
                    for item in items:
                        if isinstance(item, dict):
                            self.transitions[(str(item.get("name")), str(item.get("id")), str(item.get("category_name")))] += 1
                elif bucket == "effects":
                    for item in items:
                        if isinstance(item, dict):
                            self.effects[(str(item.get("name")), str(item.get("id")), str(item.get("category_name")))] += 1
                elif bucket == "stickers":
                    for item in items:
                        if isinstance(item, dict):
                            self.stickers[(str(item.get("name")), str(item.get("id")))] += 1
                elif bucket == "texts":
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        for key in item:
                            self.text_flat_keys[key] += 1
                        if "check_flag" in item:
                            self.check_flags[str(item.get("check_flag"))] += 1
                        raw = item.get("content")
                        if isinstance(raw, str) and raw[:1] == "{":
                            try:
                                parsed = json.loads(raw)
                            except json.JSONDecodeError:
                                continue
                            for style in parsed.get("styles") or []:
                                if isinstance(style, dict):
                                    for key in style:
                                        self.text_style_keys[key] += 1
                                    fill = style.get("fill") or {}
                                    if isinstance(fill, dict):
                                        inner = fill.get("content") or {}
                                        if isinstance(inner, dict):
                                            self.text_fill_types[str(inner.get("render_type"))] += 1

    def as_dict(self) -> dict:
        def counter_of_tuples(counter: collections.Counter) -> list:
            return [
                {"value": list(key), "count": value}
                for key, value in counter.most_common()
            ]

        return {
            "drafts_parsed": self.drafts_parsed,
            "drafts_failed": self.drafts_failed,
            "layouts": dict(self.layouts),
            "encodings": dict(self.encodings),
            "top_level_keys": dict(self.top_level_keys.most_common()),
            "track_types": dict(self.track_types),
            "track_field_keys": {k: dict(v) for k, v in self.track_field_keys.items()},
            "segment_keys": {k: dict(v.most_common()) for k, v in self.segment_keys.items()},
            "buckets": dict(self.buckets.most_common()),
            "bucket_keys": {k: dict(v.most_common()) for k, v in self.bucket_keys.items()},
            "bucket_enum_values": {k: dict(v.most_common(40)) for k, v in self.bucket_enum_values.items()},
            "interesting_keys": {k: dict(v.most_common(40)) for k, v in self.interesting.items()},
            "animations": counter_of_tuples(self.animations),
            "transitions": counter_of_tuples(self.transitions),
            "effects": counter_of_tuples(self.effects),
            "stickers": counter_of_tuples(self.stickers),
            "keyframe_property_types": dict(self.keyframe_types.most_common()),
            "keyframe_curve_types": dict(self.keyframe_curve.most_common()),
            "clip_fields": dict(self.clip_fields.most_common()),
            "canvas_ratios": dict(self.canvas_ratios.most_common()),
            "speed_values": dict(self.speed_values.most_common(30)),
            "text_flat_keys": dict(self.text_flat_keys.most_common()),
            "text_style_keys": dict(self.text_style_keys.most_common()),
            "text_fill_render_types": dict(self.text_fill_types.most_common()),
            "text_check_flags": dict(self.check_flags.most_common(40)),
        }

    def write_csvs(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)

        def dump(name: str, rows: list[list], header: list[str]) -> None:
            with (out_dir / name).open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(header)
                writer.writerows(rows)

        dump("buckets.csv", [[k, v] for k, v in self.buckets.most_common()], ["bucket", "drafts"])
        dump("bucket_keys.csv", [[b, k, c] for b, keys in self.bucket_keys.items() for k, c in keys.most_common()], ["bucket", "key", "count"])
        dump("animations.csv", [[t, n, i, c] for (t, n, i), c in self.animations.most_common()], ["type", "name", "id", "count"])
        dump("transitions.csv", [[n, i, cat, c] for (n, i, cat), c in self.transitions.most_common()], ["name", "id", "category", "count"])
        dump("effects.csv", [[n, i, cat, c] for (n, i, cat), c in self.effects.most_common()], ["name", "id", "category", "count"])
        dump("stickers.csv", [[n, i, c] for (n, i), c in self.stickers.most_common()], ["name", "id", "count"])
        dump("keyframe_types.csv", [[k, v] for k, v in self.keyframe_types.most_common()], ["property_type", "count"])
        dump("clip_fields.csv", [[k, v] for k, v in self.clip_fields.most_common()], ["field", "count"])
        dump("interesting_keys.csv", [[k, v, c] for k, vals in self.interesting.items() for v, c in vals.most_common(20)], ["key_path", "value", "count"])
        dump("text_style_keys.csv", [[k, v] for k, v in self.text_style_keys.most_common()], ["key", "count"])
        dump("text_flat_keys.csv", [[k, v] for k, v in self.text_flat_keys.most_common()], ["key", "count"])
        dump("enum_values.csv", [[k, v, c] for k, vals in self.bucket_enum_values.items() for v, c in vals.most_common(40)], ["field", "value", "count"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="0 = whole corpus")
    parser.add_argument("--batch", type=int, default=40, help="files per worker process")
    args = parser.parse_args()

    out_dir = scratch_dir("corpus-scan")
    plain_dir = assert_scratch_target(out_dir / "plain" / ".keep").parent
    csv_dir = assert_scratch_target(out_dir / "csv" / ".keep").parent

    entries = enumerate_corpus(args.limit)
    print(f"corpus entries: {len(entries)}", flush=True)

    manifest, proof = [], {}
    proof_targets = [e for e in entries if e["path"]][:PROOF_SAMPLE]
    for item in proof_targets:
        proof[str(item["path"])] = sha256(Path(item["path"]))

    pending: list[dict] = []
    for item in entries:
        path = item["path"]
        record = {"draft": item["draft"], "layout": item["layout"], "path": str(path) if path else None}
        if path is None:
            record["encoding"] = "absent"
            manifest.append(record)
            continue
        encoding = classify(Path(path))
        record["encoding"] = encoding
        record["size"] = Path(path).stat().st_size
        if encoding == "cipher":
            data = Path(path).read_bytes()
            record["key"] = hashlib.sha256(data).hexdigest()[:16]
            pending.append({**record, "path": str(path)})
        elif encoding == "plain":
            record["key"] = hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
        manifest.append(record)
    print(f"classified: cipher={sum(1 for r in manifest if r.get('encoding')=='cipher')} "
          f"plain={sum(1 for r in manifest if r.get('encoding')=='plain')} "
          f"absent={sum(1 for r in manifest if r.get('encoding')=='absent')}", flush=True)

    decrypted: dict[str, Path] = {}
    for start in range(0, len(pending), args.batch):
        chunk = pending[start : start + args.batch]
        print(f"  decrypting {start + 1}-{start + len(chunk)} / {len(pending)}", flush=True)
        try:
            decrypted.update(decrypt_batch(chunk, plain_dir))
        except Exception as exc:  # noqa: BLE001 - keep scanning after a bad batch
            print(f"  batch failed: {exc}", file=sys.stderr)

    aggregator = Aggregator()
    for record in manifest:
        key = record.get("key")
        if not key:
            continue
        source = None
        if record["encoding"] == "plain":
            source = Path(record["path"])
        elif key in decrypted:
            candidate = decrypted[key]
            source = candidate if candidate.exists() and candidate.stat().st_size else None
        if source is None:
            aggregator.drafts_failed += 1
            continue
        try:
            content = json.loads(source.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            aggregator.drafts_failed += 1
            continue
        if not isinstance(content, dict):
            aggregator.drafts_failed += 1
            continue
        aggregator.add_draft(content, record["layout"], record["encoding"])

    after = {p: sha256(Path(p)) for p in proof}
    unchanged = all(after[p] == h for p, h in proof.items())

    stats = aggregator.as_dict()
    stats["read_only_proof"] = {
        "sampled": len(proof),
        "unchanged": unchanged,
        "mismatched": [p for p, h in proof.items() if after[p] != h],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    aggregator.write_csvs(csv_dir)

    print(json.dumps({
        "drafts_parsed": stats["drafts_parsed"],
        "drafts_failed": stats["drafts_failed"],
        "layouts": stats["layouts"],
        "encodings": stats["encodings"],
        "buckets": len(stats["buckets"]),
        "animations": len(stats["animations"]),
        "transitions": len(stats["transitions"]),
        "effects": len(stats["effects"]),
        "interesting_key_paths": len(stats["interesting_keys"]),
        "read_only_proof": stats["read_only_proof"],
        "out": str(out_dir),
    }, ensure_ascii=False, indent=2))
    return 0 if unchanged else 1


if __name__ == "__main__":
    raise SystemExit(main())
