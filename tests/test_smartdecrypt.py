from __future__ import annotations

from Crypto.Cipher import AES

from smartswitch_core.crypto.common import derive_dummy_key
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


def test_infer_payload_kind_webp() -> None:
    payload = b"RIFF\x24\x00\x00\x00WEBPVP8 " + (b"\x00" * 16)
    assert infer_payload_kind(payload) == "webp"


def test_is_probably_encrypted_name() -> None:
    assert is_probably_encrypted_name("settings.exml")
    assert is_probably_encrypted_name("runPermBackup.enc")
    assert is_probably_encrypted_name("tempEncryptedBackupFile")
    assert not is_probably_encrypted_name("plain_config.json")
