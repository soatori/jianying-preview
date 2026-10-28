"""Rebuild docs/evidence/tables/* from the frozen scan outputs, in one command.

The tables are the only measurement artifacts that get committed, so they must be
regenerable, not hand-copied: the r1/r2 doubling (F-019) and the stale-coverage rows
(coverage.md claiming 39 buckets / 51 keyframe types) both came from numbers being
moved into docs by hand. `mixmode_glsl.csv` is a resource-package direct read and is
deliberately not touched here.

Run order matters: corpus_scan.py -> corpus_detail.py -> spec_audit.py -> this.

Usage:
  python scripts/build_evidence_tables.py
"""
from __future__ import annotations

import collections
import csv
import json
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN = ROOT / "temp" / "corpus-scan"
DETAIL = ROOT / "temp" / "corpus-detail"
AUDIT = ROOT / "temp" / "spec-audit"
OUT = ROOT / "docs" / "evidence" / "tables"

# tables copied verbatim from a generated CSV: committed name -> source path
COPIES = {
    "render_index_bands.csv": DETAIL / "render_index_bands.csv",
    "order_agreement.csv": DETAIL / "order_agreement.csv",
    "canvas_ratios.csv": DETAIL / "canvas_ratios.csv",
    "shape_common_mask.csv": DETAIL / "shape_common_mask.csv",
    "shape_masks.csv": DETAIL / "shape_masks.csv",
    "spec_coverage.csv": AUDIT / "spec_coverage.csv",
    "field_states.csv": SCAN / "csv" / "field_states.csv",
    "check_flag_bits.csv": SCAN / "csv" / "check_flag_bits.csv",
    "animation_timing.csv": DETAIL / "animation_timing.csv",
    "relations.csv": DETAIL / "relations.csv",
}


def read_rows(path: Path) -> list[list[str]]:
    return list(csv.reader(path.open(encoding="utf-8")))[1:]


def write(name: str, header: list[str], rows: list) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"  {name}: {len(rows)} rows")


def counter_pairs(counter: dict):
    return sorted(counter.items(), key=lambda kv: -kv[1])


