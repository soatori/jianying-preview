"""Native DLL preview capability gate (plan Task 1).

Runs the isolated MSVC x64 host over IPC v1 and checks both native paths before
any backend work starts:

* ``playerwin`` — fail closed until a legal initializer, project-open path, and
  frame-output call are evidenced; 100 timeline requests run only if open passes
* ``frame-reader-compositor`` — 100 scattered times on ``C0308.MP4`` plus 90
  in-range preview requests at 30 fps across 3 seconds (only if PlayerWin fails)

Fail-closed startup checks (hash / version / dependency / initialization) must
return explicit errors: no crash, no preview, no fallback to another renderer.

The FrameReader gate validates pixels independently of PTS: every returned
RGBA body is SHA-256'd and compared against the FFmpeg reference frame hashes
(``temp/native-probe/refs/hashes.txt``), which are used *only* as a test
reference — never as a runtime fallback.

Usage (from ``scripts/``)::

    python -X utf8 -m jypreview.tools.test_dll_native_gate
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import random
import shutil
import struct
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
# New runs write to their own directory so pre-existing evidence under
# temp/dll-native-preview/ is never overwritten.
ARTIFACT_DIR = Path(
    os.environ.get("JY_PREVIEW_ARTIFACT_DIR", str(REPO_ROOT / "temp" / "dll-native-preview-gatefix"))
)

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

# Timeline (PlayerWin path) sampling: the YASHIDA 成片 timeline, 30 fps.
FRAME_RATE = 30.0
FRAME_US = int(1_000_000 / FRAME_RATE)
RANDOM_SEED = int(os.environ.get("JY_PREVIEW_GATE_SEED", "20261005"))
FRAME_SAMPLES = 100

# C0308.MP4 source facts (measured, see temp/dll-native-preview/evidence.md):
# 1920x1080, 60000/1001 fps, 3960 frames, 66.066 s total duration.
SOURCE_FPS_NUM = 60000
SOURCE_FPS_DEN = 1001
SOURCE_FRAME_COUNT = 3960
SOURCE_DURATION_US = 66_066_000  # 3960 frames * 1001/60000 s
SOURCE_FRAME_TOL_US = 16684  # one source frame, matches the host's pts gate
CONTINUOUS_FRAMES = 90

REF_HASHES_PATH = Path(
    os.environ.get(
        "JY_PREVIEW_REF_HASHES",
        str(REPO_ROOT / "temp" / "native-probe" / "refs" / "hashes.txt"),
    )
)

PROTOCOL_VERSION = 1

# Codes after which no further requests can succeed (host dead or wedged).
ABORT_CODES = {"request_timeout", "host_exited", "host_read_error"}


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


def _require_ref_hashes() -> dict[str, int]:
    """FFmpeg reference frame hashes (test reference only, never runtime)."""
    if not REF_HASHES_PATH.is_file():
        raise GateUnavailable(
            f"reference frame hashes missing: {REF_HASHES_PATH} "
            "(regenerate with temp/native-probe/ref_hashes.py; pixel validation is fail-closed)"
        )
    by_hash: dict[str, int] = {}
    with REF_HASHES_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            parts = line.split()
            if len(parts) == 2 and parts[0].isdigit():
                by_hash[parts[1]] = int(parts[0])
    if not by_hash:
        raise GateUnavailable(f"reference frame hashes empty: {REF_HASHES_PATH}")
    return by_hash


class HostError(AssertionError):
    def __init__(self, code: str, message: str, detail: object = None):
        super().__init__(f"host error {code}: {message} detail={detail!r}")
        self.code = code
        self.message = message
        self.detail = detail


class PreviewHost:
    """IPC v1 client: 4-byte LE metadata length + UTF-8 JSON (+ RGBA bytes).

    Child stderr is redirected to a log file, never PIPE: the DLL writes
    banners/log spam to stderr, a PIPE fills up (~64 KiB), the child blocks on
    write, and requests start timing out (observed: PIPE-only run wedged at
    request 52; redirected run completed all 190).
    """

    def __init__(self, *, install_dir: Path = INSTALL_DIR, expect_version: str = EXPECTED_VERSION,
                 expect_sha256: str = EXPECTED_SHA256, label: str = "host"):
        self.label = label
        self._stderr_path = ARTIFACT_DIR / f"host-stderr-{label}.log"
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        stderr_file = open(self._stderr_path, "wb")  # noqa: SIM115 - handed to Popen
        try:
            self.proc = subprocess.Popen(
                [
                    str(_require_host()),
                    "--install-dir", str(install_dir),
                    "--expect-version", expect_version,
                    "--expect-sha256", expect_sha256,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr_file,
            )
        finally:
            stderr_file.close()
        self._request_id = 0
        self.generation = 0
        self.stderr_tail = ""
        self.last_meta_text = ""

    def _stderr_tail(self) -> str:
        """Current tail of the child's stderr log (bounded, best effort)."""
        try:
            with self._stderr_path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - 4000))
                data = handle.read()
        except OSError:
            return self.stderr_tail
        return data.decode("utf-8", "replace")

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                self.proc.kill()
        for stream in (self.proc.stdin, self.proc.stdout):
            if stream is not None:
                with contextlib.suppress(Exception):
                    stream.close()
        self.stderr_tail = self._stderr_tail()

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
        return {"returncode": self.proc.poll(), "stderr": self._stderr_tail()}

    def request_raw(self, raw: bytes, timeout: float = 120.0) -> tuple[dict, bytes]:
        """Transport only: write a pre-encoded request, read one framed response.

        Split out of request() so a regression can send hand-written JSON with
        a chosen field order; envelope assertions stay in request().
        """
        assert self.proc.stdin is not None and self.proc.stdout is not None
        deadline = time.monotonic() + timeout
        self.proc.stdin.write(struct.pack("<I", len(raw)) + raw)
        self.proc.stdin.flush()
        header = self._read_exact(4, deadline)
        (meta_len,) = struct.unpack("<I", header)
        if meta_len > 16 * 1024 * 1024:
            raise HostError("bad_frame_metadata", f"{self.label}: metadata length {meta_len} too large")
        meta_text = self._read_exact(meta_len, deadline).decode("utf-8")
        self.last_meta_text = meta_text
        meta = json.loads(meta_text)
        body = b""
        byte_length = int(meta.get("byte_length") or 0)
        if byte_length:
            body = self._read_exact(byte_length, deadline)
        return meta, body

    def request(self, op: str, payload: dict, generation: int = 0, timeout: float = 120.0,
                proto: int | None = PROTOCOL_VERSION) -> tuple[dict, bytes]:
        self._request_id += 1
        request_id = self._request_id
        message: dict = {"request_id": request_id, "generation": generation, "op": op, "payload": payload}
        if proto is not None:
            message["protocol_version"] = proto
        raw = json.dumps(message, ensure_ascii=False).encode("utf-8")
        meta, body = self.request_raw(raw, timeout)
        if meta.get("protocol_version") != PROTOCOL_VERSION:
            raise HostError("bad_protocol_version", f"{self.label}: {meta!r}")
        if str(meta.get("request_id")) != str(request_id):
            raise HostError("request_id_mismatch", f"{self.label}: expected {request_id} got {meta.get('request_id')}")
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


