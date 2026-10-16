"""Minimal PE export-directory reader (stdlib only).

We only need export *names* so the crypto layer can resolve symbols by pattern
instead of hardcoding mangled strings that drift between JianYing versions.
"""

from __future__ import annotations

import mmap
import struct
from pathlib import Path

_DOS_LFANEW = 0x3C
_PE_SIGNATURE = b"PE\0\0"
_OPT_MAGIC_PE32_PLUS = 0x20B
_OPT_MAGIC_PE32 = 0x10B
_EXPORT_DIR_INDEX = 0


class NotAPEFile(ValueError):
    pass


class PEExports:
    """Export names of a PE image, read without loading it.

    Mapped rather than slurped: the shipped DLL is tens of megabytes and we only
    ever touch the headers plus the export directory inside them.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        with self.path.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data:
            self.names = tuple(self._read_names(data))

    def find(self, *fragments: str) -> list[str]:
        """Names containing every fragment (case-sensitive, as exported)."""
        return [n for n in self.names if all(f in n for f in fragments)]

    @staticmethod
    def _sections(data: bytes, num_sections: int, opt_offset: int, opt_size: int) -> list[tuple[int, int, int]]:
        table = opt_offset + opt_size
        out = []
        for i in range(num_sections):
            base = table + i * 40
            vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", data, base + 8)
            out.append((vaddr, vsize or rawsize, rawptr))
        return out

    def _rva_to_offset(self, sections: list[tuple[int, int, int]], rva: int) -> int:
        for vaddr, vsize, rawptr in sections:
            if vaddr <= rva < vaddr + max(vsize, 1):
                return rawptr + (rva - vaddr)
        raise NotAPEFile(f"RVA {rva:#x} is not covered by any section")

    def _read_names(self, data: bytes) -> list[str]:
        if len(data) < 0x40 or data[:2] != b"MZ":
            raise NotAPEFile(f"{self.path}: missing MZ header")
        (lfanew,) = struct.unpack_from("<I", data, _DOS_LFANEW)
        if data[lfanew : lfanew + 4] != _PE_SIGNATURE:
            raise NotAPEFile(f"{self.path}: missing PE signature")
        coff = lfanew + 4
        (num_sections,) = struct.unpack_from("<H", data, coff + 2)
        (opt_size,) = struct.unpack_from("<H", data, coff + 16)
        opt = coff + 20
        (magic,) = struct.unpack_from("<H", data, opt)
        if magic == _OPT_MAGIC_PE32_PLUS:
            dirs = opt + 112
        elif magic == _OPT_MAGIC_PE32:
            dirs = opt + 96
        else:
            raise NotAPEFile(f"{self.path}: unknown optional header magic {magic:#x}")
        exp_rva, exp_size = struct.unpack_from("<II", data, dirs + _EXPORT_DIR_INDEX * 8)
        if not exp_rva:
            return []
        sections = self._sections(data, num_sections, opt, opt_size)
        exp = self._rva_to_offset(sections, exp_rva)
        (num_names,) = struct.unpack_from("<I", data, exp + 24)
        (names_rva,) = struct.unpack_from("<I", data, exp + 32)
        names_at = self._rva_to_offset(sections, names_rva)
        out: list[str] = []
        for i in range(num_names):
            (str_rva,) = struct.unpack_from("<I", data, names_at + i * 4)
            at = self._rva_to_offset(sections, str_rva)
            end = data.find(b"\0", at)
            if end < 0:
                raise NotAPEFile(f"{self.path}: export name at {at:#x} is not NUL-terminated")
            out.append(data[at:end].decode("ascii", "replace"))
        return out


def main() -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dll")
    parser.add_argument("--contains", action="append", default=[])
    args = parser.parse_args()

    exports = PEExports(args.dll)
    selected = exports.find(*args.contains) if args.contains else list(exports.names)
    print(
        json.dumps(
            {
                "dll": str(Path(args.dll).resolve()),
                "size": Path(args.dll).stat().st_size,
                "export_count": len(exports.names),
                "matched": selected,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
