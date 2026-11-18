"""Parent-side client for the crypto worker.

Decrypt policy (2026-11-18): the pure-Python implementation (``pure.py``,
AES-256-GCM with the key/nonce carried inside the container) is the DEFAULT
and runs in-process with no DLL and no worker. The worker path -- where every
DLL touch happens in a child process -- is the BACKUP: it runs when the pure
decrypt raises, or when the caller passes an explicit ``dll=`` (audit/pinning
runs that must exercise exactly that videoeditor.dll). Results land under
``temp/`` behind the write fence either way.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

try:
    from . import cache
except ImportError:
    import cache

WORKER = Path(__file__).resolve().parent / "worker.py"
SCRATCH = "crypto-probe"

last_backend = "?"  # "pure" | "dll": which backend answered the last decrypt


class WorkerError(RuntimeError):
    def __init__(self, message: str, payload: dict | None = None):
        super().__init__(message)
        self.payload = payload or {}


def _pure_decrypt_bytes(data: bytes) -> bytes:
    try:
        from . import pure
    except ImportError:
        import pure
    return pure.PureCrypto().decrypt(data)


def _run_worker(ops: list[dict], dll: str | None, timeout: int, tag: str) -> dict:
    """Run one batch of ops in a fresh worker process and return its result payload."""
    scratch = cache.scratch_dir(SCRATCH)
    token = f"{tag}-{uuid.uuid4().hex[:8]}"
    job_path = scratch / f"{token}.job.json"
    result_path = scratch / f"{token}.result.json"
    for op in ops:
        op.setdefault("dll", dll)
    job_path.write_text(json.dumps({"dll": dll, "ops": ops}, ensure_ascii=False), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(WORKER), str(job_path), str(result_path)],
        capture_output=True,
        timeout=timeout,
    )
    if not result_path.exists():
        raise WorkerError(
            f"worker produced no result (rc={proc.returncode})",
            {
                "returncode": proc.returncode,
                "stdout_tail": proc.stdout[-2000:].decode("utf-8", "replace"),
                "stderr_tail": proc.stderr[-2000:].decode("utf-8", "replace"),
            },
        )
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["returncode"] = proc.returncode
    payload["stderr_tail"] = proc.stderr[-500:].decode("utf-8", "replace")
    payload["job"] = str(job_path)
    payload["result"] = str(result_path)
    return payload


def _pure_call_decrypt_ops(ops: list[dict]) -> dict:
    results = []
    for op in ops:
        dst = cache.assert_scratch_target(op["dst"])
        data = Path(op["src"]).read_bytes()
        out = _pure_decrypt_bytes(data)
        tmp = dst.with_suffix(dst.suffix + ".part")
        tmp.write_bytes(out)
        os.replace(tmp, dst)
        results.append({"op": "decrypt_bytes", "ok": True, "src": op["src"],
                        "dst": str(dst), "in_size": len(data), "out_size": len(out)})
    return {"ok": True, "dll": "pure", "results": results, "errors": [], "backend": "pure"}


def call(ops: list[dict], dll: str | None = None, timeout: int = 600, tag: str = "job") -> dict:
    """Run one batch of ops and return its result payload.

    Pure-decrypt batches with no explicit ``dll`` run in-process first; every
    other batch goes to the worker child process. ``payload["backend"]`` says
    which one answered.
    """
    global last_backend
    if dll is None and ops and all(op.get("op") == "decrypt_bytes" for op in ops):
        try:
            payload = _pure_call_decrypt_ops(ops)
            last_backend = "pure"
            return payload
        except Exception:  # noqa: BLE001 - fall through to the DLL backup
            pass
    payload = _run_worker(ops, dll, timeout, tag)
    payload["backend"] = "dll"
    last_backend = "dll"
    return payload


def decrypt_bytes(data: bytes, dll: str | None = None, tag: str = "dec") -> bytes:
    """Memory-API decrypt of raw bytes (pure default; DLL worker as backup)."""
    global last_backend
    if dll is None:
        try:
            out = _pure_decrypt_bytes(data)
            last_backend = "pure"
            return out
        except Exception:  # noqa: BLE001 - fall through to the DLL backup
            pass
    out = _worker_decrypt_bytes(data, dll, tag)
    last_backend = "dll"
    return out


def _worker_decrypt_bytes(data: bytes, dll: str | None, tag: str) -> bytes:
    """Old worker flow: temp file the fence controls, result read back."""
    scratch = cache.scratch_dir(SCRATCH)
    token = f"{tag}-{uuid.uuid4().hex[:8]}"
    src = cache.assert_scratch_target(scratch / f"{token}.in")
    dst = cache.assert_scratch_target(scratch / f"{token}.out")
    src.write_bytes(data)
    payload = _run_worker(
        [{"op": "decrypt_bytes", "src": str(src), "dst": str(dst)}],
        dll=dll, timeout=600, tag=tag,
    )
    if payload.get("errors"):
        raise WorkerError(str(payload["errors"]), payload)
    return dst.read_bytes()
