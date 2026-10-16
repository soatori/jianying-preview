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

import csv
import json
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

    for name, source in COPIES.items():
        if not source.exists():
            print(f"  !! {name}: 源头不存在（{source}）——先跑对应的扫描脚本")
            continue
        (OUT / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        rows = len(source.read_text(encoding="utf-8").splitlines()) - 1
        print(f"  {name}: {rows} rows (copied verbatim)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
