from __future__ import annotations

import hashlib

from Crypto.Cipher import AES

from smartswitch_core.crypto.common import DEFAULT_DUMMY_HEX, derive_dummy_key
from smartswitch_core.crypto.smartdecrypt import (
    decode_iv_prefix_payload,
    infer_payload_kind,
    is_probably_encrypted_name,
)


def _encrypt_ivprefix(payload: bytes, *, iv: bytes = b"\x33" * 16, trailer: bytes = b"") -> bytes:
    pad_len = (16 - (len(payload) % 16)) % 16
    padded = payload + (b"\x00" * pad_len)
    ct = AES.new(derive_dummy_key(), AES.MODE_CBC, iv).encrypt(padded)
    return iv + ct + trailer


def test_decode_iv_prefix_payload_json_with_trailer() -> None:
    encrypted = _encrypt_ivprefix(b'{"hello":"world"}', trailer=b"\xaa\xbb\xcc")
    decoded = decode_iv_prefix_payload(encrypted, name_hint="runPermBackup.enc")
    assert decoded.kind == "json"
    assert decoded.extension == ".json"
    assert b'"hello":"world"' in decoded.payload


def test_decode_pin_password_eq5_payload() -> None:
    password = "2468"
    master_key = hashlib.pbkdf2_hmac(
        "sha1",
        password.encode(),
        bytes.fromhex(DEFAULT_DUMMY_HEX),
        1000,
        dklen=32,
    )
    key = hashlib.sha256(master_key).digest()[:16]
    iv = b"\x44" * 16
    payload = b'{"pin":"eq5"}'
    padded = payload + (b"\x00" * ((16 - len(payload) % 16) % 16))
    encrypted = iv + AES.new(key, AES.MODE_CBC, iv).encrypt(padded)

    decoded = decode_iv_prefix_payload(encrypted, password=password)

    assert decoded.kind == "json"
    assert decoded.payload == payload


def test_decode_pin_password_eq6_payload() -> None:
    password = "1357"
    master_key = hashlib.pbkdf2_hmac(
        "sha1",
        password.encode(),
        bytes.fromhex(DEFAULT_DUMMY_HEX),
        1000,
        dklen=32,
    )
    iv = b"\x55" * 16
    salt = b"\x66" * 16
    key = hashlib.pbkdf2_hmac("sha1", master_key, salt, 1000, dklen=32)
    payload = b'{"pin":"eq6"}'
    padded = payload + (b"\x00" * ((16 - len(payload) % 16) % 16))
    encrypted = iv + salt + AES.new(key, AES.MODE_CBC, iv).encrypt(padded)

    decoded = decode_iv_prefix_payload(encrypted, password=password)

    assert decoded.kind == "json"
    assert decoded.payload == payload


def test_infer_payload_kind_webp() -> None:
    payload = b"RIFF\x24\x00\x00\x00WEBPVP8 " + (b"\x00" * 16)
    assert infer_payload_kind(payload) == "webp"


def test_is_probably_encrypted_name() -> None:
    assert is_probably_encrypted_name("settings.exml")
    assert is_probably_encrypted_name("runPermBackup.enc")
    assert is_probably_encrypted_name("tempEncryptedBackupFile")
    assert not is_probably_encrypted_name("plain_config.json")
