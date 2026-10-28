"""Call JianYing's own videoeditor.dll to decrypt/encrypt draft content.

Black-box usage only: we enumerate the export table and call what JianYing
ships. No cipher is implemented, inferred, or reproduced here.

The only verified call surface is the member ``std::string`` API
(``decrypt`` / ``encrypt`` / ``enable`` under ``EncryptUtils@lvve``). The static
path-level exports (``decryptFile`` / ``encryptFile`` / ``isFileEncrypted``)
produced 0 bytes in every one of the 8 probed variants, and passing a draft path
to an export whose parameter direction is unverified is the one way this layer
could write into a draft, so they are not bound here at all (see
``docs/evidence/crypto-probe-log.md`` and U-16).

Every result must pass the round-trip gates in ``gate.py`` before it is
trusted.
"""

from __future__ import annotations

import ctypes
import glob
import os
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

try:  # package import
    from .pe import PEExports
except ImportError:  # direct script run
    from pe import PEExports

_FAMILY = "EncryptUtils@lvve"
_VERSION_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+){1,4})(?!\d)")


class CryptoUnavailable(RuntimeError):
    pass


def _version_key(path: Path) -> tuple[int, ...]:
    found = _VERSION_RE.findall(str(path))
    if not found:
        return (0,)
    return max((tuple(int(p) for p in v.split(".")) for v in found), default=(0,))


def _install_roots() -> list[Path]:
    roots: list[Path] = []
    for var in ("JIANYING_INSTALL_ROOT", "LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        value = os.environ.get(var)
        if value:
            roots.append(Path(value) / "JianyingPro")
    for drive in ("C:", "D:", "E:"):
        roots.append(Path(drive + os.sep) / "Program Files" / "JianyingPro")
    try:  # 与 scripts/jy_paths.py 共用同一份候选根，两边不会各扫各的
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import jy_paths

        roots.extend(jy_paths.candidate_roots())
    except Exception:                                 # noqa: BLE001
        pass
    return roots


def _registry_dlls() -> list[Path]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []
    out: list[Path] = []
    uninstall = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, uninstall) as parent:
                for i in range(winreg.QueryInfoKey(parent)[0]):
                    try:
                        with winreg.OpenKey(parent, winreg.EnumKey(parent, i)) as entry:
                            name = str(winreg.QueryValueEx(entry, "DisplayName")[0]).lower()
                            if "jianying" not in name and "剪映" not in name:
                                continue
                            for field in ("InstallLocation", "DisplayIcon"):
                                try:
                                    loc = str(winreg.QueryValueEx(entry, field)[0]).strip('"')
                                except OSError:
                                    continue
                                if not loc:
                                    continue
                                p = Path(loc)
                                out.append((p if p.is_dir() else p.parent) / "videoeditor.dll")
                                break
                    except OSError:
                        continue
        except OSError:
            continue
    return out


def discover_dll() -> Path:
    """Newest videoeditor.dll that exposes the EncryptUtils family.

    ``JIANYING_VIDEOEDITOR_DLL`` pins an exact file and wins outright.
    """
    pinned = os.environ.get("JIANYING_VIDEOEDITOR_DLL", "").strip('"')
    if pinned:
        path = Path(pinned)
        if not path.is_file():
            raise CryptoUnavailable(f"JIANYING_VIDEOEDITOR_DLL points to a missing file: {pinned}")
        return path.resolve()

    candidates: set[Path] = set()
    for root in _install_roots():
        if root.name.lower() == "videoeditor.dll":
            if root.is_file():
                candidates.add(root.resolve())
            continue
        if not root.is_dir():
            continue
        direct = root / "videoeditor.dll"
        if direct.is_file():
            candidates.add(direct.resolve())
        for hit in glob.glob(str(root / "*" / "videoeditor.dll")):
            candidates.add(Path(hit).resolve())
    for hit in _registry_dlls():
        if hit.is_file():
            candidates.add(hit.resolve())

    for path in sorted(candidates, key=lambda p: (_version_key(p), str(p)), reverse=True):
        try:
            if PEExports(path).find(_FAMILY):
                return path
        except (OSError, ValueError, struct.error):
            continue  # a malformed or unreadable image must not abort discovery
    raise CryptoUnavailable(
        "No videoeditor.dll exposing " + _FAMILY + " was found. "
        "Set JIANYING_VIDEOEDITOR_DLL to an exact path."
    )


