# Vendored from the jianying-decrypt skill repo (branch research/dll-free-decrypt,
# commit 348dbfe) scripts/jy_pure_crypto.py: pure-Python AES-256-GCM draft container
# decryption, verified byte-identical to videoeditor.dll on 25 real drafts + 18 synthetic
# (see research/dll-free-decryption.md there). Apart from this header the file is an exact
# copy; re-copy it if the skill module changes.
# -*- coding: utf-8 -*-
"""Pure-Python JianYing (剪映) draft container decryption — no DLL, no third-party packages.

Reverse-engineered container format (videoeditor.dll 11.6.0.14552 ``lvve::EncryptUtils``;
evidence in ``research/dll-free-decryption.md``):

    key   = 32 ASCII chars from alphabet "0123456789abcdefghijABCDEFGHIJ"
    iv    = 16 ASCII chars from the same alphabet
    blob  = AES-256-GCM(key=32 ASCII bytes, iv=16 ASCII bytes).seal(plaintext)
            # ciphertext || 16-byte tag, no AAD; 16-byte IV so J0 is GHASH-derived
            # (Crypto++ semantics, as the DLL implements)
    text  = base64.b64encode(blob)                       # length % 4 == 0
    container = text with the 48 key/iv chars inserted 4 at a time at
                offsets [0, 7, 20, 33, 40, 47, 59, 66, 76, 89, 99, 127]

decrypt() is the inverse: extract the 48 chars at those offsets (key = [0:32],
iv = [32:48]), delete those positions, base64-decode, AES-256-GCM open.
The key travels inside the ciphertext — no key store, no machine binding, no DLL.

API mirrors ``jy_draft_crypto.JianYingCrypto`` (decrypt / encrypt / decrypt_json)
so it is a drop-in replacement where the DLL is unavailable.

Known behavior divergence from the DLL on INVALID containers: the DLL often
answers ok=true with unverified partial plaintext (Crypto++ filter quirk); this
module raises. Valid containers decrypt byte-identically. encrypt() also mirrors
the DLL rule of refusing non-JSON input (no ``{`` in the first 5 bytes).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

__all__ = ["PureCrypto", "looks_encrypted", "sha256", "OFFS", "ALPH"]

OFFS = [0, 7, 20, 33, 40, 47, 59, 66, 76, 89, 99, 127]
ALPH = b"0123456789abcdefghijABCDEFGHIJ"
_MIN_CONTAINER = 131  # the DLL rejects shorter input (last key/iv slot is 127..130)

_SBOX = bytes.fromhex(
    "637c777bf26b6fc53001672bfed7ab76ca82c97dfa5947f0add4a2af9ca472c0"
    "b7fd9326363ff7cc34a5e5f171d8311504c723c31896059a071280e2eb27b275"
    "09832c1a1b6e5aa0523bd6b329e32f8453d100ed20fcb15b6acbbe394a4c58cf"
    "d0efaafb434d338545f9027f503c9fa851a3408f929d38f5bcb6da2110fff3d2"
    "cd0c13ec5f974417c4a77e3d645d197360814fdc222a908846eeb814de5e0bdb"
    "e0323a0a4906245cc2d3ac629195e479e7c8376d8dd54ea96c56f4ea657aae08"
    "ba78252e1ca6b4c6e8dd741f4bbd8b8a703eb5664803f60e613557b986c11d9e"
    "e1f8981169d98e949b1e87e9ce5528df8ca1890dbfe6426841992d0fb054bb16"
)
_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]


def _xtime(a: int) -> int:
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else (a << 1) & 0xFF


def _key_expand(key: bytes):
    n = len(key)
    nr = {16: 10, 24: 12, 32: 14}[n]
    w = [list(key[i:i + 4]) for i in range(0, n, 4)]
    for i in range(n // 4, 4 * (nr + 1)):
        t = list(w[i - 1])
        if i % (n // 4) == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= _RCON[i // (n // 4) - 1]
        elif n == 32 and i % 8 == 4:
            t = [_SBOX[b] for b in t]
        w.append([a ^ b for a, b in zip(w[i - n // 4], t)])
    return w, nr


def _enc_block(block: bytes, w, nr: int) -> bytes:
    s = [b for b in block]

    def addrk(r):
        for c in range(4):
            for r_ in range(4):
                s[r_ + 4 * c] ^= w[r * 4 + c][r_]

    def subshift():
        t = [_SBOX[b] for b in s]
        ns = [0] * 16
        for c in range(4):
            for r in range(4):
                ns[r + 4 * c] = t[r + 4 * ((c + r) % 4)]
        s[:] = ns

    def mixcol():
        for c in range(4):
            a = s[4 * c:4 * c + 4]
            s[4 * c] = _xtime(a[0]) ^ (_xtime(a[1]) ^ a[1]) ^ a[2] ^ a[3]
            s[4 * c + 1] = a[0] ^ _xtime(a[1]) ^ (_xtime(a[2]) ^ a[2]) ^ a[3]
            s[4 * c + 2] = a[0] ^ a[1] ^ _xtime(a[2]) ^ (_xtime(a[3]) ^ a[3])
            s[4 * c + 3] = (_xtime(a[0]) ^ a[0]) ^ a[1] ^ a[2] ^ _xtime(a[3])

    addrk(0)
    for r in range(1, nr):
        subshift()
        mixcol()
        addrk(r)
    subshift()
    addrk(nr)
    return bytes(s)


def _ghash_mul(x: bytes, y: bytes) -> bytes:
    r = 0xE1000000000000000000000000000000
    x = int.from_bytes(x, "big")
    v = int.from_bytes(y, "big")
    z = 0
    for i in range(127, -1, -1):
        if (x >> i) & 1:
            z ^= v
        if v & 1:
            v = (v >> 1) ^ r
        else:
            v >>= 1
    return z.to_bytes(16, "big")


def _ghash(h: bytes, data: bytes) -> bytes:
    y = b"\x00" * 16
    for i in range(0, len(data), 16):
        blk = data[i:i + 16]
        if len(blk) < 16:
            blk += b"\x00" * (16 - len(blk))
        y = _ghash_mul(bytes(a ^ b for a, b in zip(y, blk)), h)
    return y


def _gcm_setup(key: bytes, iv: bytes):
    w, nr = _key_expand(key)
    h = _enc_block(b"\x00" * 16, w, nr)
    if len(iv) == 12:
        j0 = iv + b"\x00\x00\x00\x01"
    else:
        padded = iv + b"\x00" * ((16 - len(iv) % 16) % 16)
        j0 = _ghash(h, padded + b"\x00" * 8 + (8 * len(iv)).to_bytes(8, "big"))
    return w, nr, h, j0


def _gcm_keystream(w, nr: int, j0: bytes, n: int) -> bytes:
    out = b""
    ctr = bytearray(j0)
    for j in range(15, 11, -1):
        ctr[j] = (ctr[j] + 1) & 0xFF
        if ctr[j]:
            break
    while len(out) < n:
        out += _enc_block(bytes(ctr), w, nr)
        for j in range(15, 11, -1):
            ctr[j] = (ctr[j] + 1) & 0xFF
            if ctr[j]:
                break
    return out[:n]


def _gcm_seal(key: bytes, iv: bytes, pt: bytes):
    w, nr, h, j0 = _gcm_setup(key, iv)
    ks = _gcm_keystream(w, nr, j0, len(pt))
    ct = bytes(a ^ b for a, b in zip(pt, ks))
    lenblk = b"\x00" * 8 + (8 * len(ct)).to_bytes(8, "big")
    s = _ghash(h, ct + b"\x00" * ((16 - len(ct) % 16) % 16) + lenblk)
    tag = bytes(a ^ b for a, b in zip(s, _enc_block(bytes(j0), w, nr)))
    return ct, tag


def _gcm_open(key: bytes, iv: bytes, ct: bytes, tag: bytes) -> bytes:
    w, nr, h, j0 = _gcm_setup(key, iv)
    ks = _gcm_keystream(w, nr, j0, len(ct))
    pt = bytes(a ^ b for a, b in zip(ct, ks))
    lenblk = b"\x00" * 8 + (8 * len(ct)).to_bytes(8, "big")
    s = _ghash(h, ct + b"\x00" * ((16 - len(ct) % 16) % 16) + lenblk)
    calc = bytes(a ^ b for a, b in zip(s, _enc_block(bytes(j0), w, nr)))
    if calc != tag:
        raise ValueError("GCM tag mismatch: not a valid JianYing encrypted draft (or corrupt)")
    return pt


def _is_slot(i: int) -> bool:
    return any(o <= i < o + 4 for o in OFFS)


class PureCrypto:
    """Drop-in counterpart of ``jy_draft_crypto.JianYingCrypto`` without the DLL."""

    def decrypt(self, encrypted: bytes) -> bytes:
        data = bytes(encrypted)
        if len(data) < _MIN_CONTAINER:
            raise ValueError(
                f"container too short ({len(data)} < {_MIN_CONTAINER}): "
                "not a JianYing encrypted draft"
            )
        kv = b"".join(data[o:o + 4] for o in OFFS)
        key, iv = kv[:32], kv[32:48]
        rest = bytes(b for i, b in enumerate(data) if not _is_slot(i))
        rest += b"=" * ((4 - len(rest) % 4) % 4)
        blob = base64.b64decode(rest)
        if len(blob) < 16:
            raise ValueError("container too short after base64 decode (no GCM tag)")
        return _gcm_open(key, iv, blob[:-16], blob[-16:])

    def encrypt(self, plain: bytes) -> bytes:
        source = bytes(plain)
        if b"{" not in source[:5]:
            return source  # DLL parity: non-JSON input is returned unchanged
        key = bytes(ALPH[b % 30] for b in os.urandom(32))
        iv = bytes(ALPH[b % 30] for b in os.urandom(16))
        ct, tag = _gcm_seal(key, iv, source)
        text = base64.b64encode(ct + tag)
        kv = key + iv
        out = bytearray()
        si = 0
        for i in range(len(text) + 48):
            if _is_slot(i):
                o = max(o for o in OFFS if o <= i)
                out.append(kv[sum(1 for p in OFFS if p < o) * 4 + (i - o)])
            else:
                out.append(text[si])
                si += 1
        return bytes(out)

    def decrypt_json(self, encrypted: bytes) -> dict[str, Any]:
        value = json.loads(self.decrypt(encrypted).decode("utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("decoded content is not a JSON object")
        return value


def looks_encrypted(data: bytes) -> bool:
    """Heuristic: plaintext JSON starts with ``{`` after optional BOM/whitespace."""
    sample = data.lstrip(b"\xef\xbb\xbf\r\n\t ")
    return not sample.startswith(b"{")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
