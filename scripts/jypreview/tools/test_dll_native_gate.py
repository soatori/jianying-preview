"""Native DLL preview capability gate (plan Task 1).

Runs the isolated MSVC x64 host over IPC v1 and proves, or disproves, the two
native render paths before any backend work starts:

* ``playerwin``        — 100 random requests across the active YASHIDA timeline
* ``frame-reader-compositor`` — 100 scattered source times on ``C0308.MP4``
  plus 3 s of consecutive frames (only attempted when PlayerWin did not pass)

Fail-closed startup checks (hash / version / dependency / initialization) must
return explicit errors: no crash, no preview, no fallback to another renderer.

Usage (from ``scripts/``)::

    python -X utf8 -m jypreview.tools.test_dll_native_gate
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_DIR = REPO_ROOT / "temp" / "dll-native-preview"

HOST_EXE = Path(
    os.environ.get(
        "JY_PREVIEW_HOST",
        str(REPO_ROOT / "scripts" / "jypreview" / "native" / "bin" / "x64" / "Release" / "preview_host.exe"),
    )
)

INSTALL_DIR = Path(os.environ.get("JY_PREVIEW_INSTALL_DIR", r"D:\Program Files\JianyingPro\11.5.3.14501"))
DLL_NAME = "videoeditor.dll"
EXPECTED_VERSION = os.environ.get("JY_PREVIEW_EXPECTED_VERSION", "11.5.3.14501")
EXPECTED_SHA256 = os.environ.get(
    "JY_PREVIEW_EXPECTED_SHA256",
    "E5E4020BD5B37EB19968473E19D7246CA5EFE80064A039136341A27B1FD5D8B7",
)

FRAME_RATE = 30.0
FRAME_US = int(1_000_000 / FRAME_RATE)
RANDOM_SEED = int(os.environ.get("JY_PREVIEW_GATE_SEED", "20261005"))
FRAME_SAMPLES = 100
CONTINUOUS_SECONDS = 3
CONTINUOUS_FRAME_US = FRAME_US

PROTOCOL_VERSION = 1


def _candidate_test_packs() -> list[Path]:
    env_pack = os.environ.get("JY_PREVIEW_TEST_PACK")
    out: list[Path] = [Path(env_pack)] if env_pack else []
    out.extend(
        [
            REPO_ROOT / "test" / "YASHIDA 9月24日-草稿完整包-压缩版" / "YASHIDA 9月24日-草稿完整包-压缩版",
            Path(r"E:\Develop\jianying-preview\test\YASHIDA 9月24日-草稿完整包-压缩版\YASHIDA 9月24日-草稿完整包-压缩版"),
            Path(r"E:\Develop\jianying-preview\temp\real-project-test\relocated-project"),
        ]
    )
    return out


def find_draft_root() -> Path:
    env_draft = os.environ.get("JY_PREVIEW_TEST_DRAFT_ROOT")
    if env_draft:
        return Path(env_draft)
    for pack in _candidate_test_packs():
        for candidate in (pack / "工程草稿" / "YASHIDA 9月24日", pack / "YASHIDA 9月24日"):
            if (candidate / "draft_content.json").is_file():
                return candidate
    raise FileNotFoundError(
        "YASHIDA draft root not found; set JY_PREVIEW_TEST_DRAFT_ROOT or JY_PREVIEW_TEST_PACK"
    )


def find_source_path() -> Path:
    env_source = os.environ.get("JY_PREVIEW_TEST_SOURCE")
    if env_source:
        return Path(env_source)
    for pack in _candidate_test_packs():
        candidate = pack / "外置素材" / "Z" / "YASHIDA" / "2026.4.17" / "相机" / "C0308.MP4"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("C0308.MP4 not found; set JY_PREVIEW_TEST_SOURCE")


def find_export_path() -> Path | None:
    env_export = os.environ.get("JY_PREVIEW_TEST_EXPORT")
    if env_export:
        return Path(env_export)
    for pack in _candidate_test_packs():
        for candidate in pack.glob("*.mp4"):
            return candidate
    return None


class GateUnavailable(AssertionError):
    """Raised when the gate cannot be evaluated (host/binary/inputs missing)."""


def _require_host() -> Path:
    if not HOST_EXE.is_file():
        raise GateUnavailable(
            f"preview host binary missing: {HOST_EXE} "
            "(msbuild scripts/jypreview/native/preview_host.vcxproj /p:Configuration=Release /p:Platform=x64)"
        )
    return HOST_EXE


def _require_draft_root() -> Path:
    try:
        return find_draft_root()
    except FileNotFoundError as exc:
        raise GateUnavailable(str(exc)) from exc


class HostError(AssertionError):
    def __init__(self, code: str, message: str, detail: object = None):
        super().__init__(f"host error {code}: {message} detail={detail!r}")
        self.code = code
        self.message = message
        self.detail = detail


class PreviewHost:
    """IPC v1 client: 4-byte LE metadata length + UTF-8 JSON (+ RGBA bytes)."""

    def __init__(self, *, install_dir: Path = INSTALL_DIR, expect_version: str = EXPECTED_VERSION,
                 expect_sha256: str = EXPECTED_SHA256, label: str = "host"):
        self.proc = subprocess.Popen(
            [
                str(_require_host()),
                "--install-dir", str(install_dir),
                "--expect-version", expect_version,
                "--expect-sha256", expect_sha256,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.label = label
        self._request_id = 0
        self.generation = 0
        self.stderr_tail = ""

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                self.proc.kill()
        if self.proc.stderr is not None:
            data = self.proc.stderr.read() or b""
            self.stderr_tail = data.decode("utf-8", "replace")[-4000:]

    def __enter__(self) -> PreviewHost:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _read_exact(self, size: int, deadline: float | None = None) -> bytes:
        assert self.proc.stdout is not None
        stream = self.proc.stdout
        result: dict = {"data": None, "error": None}

        def worker() -> None:
            try:
                result["data"] = stream.read(size)
            except Exception as exc:  # noqa: BLE001
                result["error"] = exc

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(None if deadline is None else max(0.0, deadline - time.monotonic()))
        if thread.is_alive():
            # The host is wedged inside the DLL; kill it so later requests fail
            # fast instead of stacking more timeouts.
            with contextlib.suppress(Exception):
                self.proc.kill()
            raise HostError(
                "request_timeout",
                f"{self.label}: no response for op read of {size} bytes before the deadline",
                self._exit_info(),
            )
        if result["error"]:
            raise HostError("host_read_error", f"{self.label}: {result['error']}", self._exit_info())
        data = result["data"] or b""
        if len(data) < size:
            raise HostError(
                "host_exited",
                f"{self.label}: host closed stdout after {len(data)}/{size} bytes",
                self._exit_info(),
            )
        return data

    def _exit_info(self) -> dict:
        return {"returncode": self.proc.poll(), "stderr": self.stderr_tail}

    def request(self, op: str, payload: dict, generation: int = 0, timeout: float = 120.0) -> tuple[dict, bytes]:
        self._request_id += 1
        request_id = self._request_id
        message = {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request_id,
            "generation": generation,
            "op": op,
            "payload": payload,
        }
        raw = json.dumps(message, ensure_ascii=False).encode("utf-8")
        assert self.proc.stdin is not None and self.proc.stdout is not None
        deadline = time.monotonic() + timeout
        self.proc.stdin.write(struct.pack("<I", len(raw)) + raw)
        self.proc.stdin.flush()
        header = self._read_exact(4, deadline)
        (meta_len,) = struct.unpack("<I", header)
        if meta_len > 16 * 1024 * 1024:
            raise HostError("bad_frame_metadata", f"{self.label}: metadata length {meta_len} too large")
        meta = json.loads(self._read_exact(meta_len, deadline).decode("utf-8"))
        if meta.get("protocol_version") != PROTOCOL_VERSION:
            raise HostError("bad_protocol_version", f"{self.label}: {meta!r}")
        if str(meta.get("request_id")) != str(request_id):
            raise HostError("request_id_mismatch", f"{self.label}: expected {request_id} got {meta.get('request_id')}")
        body = b""
        byte_length = int(meta.get("byte_length") or 0)
        if byte_length:
            body = self._read_exact(byte_length, deadline)
        if not meta.get("ok"):
            error = meta.get("error") or {}
            raise HostError(error.get("code", "unknown"), error.get("message", ""), error.get("detail"))
        return meta, body

    def alive(self) -> bool:
        return self.proc.poll() is None


def _write_artifact(name: str, data: object) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACT_DIR / name
    if isinstance(data, (dict, list)):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    else:
        path.write_text(str(data), encoding="utf-8")


class NativeGateTest(unittest.TestCase):
    maxDiff = None

    # -- fail-closed startup checks -------------------------------------
    def test_wrong_dll_hash_fails_closed(self) -> None:
        _require_host()  # raises GateUnavailable (a failing assertion) if the host is missing
        with PreviewHost(expect_sha256="0" * 64, label="wrong-hash") as host:
            with self.assertRaises(HostError) as ctx:
                host.request("open", {"render_path": "playerwin"})
            self.assertEqual(ctx.exception.code, "dll_hash_mismatch")
            detail = ctx.exception.detail if isinstance(ctx.exception.detail, dict) else {}
            self.assertFalse(detail.get("dll_loaded"), "the DLL must not be loaded on a hash mismatch")
            self.assertTrue(host.alive(), "host must stay alive")
            _write_artifact("gate-wrong-hash.json", {
                "code": ctx.exception.code, "detail": detail, "stderr": host.stderr_tail,
            })

    def test_wrong_version_fails_closed(self) -> None:
        _require_host()  # raises GateUnavailable (a failing assertion) if the host is missing
        with PreviewHost(expect_version=".".join(["0"] * 4), label="wrong-version") as host:
            with self.assertRaises(HostError) as ctx:
                host.request("open", {"render_path": "playerwin"})
            self.assertEqual(ctx.exception.code, "version_mismatch")
            detail = ctx.exception.detail if isinstance(ctx.exception.detail, dict) else {}
            self.assertFalse(detail.get("dll_loaded"), "the DLL must not be loaded on a version mismatch")
            self.assertTrue(host.alive())
            _write_artifact("gate-wrong-version.json", {
                "code": ctx.exception.code, "detail": detail, "stderr": host.stderr_tail,
            })

    def test_missing_dependency_fails_closed(self) -> None:
        _require_host()  # raises GateUnavailable (a failing assertion) if the host is missing
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        stub_dir = ARTIFACT_DIR / "dependency-stub" / EXPECTED_VERSION
        if stub_dir.is_dir():
            shutil.rmtree(stub_dir, ignore_errors=True)
        stub_dir.mkdir(parents=True)
        shutil.copy2(INSTALL_DIR / DLL_NAME, stub_dir / DLL_NAME)
        try:
            with PreviewHost(install_dir=stub_dir, label="missing-dep") as host:
                with self.assertRaises(HostError) as ctx:
                    host.request("open", {"render_path": "playerwin"})
                self.assertIn(
                    ctx.exception.code,
                    {"dependency_missing", "dll_load_failed"},
                    f"expected an explicit load/dependency failure, got {ctx.exception.code}",
                )
                self.assertTrue(host.alive(), "host must not crash on a missing dependency")
                _write_artifact("gate-missing-dependency.json", {
                    "code": ctx.exception.code,
                    "detail": ctx.exception.detail,
                    "stderr": host.stderr_tail,
                })
                # no frame can come back from a host that never loaded the DLL
                with self.assertRaises(HostError):
                    host.request("render_at", {"t_us": 0}, generation=1)
        finally:
            shutil.rmtree(stub_dir.parent, ignore_errors=True)

    def test_initialization_rejected_fails_closed(self) -> None:
        _require_host()  # raises GateUnavailable (a failing assertion) if the host is missing
        draft_root = _require_draft_root()
        with PreviewHost(label="init-rejected") as host:
            with self.assertRaises(HostError) as ctx:
                host.request(
                    "open",
                    {
                        "render_path": "playerwin",
                        "draft_root": str(draft_root),
                        "timeline_id": "00000000-0000-0000-0000-000000000000",
                        "duration_us": 0,
                        "fps": FRAME_RATE,
                    },
                )
            self.assertIn(
                ctx.exception.code,
                {"init_rejected", "timeline_unavailable"},
                f"expected an explicit initialization rejection, got {ctx.exception.code}",
            )
            self.assertTrue(host.alive(), "host must not crash when initialization is rejected")
            detail = ctx.exception.detail or {}
            self.assertNotIn("fallback", json.dumps(detail).lower())
            with self.assertRaises(HostError):
                host.request("render_at", {"t_us": 0}, generation=1)
            _write_artifact("gate-init-rejected.json", {
                "code": ctx.exception.code, "detail": detail, "stderr": host.stderr_tail,
            })

    # -- PlayerWin path -------------------------------------------------
    def test_playerwin_random_timeline_frames(self) -> None:
        _require_host()  # raises GateUnavailable (a failing assertion) if the host is missing
        draft_root = _require_draft_root()
        import random

        rng = random.Random(RANDOM_SEED)
        duration_us = int(os.environ.get("JY_PREVIEW_TEST_DURATION_US", str(54_800_000)))
        times = [rng.randrange(0, max(1, duration_us - FRAME_US)) for _ in range(FRAME_SAMPLES)]
        _write_artifact("gate-playerwin-timeline.json", {
            "draft_root": str(draft_root), "duration_us": duration_us, "samples": times,
        })
        failures: list[dict] = []
        generation = 1
        with PreviewHost(label="playerwin") as host:
            try:
                host.request(
                    "open",
                    {
                        "render_path": "playerwin",
                        "draft_root": str(draft_root),
                        "timeline_id": os.environ.get(
                            "JY_PREVIEW_TEST_TIMELINE_ID", "03B09C7D-44B6-4845-B509-E2801B198852"
                        ),
                        "duration_us": duration_us,
                        "fps": FRAME_RATE,
                    },
                    generation=generation,
                )
            except HostError as exc:
                failures.append({"stage": "open", "code": exc.code, "message": exc.message, "detail": exc.detail})
                _write_artifact("gate-playerwin-failure.json", {
                    "passed": False, "failures": failures, "stderr": host.stderr_tail,
                })
                self.fail(f"PlayerWin open failed: {exc.code}: {exc.message} detail={exc.detail!r}")
            for index, t_us in enumerate(times):
                try:
                    meta, body = host.request("render_at", {"t_us": t_us}, generation=generation, timeout=180.0)
                except HostError as exc:
                    failures.append({"stage": "render_at", "index": index, "t_us": t_us,
                                     "code": exc.code, "message": exc.message})
                    continue
                problem = _frame_problem(meta, body, generation, t_us)
                if problem:
                    failures.append({"stage": "frame", "index": index, "t_us": t_us, "problem": problem})
        if failures:
            _write_artifact("gate-playerwin-failure.json", {
                "passed": False, "checked": len(times), "failures": failures,
            })
            self.fail(
                f"PlayerWin gate failed: {len(failures)}/{len(times)} bad requests; "
                f"first={failures[0]!r}"
            )
        _write_artifact("gate-playerwin-result.json", {"passed": True, "checked": len(times)})
        self.assertTrue(True)

    # -- FrameReader path ----------------------------------------------
    def test_framereader_random_source_frames(self) -> None:
        if os.environ.get("JY_PREVIEW_PLAYERWIN_PASSED") == "1":
            self.skipTest("PlayerWin path passed; FrameReader gate only runs when it does not")
        _require_host()  # raises GateUnavailable (a failing assertion) if the host is missing
        source_path = find_source_path()
        import random

        rng = random.Random(RANDOM_SEED + 1)
        source_duration_us = int(os.environ.get("JY_PREVIEW_TEST_SOURCE_DURATION_US", str(55_000_000)))
        times = [rng.randrange(0, max(1, source_duration_us - FRAME_US)) for _ in range(FRAME_SAMPLES)]
        continuous_start = 200_000_000
        continuous = [continuous_start + i * CONTINUOUS_FRAME_US
                      for i in range(int(CONTINUOUS_SECONDS * FRAME_RATE))]
        _write_artifact("gate-framereader-plan.json", {
            "source": str(source_path), "samples": times, "continuous": continuous,
        })
        failures: list[dict] = []
        generation = 2
        with PreviewHost(label="framereader") as host:
            try:
                host.request(
                    "open",
                    {
                        "render_path": "frame-reader-compositor",
                        "source_path": str(source_path),
                        "fps": FRAME_RATE,
                    },
                    generation=generation,
                )
            except HostError as exc:
                failures.append({"stage": "open", "code": exc.code, "message": exc.message, "detail": exc.detail})
                _write_artifact("gate-framereader-failure.json", {
                    "passed": False, "failures": failures, "stderr": host.stderr_tail,
                })
                self.fail(f"FrameReader open failed: {exc.code}: {exc.message} detail={exc.detail!r}")
            for index, t_us in enumerate(times + continuous):
                try:
                    meta, body = host.request("render_at", {"t_us": t_us}, generation=generation, timeout=180.0)
                except HostError as exc:
                    failures.append({"stage": "render_at", "index": index, "t_us": t_us,
                                     "code": exc.code, "message": exc.message})
                    if exc.code in {"request_timeout", "host_exited", "host_read_error"}:
                        _write_artifact("gate-framereader-progress.json", {
                            "done": index + 1, "total": len(times) + len(continuous),
                            "failures": len(failures), "aborted": exc.code,
                        })
                        break
                    continue
                problem = _frame_problem(meta, body, generation, t_us)
                if problem:
                    failures.append({"stage": "frame", "index": index, "t_us": t_us, "problem": problem})
                if (index + 1) % 10 == 0:
                    _write_artifact("gate-framereader-progress.json", {
                        "done": index + 1, "total": len(times) + len(continuous),
                        "failures": len(failures), "aborted": None,
                    })
        if failures:
            _write_artifact("gate-framereader-failure.json", {
                "passed": False, "checked": len(times) + len(continuous), "failures": failures,
            })
            self.fail(
                f"FrameReader gate failed: {len(failures)}/{len(times) + len(continuous)} bad requests; "
                f"first={failures[0]!r}"
            )
        _write_artifact("gate-framereader-result.json", {
            "passed": True, "random": len(times), "continuous": len(continuous),
        })
        self.assertTrue(True)


def _frame_problem(meta: dict, body: bytes, generation: int, requested_us: int) -> str | None:
    if meta.get("generation") != generation:
        return f"generation {meta.get('generation')} != {generation}"
    width = int(meta.get("width") or 0)
    height = int(meta.get("height") or 0)
    if meta.get("format") != "RGBA":
        return f"format {meta.get('format')!r} != 'RGBA'"
    if width <= 0 or height <= 0:
        return f"bad geometry {width}x{height}"
    expected = width * height * 4
    if len(body) != expected or int(meta.get("byte_length") or -1) != expected:
        return f"byte_length {len(body)} != {expected}"
    if not body:
        return "empty frame"
    if len(set(body[:4096])) == 1:
        return "frame body looks uniform/blank in first 4 KiB"
    pts_us = meta.get("pts_us")
    if not isinstance(pts_us, int):
        return f"pts_us missing/not int: {pts_us!r}"
    if abs(pts_us - requested_us) > FRAME_US:
        return f"pts deviation {abs(pts_us - requested_us)} us > one frame ({FRAME_US} us)"
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.time()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(NativeGateTest)
    result = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(suite)
    report = {
        "host": str(HOST_EXE),
        "host_exists": HOST_EXE.is_file(),
        "install_dir": str(INSTALL_DIR),
        "dll_sha256": _sha256(INSTALL_DIR / DLL_NAME) if (INSTALL_DIR / DLL_NAME).is_file() else None,
        "dll_sha256_expected": EXPECTED_SHA256,
        "tests_run": result.testsRun,
        "failures": [str(f[0]) for f in result.failures],
        "errors": [str(e[0]) for e in result.errors],
        "skipped": [str(s[0]) for s in result.skipped],
        "elapsed_s": round(time.time() - started, 3),
    }
    _write_artifact("gate-run.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
