"""Parent-side client for the crypto worker.

Every DLL touch happens in a child process; this module only writes job files
under ``temp/``, spawns the worker, and reads its result file back.
"""

from __future__ import annotations

import json
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


class WorkerError(RuntimeError):
    def __init__(self, message: str, payload: dict | None = None):
        super().__init__(message)
        self.payload = payload or {}


def call(ops: list[dict], dll: str | None = None, timeout: int = 600, tag: str = "job") -> dict:
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


def decrypt_bytes(data: bytes, dll: str | None = None, tag: str = "dec") -> bytes:
    """Memory-API decrypt of raw bytes, via a temp file the fence controls."""
    scratch = cache.scratch_dir(SCRATCH)
    token = f"{tag}-{uuid.uuid4().hex[:8]}"
    src = cache.assert_scratch_target(scratch / f"{token}.in")
    dst = cache.assert_scratch_target(scratch / f"{token}.out")
    src.write_bytes(data)
    payload = call([{"op": "decrypt_bytes", "src": str(src), "dst": str(dst)}], dll=dll, tag=tag)
    if payload.get("errors"):
        raise WorkerError(str(payload["errors"]), payload)
    return dst.read_bytes()
