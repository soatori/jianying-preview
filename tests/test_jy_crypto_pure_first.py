# -*- coding: utf-8 -*-
"""jy_crypto client: pure implementation is the default decrypt, DLL worker is the backup.

Policy under test (2026-11-18, user-approved):
  - dll=None  -> pure decrypt in-process first; on failure fall back to the
                 existing worker/DLL machinery.
  - dll=<path> -> explicit audit/pin: skip pure entirely and exercise exactly
                 that DLL through the worker.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import os

from jy_crypto import cache, client, pure as jy_pure  # noqa: E402

DLL_116 = Path(os.environ.get(
    "JY_TEST_DLL",
    Path.home() / ".agents" / "skills" / "jianying-decrypt" / "lib" / "videoeditor.dll",
))

PT = b'{"preview":"pure-first","pad":"' + b"A" * 200 + b'"}'


@pytest.fixture()
def container() -> bytes:
    return jy_pure.PureCrypto().encrypt(PT)


def test_t1_default_decrypt_pure_no_worker(container, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("worker path touched in default decrypt")

    monkeypatch.setattr(client, "call", boom)
    out = client.decrypt_bytes(container)
    assert out == PT
    assert client.last_backend == "pure"


def test_t2_call_batch_pure_in_process(container, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("subprocess touched in pure batch")

    monkeypatch.setattr(client.subprocess, "run", boom)
    scratch = cache.scratch_dir("test-pure-first")
    src = scratch / "batch.in"
    dst = cache.assert_scratch_target(scratch / "batch.out")
    src.write_bytes(container)
    payload = client.call([{"op": "decrypt_bytes", "src": str(src), "dst": str(dst)}])
    assert payload["ok"] is True
    assert payload["backend"] == "pure"
    assert dst.read_bytes() == PT
    assert client.last_backend == "pure"


def test_t3_pure_failure_falls_back_to_worker(container, monkeypatch):
    def broken(data):
        raise ValueError("forced pure failure")

    called = {}

    def fake_worker(data, dll, tag):
        called["yes"] = True
        return PT

    monkeypatch.setattr(client, "_pure_decrypt_bytes", broken)
    monkeypatch.setattr(client, "_worker_decrypt_bytes", fake_worker)
    out = client.decrypt_bytes(container)
    assert out == PT
    assert called.get("yes") is True
    assert client.last_backend == "dll"


def test_t4_explicit_dll_backup_works_end_to_end(container):
    assert DLL_116.is_file(), f"test needs a pinned 11.6 DLL, missing: {DLL_116}"
    out = client.decrypt_bytes(container, dll=str(DLL_116))
    assert out == PT
    assert client.last_backend == "dll"


def test_t5_explicit_dll_skips_pure(container, monkeypatch):
    def boom(data):
        raise AssertionError("pure consulted for a pinned DLL run")

    monkeypatch.setattr(client, "_pure_decrypt_bytes", boom)
    out = client.decrypt_bytes(container, dll=str(DLL_116))
    assert out == PT
    assert client.last_backend == "dll"