def _write_progress_every_ten(name: str, counts: dict) -> None:
    attempted = counts["attempted"]
    if attempted and attempted % 10 == 0:
        _write_artifact(name, {"counts": counts, "at_index": attempted})


# Shared between the two render-path tests: FrameReader only runs when
# PlayerWin did not pass (set by test_playerwin_random_timeline_frames).
_STATE: dict[str, bool | None] = {"playerwin_passed": None}


def _framereader_should_skip() -> bool:
    return _STATE["playerwin_passed"] is True or os.environ.get("JY_PREVIEW_PLAYERWIN_PASSED") == "1"


# ---------------------------------------------------------------------------
# C0308.MP4 time grid (60000/1001 fps) — mirrors the host's mapping.
# ---------------------------------------------------------------------------
def _source_frame_of_time(t_us: int) -> int:
    """Source frame index a request time maps to (host's floor mapping)."""
    return (t_us * SOURCE_FPS_NUM) // (SOURCE_FPS_DEN * 1_000_000)


def _source_request_plan(duration_us: int = SOURCE_DURATION_US) -> tuple[list[int], list[int]]:
    """100 scattered sample times + 90 consecutive frames, all inside duration."""
    rng = random.Random(RANDOM_SEED + 1)
    times = [rng.randrange(0, duration_us) for _ in range(FRAME_SAMPLES)]
    # 3 s of preview cadence: 90 requests 33,333 us apart (30 fps), all inside
    # the source duration; starts at t=0 so the near-zero seek is exercised.
    continuous: list[int] = []
    for i in range(CONTINUOUS_FRAMES):
        t_us = i * FRAME_US
        if t_us >= duration_us:
            break
        continuous.append(t_us)
    return times, continuous


def _pixel_problem(sha_hex: str, expected_frame: int, ref_by_hash: dict[str, int],
                   n_frames: int) -> str | None:
    """Independent pixel check: does this RGBA body decode to the wanted frame?"""
    match = ref_by_hash.get(sha_hex)
    if match is None:
        decoded = f"pixel sha256 {sha_hex} matches no reference frame"
    else:
        decoded = (f"pixels decode to source frame {match} "
                   f"({match * SOURCE_FPS_DEN / SOURCE_FPS_NUM / 1000:.3f} s)")
    if expected_frame < 0 or expected_frame >= n_frames:
        return (f"requested frame {expected_frame} outside reference range "
                f"0..{n_frames - 1}; {decoded}")
    if match == expected_frame:
        return None
    if match is None:
        return f"{decoded}; expected source frame {expected_frame}"
    return (
        f"{decoded} but source frame {expected_frame} "
        f"({expected_frame * SOURCE_FPS_DEN / SOURCE_FPS_NUM / 1000:.3f} s) was requested "
        f"(sha256 {sha_hex})"
    )


