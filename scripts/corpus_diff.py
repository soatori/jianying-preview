"""Regression diff between two corpus-scan snapshots.

Two modes, picked by the file each directory holds:

* ``manifest.json`` -> inventory diff. Which content files appeared or vanished,
  and which existing file's content sha changed. Used to attribute a changed
  number to *new draft-root coverage* rather than to the corpus drifting under
  us, because those two have different consequences for the spec: coverage
  widens the denominator, drift invalidates a measurement that was already
  quoted.
* ``stats.json`` -> flat numeric diff of every count in every table.

Root attribution uses the first three path components (``D:\\JianyingPro\\JianyingPro
Drafts``), so a control run and a wider-roots run can be told apart without
threading the roots through the scanner.

Usage:
  python scripts/corpus_diff.py temp/corpus-scan-r3 temp/corpus-scan-r4d
  python scripts/corpus_diff.py temp/corpus-scan-r4d temp/corpus-scan-r4de --mode stats --top 30
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path, PureWindowsPath

ROOT_PARTS = 3


def root_of(path: str | None) -> str:
    if not path:
        return "(no content file)"
    return "\\".join(str(part) for part in PureWindowsPath(path).parts[:ROOT_PARTS])


def load(directory: Path, name: str) -> object:
    target = directory / name
    if not target.is_file():
        raise SystemExit(f"missing {target}")
    return json.loads(target.read_text(encoding="utf-8"))


def inventory(directory: Path) -> dict[str, dict]:
    return {r["path"]: r for r in load(directory, "manifest.json") if r.get("path")}


def diff_manifest(base_dir: Path, new_dir: Path) -> int:
    base, new = inventory(base_dir), inventory(new_dir)
    added = sorted(set(new) - set(base))
    removed = sorted(set(base) - set(new))
    changed = [p for p in sorted(set(base) & set(new)) if base[p].get("key") != new[p].get("key")]
    by_root = Counter(root_of(p) for p in set(new) | set(base))
    print(f"content files  base={len(base)}  new={len(new)}")
    print(f"by root (new ∪ base): " + json.dumps(dict(by_root.most_common()), ensure_ascii=False))
    print(f"added={len(added)}  removed={len(removed)}  content-changed={len(changed)}")
    for label, group in (("added", added), ("removed", removed), ("content-changed", changed)):
        if not group:
            continue
        per_root = Counter(root_of(p) for p in group)
        print(f"\n{label} by root: " + json.dumps(dict(per_root.most_common()), ensure_ascii=False))
        drafts = Counter(new[p]["draft"] if label == "added" else (new[p]["draft"] if p in new else base[p]["draft"]) for p in group)
        shown = list(group)[:5]
        for path in shown:
            state = new.get(path) or base[path]
            print(f"  {state['layout']:<18}{state['encoding']:<7}{path}")
        if len(group) > len(shown):
            print(f"  ... {len(group) - len(shown)} more across {len(per_root)} root(s), {len(drafts)} draft folder(s)")
    distinct_base = len({r["key"] for r in base.values()})
    distinct_new = len({r["key"] for r in new.values()})
    print(f"\ndistinct contents  base={distinct_base}  new={distinct_new}")
    return 0


def flatten(node, prefix: str = "") -> dict[str, float]:
    out: dict[str, float] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            out.update(flatten(value, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            out.update(flatten(value, f"{prefix}[{index}]"))
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        out[prefix] = node
    return out


def diff_stats(base_dir: Path, new_dir: Path, top: int) -> int:
    base = flatten(load(base_dir, "stats.json"))
    new = flatten(load(new_dir, "stats.json"))
    common = set(base) & set(new)
    changed = [(k, base[k], new[k]) for k in common if base[k] != new[k]]
    added, removed = sorted(set(new) - set(base)), sorted(set(base) - set(new))
    print(f"numeric leaves  base={len(base)}  new={len(new)}")
    print(f"changed={len(changed)}  added={len(added)}  removed={len(removed)}")
    for key, before, after in sorted(changed, key=lambda r: -abs(r[2] - r[1]))[:top]:
        share = f"{100.0 * (after - before) / before:+.1f}%" if before else "new"
        print(f"  {before:>10.0f} -> {after:<10.0f} {share:<9} {key}")
    if len(changed) > top:
        print(f"  ... {len(changed) - top} more changed leaves")
    for label, group in (("added", added), ("removed", removed)):
        if group:
            print(f"\n{label} leaves (first {top}):")
            for key in group[:top]:
                value = new.get(key, base.get(key))
                print(f"  {value:>10.0f}  {key}")
            if len(group) > top:
                print(f"  ... {len(group) - top} more")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base")
    parser.add_argument("new")
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--mode", choices=("auto", "stats", "manifest"), default="auto",
                        help="a snapshot holds both files; auto reads the inventory")
    args = parser.parse_args()
    base_dir, new_dir = Path(args.base), Path(args.new)
    if args.mode == "stats":
        return diff_stats(base_dir, new_dir, args.top)
    if args.mode == "manifest" or (base_dir / "manifest.json").is_file() and (new_dir / "manifest.json").is_file():
        return diff_manifest(base_dir, new_dir)
    return diff_stats(base_dir, new_dir, args.top)


if __name__ == "__main__":
    raise SystemExit(main())
