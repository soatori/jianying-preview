"""Spec gate: every docs/spec YAML must parse, with no duplicate keys.

Hard failures (block the commit) are the two things that actually broke docs
commits: an unparseable file, and a duplicate mapping key -- the usual result of
merging concurrent edits. A list item starting with `**` or a backtick is the
concrete form the parse error took twice. Advisory (never blocks): a plain scalar
containing ": ", which parses today only because of what surrounds it.

Usage:
  python scripts/check_spec_yaml.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs" / "spec"
errors: list[str] = []
advisories: list[str] = []


class Strict(yaml.SafeLoader):
    """Fail loudly on duplicate mapping keys -- the usual symptom of a merged edit."""


def no_duplicates(loader, node, deep=False):
    mapping = loader.construct_mapping(node, deep=deep)
    seen: set[object] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.YAMLError(f"duplicate key {key!r} at line {key_node.start_mark.line + 1}")
        seen.add(key)
    return mapping


Strict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, no_duplicates)

for path in sorted(SPEC.glob("*.yaml")):
    text = path.read_text(encoding="utf-8")
    try:
        yaml.load(text, Loader=Strict)
    except yaml.YAMLError as exc:
        errors.append(f"{path.name}: {str(exc)[:200]}")
    for number, line in enumerate(text.splitlines(), 1):
        if re.match(r"^\s*-\s*[*`]", line):
            errors.append(f"{path.name}:{number}: list item starts with a marker character: {line.strip()[:90]}")
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if re.match(r"^\s*-\s+[*`]", line):
            errors.append(f"{path.name}:{number}: list item starts with an alias/marker character: {stripped[:90]}")
        match = re.match(r"^(\s*)([A-Za-z_][\w]*):\s+(\S.*)$", line)
        if match:
            value = match.group(3)
            if value[0] not in "\"'|>&[*{" and ": " in value:
                advisories.append(f"{path.name}:{number}: unquoted scalar contains ': ' (parses only by luck): {stripped[:90]}")

if advisories:
    print("--- 提示（不拦住提交，但值得加引号）---")
    print("\n".join(advisories))
print("\n".join(errors) if errors else f"gate OK: {len(list(SPEC.glob('*.yaml')))} spec YAML files parse, no duplicate keys, no marker-start list items")
raise SystemExit(1 if errors else 0)
