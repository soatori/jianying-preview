"""Subprocess worker: the only place videoeditor.dll is ever loaded.

The DLL writes banner text into stdout when it detaches and leaks one heap
block per call, so it gets a short-lived process of its own. Results go to a
file (not stdout) so banner noise can never corrupt them, and the process ends
via TerminateProcess so the DLL never runs its detach path.

Usage:  python worker.py <job.json> <result.json>
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cache import assert_scratch_target  # noqa: E402
from dll import CryptoUnavailable, DllCrypto, discover_dll, report  # noqa: E402


def _run_op(crypto_holder: list, op: dict) -> dict:
    kind = op["op"]

    if kind == "report":
        return {"op": kind, "ok": True, **report(op.get("dll"))}

    if not crypto_holder:
        crypto_holder.append(DllCrypto(op.get("dll")))
    crypto = crypto_holder[0]

    if kind in ("decrypt_bytes", "encrypt_bytes"):
        dst = assert_scratch_target(op["dst"])
        data = Path(op["src"]).read_bytes()
        out = crypto.decrypt_bytes(data) if kind == "decrypt_bytes" else crypto.encrypt_bytes(data)
        tmp = dst.with_suffix(dst.suffix + ".part")
        tmp.write_bytes(out)
        os.replace(tmp, dst)
        return {"op": kind, "ok": True, "src": op["src"], "dst": str(dst), "in_size": len(data), "out_size": len(out)}

    raise ValueError(f"unknown op: {kind}")


def main(job_path: str, result_path: str) -> int:
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    crypto_holder: list = []
    results, errors = [], []
    for op in job.get("ops", []):
        try:
            results.append(_run_op(crypto_holder, op))
        except (CryptoUnavailable, OSError, ValueError, RuntimeError) as exc:
            errors.append({"op": op.get("op"), "error": type(exc).__name__, "message": str(exc)})
        except Exception as exc:  # noqa: BLE001 - worker must never die silently
            errors.append(
                {
                    "op": op.get("op"),
                    "error": type(exc).__name__,
                    "message": str(exc),
                    "trace": traceback.format_exc(limit=3),
                }
            )
    payload = {
        "ok": not errors,
        "dll": str(crypto_holder[0].dll_path) if crypto_holder else job.get("dll"),
        "results": results,
        "errors": errors,
    }
    out = Path(result_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if not errors else 1


if __name__ == "__main__":
    code = 2
    try:
        code = main(sys.argv[1], sys.argv[2])
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        code = 2
    sys.stdout.flush()
    sys.stderr.flush()
    if os.name == "nt":
        # Skip the DLL's detach path: it flushes banners and can hang the exit.
        ctypes.windll.kernel32.TerminateProcess(ctypes.c_void_p(-1), code)
    os._exit(code)