class StdString(ctypes.Structure):
    """MSVC x64 ``std::string``: 16-byte inline buffer, then size, then capacity."""

    _fields_ = [
        ("inline", ctypes.c_ubyte * 16),
        ("size", ctypes.c_uint64),
        ("capacity", ctypes.c_uint64),
    ]

    SSO = 16

    @classmethod
    def wrap(cls, data: bytes) -> tuple["StdString", list]:
        """Build an input string. The returned list keeps heap buffers alive."""
        value = cls()
        keep: list = []
        value.size = len(data)
        if len(data) < cls.SSO:
            ctypes.memmove(value.inline, data, len(data))
            value.capacity = cls.SSO - 1
        else:
            buffer = ctypes.create_string_buffer(data, len(data) + 1)
            keep.append(buffer)
            pointer = ctypes.c_uint64(ctypes.addressof(buffer))
            ctypes.memmove(value.inline, ctypes.byref(pointer), 8)
            value.capacity = len(data)
        return value, keep

    def read(self) -> bytes:
        if self.capacity < self.SSO:
            return bytes(self.inline[: self.size])
        pointer = ctypes.c_uint64.from_buffer_copy(self.inline).value
        return ctypes.string_at(pointer, self.size) if pointer else b""


@dataclass
class Symbols:
    """Resolved memory-API export names, discovered by pattern rather than hardcoded."""

    mem_decrypt: list[str] = None
    mem_encrypt: str | None = None
    mem_enable: str | None = None

    @classmethod
    def resolve(cls, exports: PEExports) -> "Symbols":
        def one(*fragments: str) -> str | None:
            hits = exports.find(_FAMILY, *fragments)
            return hits[0] if hits else None

        def many(*fragments: str) -> list[str]:
            return exports.find(_FAMILY, *fragments)

        return cls(
            mem_decrypt=many("?decrypt@"),
            mem_encrypt=one("?encrypt@"),
            mem_enable=one("?enable@"),
        )