def _frame_problem(meta: dict, body: bytes, generation: int, requested_us: int,
                   *, ref: dict[str, int] | None = None, tol_us: int = FRAME_US) -> str | None:
    """Validate a returned frame: geometry, generation, PTS, then pixels.

    ``ref`` (when given) is the FFmpeg reference hash map and enables the
    independent pixel check — PTS alone is insufficient: a request answered
    with a plausible pts_us carried pixels from a different source time
    (request 200233331 -> pts 200200000, pixels of frame 3750).
    """
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
    if pts_us < 0:
        return f"negative pts_us: {pts_us}"
    if abs(pts_us - requested_us) > tol_us:
        return f"pts deviation {abs(pts_us - requested_us)} us > one frame ({tol_us} us)"
    if ref is not None:
        problem = _pixel_problem(
            hashlib.sha256(body).hexdigest(),
            _source_frame_of_time(requested_us),
            ref,
            max(ref.values()) + 1 if ref else 0,
        )
        if problem:
            return problem
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_hash(root: Path) -> tuple[str, int]:
    """Deterministic SHA-256 over the sorted relative-path + content-hash tree."""
    digest = hashlib.sha256()
    files = sorted(p for p in root.rglob("*") if p.is_file())
    for path in files:
        digest.update(str(path.relative_to(root)).replace("\\", "/").encode("utf-8"))
        digest.update(b"\t")
        digest.update(_sha256(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest(), len(files)


def _input_hashes() -> dict:
    """Before/after snapshot inputs: real MP4 and draft tree (read-only)."""
    out: dict = {
        "source_path": None,
        "source_sha256": None,
        "draft_root": None,
        "draft_tree_sha256": None,
        "draft_tree_files": None,
    }
    try:
        source = find_source_path()
        out["source_path"] = str(source)
        out["source_sha256"] = _sha256(source)
    except FileNotFoundError:
        pass
    try:
        root = find_draft_root()
        tree_sha, n_files = _tree_hash(root)
        out["draft_root"] = str(root)
        out["draft_tree_sha256"] = tree_sha
        out["draft_tree_files"] = n_files
    except FileNotFoundError:
        pass
    return out


SELF_TEST_ORDER = [
    "test_close_terminates_host_after_response",
    "test_envelope_ignores_nested_payload_fields",
    "test_envelope_rejects_missing_and_duplicate_fields",
    "test_failed_open_switch_clears_reader_state",
    "test_frame_problem_rejects_negative_and_missing_pts",
    "test_payload_accepts_valid_json_values",
    "test_payload_rejects_bad_escapes_and_control_chars",
    "test_payload_rejects_duplicate_fields",
    "test_payload_rejects_malformed_json_before_close",
    "test_pixel_validation_catches_wrong_pixels_with_valid_pts",
    "test_pixel_validation_identifies_real_repro_mismatch",
    "test_ping_has_single_protocol_version",
    "test_progress_snapshot_updates_for_host_errors",
    "test_previewhost_stderr_is_redirected",
    "test_protocol_version_rejected_by_host",
    "test_source_request_plan_inside_real_duration",
    "test_suite_runs_playerwin_before_framereader",
]

GATE_TEST_ORDER = [
    "test_wrong_dll_hash_fails_closed",
    "test_wrong_version_fails_closed",
    "test_missing_dependency_fails_closed",
    "test_initialization_rejected_fails_closed",
    "test_playerwin_open_blocked_without_fabricated_calls",
    "test_playerwin_random_timeline_frames",
    "test_framereader_random_source_frames",
]


def build_suite() -> unittest.TestSuite:
    """Gate self-tests first (cheap), then the fail-closed checks, then
    PlayerWin before FrameReader — the FrameReader scan must only run when
    PlayerWin did not pass."""
    suite = unittest.TestSuite()
    for name in SELF_TEST_ORDER:
        suite.addTest(GateSelfTest(name))
    for name in GATE_TEST_ORDER:
        suite.addTest(NativeGateTest(name))
    return suite


class GateSelfTest(unittest.TestCase):
    """Regression tests for the gate's own findings (no full scan needed)."""

    maxDiff = None

    def test_source_request_plan_inside_real_duration(self) -> None:
        times, continuous = _source_request_plan()
        self.assertEqual(len(times), FRAME_SAMPLES, "100 scattered samples required")
        self.assertTrue(
            all(0 <= t < SOURCE_DURATION_US for t in times),
            f"every sample must be inside the real 66.066 s duration, got max={max(times)}",
        )
        self.assertEqual(len(continuous), CONTINUOUS_FRAMES, "90 continuous frames required")
        self.assertTrue(
            all(0 <= t < SOURCE_DURATION_US for t in continuous),
            f"every continuous frame must be inside 66.066 s, got max={max(continuous)}",
        )
        self.assertEqual(
            [b - a for a, b in zip(continuous, continuous[1:], strict=False)],
            [FRAME_US] * (CONTINUOUS_FRAMES - 1),
            "continuous requests must be 33,333 us apart (30 fps preview cadence)",
        )
        self.assertGreaterEqual(
            continuous[-1] - continuous[0], 2_900_000,
            "the continuous segment must span ~3 seconds",
        )
        self.assertEqual(continuous[0], 0, "the near-zero seek must be exercised")
        # expected source frame (59.94 fps) advances by ~2 per preview request
        mapped = [_source_frame_of_time(t) for t in continuous]
        self.assertTrue(
            all(1 <= b - a <= 2 for a, b in zip(mapped, mapped[1:], strict=False)),
            f"expected source frames must advance ~2 per request, got {mapped[:8]}",
        )

    def test_frame_problem_rejects_negative_and_missing_pts(self) -> None:
        body = bytes(range(16)) * 4  # non-uniform 4x4 RGBA payload
        base = {"generation": 1, "format": "RGBA", "width": 4, "height": 4, "byte_length": len(body)}
        negative = dict(base, pts_us=-1)
        self.assertIsNotNone(
            _frame_problem(negative, body, 1, 0),
            "a negative pts_us must be rejected (stale/near-zero seek guard)",
        )
        missing = dict(base)
        self.assertIsNotNone(_frame_problem(missing, body, 1, 0), "missing pts_us must be rejected")

    def test_payload_accepts_valid_json_values(self) -> None:
        """Guard for the strictness fix: legal primitives, escapes and nested
        structures inside `payload` must still be served, and a consumed
        string field must see the *decoded* value."""
        _require_host()
        with PreviewHost(label="payload-valid") as host:
            raw = (
                b'{"protocol_version":1,"request_id":9,"generation":1,"op":"ping",'
                b'"payload":{"t":true,"f":false,"n":null,"i":0,"neg":-12.5e2,'
                b'"esc":"\\u76f8\\u673a","nested":{"deep":[1,{"x":"y"}]},"empty":{}}}'
            )
            meta, _ = host.request_raw(raw)
            self.assertTrue(meta.get("ok"), f"a legal payload must be served: {meta}")
            self.assertEqual(meta.get("op"), "ping")
            self.assertTrue(host.alive())

            # A \u escape in a *consumed* payload field must decode: render_path
            # \u0066oo -> "foo" is then reported as the unknown render_path.
            raw = (
                b'{"protocol_version":1,"request_id":10,"generation":1,"op":"open",'
                b'"payload":{"render_path":"\\u0066oo"}}'
            )
            meta, _ = host.request_raw(raw)
            self.assertFalse(meta.get("ok"), "an unknown render_path is still an error")
            error = meta.get("error") or {}
            self.assertEqual(error.get("code"), "bad_request")
            self.assertIn("render_path", str(error.get("message", "")))
            self.assertEqual(
                (error.get("detail") or {}).get("reason"),
                "foo",
                "the \\u0066 escape must decode to 'f' inside the consumed field",
            )
            self.assertTrue(host.alive())
            meta, _ = host.request("ping", {})
            self.assertTrue(meta.get("ok"), "the host must stay usable")

    def test_payload_rejects_bad_escapes_and_control_chars(self) -> None:
        """Regression: payload strings obey RFC 8259 — an unknown escape or a
        raw control character rejects the request instead of silently
        corrupting the value, and no op is dispatched from such a document."""
        _require_host()
        with PreviewHost(label="payload-escapes") as host:
            cases = {
                "unknown escape in payload": (
                    b'{"protocol_version":1,"request_id":7,"generation":1,"op":"ping",'
                    b'"payload":{"path":"a\\qb"}}'
                ),
                "truncated unicode escape": (
                    b'{"protocol_version":1,"request_id":7,"generation":1,"op":"ping",'
                    b'"payload":{"path":"\\u12"}}'
                ),
                "raw control char in payload": (
                    b'{"protocol_version":1,"request_id":7,"generation":1,"op":"ping",'
                    b'"payload":{"path":"a\x01b"}}'
                ),
                "unknown escape in envelope op": (
                    b'{"protocol_version":1,"request_id":7,"generation":1,"op":"pin\\xg",'
                    b'"payload":{}}'
                ),
                "raw control char in envelope op": (
                    b'{"protocol_version":1,"request_id":7,"generation":1,"op":"pi\x01ng",'
                    b'"payload":{}}'
                ),
            }
            for label, raw in cases.items():
                with self.subTest(case=label):
                    meta, _ = host.request_raw(raw)
                    self.assertFalse(meta.get("ok"), f"{label}: a malformed string must be rejected")
                    self.assertEqual((meta.get("error") or {}).get("code"), "bad_request", label)
                    self.assertEqual(
                        meta.get("op"),
                        "",
                        f"{label}: an unparsable document must not echo/dispatch an op",
                    )
                    self.assertTrue(host.alive(), f"{label}: the host must survive")
                    meta, _ = host.request("ping", {})
                    self.assertTrue(meta.get("ok"), f"{label}: the host must stay usable")

    def test_payload_rejects_duplicate_fields(self) -> None:
        """Regression: a consumed payload field must appear once — duplicates
        are rejected instead of resolving to whichever came first."""
        _require_host()
        with PreviewHost(label="payload-dup") as host:
            cases = {
                "render_path": (
                    b'{"protocol_version":1,"request_id":8,"generation":1,"op":"open",'
                    b'"payload":{"render_path":"playerwin",'
                    b'"render_path":"frame-reader-compositor"}}'
                ),
                "t_us": (
                    b'{"protocol_version":1,"request_id":8,"generation":1,"op":"render_at",'
                    b'"payload":{"t_us":1,"t_us":2}}'
                ),
            }
            for field, raw in cases.items():
                with self.subTest(duplicated_field=field):
                    meta, _ = host.request_raw(raw)
                    self.assertFalse(meta.get("ok"), f"{field}: duplicates must be rejected")
                    message = str((meta.get("error") or {}).get("message", ""))
                    self.assertEqual((meta.get("error") or {}).get("code"), "bad_request", field)
                    self.assertIn("duplicate payload field", message, field)
                    self.assertIn(field, message, field)
                    self.assertTrue(host.alive(), f"{field}: the host must survive")
                    meta, _ = host.request("ping", {})
                    self.assertTrue(meta.get("ok"), f"{field}: the host must stay usable")

    def test_payload_rejects_malformed_json_before_close(self) -> None:
        """Regression: `payload` must be valid JSON, not merely brace-balanced.

        Each case uses `op:"close"`, so a parser that accepts the payload would
        close the host — it must answer bad_request, dispatch nothing, stay
        alive and keep serving pings.
        """
        _require_host()
        with PreviewHost(label="payload-malformed") as host:
            cases = {
                "bare word literal": (
                    b'{"protocol_version":1,"request_id":6,"generation":1,'
                    b'"op":"close","payload":{"ignored":not_json}}'
                ),
                "NaN in array": (
                    b'{"protocol_version":1,"request_id":6,"generation":1,'
                    b'"op":"close","payload":{"a":[1,2,{"b":NaN}]}}'
                ),
                "hex literal nested in object": (
                    b'{"protocol_version":1,"request_id":6,"generation":1,'
                    b'"op":"close","payload":{"a":{"b":0x10}}}'
                ),
                "trailing garbage after a value": (
                    b'{"protocol_version":1,"request_id":6,"generation":1,'
                    b'"op":"close","payload":{"a":1 2}}'
                ),
                "missing value": (
                    b'{"protocol_version":1,"request_id":6,"generation":1,'
                    b'"op":"close","payload":{"a":}}'
                ),
            }
            for label, raw in cases.items():
                with self.subTest(case=label):
                    meta, _ = host.request_raw(raw)
                    self.assertFalse(meta.get("ok"), f"{label}: malformed payload must be rejected")
                    self.assertEqual((meta.get("error") or {}).get("code"), "bad_request", label)
                    self.assertEqual(meta.get("op"), "", f"{label}: close must never be dispatched")
                    self.assertTrue(host.alive(), f"{label}: close must not run")
                    meta, _ = host.request("ping", {})
                    self.assertTrue(meta.get("ok"), f"{label}: the host must stay usable")
                    self.assertTrue(host.alive(), label)

    def test_pixel_validation_catches_wrong_pixels_with_valid_pts(self) -> None:
        # PTS passes (deviation 0), but the pixels belong to frame 3750 —
        # the exact class of false pass found in review (PTS-only checks lied).
        body = bytes(range(16)) * 4
        requested_us = 20_000_000
        expected_frame = _source_frame_of_time(requested_us)
        meta = {"generation": 1, "format": "RGBA", "width": 4, "height": 4,
                "byte_length": len(body), "pts_us": requested_us}
        sha = hashlib.sha256(body).hexdigest()
        wrong_ref = {sha: 3750}
        self.assertIsNotNone(
            _frame_problem(meta, body, 1, requested_us, ref=wrong_ref, tol_us=SOURCE_FRAME_TOL_US),
            "pixels from another source frame must fail even when PTS is perfect",
        )
        right_ref = {sha: expected_frame}
        self.assertIsNone(
            _frame_problem(meta, body, 1, requested_us, ref=right_ref, tol_us=SOURCE_FRAME_TOL_US),
            "matching pixels with matching PTS must pass",
        )

    def test_pixel_validation_identifies_real_repro_mismatch(self) -> None:
        # Review reproduction: request 200233331 returned pts 200200000 and
        # passed _frame_problem, but its RGBA SHA-256 is source frame 3750
        # (~62.56 s) — see temp/native-probe/refs/hashes.txt line 3751.
        ref = _require_ref_hashes()
        repro_sha = "9d21694dec355651bda13c63f5ae30381ac8a6b2a2289ae7311f7a2f86040b42"
        self.assertEqual(ref.get(repro_sha), 3750, "reference hash for frame 3750 changed")
        problem = _pixel_problem(repro_sha, 12001, ref, max(ref.values()) + 1)
        self.assertIsNotNone(problem, "the reproduced pixel/PTS mismatch must be rejected")
        self.assertIn("3750", problem or "")

    def test_suite_runs_playerwin_before_framereader(self) -> None:
        self.assertLess(
            GATE_TEST_ORDER.index("test_playerwin_random_timeline_frames"),
            GATE_TEST_ORDER.index("test_framereader_random_source_frames"),
            "PlayerWin must be attempted explicitly before FrameReader",
        )
        self.assertIn("test_playerwin_open_blocked_without_fabricated_calls", GATE_TEST_ORDER)
        # Fail-closed startup checks must stay in the suite.
        for name in ("test_wrong_dll_hash_fails_closed", "test_wrong_version_fails_closed",
                     "test_missing_dependency_fails_closed", "test_initialization_rejected_fails_closed"):
            self.assertIn(name, GATE_TEST_ORDER)
        names = [t._testMethodName for t in build_suite() if isinstance(t, unittest.TestCase)]
        self.assertLess(
            names.index("test_playerwin_random_timeline_frames"),
            names.index("test_framereader_random_source_frames"),
            f"build_suite() must order PlayerWin before FrameReader, got {names}",
        )
        # FrameReader is skipped only when PlayerWin passed.
        _STATE["playerwin_passed"] = True
        try:
            self.assertTrue(_framereader_should_skip())
            _STATE["playerwin_passed"] = False
            self.assertFalse(_framereader_should_skip())
        finally:
            _STATE["playerwin_passed"] = None

    def test_ping_has_single_protocol_version(self) -> None:
        _require_host()
        with PreviewHost(label="ping-proto") as host:
            host.request("ping", {})
            self.assertEqual(
                host.last_meta_text.count('"protocol_version"'), 1,
                f"ping response must carry protocol_version exactly once: {host.last_meta_text}",
            )

    def test_envelope_ignores_nested_payload_fields(self) -> None:
        """Regression: envelope keys are read from the top level only.

        `payload` is deliberately ordered *before* the envelope keys, so a
        depth-blind lookup would see payload.op="close" first and close the
        host on a ping. Reordering the same legal document must not change
        which op runs or which request_id/generation are echoed.
        """
        _require_host()
        with PreviewHost(label="envelope-order") as host:
            payload_first = (
                b'{"payload":{"op":"close","generation":99,"request_id":777,'
                b'"protocol_version":99,"render_path":"playerwin","t_us":123456},'
                b'"protocol_version":1,"generation":3,"request_id":42,"op":"ping"}'
            )
            meta, _ = host.request_raw(payload_first)
            self.assertTrue(meta.get("ok"), f"a well-formed ping must be served: {meta}")
            self.assertEqual(meta.get("op"), "ping", "payload.op must never reach the dispatcher")
            self.assertEqual(str(meta.get("request_id")), "42", "payload.request_id must not win")
            self.assertEqual(meta.get("generation"), 3, "payload.generation must not win")
            self.assertTrue(host.alive(), "payload op=close must not close the host")
            # Still usable afterwards: close really never ran.
            meta, _ = host.request("ping", {})
            self.assertTrue(meta.get("ok"))

            envelope_first = (
                b'{"protocol_version":1,"generation":3,"request_id":42,"op":"ping",'
                b'"payload":{"op":"close","generation":99,"request_id":777}}'
            )
            meta, _ = host.request_raw(envelope_first)
            self.assertTrue(meta.get("ok"), meta)
            self.assertEqual(meta.get("op"), "ping")
            self.assertEqual(str(meta.get("request_id")), "42")
            self.assertEqual(meta.get("generation"), 3)
            self.assertTrue(host.alive())

    def test_envelope_rejects_missing_and_duplicate_fields(self) -> None:
        """Regression: a missing or repeated envelope field is rejected, never
        silently resolved to the first match anywhere in the document.

        Every duplicated field gets its own request: a parser that returns on
        the first duplicate would otherwise mask request_id/generation/op, and
        the duplicated `op` case must prove `close` never executes.
        """
        _require_host()
        with PreviewHost(label="envelope-dup") as host:
            duplicated = {
                "request_id": (
                    b'{"protocol_version":1,"request_id":7,"request_id":8,'
                    b'"generation":1,"op":"ping","payload":{}}'
                ),
                "protocol_version": (
                    b'{"protocol_version":1,"protocol_version":1,'
                    b'"request_id":7,"generation":1,"op":"ping","payload":{}}'
                ),
                "generation": (
                    b'{"protocol_version":1,"request_id":7,"generation":1,'
                    b'"generation":2,"op":"ping","payload":{}}'
                ),
                "op": (
                    b'{"protocol_version":1,"request_id":7,"generation":1,'
                    b'"op":"ping","op":"close","payload":{}}'
                ),
            }
            for field, raw in duplicated.items():
                with self.subTest(duplicated_field=field):
                    meta, _ = host.request_raw(raw)
                    self.assertFalse(meta.get("ok"), f"{field}: a duplicated envelope must be rejected")
                    error = meta.get("error") or {}
                    self.assertEqual(error.get("code"), "bad_request", field)
                    self.assertIn("duplicate", str(error.get("message", "")), field)
                    self.assertTrue(host.alive(), f"{field}: no op may execute from a rejected envelope")
                    meta, _ = host.request("ping", {})
                    self.assertTrue(meta.get("ok"), f"{field}: the host must stay usable")
                    self.assertTrue(host.alive(), field)

            missing = b'{"protocol_version":1,"generation":1,"op":"ping","payload":{}}'
            meta, _ = host.request_raw(missing)
            self.assertFalse(meta.get("ok"), "a missing envelope field must be rejected")
            error = meta.get("error") or {}
            self.assertEqual(error.get("code"), "bad_request")
            self.assertIn("request_id", str(error.get("message", "")))

            no_op = b'{"protocol_version":1,"request_id":9,"generation":1,"payload":{}}'
            meta, _ = host.request_raw(no_op)
            self.assertFalse(meta.get("ok"), "a missing op must be rejected")
            self.assertIn("op", str((meta.get("error") or {}).get("message", "")))

            meta, _ = host.request("ping", {})
            self.assertTrue(meta.get("ok"), "the host must stay usable after rejected envelopes")

    def test_failed_open_switch_clears_reader_state(self) -> None:
        """Regression: a failed path switch must not serve the old source.

        Sequence: open FrameReader (ok) -> open PlayerWin (fail closed) ->
        render_at. After the failed switch no render path may be attached, so
        render_at answers host_not_open instead of reading the previous source.
        """
        _require_host()
        try:
            source = find_source_path()
        except FileNotFoundError as exc:
            raise GateUnavailable(str(exc)) from exc
        with PreviewHost(label="open-switch") as host:
            meta, _ = host.request(
                "open",
                {"render_path": "frame-reader-compositor", "source_path": str(source), "fps": 30},
                generation=1,
            )
            self.assertTrue(meta.get("ok"), f"the frame reader must open first: {meta}")
            # The reader must be attached *before* the switch: render_at either
            # returns a frame or a reader-path error, but never host_not_open.
            try:
                host.request("render_at", {"t_us": 3_000_000}, generation=1, timeout=120)
                pre = "frame"
            except HostError as exc:
                pre = exc.code
            if pre in ABORT_CODES:
                self.skipTest(f"host aborted during the pre-switch render_at ({pre}); native blocker")
            self.assertNotEqual(pre, "host_not_open", "the reader must stay attached after a successful open")

            with self.assertRaises(HostError) as switched:
                host.request(
                    "open",
                    {
                        "render_path": "playerwin",
                        "draft_root": "C:/nonexistent-jypreview-draft",
                        "timeline_id": "00000000-0000-0000-0000-000000000000",
                    },
                    generation=1,
                )
            self.assertEqual(switched.exception.code, "init_rejected")
            self.assertTrue(host.alive(), "a failed switch must not kill the host")

            with self.assertRaises(HostError) as after:
                host.request("render_at", {"t_us": 3_000_000}, generation=1, timeout=120)
            self.assertEqual(
                after.exception.code,
                "host_not_open",
                "a failed path switch must not leave the previous source reachable",
            )
            self.assertTrue(host.alive())
            _write_artifact(
                "gate-open-switch-lifecycle.json",
                {
                    "pre_switch_render": pre,
                    "switch_error": switched.exception.code,
                    "post_switch_render": after.exception.code,
                },
            )

    def test_progress_snapshot_updates_for_host_errors(self) -> None:
        writes: list[tuple[str, object]] = []

        class FailingHost:
            def __init__(self, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return None

            def request(self, op, *_args, **_kwargs):
                if op == "open":
                    return {"ok": True}, b""
                raise HostError("pts_out_of_range", "synthetic progress-test failure")

        name = f"{__name__}."
        patches = (
            mock.patch(name + "_framereader_should_skip", return_value=False),
            mock.patch(name + "_require_host", return_value=HOST_EXE),
            mock.patch(name + "_require_ref_hashes", return_value={}),
            mock.patch(name + "_source_request_plan", return_value=(list(range(10)), [])),
            mock.patch(name + "find_source_path", return_value=Path("C0308.MP4")),
            mock.patch(name + "PreviewHost", FailingHost),
            mock.patch(name + "_write_artifact", side_effect=lambda key, value: writes.append((key, value))),
        )
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
            self.assertRaises(AssertionError),
        ):
            NativeGateTest("test_framereader_random_source_frames").test_framereader_random_source_frames()

        snapshots = [
            value for key, value in writes
            if key == "gate-framereader-progress.json" and isinstance(value, dict)
            and value.get("at_index") == 10
        ]
        self.assertTrue(snapshots, "progress must be written every ten attempts, including HostError paths")
        self.assertEqual(snapshots[-1]["counts"]["attempted"], 10)
        self.assertEqual(snapshots[-1]["counts"]["failed"], 10)

    def test_close_terminates_host_after_response(self) -> None:
        _require_host()
        host = PreviewHost(label="close")
        try:
            meta, _ = host.request("close", {})
            self.assertTrue(meta.get("ok"), "close must answer ok first")
            try:
                host.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.fail("host must exit after returning the close response")
            self.assertIsNotNone(host.proc.poll())
        finally:
            host.close()

    def test_previewhost_stderr_is_redirected(self) -> None:
        _require_host()
        host = PreviewHost(label="stderr-selftest")
        try:
            self.assertIsNone(
                host.proc.stderr,
                "stderr must be redirected to a file, never PIPE (PIPE fills up and "
                "wedges the DLL's log spam — observed timeout at request 52)",
            )
            self.assertTrue(host._stderr_path.is_file(), "stderr log file must exist")
        finally:
            host.close()

    def test_protocol_version_rejected_by_host(self) -> None:
        _require_host()
        with PreviewHost(label="proto") as host:
            with self.assertRaises(HostError) as missing:
                host.request("ping", {}, proto=None)
            self.assertEqual(missing.exception.code, "unsupported_protocol_version")
            self.assertTrue(host.alive(), "host must stay alive on a protocol violation")
            with self.assertRaises(HostError) as unsupported:
                host.request("ping", {}, proto=99)
            self.assertEqual(unsupported.exception.code, "unsupported_protocol_version")
            self.assertTrue(host.alive())
            with self.assertRaises(HostError) as nested:
                host.request("ping", {"protocol_version": 1}, proto=99)
            self.assertEqual(
                nested.exception.code,
                "unsupported_protocol_version",
                "a payload field must not override the top-level protocol_version",
            )
            self.assertTrue(host.alive())
            meta, _ = host.request("ping", {})
            self.assertTrue(meta.get("ok"), "a valid request must still be served")


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
                "code": ctx.exception.code, "detail": detail, "stderr": host._stderr_tail(),
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
                "code": ctx.exception.code, "detail": detail, "stderr": host._stderr_tail(),
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
                    "stderr": host._stderr_tail(),
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
                "code": ctx.exception.code, "detail": detail, "stderr": host._stderr_tail(),
            })

    # -- PlayerWin path -------------------------------------------------
    def test_playerwin_open_blocked_without_fabricated_calls(self) -> None:
        """PlayerWin open must fail closed on the documented ABI blocker.

        No unevidenced call may execute: a zeroed VEAdapterConfig faults
        (InitVEAbConfig AV, evidence.md §2), the PlayerWin ctor contract is
        unknown (never call it with a fabricated/null "this"), and
        draft_root/timeline_id have no recovered load path — so the blocker
        detail must name them instead of pretending an initialization ran.
        """
        _require_host()
        draft_root = _require_draft_root()
        timeline_id = os.environ.get("JY_PREVIEW_TEST_TIMELINE_ID", "03B09C7D-44B6-4845-B509-E2801B198852")
        with PreviewHost(label="playerwin-abi") as host:
            with self.assertRaises(HostError) as ctx:
                host.request(
                    "open",
                    {
                        "render_path": "playerwin",
                        "draft_root": str(draft_root),
                        "timeline_id": timeline_id,
                        "duration_us": 54_800_000,
                        "fps": FRAME_RATE,
                    },
                )
            self.assertEqual(ctx.exception.code, "init_rejected")
            detail = ctx.exception.detail if isinstance(ctx.exception.detail, dict) else {}
            reason = str(detail.get("reason", ""))
            self.assertNotIn(
                "exception=", reason,
                "no unevidenced PlayerWin call may run (AV detail means fabricated config/this)",
            )
            self.assertIn("draft_root", reason, "blocker detail must record the unwired draft_root")
            self.assertIn("timeline_id", reason, "blocker detail must record the unwired timeline_id")
            self.assertTrue(host.alive(), "host must stay alive on the PlayerWin blocker")
            _write_artifact("gate-playerwin-abi.json", {
                "code": ctx.exception.code, "detail": detail, "stderr": host._stderr_tail(),
            })

    def test_playerwin_random_timeline_frames(self) -> None:
        _require_host()  # raises GateUnavailable (a failing assertion) if the host is missing
        draft_root = _require_draft_root()
        rng = random.Random(RANDOM_SEED)
        duration_us = int(os.environ.get("JY_PREVIEW_TEST_DURATION_US", str(54_800_000)))
        times = [rng.randrange(0, max(1, duration_us - FRAME_US)) for _ in range(FRAME_SAMPLES)]
        counts = {"planned": FRAME_SAMPLES, "attempted": 0, "succeeded": 0,
                  "failed": 0, "aborted": None}
        _write_artifact("gate-playerwin-timeline.json", {
            "draft_root": str(draft_root), "duration_us": duration_us, "samples": times,
        })
        failures: list[dict] = []
        generation = 1
        passed = False
        try:
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
                    counts["aborted"] = "open_failed"
                    failures.append({"stage": "open", "code": exc.code, "message": exc.message,
                                     "detail": exc.detail})
                    _write_artifact("gate-playerwin-progress.json", {
                        "counts": counts, "at_index": counts["attempted"],
                    })
                    _write_artifact("gate-playerwin-failure.json", {
                        "passed": False, "counts": counts, "failures": failures,
                        "stderr": host._stderr_tail(),
                    })
                    self.fail(f"PlayerWin open failed: {exc.code}: {exc.message} detail={exc.detail!r}")
                try:
                    for index, t_us in enumerate(times):
                        counts["attempted"] += 1
                        try:
                            meta, body = host.request("render_at", {"t_us": t_us},
                                                       generation=generation, timeout=180.0)
                        except HostError as exc:
                            counts["failed"] += 1
                            failures.append({"stage": "render_at", "index": index, "t_us": t_us,
                                             "code": exc.code, "message": exc.message})
                            _write_progress_every_ten("gate-playerwin-progress.json", counts)
                            if exc.code in ABORT_CODES:
                                counts["aborted"] = exc.code
                                break
                            continue
                        # Timeline composite frames have no single-source reference;
                        # pixel hashing applies to the FrameReader source gate.
                        problem = _frame_problem(meta, body, generation, t_us, tol_us=FRAME_US)
                        if problem:
                            counts["failed"] += 1
                            failures.append({"stage": "frame", "index": index, "t_us": t_us,
                                             "problem": problem})
                        else:
                            counts["succeeded"] += 1
                        _write_progress_every_ten("gate-playerwin-progress.json", counts)
                finally:
                    _write_artifact("gate-playerwin-progress.json", {
                        "counts": counts, "at_index": counts["attempted"],
                    })
                if counts["aborted"] or failures:
                    _write_artifact("gate-playerwin-failure.json", {
                        "passed": False, "checked": counts["attempted"], "counts": counts,
                        "failures": failures,
                    })
                    self.fail(
                        f"PlayerWin gate failed: counts={counts} "
                        f"first={failures[0] if failures else None!r}"
                    )
                passed = True
                _write_artifact("gate-playerwin-result.json", {"passed": True, "counts": counts})
        finally:
            _STATE["playerwin_passed"] = passed

    # -- FrameReader path ----------------------------------------------
    def test_framereader_random_source_frames(self) -> None:
        if _framereader_should_skip():
            self.skipTest("PlayerWin path passed; FrameReader gate only runs when it does not")
        _require_host()  # raises GateUnavailable (a failing assertion) if the host is missing
        source_path = find_source_path()
        ref = _require_ref_hashes()  # pixel validation is fail-closed: no refs, no gate
        times, continuous = _source_request_plan()
        counts = {"planned": len(times) + len(continuous), "attempted": 0, "succeeded": 0,
                  "failed": 0, "aborted": None}
        _write_artifact("gate-framereader-plan.json", {
            "source": str(source_path),
            "source_duration_us": SOURCE_DURATION_US,
            "fps": f"{SOURCE_FPS_NUM}/{SOURCE_FPS_DEN}",
            "random": times,
            "continuous": continuous,
            "planned": counts["planned"],
            "ref_hashes": str(REF_HASHES_PATH),
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
                counts["aborted"] = "open_failed"
                failures.append({"stage": "open", "code": exc.code, "message": exc.message,
                                 "detail": exc.detail})
                _write_artifact("gate-framereader-progress.json", {
                    "counts": counts, "at_index": counts["attempted"],
                })
                _write_artifact("gate-framereader-failure.json", {
                    "passed": False, "counts": counts, "failures": failures,
                    "stderr": host._stderr_tail(),
                })
                self.fail(f"FrameReader open failed: {exc.code}: {exc.message} detail={exc.detail!r}")
            try:
                for index, t_us in enumerate(times + continuous):
                    counts["attempted"] += 1
                    try:
                        meta, body = host.request("render_at", {"t_us": t_us},
                                                   generation=generation, timeout=180.0)
                    except HostError as exc:
                        counts["failed"] += 1
                        failures.append({"stage": "render_at", "index": index, "t_us": t_us,
                                         "code": exc.code, "message": exc.message})
                        _write_progress_every_ten("gate-framereader-progress.json", counts)
                        if exc.code in ABORT_CODES:
                            counts["aborted"] = exc.code
                            break
                        continue
                    problem = _frame_problem(meta, body, generation, t_us,
                                             ref=ref, tol_us=SOURCE_FRAME_TOL_US)
                    if problem:
                        counts["failed"] += 1
                        failures.append({"stage": "frame", "index": index, "t_us": t_us,
                                         "problem": problem})
                    else:
                        counts["succeeded"] += 1
                    _write_progress_every_ten("gate-framereader-progress.json", counts)
            finally:
                # Always record progress, including HostError/abort paths.
                _write_artifact("gate-framereader-progress.json", {
                    "counts": counts, "at_index": counts["attempted"],
                })
            if counts["aborted"] or failures:
                _write_artifact("gate-framereader-failure.json", {
                    "passed": False, "checked": counts["attempted"], "counts": counts,
                    "failures": failures,
                })
                self.fail(
                    f"FrameReader gate failed: counts={counts} "
                    f"first={failures[0] if failures else None!r}"
                )
        _write_artifact("gate-framereader-result.json", {
            "passed": True, "counts": counts,
            "random": len(times), "continuous": len(continuous),
        })


def main() -> int:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.time()
    inputs_before = _input_hashes()
    _write_artifact("gate-input-hashes.json", {"stage": "before", **inputs_before})
    suite = build_suite()
    result = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(suite)
    inputs_after = _input_hashes()
    hashes_record = {
        "before": inputs_before,
        "after": inputs_after,
        "unchanged": inputs_before == inputs_after,
    }
    _write_artifact("gate-input-hashes.json", hashes_record)
    report = {
        "host": str(HOST_EXE),
        "host_exists": HOST_EXE.is_file(),
        "install_dir": str(INSTALL_DIR),
        "dll_sha256": _sha256(INSTALL_DIR / DLL_NAME) if (INSTALL_DIR / DLL_NAME).is_file() else None,
        "dll_sha256_expected": EXPECTED_SHA256,
        "ref_hashes": str(REF_HASHES_PATH),
        "tests_run": result.testsRun,
        "failures": [str(f[0]) for f in result.failures],
        "errors": [str(e[0]) for e in result.errors],
        "skipped": [str(s[0]) for s in result.skipped],
        "input_hashes": hashes_record,
        "elapsed_s": round(time.time() - started, 3),
    }
    _write_artifact("gate-run.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
