from __future__ import annotations

import hashlib
import io
import json
import tarfile
import zipfile
from pathlib import Path
from secrets import token_bytes

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from smartswitch_core.applications.decrypt_extract import copy_app_apk_payload, decrypt_extract_app
from smartswitch_core.crypto.common import DEFAULT_PENC_IV, derive_dummy_key


def _make_penc_from_plain(plain: bytes, dummy: str = "9AB412D3C1F2EF658BFC0CFFCCC344D44C0A") -> bytes:
    encrypted_plain = plain[: 1024 * 1024]
    encrypted = AES.new(
        derive_dummy_key(dummy),
        AES.MODE_CBC,
        DEFAULT_PENC_IV,
    ).encrypt(pad(encrypted_plain, 16))
    return len(encrypted).to_bytes(4, "big") + encrypted + plain[len(encrypted_plain) :]


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
    zip_buf = io.BytesIO()

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


def test_copy_app_apk_payload(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    apk_dir = backup / "APKFILE"
    apk_dir.mkdir(parents=True)

    (apk_dir / "com.example.app.penc").write_bytes(b"enc")
    (apk_dir / "com.example.app_split_config.en.apk").write_bytes(b"apk")

    out = tmp_path / "out"
    result = copy_app_apk_payload("com.example.app", backup, out)

    assert result.ok
    assert (out / "com.example.app" / "apk_payload" / "com.example.app.penc").exists()
    assert (out / "com.example.app" / "apk_payload" / "com.example.app_split_config.en.apk").exists()
    assert (out / "com.example.app" / "manifest_apk.json").exists()



def test_app_data_uses_password_from_export_options(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    apk_dir = backup / "APKFILE"
    apk_dir.mkdir(parents=True)
    (apk_dir / "com.example.app.data").write_bytes(
        _make_data_file_from_tar_payload(b"payload", password="user-secret")
    )

    result = decrypt_extract_app(
        "com.example.app",
        "data",
        backup,
        tmp_path / "out",
        app_data_password="user-secret",
        include_decrypt=False,
        include_extract=False,
    )

    assert result.ok
    assert not result.errors


def test_app_data_uses_password_from_backup_metadata(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    apk_dir = backup / "APKFILE"
    apk_dir.mkdir(parents=True)
    (backup / "SmartSwitchBackup.json").write_text(
        json.dumps({"Security": {"EncryptionPassword": "metadata-secret"}}),
        encoding="utf-8",
    )
    (apk_dir / "com.example.app.data").write_bytes(
        _make_data_file_from_tar_payload(b"payload", password="metadata-secret")
    )

    result = decrypt_extract_app(
        "com.example.app",
        "data",
        backup,
        tmp_path / "out",
        include_decrypt=False,
        include_extract=False,
    )

    assert result.ok
    assert not result.errors



def test_app_uses_hex_encoded_dummy_from_backup_metadata(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    apk_dir = backup / "APKFILE"
    apk_dir.mkdir(parents=True)
    dummy = "0123456789abcdef0123456789abcdef"
    (backup / "SmartSwitchBackup.json").write_text(
        json.dumps({"Dummy": dummy.encode("utf-8").hex()}),
        encoding="utf-8",
    )
    (apk_dir / "com.example.app.penc").write_bytes(
        _make_penc_from_plain(b"PK\x03\x04payload", dummy=dummy)
    )
    (apk_dir / "com.example.app.data").write_bytes(
        _make_data_file_from_tar_payload(b"payload", password=dummy)
    )

    result = decrypt_extract_app(
        "com.example.app",
        "both",
        backup,
        tmp_path / "out",
        include_decrypt=True,
        include_extract=False,
    )

    assert result.ok
    assert not result.errors
    assert (
        tmp_path / "out" / "com.example.app" / "com.example.app.decrypted.apk"
    ).read_bytes() == b"PK\x03\x04payload"

def test_app_data_rejected_key_has_actionable_error(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    apk_dir = backup / "APKFILE"
    apk_dir.mkdir(parents=True)
    (apk_dir / "com.example.app.data").write_bytes(
        _make_data_file_from_tar_payload(b"payload", password="unavailable-secret")
    )

    result = decrypt_extract_app(
        "com.example.app",
        "data",
        backup,
        tmp_path / "out",
        include_decrypt=False,
        include_extract=False,
    )

    assert not result.ok
    assert "SmartSwitchBackup.json is missing" in result.errors[0]
    assert "without showing a password prompt" in result.errors[0]
    assert "Padding" not in result.errors[0]


def test_app_apk_recovers_entries_after_encrypted_penc_segment(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    apk_dir = backup / "APKFILE"
    apk_dir.mkdir(parents=True)
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("blocked.bin", b"x" * (1024 * 1024 + 128))
        archive.writestr("available.txt", b"recovered")
        archive.writestr("../escaped.txt", b"escape")
    (apk_dir / "com.example.app.penc").write_bytes(
        _make_penc_from_plain(zip_buf.getvalue(), dummy="unavailable-secret")
    )

    out = tmp_path / "out"
    result = decrypt_extract_app("com.example.app", "apk", backup, out)

    assert not result.ok
    assert (
        out / "com.example.app" / "apk_recovered_files" / "available.txt"
    ).read_bytes() == b"recovered"
    assert not (
        out / "com.example.app" / "apk_recovered_files" / "blocked.bin"
    ).exists()
    assert not (out / "com.example.app" / "escaped.txt").exists()
    assert "Recovered 1 unencrypted APK entries" in result.warnings[0]


def test_app_apk_rejected_key_does_not_write_bogus_apk(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    apk_dir = backup / "APKFILE"
    apk_dir.mkdir(parents=True)
    (apk_dir / "com.example.app.penc").write_bytes(_make_penc_from_plain(b"not a zip"))
    out = tmp_path / "out"

    result = decrypt_extract_app("com.example.app", "apk", backup, out)

    assert not result.ok
    assert "backup dummy keys" in result.errors[0]
    assert not (out / "com.example.app" / "com.example.app.decrypted.apk").exists()