"""Three gates the self-written crypto layer must pass before anything trusts it.

  G1 length preserved      ciphertext -> plaintext -> ciphertext keeps the exact byte length
                           (byte-identical re-encryption is impossible: the container
                           carries random entropy, see F-003 / U-20)
  G2 semantic round-trip   plaintext -> ciphertext -> plaintext == original plaintext
  G3 external oracle       our plaintext == jianying-editor-skill CLI plaintext (sha256)

Drafts are never written: sources are hashed before and after, and every generated
byte lands under temp/.

Usage:
  python gate.py --samples 6 --oracle
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cache import assert_scratch_target, draft_roots, scratch_dir  # noqa: E402
from client import call  # noqa: E402

ORACLE_CLI = Path(
    os.environ.get(
        "JY_ORACLE_CLI",
        str(Path.home() / ".agents" / "skills" / "jianying-editor-skill" / "scripts" / "jy_draft_crypto.py"),
    )
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_cipher(path: Path) -> bool:
    with path.open("rb") as handle:
        head = handle.read(1)
    return bool(head) and head != b"{"


def collect_samples(limit: int) -> list[dict]:
    """Read-only sweep: encrypted draft_content.json, half legacy and half hybrid."""
    legacy: list[dict] = []
    hybrid: list[dict] = []
    quota = max(1, (limit + 1) // 2)
    for root in draft_roots():
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or (len(legacy) >= quota and len(hybrid) >= quota):
                continue
            timelines = entry / "Timelines"
            if timelines.is_dir() and len(hybrid) < quota:
                for sub in sorted(timelines.iterdir()):
                    path = sub / "draft_content.json"
                    if path.is_file() and is_cipher(path):
                        hybrid.append({"path": str(path), "layout": "hybrid", "draft": entry.name})
                        break
            elif not timelines.is_dir() and len(legacy) < quota:
                path = entry / "draft_content.json"
                if path.is_file() and is_cipher(path):
                    legacy.append({"path": str(path), "layout": "legacy", "draft": entry.name})
        if len(legacy) >= quota and len(hybrid) >= quota:
            break
    picked: list[dict] = []
    for pair in zip(legacy, hybrid):
        picked.extend(pair)
    picked.extend(legacy[len(hybrid):] if len(legacy) > len(hybrid) else hybrid[len(legacy):])
    return picked[:limit]


def run_oracle(src: Path, dst: Path) -> dict:
    if not ORACLE_CLI.is_file():
        return {"ok": False, "error": f"oracle CLI missing: {ORACLE_CLI}"}
    proc = subprocess.run(
        [sys.executable, str(ORACLE_CLI), "--decrypt", str(src), "--output", str(dst)],
        capture_output=True,
        timeout=300,
    )
    return {
        "ok": proc.returncode == 0 and dst.exists(),
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-300:].decode("utf-8", "replace"),
        "stderr_tail": proc.stderr[-300:].decode("utf-8", "replace"),
    }


def probe_sample(sample: dict, work: Path, use_oracle: bool) -> dict:
    src = Path(sample["path"])
    before = sha256(src)
    key = before[:16]
    cipher_copy = assert_scratch_target(work / f"{key}.cipher")
    shutil.copyfile(src, cipher_copy)

    plain_mem = assert_scratch_target(work / f"{key}.memapi.json")
    recipher = assert_scratch_target(work / f"{key}.recipher")
    replain = assert_scratch_target(work / f"{key}.replain")
    oracle_out = assert_scratch_target(work / f"{key}.oracle.json")

    batch = call(
        [{"op": "decrypt_bytes", "src": str(cipher_copy), "dst": str(plain_mem)}],
        tag=f"probe-{key}",
    )

    record: dict = {
        "draft": sample["draft"],
        "layout": sample["layout"],
        "src": str(src),
        "src_sha256": before,
        "worker_errors": batch.get("errors", []),
    }
    mem_plain = plain_mem.read_bytes() if plain_mem.exists() else b""
    record["memory_api"] = {"size": len(mem_plain), "sha256": hashlib.sha256(mem_plain).hexdigest()}

    plain = mem_plain
    if not plain:
        record["verdict"] = "FAIL: no plaintext produced"
        return record
    try:
        parsed = json.loads(plain.decode("utf-8-sig"))
        record["json_ok"] = isinstance(parsed, dict)
        record["top_level_keys"] = sorted(parsed)[:12] if isinstance(parsed, dict) else None
        record["has_tracks_and_materials"] = isinstance(parsed, dict) and "tracks" in parsed and "materials" in parsed
        record["is_minimal_draft"] = parsed.get("is_minimal_draft") if isinstance(parsed, dict) else None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        record["json_ok"] = False
        record["json_error"] = str(exc)

    # G1 + G2: re-encrypt the plaintext we produced, then decrypt it again
    rt = call(
        [{"op": "encrypt_bytes", "src": str(plain_mem), "dst": str(recipher)}],
        tag=f"enc-{key}",
    )
    record["encrypt_errors"] = rt.get("errors", [])
    if recipher.exists():
        new_cipher = recipher.read_bytes()
        original = cipher_copy.read_bytes()
        # Byte-identical re-encryption is NOT expected: the export table carries
        # calcEntropyDynamicString, and measurements confirm equal length with a
        # different digest. Length preservation + semantic round-trip is the gate.
        record["g1_byte_identical"] = new_cipher == original
        record["g1_length_preserved"] = len(new_cipher) == len(original)
        record["recipher_size"] = len(new_cipher)
        record["recipher_sha256"] = hashlib.sha256(new_cipher).hexdigest()
        back = call(
            [{"op": "decrypt_bytes", "src": str(recipher), "dst": str(replain)}],
            tag=f"redec-{key}",
        )
        record["redecrypt_errors"] = back.get("errors", [])
        record["g2_semantic_roundtrip"] = replain.exists() and replain.read_bytes() == plain
    else:
        record["g1_byte_identical"] = False
        record["g1_length_preserved"] = False
        record["g2_semantic_roundtrip"] = False

    if use_oracle:
        oracle = run_oracle(cipher_copy, oracle_out)
        record["oracle"] = {k: v for k, v in oracle.items() if k != "stdout_tail"}
        record["g3_oracle_match"] = bool(
            oracle.get("ok") and oracle_out.exists() and sha256(oracle_out) == hashlib.sha256(plain).hexdigest()
        )

    record["src_sha256_after"] = sha256(src)
    record["source_untouched"] = record["src_sha256_after"] == before
    gates = [
        record.get("g2_semantic_roundtrip"),
        record.get("g1_length_preserved"),
        record.get("json_ok"),
    ]
    if use_oracle:
        gates.append(record.get("g3_oracle_match"))
    record["verdict"] = "PASS" if all(gates) and record["source_untouched"] else "FAIL"
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=6)
    parser.add_argument("--oracle", action="store_true", help="also compare against jianying-editor-skill CLI")
    parser.add_argument("--dll", default=None)
    args = parser.parse_args()

    work = scratch_dir("crypto-probe")
    samples = collect_samples(args.samples)
    if not samples:
        print(json.dumps({"ok": False, "error": "no encrypted drafts found"}, ensure_ascii=False))
        return 1

    identity = call([{"op": "report", "dll": args.dll}], tag="report")
    records = [probe_sample(s, work, args.oracle) for s in samples]

    summary = {
        "ok": all(r["verdict"] == "PASS" for r in records),
        "dll": identity.get("results", [{}])[0].get("dll") if identity.get("results") else None,
        "export_count": identity.get("results", [{}])[0].get("export_count"),
        "samples": len(records),
        "g1_length_preserved_pass": sum(1 for r in records if r.get("g1_length_preserved")),
        "g1_byte_identical_count": sum(1 for r in records if r.get("g1_byte_identical")),
        "g2_semantic_roundtrip_pass": sum(1 for r in records if r.get("g2_semantic_roundtrip")),
        "g3_oracle_pass": sum(1 for r in records if r.get("g3_oracle_match")) if args.oracle else None,
        "sources_untouched": all(r.get("source_untouched") for r in records),
        "layouts": sorted({r["layout"] for r in records}),
    }
    log = assert_scratch_target(work / "probe-log.json")
    log.write_text(
        json.dumps({"summary": summary, "identity": identity, "records": records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"summary": summary, "log": str(log)}, ensure_ascii=False, indent=2))
    for r in records:
        print(f"  {r['layout']:7s} {r['verdict']:5s} len={r.get('g1_length_preserved')} sem={r.get('g2_semantic_roundtrip')}"
              f" g3={r.get('g3_oracle_match')} untouched={r.get('source_untouched')} {r['draft'][:28]}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
