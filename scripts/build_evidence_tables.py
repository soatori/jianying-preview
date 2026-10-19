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

    check_flag_carriers()

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
    plain = SCAN / "plain"
    if not plain.is_dir():
        print("  !! check_flag_carriers.csv: 没有冻结明文（先跑 corpus_scan）")
        return
    tab: dict[tuple, int] = {}
    for path in sorted(plain.glob("*.json")):
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
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


if __name__ == "__main__":
    raise SystemExit(main())
