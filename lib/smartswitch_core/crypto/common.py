from __future__ import annotations

import hashlib


DEFAULT_DUMMY_HEX = "9AB412D3C1F2EF658BFC0CFFCCC344D44C0A"
DEFAULT_PENC_IV = bytes.fromhex("26c7d1d26c142de0a3b82f7e8f90860a")


def derive_dummy_key(dummy_hex: str = DEFAULT_DUMMY_HEX) -> bytes:
    return hashlib.sha256(dummy_hex.encode("utf-8")).digest()[:16]
