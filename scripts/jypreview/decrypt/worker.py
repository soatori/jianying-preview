"""Short-lived subprocess that is the only place holding ``videoeditor.dll``.

The DLL spawns bytenn/mobilecv2 worker threads, leaks one heap block per call by
design, and flushes CRT banners on detach, so results are written to staging
files and the process is terminated rather than allowed to unwind.

Jobs (JSON list, one file per pass)::

    {"kind": "content", "job_id": "...", "src": "<abs path>", "key": "<24 hex>",
     "expect_id": "<timeline id or ''>"}
    {"kind": "probe",   "job_id": "...", "draft": "<abs draft dir>", "did": "..."}

Staging outputs land under ``<staging>/content/<key>.json`` and
``<staging>/probe/<did>.json``; the fenced cache in the server ingests them.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _reconfigure() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _ack(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def _write_staging(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".tmp{os.getpid()}")
    temp.write_bytes(payload)
    os.replace(temp, path)


def _canonical(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _read_bytes(path: Path) -> bytes:
    last: Exception | None = None
    for _ in range(3):
        try:
            with open(path, "rb") as handle:
                return handle.read()
        except OSError as exc:
            last = exc
            import time
            time.sleep(0.05)
    raise last or OSError(f"cannot read {path}")


def run_content(job: dict, staging: Path, backend_holder: dict) -> dict:
    import hashlib

    from jypreview.skill_import import parse_plain_json

    src = Path(job["src"])
    key = job["key"]
    raw = _read_bytes(src)
    sha256 = hashlib.sha256(raw).hexdigest()
    plain = parse_plain_json(raw)
    if plain is not None:
        value, encoding = plain, "plaintext"
    else:
        if backend_holder.get("crypto") is None:
            from jypreview.skill_import import JyDraftCrypto

            backend_holder["crypto"] = JyDraftCrypto(job.get("dll") or None)
        value = backend_holder["crypto"].decrypt_json(raw)
        encoding = "jianying-dll"
    expect = str(job.get("expect_id") or "")
    content_id = str(value.get("id") or "")
    if expect and content_id and content_id.upper() != expect.upper():
        raise ValueError(f"content id {content_id!r} does not match timeline {expect!r}")
    _write_staging(staging / "content" / f"{key}.json", _canonical(value))
    return {
        "kind": "content", "job_id": job.get("job_id"), "ok": True, "key": key, "src": str(src),
        "src_sha256": sha256, "encoding": encoding, "content_id": content_id,
        "bytes": len(raw), "staged": str(staging / "content" / f"{key}.json"),
        "duration_us": int(value.get("duration", 0) or 0),
    }


def run_probe(job: dict, staging: Path) -> dict:
    from jypreview.skill_import import JianyingProject

    draft = Path(job["draft"])
    did = job["did"]
    project = JianyingProject(str(draft), dll_path=job.get("dll"))
    probe = project.probe()
    timelines = []
    for entry in probe.get("timelines", []):
        tid = str(entry.get("id"))
        try:
            manifest = project.replica_manifest(tid)
        except Exception as exc:
            manifest = {"replicas": [], "errors": [str(exc)], "count": 0}
        try:
            primary = str(project.content_path(tid))
        except Exception as exc:
            primary = None
            manifest.setdefault("errors", []).append(str(exc))
        timelines.append({
            "id": tid, "name": entry.get("name"), "deleted": bool(entry.get("deleted")),
            "content_id": entry.get("content_id"), "encoding": entry.get("encoding"),
            "duration_us": entry.get("duration_us"), "primary": primary,
            "replicas": [
                {"path": item["path"], "relative_path": item["relative_path"], "role": item["role"],
                 "primary": item["primary"], "sha256": item["sha256"], "encoding": item.get("encoding")}
                for item in manifest.get("replicas", [])
            ],
            "replica_errors": manifest.get("errors", []),
        })
    payload = {
        "root": probe.get("root"), "did": did, "layout": probe.get("layout"),
        "project_index": probe.get("project_index"),
        "active_timeline_id": probe.get("active_timeline_id"),
        "active_evidence": probe.get("active_evidence"),
        "timelines": timelines,
    }
    _write_staging(staging / "probe" / f"{did}.json", json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    return {"kind": "probe", "job_id": job.get("job_id"), "ok": True, "did": did,
            "layout": payload["layout"], "active_timeline_id": payload["active_timeline_id"],
            "timeline_count": len(timelines), "staged": str(staging / "probe" / f"{did}.json")}


def main(argv: list[str] | None = None) -> int:
    _reconfigure()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", required=True)
    parser.add_argument("--staging", required=True)
    parser.add_argument("--dll")
    args = parser.parse_args(argv)

    jobs = json.loads(Path(args.jobs).read_text(encoding="utf-8"))
    staging = Path(args.staging)
    staging.mkdir(parents=True, exist_ok=True)
    backend_holder: dict = {}
    failures = 0
    for job in jobs:
        try:
            if job.get("kind") == "probe":
                ack = run_probe({**job, "dll": job.get("dll") or args.dll}, staging)
            else:
                ack = run_content({**job, "dll": job.get("dll") or args.dll}, staging, backend_holder)
        except Exception as exc:
            failures += 1
            ack = {"kind": job.get("kind"), "job_id": job.get("job_id"), "ok": False,
                   "src": job.get("src") or job.get("draft"),
                   "error": f"{exc.__class__.__name__}: {exc}"}
        _ack(ack)
    _ack({"kind": "summary", "ok": failures == 0, "jobs": len(jobs), "failures": failures,
          "dll_loaded": backend_holder.get("crypto") is not None})
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    if os.name == "nt":
        import ctypes

        ctypes.windll.kernel32.TerminateProcess(ctypes.c_void_p(-1), code)
    os._exit(code)
