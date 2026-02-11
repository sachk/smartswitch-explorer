from __future__ import annotations

import io
import tarfile
from pathlib import Path
from secrets import token_bytes
import hashlib

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from smartswitch_core.applications.decrypt_extract import decrypt_extract_app
from smartswitch_core.crypto.common import DEFAULT_PENC_IV, derive_dummy_key


def _make_penc_from_plain(plain: bytes) -> bytes:
    aligned = plain + (b"\x00" * ((16 - (len(plain) % 16)) % 16))
    key = derive_dummy_key()
    ct = AES.new(key, AES.MODE_CBC, DEFAULT_PENC_IV).encrypt(aligned)
    return bytes.fromhex("00100010") + ct


def _make_data_file_from_tar_payload(payload: bytes, password: str) -> bytes:
    user_salt = token_bytes(64)
    ck_salt = token_bytes(64)
    rounds = 10000
    user_iv = token_bytes(16)

    mk = token_bytes(32)
    mk_iv = token_bytes(16)
    ck = token_bytes(32)

    mk_blob_plain = bytes([len(mk_iv)]) + mk_iv + bytes([len(mk)]) + mk + bytes([len(ck)]) + ck
    user_key = hashlib.pbkdf2_hmac("sha1", password.encode("utf-8"), user_salt, rounds, dklen=32)
    mk_blob = AES.new(user_key, AES.MODE_CBC, user_iv).encrypt(pad(mk_blob_plain, 16))

    payload_enc = AES.new(mk, AES.MODE_CBC, mk_iv).encrypt(pad(payload, 16))

    header = b"\n".join(
        [
            b"ANDROID BACKUP",
            b"5",
            b"0",
            b"AES-256",
            user_salt.hex().encode("ascii"),
            ck_salt.hex().encode("ascii"),
            str(rounds).encode("ascii"),
            user_iv.hex().encode("ascii"),
            mk_blob.hex().encode("ascii"),
        ]
    ) + b"\n"

    return header + payload_enc


def test_decrypt_extract_app_apk_and_data(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    apk_dir = backup / "APKFILE"
    apk_dir.mkdir(parents=True)

    # Build a tiny zip for .penc extraction.
    zip_buf = io.BytesIO()
    import zipfile

    with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("hello.txt", b"world")
    (apk_dir / "com.example.app.penc").write_bytes(_make_penc_from_plain(zip_buf.getvalue()))

    # Build a tiny tar payload for .data decoding.
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w") as tf:
        info = tarfile.TarInfo("apps/com.example.app/_manifest")
        payload = b"manifest"
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    data_raw = _make_data_file_from_tar_payload(
        tar_buf.getvalue(),
        password="9AB412D3C1F2EF658BFC0CFFCCC344D44C0A",
    )
    (apk_dir / "com.example.app.data").write_bytes(data_raw)

    out = tmp_path / "out"
    result = decrypt_extract_app(
        "com.example.app",
        "both",
        backup,
        out,
        include_decrypt=True,
        include_extract=True,
    )

    assert result.ok
    assert (out / "com.example.app" / "manifest.json").exists()
    assert (out / "com.example.app" / "apk_files" / "hello.txt").read_bytes() == b"world"
    assert (out / "com.example.app" / "data_files" / "apps" / "com.example.app" / "_manifest").exists()