@cache
def frozen_contents() -> list[tuple[str, dict]]:
    """The manifest's distinct contents only -- and why that filter exists.

    plain/ accumulates every ad-hoc decryption ever done (11.6.0 differential
    samples, the all-styles draft), so a raw glob over-counts stats.json's basis
    by 28 contents / 814 text materials (F-030). Derived tables must not mix
    constructed samples into usage frequency.
    """
    plain = SCAN / "plain"
    if not plain.is_dir():
        return []
    manifest = json.loads((SCAN / "manifest.json").read_text(encoding="utf-8"))
    keys = {rec["key"] for rec in manifest if rec.get("key")}
    rows: list[tuple[str, dict]] = []
    stray = 0
    for path in sorted(plain.glob("*.json")):
        if path.stem not in keys:
            stray += 1
            continue
        try:
            rows.append((path.stem, json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    print(f"  冻结明文 {len(rows)} 份参与统计（已排除 {stray} 份非本快照的残留明文）")
    return rows


def main() -> int:
    stats = json.loads((SCAN / "stats.json").read_text(encoding="utf-8"))

    write("buckets.csv", ["bucket", "drafts"], counter_pairs(stats["buckets"]))
    write("clip_fields.csv", ["field", "count"], counter_pairs(stats["clip_fields"]))
    write("text_style_keys.csv", ["key", "count"], counter_pairs(stats["text_style_keys"]))
    write("text_flat_keys.csv", ["key", "count"], counter_pairs(stats["text_flat_keys"]))
    write("keyframe_types.csv", ["property_type", "count"], counter_pairs(stats["keyframe_property_types"]))
    write("effects_type_values.csv", ["effects.type", "value", "count"],
          [("effects.type", k, v) for k, v in counter_pairs(stats["bucket_enum_values"].get("effects.type", {}))])

    bucket_rows = [[bucket, key, count] for bucket, keys in stats["bucket_keys"].items()
                   for key, count in counter_pairs(keys)]
    bucket_rows.sort(key=lambda row: -int(row[2]))
    write("bucket_keys_top80.csv", ["bucket", "key", "count"], bucket_rows[:80])

    write("animations_top60.csv", ["type", "name", "id", "count"],
          [[*entry["value"], entry["count"]] for entry in stats["animations"]][:60])
    write("transitions_top60.csv", ["name", "id", "category", "count"],
          [[*entry["value"], entry["count"]] for entry in stats["transitions"]][:60])

    check_flag_carriers()
    alignment_by_version()
    position_quantum()
    font_size_mirror()

    for name, source in COPIES.items():
        if not source.exists():
            print(f"  !! {name}: 源头不存在（{source}）——先跑对应的扫描脚本")
            continue
        (OUT / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        rows = len(source.read_text(encoding="utf-8").splitlines()) - 1
        print(f"  {name}: {rows} rows (copied verbatim)")
    return 0


def check_flag_carriers() -> None:
    """Cross-tab check_flag bits against the text style carriers (F-029)."""
    contents = frozen_contents()
    if not contents:
        print("  !! check_flag_carriers.csv: 没有冻结明文（先跑 corpus_scan）")
        return
    tab: dict[tuple, int] = {}
    for _key, content in contents:
        for material in (content.get("materials") or {}).get("texts", []) or []:
            flag = material.get("check_flag") if isinstance(material, dict) else None
            if not isinstance(flag, int):
                continue
            try:
                styles = (json.loads(material.get("content") or "{}").get("styles") or [{}])
                style = styles[0] if styles else {}
            except Exception:
                style = {}

            def state(key: str) -> str:
                if key not in style:
                    return "absent"
                value = style[key]
                if not isinstance(value, list):
                    return "other"
                return "filled" if value else "empty"

            strokes, shadows = state("strokes"), state("shadows")
            has_shadow = material.get("has_shadow", "absent")
            for bit in (1, 2, 4, 8, 16, 32, 64):
                set_bit = bool(flag & bit)
                for carrier, value in (("strokes", strokes), ("shadows", shadows),
                                       ("has_shadow", has_shadow)):
                    key = ("check_flag_bit", f"bit{bit}", f"{carrier}.{value}", set_bit)
                    tab[key] = tab.get(key, 0) + 1
            key = ("has_shadow_vs_carrier", str(has_shadow), f"shadows.{shadows}", "")
            tab[key] = tab.get(key, 0) + 1
    write("check_flag_carriers.csv", ["measure", "bit_or_key", "carrier_state", "flag_set", "count"],
          [[*k, v] for k, v in sorted(tab.items())])
    print(f"  check_flag_carriers.csv: {len(tab)} rows")


def alignment_by_version() -> None:
    """texts.alignment encodings split by the saving app version (F-030/U-30)."""
    contents = frozen_contents()
    if not contents:
        print("  !! alignment_by_version.csv: 没有冻结明文（先跑 corpus_scan）")
        return
    per: dict[str, dict[str, int]] = {}
    for _key, content in contents:
        texts = (content.get("materials") or {}).get("texts") or []
        if not texts:
            continue
        version = str((content.get("last_modified_platform") or {}).get("app_version", "<none>"))
        row = per.setdefault(version, {"drafts": 0, "texts": 0, "absent": 0, "other": 0,
                                       "a0": 0, "a1": 0, "a2": 0, "a3": 0, "a4": 0})
        row["drafts"] += 1
        for material in texts:
            row["texts"] += 1
            if "alignment" not in material:
                row["absent"] += 1
                continue
            bucket = {0: "a0", 1: "a1", 2: "a2", 3: "a3", 4: "a4"}.get(material["alignment"])
            row["other" if bucket is None else bucket] += 1

    def era(version: str) -> str:
        try:
            parts = [int(x) for x in version.split(".")[:2]]
        except ValueError:
            return "unknown"
        return "<=8.0" if (parts[0], parts[1]) <= (8, 0) else ">=8.7"

    totals: dict[str, dict[str, int]] = {}
    for version, row in per.items():
        agg = totals.setdefault(era(version), dict.fromkeys(row, 0))
        for field, value in row.items():
            agg[field] += value

    header = ["era", "app_version", "drafts_with_texts", "texts", "absent", "alignment_0",
              "alignment_1", "alignment_2", "alignment_3", "alignment_4", "other_value",
              "share_of_keyed_is_1"]
    rows = []

    def emit(era_name: str, version: str, row: dict) -> None:
        keyed = row["texts"] - row["absent"]
        share = f"{row['a1'] / keyed:.4f}" if keyed else ""
        rows.append([era_name, version, row["drafts"], row["texts"], row["absent"], row["a0"],
                     row["a1"], row["a2"], row["a3"], row["a4"], row["other"], share])

    for era_name in ("<=8.0", ">=8.7", "unknown"):
        if era_name in totals:
            emit(era_name, "(汇总)", totals[era_name])
    for version in sorted(per, key=lambda v: (era(v), -per[v]["texts"])):
        emit(era(version), version, per[version])
    write("alignment_by_version.csv", header, rows)


def font_size_mirror() -> None:
    """Is texts.font_size a trustworthy mirror of styles[].size (F-034)?"""
    contents = frozen_contents()
    if not contents:
        print("  !! font_size_mirror.csv: 没有冻结明文（先跑 corpus_scan）")
        return
    tab: collections.Counter = collections.Counter()
    for _key, content in contents:
        for material in (content.get("materials") or {}).get("texts", []) or []:
            try:
                styles = (json.loads(material.get("content") or "{}").get("styles")) or []
            except Exception:
                styles = []
            sizes = [s.get("size") for s in styles if isinstance(s, dict)
                     and isinstance(s.get("size"), (int, float))]
            tab[("styles 段数", "多段" if len(styles) > 1 else "单段/无", "")] += 1
            if "font_size" not in material:
                tab[("font_size", "键缺席", "styles.size 有" if sizes else "styles.size 无")] += 1
                continue
            if not sizes:
                tab[("font_size", "有键", "styles.size 无")] += 1
                continue
            flag = float(material["font_size"])
            if any(abs(flag - float(size)) < 1e-6 for size in sizes):
                which = "等于 styles[0]" if abs(flag - float(sizes[0])) < 1e-6 else "等于其它段"
            else:
                which = "与所有段都不等"
            tab[("font_size", which, "")] += 1
    write("font_size_mirror.csv", ["measure", "state", "detail", "count"],
          [[*k, v] for k, v in sorted(tab.items())])


def position_quantum() -> None:
    """Is clip position a quantised UI pixel, and per which divisor (F-032)?

    For each (track type, axis, canvas size) report how many stored values land
    exactly on an integer when multiplied by the axis' own canvas length, by the
    other axis, or by a fixed 1920 - plus the most common recovered pixel value.
    """
    contents = frozen_contents()
    if not contents:
        print("  !! position_quantum.csv: 没有冻结明文（先跑 corpus_scan）")
        return
    buckets: dict[tuple, dict] = {}
    for _key, content in contents:
        canvas = content.get("canvas_config") or {}
        width, height = canvas.get("width") or 0, canvas.get("height") or 0
        if not width or not height:
            continue
        for track in content.get("tracks") or []:
            ttype = str(track.get("type") or "?")
            for segment in track.get("segments") or []:
                clip = segment.get("clip")
                transform = clip.get("transform") if isinstance(clip, dict) else None
                if not isinstance(transform, dict):
                    continue
                for axis, own, other in (("x", float(width), float(height)), ("y", float(height), float(width))):
                    value = transform.get(axis)
                    if not isinstance(value, (int, float)) or value == 0:
                        continue
                    row = buckets.setdefault((ttype, axis, f"{int(width)}x{int(height)}"),
                                             {"n": 0, "own": 0, "other": 0, "d1920": 0, "px": collections.Counter()})
                    row["n"] += 1
                    scaled = value * own
                    if abs(scaled - round(scaled)) <= 1e-9:
                        row["own"] += 1
                        row["px"][int(round(scaled))] += 1
                    if abs(value * other - round(value * other)) <= 1e-9:
                        row["other"] += 1
                    if abs(value * 1920.0 - round(value * 1920.0)) <= 1e-9:
                        row["d1920"] += 1
    rows = []
    for (ttype, axis, canvas), row in sorted(buckets.items(), key=lambda kv: -kv[1]["n"]):
        if row["n"] < 40:
            continue
        modal = row["px"].most_common(1)
        rows.append([ttype, axis, canvas, row["n"],
                     f"{row['own'] / row['n']:.4f}", f"{row['other'] / row['n']:.4f}",
                     f"{row['d1920'] / row['n']:.4f}",
                     modal[0][0] if modal else "", modal[0][1] if modal else ""])
    write("position_quantum.csv",
          ["track_type", "axis", "canvas", "nonzero_values", "integer_at_own_axis",
           "integer_at_other_axis", "integer_at_1920", "modal_pixel", "modal_pixel_count"], rows)


if __name__ == "__main__":
    raise SystemExit(main())