class DllCrypto:
    """Loads videoeditor.dll in *this* process. Only ever use it from a worker."""

    def __init__(self, dll_path: str | Path | None = None):
        if os.name != "nt":
            raise CryptoUnavailable("videoeditor.dll is Windows-only")
        self.dll_path = Path(dll_path) if dll_path else discover_dll()
        if not self.dll_path.is_file():
            raise CryptoUnavailable(f"missing DLL: {self.dll_path}")
        self.symbols = Symbols.resolve(PEExports(self.dll_path))
        self._dll_dir_token = None
        self._lib = None
        self._fns: dict[str, ctypes._CFuncPtr] = {}

    @property
    def version(self) -> str:
        return self.dll_path.parent.name

    def load(self) -> None:
        if self._lib is not None:
            return
        if hasattr(os, "add_dll_directory"):
            self._dll_dir_token = os.add_dll_directory(str(self.dll_path.parent))
        self._lib = ctypes.WinDLL(str(self.dll_path))
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        kernel32.GetProcAddress.restype = ctypes.c_void_p

        def address(symbol: str) -> int:
            found = kernel32.GetProcAddress(self._lib._handle, symbol.encode("ascii"))
            if not found:
                raise CryptoUnavailable(f"symbol not resolvable at load time: {symbol}")
            return found

        self._address = address

    def _fn(self, key: str, symbol: str, proto):
        self.load()
        if key not in self._fns:
            self._fns[key] = proto(self._address(symbol))
        return self._fns[key]

    # ---- memory API -----------------------------------------------------

    def _enable(self, on: bool) -> None:
        sym = self.symbols.mem_enable
        if not sym:
            return
        proto = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_bool)
        self._fn("enable", sym, proto)(None, on)

    def _mem_decrypt(self, symbol: str, data: bytes, with_flag: bool) -> bytes:
        source, keep_src = StdString.wrap(data)
        params, keep_params = StdString.wrap(b"{}")
        out = StdString()
        ok = ctypes.c_bool(False)
        if with_flag:
            proto = ctypes.CFUNCTYPE(
                ctypes.POINTER(StdString), ctypes.c_void_p, ctypes.POINTER(StdString),
                ctypes.POINTER(StdString), ctypes.POINTER(StdString), ctypes.POINTER(ctypes.c_bool),
            )
            fn = self._fn(f"dec_flag_{symbol}", symbol, proto)
            fn(None, ctypes.byref(out), ctypes.byref(source), ctypes.byref(params), ctypes.byref(ok))
            if not ok.value:
                raise CryptoUnavailable("decrypt reported ok=false")
        else:
            proto = ctypes.CFUNCTYPE(
                ctypes.POINTER(StdString), ctypes.c_void_p, ctypes.POINTER(StdString),
                ctypes.POINTER(StdString), ctypes.POINTER(StdString),
            )
            fn = self._fn(f"dec_{symbol}", symbol, proto)
            fn(None, ctypes.byref(out), ctypes.byref(source), ctypes.byref(params))
        del keep_src, keep_params
        return out.read()

    def _mem_encrypt(self, data: bytes) -> bytes:
        sym = self.symbols.mem_encrypt
        if not sym:
            raise CryptoUnavailable("encrypt export not present")
        self._enable(True)
        source, keep = StdString.wrap(data)
        out = StdString()
        proto = ctypes.CFUNCTYPE(
            ctypes.POINTER(StdString), ctypes.c_void_p,
            ctypes.POINTER(StdString), ctypes.POINTER(StdString),
        )
        self._fn("enc", sym, proto)(None, ctypes.byref(out), ctypes.byref(source))
        del keep
        return out.read()

    def decrypt_bytes(self, data: bytes) -> bytes:
        """In-memory decrypt. Tries the flagged overload first, then the plain one."""
        flagged = [s for s in (self.symbols.mem_decrypt or []) if s.endswith("AEA_N@Z")]
        plain = [s for s in (self.symbols.mem_decrypt or []) if s not in flagged]
        errors: list[str] = []
        for symbol, with_flag in [(s, True) for s in flagged] + [(s, False) for s in plain]:
            try:
                return self._mem_decrypt(symbol, data, with_flag)
            except CryptoUnavailable as exc:
                errors.append(f"{symbol}: {exc}")
        raise CryptoUnavailable("no decrypt overload succeeded: " + "; ".join(errors))

    def encrypt_bytes(self, data: bytes) -> bytes:
        return self._mem_encrypt(data)

    def close(self) -> None:
        self._fns.clear()
        self._lib = None
        if self._dll_dir_token is not None and hasattr(self._dll_dir_token, "close"):
            self._dll_dir_token.close()
            self._dll_dir_token = None


def report(dll_path: str | Path | None = None) -> dict:
    path = Path(dll_path) if dll_path else discover_dll()
    exports = PEExports(path)
    symbols = Symbols.resolve(exports)
    return {
        "dll": str(path),
        "size": path.stat().st_size,
        "export_count": len(exports.names),
        "family_exports": exports.find(_FAMILY),
        "resolved": {k: v for k, v in symbols.__dict__.items()},
    }


if __name__ == "__main__":
    import argparse
    import hashlib
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dll")
    args = parser.parse_args()
    info = report(args.dll)
    info["sha256"] = hashlib.sha256(Path(info["dll"]).read_bytes()).hexdigest()
    print(json.dumps(info, ensure_ascii=False, indent=2))
