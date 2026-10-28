"""Read-only PE structure harvest: MSVC RTTI type names + data-section literals.

Stands up the *structure* half of the native evidence channel (scope.md §1.1):
what types and literals the shipped binary itself carries. No disassembly, no
decompilation, no cipher work -- the image is mapped read-only and never loaded.

Two independent harvests, both keyed by RVA so any later Ghidra query can land
on the same object:

``--rtti``      MSVC type descriptors (``.?AV``/``.?AU`` names preceded by the
                16 zero bytes of the TypeDescriptor header). A ``.?AV`` hit
                *without* that header is a stray mention, not a real type, so
                both cases are reported apart.
``--literals``  identifier-shaped strings in initialized-data sections, the
                raw material behind JSON field names and enum values.
``--against``   a stats.json from corpus_scan.py; classifies each corpus key as
                present / absent in the binary's literals. Per §6.1 the binary
                answers "what name is legal", the corpus answers "what actually
                appears" -- a key in one and not the other is a finding, not an
                error to normalize away.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import re
import struct
from pathlib import Path

_MZ = b"MZ"
_PE = b"PE\0\0"
_RTTI_PREFIX = b".?A"
# Word-bounded so "HelloWorld" cannot yield the substring "elloWorld".
_IDENT = re.compile(rb"(?<![A-Za-z0-9_])[a-z][a-z0-9_]{1,31}(?![A-Za-z0-9_])")
_IDENT_EXACT = re.compile(rb"[a-z][a-z0-9_]{1,31}\Z")
# Initialized data is where field-name and enum literals live; .text is code and
# .pdata is unwind tables -- scanning either drowns the signal in byte noise.
_DATA_SECTIONS = {".rdata", ".data", ".const"}


class NotAPE(ValueError):
    pass


def _sections(data: memoryview | mmap.mmap) -> tuple[list[dict], int, int]:
    """(sections, image_base, size_of_image) -- read without mapping the image."""
    if data[:2] != _MZ:
        raise NotAPE("missing MZ header")
    (lfanew,) = struct.unpack_from("<I", data, 0x3C)
    if data[lfanew : lfanew + 4] != _PE:
        raise NotAPE("missing PE signature")
    coff = lfanew + 4
    (num_sections,) = struct.unpack_from("<H", data, coff + 2)
    (opt_size,) = struct.unpack_from("<H", data, coff + 16)
    opt = coff + 20
    (magic,) = struct.unpack_from("<H", data, opt)
    if magic == 0x20B:
        image_base = struct.unpack_from("<Q", data, opt + 24)[0]
        size_of_image = struct.unpack_from("<I", data, opt + 56)[0]
    elif magic == 0x10B:
        image_base = struct.unpack_from("<I", data, opt + 28)[0]
        size_of_image = struct.unpack_from("<I", data, opt + 52)[0]
    else:
        raise NotAPE(f"unknown optional header magic {magic:#x}")
    table = opt + opt_size
    out = []
    for i in range(num_sections):
        base = table + i * 40
        name = bytes(data[base : base + 8]).rstrip(b"\0").decode("ascii", "replace")
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", data, base + 8)
        characteristics = struct.unpack_from("<I", data, base + 36)[0]
        out.append(
            {
                "name": name,
                "vaddr": vaddr,
                "vsize": vsize or rawsize,
                "rawptr": rawptr,
                "rawsize": rawsize,
                "executable": bool(characteristics & 0x20000000),
                "writable": bool(characteristics & 0x80000000),
            }
        )
    return out, image_base, size_of_image


def _rva_of(sections: list[dict], offset: int) -> int | None:
    for sec in sections:
        if sec["rawptr"] <= offset < sec["rawptr"] + sec["rawsize"]:
            return sec["vaddr"] + (offset - sec["rawptr"])
    return None


def harvest_rtti(data: mmap.mmap, sections: list[dict], image_base: int, size_of_image: int) -> dict:
    """Inventory of MSVC mangled type-name strings (``.?AV``/``.?AU``/``.?A$``).

    Deliberately a *string* inventory, not a TypeDescriptor claim. The first run
    here assumed x64 TypeDescriptor's two leading null words and got zero hits;
    the CFG variant was then guessed and appeared to match 34,703 of them, but
    dereferencing that leading qword landed on an `api-ms-win-*` string pool, not
    a CompleteObjectLocator. So the qword is only counted as an observation, and
    the inheritance graph stays a Ghidra question instead of an inferred layout.
    """
    names: dict[str, dict] = {}
    precedents: dict[str, int] = {"null_words": 0, "in_image_qword": 0, "other": 0}
    for match in re.finditer(re.escape(_RTTI_PREFIX), data):
        at = match.start()
        end = data.find(b"\0", at)
        if end < 0 or end - at > 400 or at < 16:
            continue
        try:
            name = data[at:end].decode("ascii")
        except UnicodeDecodeError:
            continue
        pvf, spare = struct.unpack_from("<QQ", data, at - 16)
        if pvf == 0 and spare == 0:
            precedents["null_words"] += 1
        elif spare == 0 and image_base <= pvf < image_base + size_of_image:
            precedents["in_image_qword"] += 1
        else:
            precedents["other"] += 1
        rva = _rva_of(sections, at)
        entry = names.setdefault(
            name, {"name": name, "rva": hex(rva) if rva is not None else None, "hits": 0}
        )
        entry["hits"] += 1
    return {
        "mangled_type_names": len(names),
        "leading_qword_observation": precedents,
        "outermost_namespaces": _namespace_counts(names),
        "names": sorted(names),
    }


def _qualified_root(name: str) -> str:
    """Outermost namespace of an MSVC mangled type name.

    Mangling nests innermost-first -- ``.?AVFoo@ns@outer@@`` is
    ``outer::ns::Foo`` -- so the root is the last ``@`` segment, not the first.
    Anonymous types have no namespace to report and are bucketed, not leaked
    into the histogram as their own key.
    """
    body = re.sub(r"^\.?\?A[vu$]", "", name)
    body = re.sub(r"@@?$", "", body)
    if body.startswith("<lambda") or "?A0x" in name:
        return "anonymous"
    segments = [s for s in body.split("@") if s and not s.startswith("$")]
    if "@" not in body:
        return "global"  # a top-level class is not its own namespace
    root = segments[-1] if segments else body
    # Template/anonymous leftovers are not namespaces; bucketing them keeps the
    # histogram honest instead of giving each one a count-1 row.
    return root if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", root) else "unnested"


def _namespace_counts(names: dict[str, dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in names:
        root = _qualified_root(name)
        counts[root] = counts.get(root, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:40])


def harvest_literals(data: mmap.mmap, sections: list[dict]) -> dict:
    """Identifier-shaped literals from initialized-data sections, keyed by string."""
    found: dict[str, dict] = {}
    targets = [s for s in sections if s["name"] in _DATA_SECTIONS and s["rawsize"]]
    for sec in targets:
        view = data[sec["rawptr"] : sec["rawptr"] + sec["rawsize"]]
        for match in _IDENT.finditer(view):
            token = match.group().decode("ascii")
            entry = found.setdefault(token, {"token": token, "rvas": [], "sections": set()})
            if len(entry["rvas"]) < 4:
                entry["rvas"].append(hex(sec["vaddr"] + match.start()))
            entry["sections"].add(sec["name"])
    return {
        "scanned_sections": [s["name"] for s in targets],
        "distinct_tokens": len(found),
        "tokens": {k: {"rvas": v["rvas"], "sections": sorted(v["sections"])} for k, v in sorted(found.items())},
    }


def _cstr(data: mmap.mmap, sections: list[dict], rva: int, limit: int = 64) -> str | None:
    for sec in sections:
        if sec["vaddr"] <= rva < sec["vaddr"] + max(sec["vsize"], 1):
            at = sec["rawptr"] + (rva - sec["vaddr"])
            end = data.find(b"\x00", at, at + limit)
            if end < 0:
                return None
            try:
                return data[at:end].decode("ascii")
            except UnicodeDecodeError:
                return None
    return None


def harvest_name_tables(data: mmap.mmap, sections: list[dict], image_base: int, size_of_image: int) -> dict:
    """Runs of ``const char*`` that point at identifier-shaped literals.

    This is the reflection-table shape a serializer or protocol schema uses for a
    field-name array, so the run order is the declared order of the fields. The
    physically-adjacent-literal variant was tried first on this target and found
    no draft keys at all -- only format lists and an HSL matrix -- which is what
    pointed here.
    """
    tables: list[dict] = []
    for sec in sections:
        if sec["name"] not in {".rdata", ".data"} or not sec["rawsize"]:
            continue
        view = data[sec["rawptr"] : sec["rawptr"] + sec["rawsize"]]
        run: list[str] = []
        start = 0
        for i in range(0, len(view) - 8, 8):
            (value,) = struct.unpack_from("<Q", view, i)
            name = _cstr(data, sections, value - image_base) if image_base <= value < image_base + size_of_image else None
            if name and _IDENT_EXACT.match(name.encode()):
                if not run:
                    start = i
                run.append(name)
            else:
                if len(run) >= 5:
                    tables.append({"rva": hex(sec["vaddr"] + start), "section": sec["name"], "fields": run})
                run = []
        if len(run) >= 5:
            tables.append({"rva": hex(sec["vaddr"] + start), "section": sec["name"], "fields": run})
    return {"min_run": 5, "tables": len(tables), "found": tables}


def cross_check(tokens: dict[str, dict], stats_path: Path) -> dict:
    """Classify each corpus key against the binary's literal inventory."""
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    groups = {k: stats[k] for k in ("top_level_keys", "track_field_keys", "segment_keys", "bucket_keys") if k in stats}
    out: dict[str, dict[str, list[str]]] = {}
    for group, keys in groups.items():
        names = list(keys)  # dict -> keys, list -> items; both are the corpus key set
        present = [k for k in names if isinstance(k, str) and k in tokens]
        absent = [k for k in names if isinstance(k, str) and k not in tokens]
        out[group] = {"total": len(names), "in_binary": present, "not_in_binary": absent}
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pe", help="absolute path to the PE image (read only)")
    parser.add_argument("--rtti", action="store_true")
    parser.add_argument("--literals", action="store_true")
    parser.add_argument("--tables", action="store_true", help="const char* field-name tables")
    parser.add_argument("--against", type=Path, help="stats.json from corpus_scan.py")
    parser.add_argument("--out", type=Path, required=True, help="artifact directory (keep under temp/)")
    args = parser.parse_args()

    path = Path(args.pe)
    if not (args.rtti or args.literals or args.tables):
        parser.error("pick at least one of --rtti / --literals / --tables")
    args.out.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
        with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data:
            sections, image_base, size_of_image = _sections(data)
            report: dict = {
                "target": str(path.resolve()),
                "sha256": digest.hexdigest(),
                "size": path.stat().st_size,
                "image_base": hex(image_base),
                "size_of_image": size_of_image,
                "sections": [
                    {**s, "vaddr": hex(s["vaddr"]), "rawptr": hex(s["rawptr"])} for s in sections
                ],
            }
            literal_tokens: dict[str, dict] | None = None
            if args.literals:
                literals = harvest_literals(data, sections)
                literal_tokens = literals["tokens"]
                (args.out / "literals.json").write_text(
                    json.dumps(literals, ensure_ascii=False, indent=1), encoding="utf-8"
                )
                report["literals"] = {
                    k: v for k, v in literals.items() if k != "tokens"
                }
            if args.tables:
                tables = harvest_name_tables(data, sections, image_base, size_of_image)
                (args.out / "name-tables.json").write_text(
                    json.dumps(tables, ensure_ascii=False, indent=1), encoding="utf-8"
                )
                widest = sorted(tables["found"], key=lambda t: -len(t["fields"]))[:5]
                report["name_tables"] = {
                    "tables": tables["tables"],
                    "widest": [{"rva": t["rva"], "fields": len(t["fields"])} for t in widest],
                }
            if args.rtti:
                rtti = harvest_rtti(data, sections, image_base, size_of_image)
                (args.out / "rtti.json").write_text(
                    json.dumps(rtti, ensure_ascii=False, indent=1), encoding="utf-8"
                )
                report["rtti"] = {k: v for k, v in rtti.items() if k != "names"}
            if args.against:
                if literal_tokens is None:
                    parser.error("--against needs --literals (the key inventory comes from it)")
                report["cross_check"] = cross_check(literal_tokens, args.against)
                (args.out / "cross-check.json").write_text(
                    json.dumps(report["cross_check"], ensure_ascii=False, indent=1), encoding="utf-8"
                )

    (args.out / "harvest-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
