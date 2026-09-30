"""Server-side decrypt orchestration: never loads the DLL, always fenced cache.

Plain drafts are parsed in-process (no DLL needed). Encrypted drafts and full
``probe`` walks are delegated to :mod:`jypreview.decrypt.worker`, one subprocess
per batch, results staged then ingested into the draft's fenced cache.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

from .. import __version__
from ..config import DRAFT_CACHE_DIRNAME
from ..draft_id import draft_id, normalize
from .cache import DraftCache, key_for

PROBE_FILE = "probe/probe.json"
CONTENT_FILENAMES = ("draft_content.json", "draft_info.json")
WATCH_NAMES = CONTENT_FILENAMES + ("draft_content.json.bak", "template-2.tmp", "timeline_layout.json",
                                   "project.json")


def _stat_sig(path: Path) -> str:
    try:
        info = path.stat()
    except OSError:
        return "-"
    return f"{info.st_mtime_ns}|{info.st_size}"


class DecryptError(RuntimeError):
    pass


class DecryptManager:
    def __init__(self, config):
        self.cfg = config
        self.staging = Path(config.user_state_dir) / "staging"
        self.staging.mkdir(parents=True, exist_ok=True)
        self._slot = threading.Semaphore(1)
        self._values: "OrderedDict[str, dict]" = OrderedDict()
        self._user_caches: dict[str, DraftCache] = {}
        self._writes: dict[str, int] = {}
        self.stats: dict[str, Any] = {"passes": 0, "jobs": 0, "errors": 0, "last_ms": 0,
                                      "degraded_passes": 0}
        try:
            from ..skill_import import videoeditor_dll_path

            self.dll_path = videoeditor_dll_path()
        except Exception:
            self.dll_path = None

    # -- subprocess --------------------------------------------------------
    def _spawn(self, jobs: list[dict]) -> list[dict]:
        if not jobs:
            return []
        scripts_dir = Path(__file__).resolve().parents[2]
        job_file = self.staging / f"jobs-{uuid.uuid4().hex[:12]}.json"
        job_file.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(scripts_dir) + os.pathsep + env.get("PYTHONPATH", "")
        if self.dll_path:
            env["JIANYING_VIDEOEDITOR_DLL"] = self.dll_path
        cmd = [sys.executable, "-X", "utf8", "-X", "faulthandler", "-m", "jypreview.decrypt.worker",
               "--jobs", str(job_file), "--staging", str(self.staging)]
        if self.dll_path:
            cmd += ["--dll", self.dll_path]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        started = time.monotonic()
        acks: list[dict] = []
        with self._slot:
            proc = subprocess.Popen(cmd, cwd=str(scripts_dir), stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    text=True, encoding="utf-8", errors="replace",
                                    creationflags=flags, env=env)
            deadline = started + self.cfg.decrypt_timeout_s
            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    line = line.strip()
                    if line.startswith("{") and line.endswith("}"):
                        try:
                            acks.append(json.loads(line))
                        except json.JSONDecodeError:
                            self.stats["errors"] += 1
                    if time.monotonic() > deadline:
                        raise subprocess.TimeoutExpired(cmd, self.cfg.decrypt_timeout_s)
            except subprocess.TimeoutExpired:
                proc.kill()
                self.stats["degraded_passes"] += 1
            finally:
                try:
                    proc.wait(5)
                except Exception:
                    proc.kill()
                    try:
                        proc.wait(5)
                    except Exception:
                        pass
                job_file.unlink(missing_ok=True)
        self.stats["passes"] += 1
        self.stats["jobs"] += len(jobs)
        self.stats["errors"] += sum(1 for ack in acks if ack.get("ok") is False)
        self.stats["last_ms"] = int((time.monotonic() - started) * 1000)
        return acks

    def _single_pass(self, job: dict) -> dict | None:
        return next((ack for ack in self._spawn([job]) if ack.get("job_id") == job["job_id"]), None)

    # -- caches ------------------------------------------------------------
    def cache_for(self, draft_dir: Path, did: str | None = None) -> DraftCache:
        did = did or draft_id(draft_dir)
        return DraftCache.open(self.cfg, Path(draft_dir), did)

    def _user_cache(self, draft_dir: Path, did: str) -> DraftCache:
        if did not in self._user_caches:
            self._user_caches[did] = DraftCache.user(self.cfg, Path(draft_dir), did)
        return self._user_caches[did]

    # -- probe -------------------------------------------------------------
    def probe_signature(self, draft_dir: Path, probe: dict | None = None) -> str:
        root = Path(draft_dir)
        paths = [root / name for name in CONTENT_FILENAMES]
        paths += [root / "timeline_layout.json", root / "Timelines" / "project.json",
                  root / "project.json"]
        timelines = root / "Timelines"
        if timelines.is_dir():
            for entry in sorted(timelines.iterdir()):
                if entry.is_dir():
                    paths += [entry / name for name in WATCH_NAMES]
        blob = "\n".join(f"{normalize(p)}|{_stat_sig(p)}" for p in paths)
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]

    def probe(self, draft_dir: Path, did: str | None = None, force: bool = False,
              cache: DraftCache | None = None) -> dict:
        root = Path(draft_dir)
        did = did or draft_id(root)
        cache = cache or self.cache_for(root, did)
        cached = cache.get_extra(PROBE_FILE)
        if cached and not force:
            try:
                record = json.loads(cached.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                record = None
            if isinstance(record, dict) and record.get("payload"):
                if record["sig"] == self.probe_signature(root, record["payload"]):
                    return record["payload"]

        ack = self._single_pass({"kind": "probe", "job_id": f"probe-{did}", "draft": str(root), "did": did})
        if not ack or not ack.get("ok"):
            if cached:
                payload = (json.loads(cached.decode("utf-8")) or {}).get("payload")
                if payload:
                    payload["stale"] = True
                    return payload
            raise DecryptError(f"probe failed for {root.name}: {(ack or {}).get('error', 'no ack')}")
        staged = Path(ack["staged"])
        try:
            payload = json.loads(staged.read_text(encoding="utf-8"))
        finally:
            staged.unlink(missing_ok=True)
        sig = self.probe_signature(root, payload)
        record = json.dumps({"sig": sig, "did": did, "payload": payload}, ensure_ascii=False).encode("utf-8")
        if cache.put_extra(PROBE_FILE, record) is None:
            self._user_cache(root, did).put_extra(PROBE_FILE, record)
        payload["cache"] = cache.describe()
        return payload

    # -- content -----------------------------------------------------------
    def timeline_primary(self, probe: dict, tid: str) -> dict:
        for entry in probe.get("timelines", []):
            if str(entry.get("id")).upper() == str(tid).upper():
                return entry
        raise DecryptError(f"timeline not found in probe: {tid}")

    def content(self, draft_dir: Path, tid: str, probe: dict | None = None,
                cache: DraftCache | None = None, force: bool = False) -> tuple[dict, dict]:
        """Return ``(content dict, meta)`` for one timeline from the fenced cache."""
        root = Path(draft_dir)
        did = draft_id(root)
        cache = cache or self.cache_for(root, did)
        probe = probe or self.probe(root, did, cache=cache)
        entry = self.timeline_primary(probe, tid)
        primary = entry.get("primary")
        if not primary:
            raise DecryptError(f"no primary content file for timeline {tid} in {root.name}")
        path = Path(primary)
        if not path.is_file():
            raise DecryptError(f"primary content file disappeared: {path}")

        raw = self._read(path)
        key, src_sha256 = key_for(path, raw)
        lru_key = f"{did}:{tid}:{key}"
        if not force and lru_key in self._values:
            self._values.move_to_end(lru_key)
            return self._values[lru_key], {"key": key, "cache": "memory", "src": str(path)}

        hit = None if force else cache.get(key)
        if hit is None and cache.location == "draft":
            hit = None if force else self._user_cache(root, did).get(key)
        if hit is not None:
            payload, sidecar = hit
            value = json.loads(payload.decode("utf-8"))
            self._remember(lru_key, value)
            return value, {"key": key, "cache": "disk", "src": str(path), "sidecar": sidecar}

        value, encoding = self._decode(path, raw, key, tid, did, entry, cache)
        sidecar = {
            "src": str(path), "src_sha256": src_sha256, "src_size": len(raw),
            "src_mtime_ns": self._mtime_ns(path), "encoding": encoding,
            "content_id": str(value.get("id") or ""), "did": did, "tid": str(tid),
            "duration_us": int(value.get("duration", 0) or 0),
            "previewer_version": __version__,
            "replicas": [{"path": item.get("path"), "sha256": item.get("sha256"),
                          "role": item.get("role")} for item in entry.get("replicas", [])],
        }
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        written, reason = cache.put(key, payload, sidecar)
        if reason:
            written = self._user_cache(root, did).put(key, payload, sidecar)[0]
        self._remember(lru_key, value)
        index = cache.load_index()
        index[str(tid)] = {"key": key, "primary": str(path), "src_sha256": src_sha256,
                           "encoding": encoding, "duration_us": sidecar["duration_us"],
                           "updated_at": int(time.time())}
        cache.save_index(index)
        self._writes[did] = self._writes.get(did, 0) + 1
        if self._writes[did] % 12 == 0:
            try:
                cache.prune(self.cfg.cache_prune_mb)
            except OSError:
                pass
        return value, {"key": key, "cache": "fresh", "src": str(path), "sidecar": sidecar}

    def _decode(self, path: Path, raw: bytes, key: str, tid: str, did: str,
                entry: dict, cache: DraftCache) -> tuple[dict, str]:
        from ..skill_import import parse_plain_json

        plain = parse_plain_json(raw)
        if plain is not None:
            return plain, "plaintext"
        if self.dll_path is None or not Path(self.dll_path).is_file():
            raise DecryptError(
                f"{path.name} is encrypted and no videoeditor.dll is available. "
                "Set JIANYING_VIDEOEDITOR_DLL to an exact path.")
        job = {"kind": "content", "job_id": f"{did}-{tid}-{key[:8]}", "src": str(path), "key": key,
               "expect_id": str(tid)}
        ack = self._single_pass(job)
        if not ack or not ack.get("ok"):
            raise DecryptError(f"decrypt failed for {path}: {(ack or {}).get('error', 'no ack')}")
        staged = Path(ack["staged"])
        try:
            value = json.loads(staged.read_bytes().decode("utf-8-sig"))
        finally:
            staged.unlink(missing_ok=True)
        return value, "jianying-dll"

    def _remember(self, key: str, value: dict) -> None:
        self._values[key] = value
        self._values.move_to_end(key)
        while len(self._values) > 6:
            self._values.popitem(last=False)

    @staticmethod
    def _mtime_ns(path: Path) -> int:
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return 0

    @staticmethod
    def _read(path: Path) -> bytes:
        last: Exception | None = None
        for _ in range(3):
            try:
                with open(path, "rb") as handle:
                    return handle.read()
            except OSError as exc:
                last = exc
                time.sleep(0.05)
        raise DecryptError(f"cannot read {path}: {last}")

    # -- helpers for callers ----------------------------------------------
    def mirror_drift(self, probe: dict) -> dict[str, Any]:
        """Root ``draft_content.json`` is a mirror; report when it is not the active one."""
        root_id = None
        for entry in probe.get("timelines", []):
            for replica in entry.get("replicas", []):
                if replica.get("relative_path") == "draft_content.json":
                    root_id = str(entry.get("id"))
        active = probe.get("active_timeline_id")
        root_path = Path(str(probe.get("root", ""))) / "draft_content.json"
        if not root_path.is_file() or len(probe.get("timelines", [])) < 2:
            return {"present": root_path.is_file(), "drift": False, "root_timeline_id": root_id,
                    "active_timeline_id": active}
        root_sha = hashlib.sha256(self._read(root_path)).hexdigest()
        matching = [str(entry["id"]) for entry in probe.get("timelines", [])
                    for replica in entry.get("replicas", [])
                    if replica.get("path") and normalize(replica["path"]) == normalize(root_path)]
        return {
            "present": True,
            "root_timeline_id": matching[0] if matching else root_id,
            "active_timeline_id": active,
            "root_sha256": root_sha,
            "drift": bool(active and matching and matching[0].upper() != str(active).upper()),
        }
