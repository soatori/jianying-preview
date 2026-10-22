"""Count-citation sweep: every number quoted in docs must be tied to the r3 evidence.

This exists because the r1/r2 incident (F-019) and the 10/16 re-test (F-020) were both
found by prose quoting numbers nobody could re-derive. A number is "tied" if the same
integer appears in the frozen evidence (stats.json, the scan/detail/audit CSVs, or a
probe report). Untied numbers are not necessarily wrong -- sampling-basis figures and
UI readings are legitimately absent -- but each one must be labelled as such.

Usage:
  python scripts/check_doc_counts.py [--quiet]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
# Every corpus snapshot on the machine is tie-able: the r3 baseline lives in
# corpus-scan/, and the 2026-10-22 legs (drift control, both-roots) sit beside it.
# A quoted number is only honest if the run it came from is still on disk.
CORPUS_SNAPSHOTS = sorted((ROOT / "temp").glob("corpus-scan*"))
EVIDENCE_FILES = [path for folder in CORPUS_SNAPSHOTS
                  for path in (folder / "stats.json", folder / "manifest.json") if path.is_file()]
EVIDENCE_DIRS = [folder / "csv" for folder in CORPUS_SNAPSHOTS if (folder / "csv").is_dir()]
EVIDENCE_DIRS += [ROOT / "temp" / "corpus-detail",
                  ROOT / "temp" / "spec-audit", DOCS / "evidence" / "tables"]
PROBE_DIRS = [ROOT / "temp" / "check-1016", ROOT / "temp" / "px-probe",
              ROOT / "temp" / "playback-test", ROOT / "temp" / "rea-native"]
NUMBER = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})*|\d+)(?![\d.])")
KEYED = re.compile(r"(count:\s*|次数?|出现|共|计|达)?\s*\d")
CITE = re.compile(r"(count:\s*[\d,]+|\d[\d,]*\s*(?:次|条|份|个|行|对|批|种|点))")


def evidence_numbers() -> set[int]:
    found: set[int] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, bool):
            return
        elif isinstance(node, int):
            found.add(abs(node))
        elif isinstance(node, float):
            found.add(int(round(abs(node))))
        elif isinstance(node, str):
            found.update(int(text.replace(",", "")) for text in NUMBER.findall(node))

    for path in EVIDENCE_FILES:
        if path.exists():
            walk(json.loads(path.read_text(encoding="utf-8")))
    for folder in EVIDENCE_DIRS + PROBE_DIRS:
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.csv")) + sorted(folder.glob("*.txt")) + sorted(folder.glob("*.json")):
            if path.stat().st_size > 60_000_000:
                continue
            found.update(int(text.replace(",", "")) for text in NUMBER.findall(path.read_text(encoding="utf-8", errors="ignore")))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true", help="only print the summary lines")
    args = parser.parse_args()
    known = evidence_numbers()
    print(f"evidence integers collected: {len(known)}")

    untied: list[str] = []
    total = 0
    for doc in sorted(DOCS.glob("spec/*.yaml")) + sorted(DOCS.glob("spec/*.md")) + sorted(DOCS.glob("evidence/*.md")):
        lines = doc.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, 1):
            cited = CITE.findall(line)
            if not cited:
                continue
            for token in NUMBER.findall(" ".join(cited)):
                value = int(token.replace(",", ""))
                total += 1
                if value < 10 or value in known:
                    continue
                untied.append(f"{doc.relative_to(DOCS.parent)}:{number}: {value:>9}  {line.strip()[:110]}")
    print(f"cited numbers >=10: {total}   untied: {len(untied)}")
    if untied and not args.quiet:
        print("\n".join(untied))
    elif untied:
        print("（用不带 --quiet 的方式查看全部未绑定数字）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
