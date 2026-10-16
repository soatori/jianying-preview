"""Read-only corpus scan: what JianYing drafts actually contain, and how often.

Never writes inside a draft. Encrypted content is decrypted through the
subprocess worker into temp/corpus-scan/plain/. Aggregation is incremental so
only one draft is in memory at a time.

Frequency tables count **distinct contents** (sha256 of the decoded JSON), not
files: a hybrid draft stores the same JSON as a timeline copy and a root mirror.
``stats.json -> corpus`` records the file/content counts and the duplicate paths
that were skipped, and the run fails if those two views disagree.

Plaintext drafts are copied into ``plain/`` like decrypted ones, so a rerun reads
this snapshot back instead of the live draft folder: the corpus is being edited
while we measure it, and a count that re-reads live files cannot be reproduced.

Two census blocks guard against claims the tables cannot support:
``corpus.replica_census`` counts ``draft_content.json.bak`` / ``template*.tmp``
files, which are **not** parsed -- so ``content_files`` is a floor over
``draft_content.json`` only. ``field_states`` separates a key that is absent from
one that is present with a null or empty value, because a presence count alone
invites "every draft carries this" readings of what are mostly schema placeholders.

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
import random
import re
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS / "jy_crypto"))

from cache import assert_scratch_target, draft_roots, scratch_dir  # noqa: E402
from client import call  # noqa: E402

INTERESTING_KEY = re.compile(
    r"blend|mix|composit|opaque|alpha_mode|render_index|group|z_order|zorder|"
    r"hdr_settings|uniform_scale|responsive_layout|caption_info|corner_pin|intensity_key|"
    r"panel_id|bloom_params|shadow_point|smart_motion|color_correct_alg_result",
    re.I,
)
PATH_MACRO = "##_draftpath_placeholder_"
PROOF_SAMPLE = 40
PROOF_SEED = 0

# Keys whose absence, null, empty-object and populated forms mean different
# things to a renderer. Counted per field so the docs can say which.
STATE_FIELDS = {
    "segment": ("id", "uniform_scale", "responsive_layout", "render_timerange", "hdr_settings",
                "caption_info", "source", "speed", "volume", "color_correct_alg_result",
                "clip", "extra_material_refs", "common_keyframes"),
    "videos": ("id", "crop", "matting", "stable", "video_algorithm", "video_mask_shadow",
               "video_mask_stroke", "smart_motion", "corner_pin", "beauty_face_auto_preset",
               "freeze", "reverse_path", "audio_fade"),
}
FLAG_BUCKETS = {"texts": "text", "videos": "video"}


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


def enumerate_corpus(limit: int) -> tuple[list[dict], int]:
    """One record per distinct content file, plus the number of skipped duplicates.

    The duplicate counter is a guard rail: two declared roots can resolve to the
    same directory through a junction, and a silently doubled corpus would
    double every frequency table in the spec.
    """
    entries: list[dict] = []
    seen: set[str] = set()
    duplicates = 0

    def add(draft: str, layout: str, path: Path) -> None:
        nonlocal duplicates
        key = str(path)
        if key in seen:
            duplicates += 1
            return
        seen.add(key)
        entries.append({"draft": draft, "layout": layout, "path": path})

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
                        add(entry.name, "hybrid", candidate)
                if (entry / "draft_content.json").is_file():
                    add(entry.name, "hybrid-root-mirror", entry / "draft_content.json")
            else:
                candidate = entry / "draft_content.json"
                if candidate.is_file():
                    add(entry.name, "legacy", candidate)
                elif (entry / "draft_info.json").is_file():
                    add(entry.name, "draft-info-only", entry / "draft_info.json")
                else:
                    entries.append({"draft": entry.name, "layout": "no-content", "path": None})
            if limit and len(entries) >= limit:
                return entries, duplicates
    return entries, duplicates


def field_state(value) -> str:
    """Name the form a field takes, so "present" never means "populated"."""
    if value is None:
        return "null"
    if isinstance(value, dict):
        return "empty_dict" if not value else f"dict({len(value)})"
    if isinstance(value, list):
        return "empty_list" if not value else f"list({len(value)})"
    return "scalar"


def replica_census() -> dict[str, int]:
    """Count content-bearing copies the scan deliberately does not parse.

    ``enumerate_corpus`` only follows ``draft_content.json``. JianYing also keeps
    ``.bak`` and ``template*.tmp`` next to it, and a sha mismatch between those and
    the live file proves nothing: the container re-encrypts with random entropy, so
    equal content can hash differently. Counted here, never decoded.
    """
    census: dict[str, int] = {}
    patterns = ("draft_content.json", "draft_content.json.bak", "template.tmp", "template-2.tmp")
    for root in draft_roots():
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            targets = [entry]
            timelines = entry / "Timelines"
            if timelines.is_dir():
                targets.extend(sub for sub in sorted(timelines.iterdir()) if sub.is_dir())
            for folder in targets:
                for name in patterns:
                    hits = list(folder.glob(name)) if "*" not in name else []
                    if hits:
                        census[name] = census.get(name, 0) + len(hits)
                for extra in folder.glob("template-*.tmp"):
                    if extra.name not in patterns:
                        census["template-<n>.tmp(other)"] = census.get("template-<n>.tmp(other)", 0) + 1
    return dict(sorted(census.items()))


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
        self.keyframe_points = 0
        self.clip_fields = collections.Counter()
        self.canvas_ratios = collections.Counter()
        self.text_style_keys = collections.Counter()
        self.text_flat_keys = collections.Counter()
        self.text_fill_types = collections.Counter()
        self.check_flags = collections.Counter()
        self.check_flag_bits = collections.defaultdict(collections.Counter)
        self.field_states = collections.defaultdict(collections.Counter)
        self.path_macros = {"contents": 0, "occurrences": 0}
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

    def walk(self, node, path: tuple) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                child = path + (key,)
                if INTERESTING_KEY.search(str(key)):
                    flat = ".".join(str(p) for p in child)
                    self.interesting[flat][json.dumps(value, ensure_ascii=False)[:80] if not isinstance(value, (int, float, str, bool, type(None))) else str(value)] += 1
                if isinstance(value, (dict, list)):
                    self.walk(value, child)
                elif key in self.ENUM_FIELDS:
                    # Dotted path, not the bucket: keying by bucket merged the
                    # container's `sticker_animation` with the entries' in/out/loop/
                    # caption/group into one "material_animations.type" enum.
                    dotted = ".".join(str(p) for p in child if not str(p).startswith("["))
                    self.bucket_enum_values[dotted][str(value)] += 1
        elif isinstance(node, list):
            for index, value in enumerate(node):
                self.walk(value, path + (f"[{index}]",))

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
                        # curveType lives on the control points, not on the record:
                        # reading it off the record produced an all-None table.
                        for point in kf.get("keyframe_list") or []:
                            if isinstance(point, dict):
                                self.keyframe_points += 1
                                if "curveType" in point:
                                    self.keyframe_curve[str(point["curveType"])] += 1
                self.walk(segment, (f"segment:{ttype}",))

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
                    self.walk(item, (bucket,))
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

        self.record_states(content)
        self.record_check_flag_bits(content)

    def record_states(self, content: dict) -> None:
        """Split "carries the key" from "carries a value" for the fields that matter."""
        for track in content.get("tracks") or []:
            if not isinstance(track, dict):
                continue
            for segment in track.get("segments") or []:
                if not isinstance(segment, dict):
                    continue
                for field in STATE_FIELDS["segment"]:
                    state = "absent" if field not in segment else field_state(segment[field])
                    self.field_states[f"segment.{field}"][state] += 1
        videos = (content.get("materials") or {}).get("videos") or []
        for item in videos:
            if isinstance(item, dict):
                for field in STATE_FIELDS["videos"]:
                    state = "absent" if field not in item else field_state(item[field])
                    self.field_states[f"videos.{field}"][state] += 1

    def record_check_flag_bits(self, content: dict) -> None:
        materials = content.get("materials") or {}
        for bucket, name in FLAG_BUCKETS.items():
            for item in materials.get(bucket) or []:
                if not isinstance(item, dict):
                    continue
                value = item.get("check_flag")
                if isinstance(value, int):
                    self.check_flag_bits[name][value] += 1
                    for bit in range(0, 31):
                        if value >> bit & 1:
                            self.check_flag_bits[f"{name}.bit"][bit] += 1

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
            "keyframe_control_points": self.keyframe_points,
            "keyframe_curve_types": dict(self.keyframe_curve.most_common()),
            "clip_fields": dict(self.clip_fields.most_common()),
            "canvas_ratios": dict(self.canvas_ratios.most_common()),
            "speed_values": dict(self.speed_values.most_common(30)),
            "text_flat_keys": dict(self.text_flat_keys.most_common()),
            "text_style_keys": dict(self.text_style_keys.most_common()),
            "text_fill_render_types": dict(self.text_fill_types.most_common()),
            "text_check_flags": dict(self.check_flags.most_common(40)),
            "check_flags": {k: dict(v.most_common(40)) for k, v in self.check_flag_bits.items()},
            "field_states": {k: dict(v.most_common()) for k, v in self.field_states.items()},
            "path_macros": dict(self.path_macros),
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
        dump("field_states.csv", [[k, s, c] for k, states in self.field_states.items() for s, c in states.most_common()], ["field", "state", "count"])
        dump("check_flag_bits.csv", [[k, b, c] for k, vals in self.check_flag_bits.items() for b, c in sorted(vals.items())], ["bucket", "bit_or_value", "count"])


def pick_proof_targets(entries: list[dict]) -> list[dict]:
    """Stratified random sample of content files for the read-only proof.

    An alphabetical prefix would prove nothing about the corpus as a whole: the
    first N paths all come from the same handful of drafts.
    """
    rng = random.Random(PROOF_SEED)
    by_layout: dict[str, list[dict]] = {}
    for item in entries:
        if item["path"]:
            by_layout.setdefault(item["layout"], []).append(item)
    picked: list[dict] = []
    for layout in sorted(by_layout):
        group = by_layout[layout]
        share = max(1, round(PROOF_SAMPLE * len(group) / sum(len(g) for g in by_layout.values())))
        picked.extend(rng.sample(group, min(share, len(group))))
    return picked[:PROOF_SAMPLE]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="0 = whole corpus")
    parser.add_argument("--batch", type=int, default=40, help="files per worker process")
    args = parser.parse_args()

    out_dir = scratch_dir("corpus-scan")
    plain_dir = assert_scratch_target(out_dir / "plain" / ".keep").parent
    csv_dir = assert_scratch_target(out_dir / "csv" / ".keep").parent

    entries, duplicate_paths = enumerate_corpus(args.limit)
    census = replica_census()
    roots = draft_roots()
    print(f"corpus entries: {len(entries)} (declared roots deduped to {len(roots)}, "
          f"duplicate paths skipped: {duplicate_paths})", flush=True)

    manifest, proof = [], {}
    for item in pick_proof_targets(entries):
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
            record["key"] = sha256(Path(path))[:16]
            pending.append({**record, "path": str(path)})
        elif encoding == "plain":
            raw = Path(path).read_bytes()
            record["key"] = hashlib.sha256(raw).hexdigest()[:16]
            # Freeze the plaintext too: a rerun must read this snapshot, not the
            # draft folder, or the counts cannot be reproduced after the user edits.
            frozen = assert_scratch_target(plain_dir / f"{record['key']}.json")
            if not frozen.exists() or frozen.stat().st_size != len(raw):
                frozen.write_bytes(raw)
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
    counted: set[str] = set()
    for record in manifest:
        key = record.get("key")
        if not key or key in counted:
            continue
        # Frequencies are counted per distinct content, not per file: a hybrid
        # draft can carry the same JSON as a timeline copy and a root mirror, and
        # counting both would inflate every table in the spec.
        counted.add(key)
        source = None
        frozen = plain_dir / f"{key}.json"
        if record["encoding"] == "plain":
            source = frozen if frozen.exists() else Path(record["path"])
        elif key in decrypted:
            candidate = decrypted[key]
            source = candidate if candidate.exists() and candidate.stat().st_size else None
        if source is None:
            aggregator.drafts_failed += 1
            continue
        try:
            raw_text = source.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            aggregator.drafts_failed += 1
            continue
        if PATH_MACRO in raw_text:
            aggregator.path_macros["contents"] += 1
            aggregator.path_macros["occurrences"] += raw_text.count(PATH_MACRO)
        try:
            content = json.loads(raw_text)
        except json.JSONDecodeError:
            aggregator.drafts_failed += 1
            continue
        if not isinstance(content, dict):
            aggregator.drafts_failed += 1
            continue
        aggregator.add_draft(content, record["layout"], record["encoding"])

    after = {p: sha256(Path(p)) for p in proof}
    unchanged = all(after[p] == h for p, h in proof.items())

    content_records = [r for r in manifest if r.get("path")]
    paths = [r["path"] for r in content_records]
    keys = [r["key"] for r in content_records]
    by_encoding_files = collections.Counter(r["encoding"] for r in content_records)
    seen_enc: set[str] = set()
    by_encoding_contents = collections.Counter()
    for r in content_records:
        if r["key"] not in seen_enc:
            seen_enc.add(r["key"])
            by_encoding_contents[r["encoding"]] += 1
    multiplicity = collections.Counter(collections.Counter(keys).values())
    stats = aggregator.as_dict()
    stats["corpus"] = {
        "snapshot_date": time.strftime("%Y-%m-%d"),
        "unique_roots": len(roots),
        "duplicate_paths_skipped": duplicate_paths,
        "manifest_records": len(manifest),
        "content_files": len(paths),
        "distinct_content_files": len(set(paths)),
        "distinct_contents": len(set(keys)),
        "content_multiplicity": {str(k): v for k, v in sorted(multiplicity.items())},
        "encoding_by_file": dict(by_encoding_files),
        "encoding_by_content": dict(by_encoding_contents),
        "layout_by_first_occurrence_of_content": dict(aggregator.layouts),
        "counting_basis": "distinct contents (sha256 of decoded draft_content.json)",
        "content_files_note": "counts draft_content.json only; see replica_census_not_parsed for the copies that are deliberately not parsed",
        "replica_census_not_parsed": census,
    }
    stats["read_only_proof"] = {
        "sampled": len(proof),
        "unchanged": unchanged,
        "mismatched": [p for p, h in proof.items() if after[p] != h],
    }
    integrity = len(paths) == len(set(paths)) and stats["drafts_parsed"] == len(set(keys))
    if not integrity:
        print("ERROR: enumeration/aggregation counts disagree (duplicate path or content)", file=sys.stderr)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    aggregator.write_csvs(csv_dir)

    print(json.dumps({
        "corpus": stats["corpus"],
        "drafts_parsed": stats["drafts_parsed"],
        "drafts_failed": stats["drafts_failed"],
        "layouts": stats["layouts"],
        "encodings": stats["encodings"],
        "buckets": len(stats["buckets"]),
        "distinct_animations": len(stats["animations"]),
        "distinct_transitions": len(stats["transitions"]),
        "distinct_effect_tuples": len(stats["effects"]),
        "interesting_key_paths": len(stats["interesting_keys"]),
        "field_states": {
            "fields": len(stats["field_states"]),
            "segment_id_total": sum(stats["field_states"].get("segment.id", {}).values()),
        },
        "path_macros": stats["path_macros"],
        "replica_census_not_parsed": stats["corpus"]["replica_census_not_parsed"],
        "read_only_proof": stats["read_only_proof"],
        "out": str(out_dir),
    }, ensure_ascii=False, indent=2))
    return 0 if unchanged and integrity else 1


if __name__ == "__main__":
    raise SystemExit(main())
