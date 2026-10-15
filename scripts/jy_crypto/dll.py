"""Call JianYing's own videoeditor.dll to decrypt/encrypt draft content.

Black-box usage only: we enumerate the export table and call what JianYing
ships. No cipher is implemented, inferred, or reproduced here.

Two call surfaces, preferred in this order:

1. path API   -- static exports taking ``const char*`` and returning ``int``
                 (``isFileEncrypted`` / ``decryptFile`` / ``encryptFile``).
                 Simplest ABI, so least to get wrong.
2. memory API -- member exports speaking MSVC x64 ``std::string``
                 (``decrypt`` / ``encrypt`` / ``enable``). Fallback.

Every result must pass the round-trip gates in ``gate.py`` before it is
trusted. A failed probe writes nothing.
"""

from __future__ import annotations

import ctypes
import glob
import os
import re
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
        except (NotADirectoryError, OSError, ValueError):
            continue
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
    """Resolved export names, discovered by pattern rather than hardcoded."""

    path_is_encrypted: str | None = None
    path_decrypt: list[str] = None
    path_encrypt: list[str] = None
    mem_decrypt: list[str] = None
    mem_encrypt: str | None = None
    mem_enable: str | None = None
    mem_is_enable: str | None = None

    @classmethod
    def resolve(cls, exports: PEExports) -> "Symbols":
        def one(*fragments: str) -> str | None:
            hits = exports.find(_FAMILY, *fragments)
            return hits[0] if hits else None

        def many(*fragments: str) -> list[str]:
            return exports.find(_FAMILY, *fragments)

        return cls(
            path_is_encrypted=one("?isFileEncrypted@") or one("isFileEncrypted"),
            path_decrypt=many("?decryptFile@") or many("decryptFile"),
            path_encrypt=many("?encryptFile@") or many("encryptFile"),
            mem_decrypt=many("?decrypt@"),
            mem_encrypt=one("?encrypt@"),
            mem_enable=one("?enable@"),
            mem_is_enable=one("?isEnable@"),
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

    # ---- path API -------------------------------------------------------

    def is_file_encrypted(self, path: str | Path) -> bool:
        sym = self.symbols.path_is_encrypted
        if not sym:
            raise CryptoUnavailable("isFileEncrypted export not present")
        proto = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_char_p)
        return bool(self._fn("is_file_encrypted", sym, proto)(str(path).encode("utf-8")))

    def decrypt_file(self, src: str | Path, dst: str | Path, extra: bytes = b"") -> int:
        """Call the static path-level decrypt. Returns the export's int status."""
        candidates = [s for s in (self.symbols.path_decrypt or []) if "Stream" not in s and "Bytes" not in s]
        if not candidates:
            raise CryptoUnavailable("decryptFile export not present")
        proto = ctypes.CFUNCTYPE(
            ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p
        )
        return self._fn("decrypt_file", candidates[0], proto)(
            str(src).encode("utf-8"), str(dst).encode("utf-8"), extra
        )

    def encrypt_file(self, src: str | Path, dst: str | Path, extra: bytes = b"") -> int:
        candidates = self.symbols.path_encrypt or []
        if not candidates:
            raise CryptoUnavailable("encryptFile export not present")
        proto = ctypes.CFUNCTYPE(
            ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p
        )
        return self._fn("encrypt_file", candidates[0], proto)(
            str(src).encode("utf-8"), str(dst).encode("utf-8"), extra
        )

    # ---- memory API -----------------------------------------------------

    def _enable(self, on: bool) -> None:
        sym = self.symbols.mem_enable
        if not sym:
            return
        proto = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_bool)
        self._fn("enable", sym, proto)(None, on)

    def is_enabled(self) -> bool | None:
        sym = self.symbols.mem_is_enable
        if not sym:
            return None
        proto = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p)
        return bool(self._fn("is_enable", sym, proto)(None))

    def enable(self, on: bool) -> None:
        self._enable(on)

    def probe_path_api(self, src: str | Path, out_dir: str | Path, extras: tuple[bytes, ...] = (b"", b"{}")) -> list[dict]:
        """Bounded black-box probe of the static path-level exports.

        Tries enable(True) first, then each argument order and each extra-arg
        value, writing to a distinct output file. Reports status codes and
        output sizes only -- never trusts a variant that did not produce JSON.
        """
        out_dir = Path(out_dir)
        trials: list[dict] = []
        for state in (False, True):
            self._enable(state)
            enabled = self.is_enabled()
            if self.symbols.path_is_encrypted:
                proto = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_char_p)
                fn = self._fn("is_file_encrypted", self.symbols.path_is_encrypted, proto)
                trials.append(
                    {
                        "probe": "isFileEncrypted",
                        "enable": state,
                        "is_enabled": enabled,
                        "value": bool(fn(str(src).encode("utf-8"))),
                    }
                )
            candidates = [s for s in (self.symbols.path_decrypt or []) if "Stream" not in s and "Bytes" not in s]
            if not candidates:
                continue
            proto = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p)
            fn = self._fn("decrypt_file", candidates[0], proto)
            for extra in extras:
                for order in ("src_dst", "dst_src"):
                    dst = out_dir / f"variant-e{state}-x{len(extra)}-{order}.out"
                    args = (str(src), str(dst)) if order == "src_dst" else (str(dst), str(src))
                    status = fn(args[0].encode("utf-8"), args[1].encode("utf-8"), extra)
                    size = dst.stat().st_size if dst.exists() else 0
                    head = b""
                    if size:
                        with dst.open("rb") as handle:
                            head = handle.read(1)
                    trials.append(
                        {
                            "probe": "decryptFile",
                            "enable": state,
                            "is_enabled": enabled,
                            "extra": extra.decode("utf-8", "replace"),
                            "order": order,
                            "status": status,
                            "out_size": size,
                            "looks_like_json": head == b"{",
                            "dst": str(dst),
                        }
                    )
        return trials

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
        "sha256": None,
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
