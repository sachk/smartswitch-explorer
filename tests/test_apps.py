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
import pytest

from smartswitch_core.applications.android_backup import (
    AndroidBackupDecodeError,
    _checksum_password_bytes,
    _password_bytes,
    decode_android_backup_file,
    inspect_android_backup_file,
)
from smartswitch_core.applications.decrypt_extract import copy_app_apk_payload, decrypt_extract_app
from smartswitch_core.applications.decrypt_extract import _decode_data_payload, _safe_extract_tar, _safe_join
from smartswitch_core.crypto.common import DEFAULT_PENC_IV, derive_dummy_key


def _make_penc_from_plain(plain: bytes, dummy: str = "9AB412D3C1F2EF658BFC0CFFCCC344D44C0A") -> bytes:
    encrypted_plain = plain[: 1024 * 1024]
    encrypted = AES.new(
        derive_dummy_key(dummy),
        AES.MODE_CBC,
        DEFAULT_PENC_IV,
    ).encrypt(pad(encrypted_plain, 16))
    return len(encrypted).to_bytes(4, "big") + encrypted + plain[len(encrypted_plain) :]


def _make_key_checksum(master_key: bytes, checksum_salt: bytes, rounds: int, encoding_name: str) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha1",
        _checksum_password_bytes(master_key, encoding_name),
        checksum_salt,
        rounds,
        dklen=32,
    )


def _make_data_file_from_tar_payload(
    payload: bytes,
    password: str,
    *,
    compressed: bool = False,
    user_key_encoding: str = "utf-8",
    checksum_encoding: str = "utf-8",
    checksum: bytes | None = None,
    master_key_blob_plain: bytes | None = None,
    payload_plain: bytes | None = None,
) -> bytes:
    user_salt = token_bytes(64)
    ck_salt = token_bytes(64)
    rounds = 10000
    user_iv = token_bytes(16)

    mk = token_bytes(32)
    mk_iv = token_bytes(16)
    ck = checksum if checksum is not None else _make_key_checksum(mk, ck_salt, rounds, checksum_encoding)

    if master_key_blob_plain is None:
        master_key_blob_plain = bytes([len(mk_iv)]) + mk_iv + bytes([len(mk)]) + mk + bytes([len(ck)]) + ck
    user_key = hashlib.pbkdf2_hmac(
        "sha1",
        _password_bytes(password, user_key_encoding),
        user_salt,
        rounds,
        dklen=32,
    )
    mk_blob = AES.new(user_key, AES.MODE_CBC, user_iv).encrypt(pad(master_key_blob_plain, 16))

    if payload_plain is None:
        if compressed:
            import zlib

            payload_plain = zlib.compress(payload)
        else:
            payload_plain = payload
    payload_enc = AES.new(mk, AES.MODE_CBC, mk_iv).encrypt(pad(payload_plain, 16))

    header = b"\n".join(
        [
            b"ANDROID BACKUP",
            b"5",
            b"1" if compressed else b"0",
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


def test_decode_data_payload_rejects_wrong_password(tmp_path: Path) -> None:
    data_path = tmp_path / "sample.data"
    data_path.write_bytes(_make_data_file_from_tar_payload(_tar_payload(), password="correct"))

    with pytest.raises(AndroidBackupDecodeError) as exc:
        _decode_data_payload(data_path, "wrong")

    assert exc.value.phase == "master-key padding failure"
    assert "Unable to unwrap the master key" in str(exc.value)


def test_decode_data_payload_rejects_invalid_payload_padding(tmp_path: Path) -> None:
    data_path = tmp_path / "sample.data"
    raw = bytearray(_make_data_file_from_tar_payload(_tar_payload(), password="correct"))
    raw[-32] ^= 0x01
    data_path.write_bytes(raw)

    with pytest.raises(AndroidBackupDecodeError) as exc:
        _decode_data_payload(data_path, "correct")

    assert exc.value.phase == "payload padding failure"


def test_decode_data_payload_rejects_invalid_checksum(tmp_path: Path) -> None:
    data_path = tmp_path / "sample.data"
    data_path.write_bytes(
        _make_data_file_from_tar_payload(
            _tar_payload(),
            password="correct",
            checksum=b"\x00" * 32,
        )
    )

    with pytest.raises(AndroidBackupDecodeError) as exc:
        _decode_data_payload(data_path, "correct")

    assert exc.value.phase == "master-key checksum mismatch"


def test_decode_data_payload_rejects_truncated_master_key_blob(tmp_path: Path) -> None:
    data_path = tmp_path / "sample.data"
    raw = _make_data_file_from_tar_payload(_tar_payload(), password="correct")
    lines = raw.split(b"\n", 9)
    lines[8] = lines[8][:-2]
    data_path.write_bytes(b"\n".join(lines))

    with pytest.raises(AndroidBackupDecodeError) as exc:
        _decode_data_payload(data_path, "correct")

    assert exc.value.phase == "ciphertext not block-aligned"


def test_decode_data_payload_rejects_invalid_master_key_lengths(tmp_path: Path) -> None:
    data_path = tmp_path / "sample.data"
    data_path.write_bytes(
        _make_data_file_from_tar_payload(
            _tar_payload(),
            password="correct",
            master_key_blob_plain=b"\x10" + (b"\x00" * 16) + b"\x20" + (b"\x00" * 8),
        )
    )

    with pytest.raises(AndroidBackupDecodeError) as exc:
        _decode_data_payload(data_path, "correct")

    assert exc.value.phase == "malformed master-key structure"


def test_decode_data_payload_rejects_non_aligned_payload(tmp_path: Path) -> None:
    data_path = tmp_path / "sample.data"
    raw = _make_data_file_from_tar_payload(_tar_payload(), password="correct")
    data_path.write_bytes(raw[:-1])

    with pytest.raises(AndroidBackupDecodeError) as exc:
        _decode_data_payload(data_path, "correct")

    assert exc.value.phase == "ciphertext not block-aligned"


def test_decode_data_payload_rejects_invalid_zlib_payload(tmp_path: Path) -> None:
    data_path = tmp_path / "sample.data"
    data_path.write_bytes(
        _make_data_file_from_tar_payload(
            _tar_payload(),
            password="correct",
            compressed=True,
            payload_plain=b"not-zlib",
        )
    )

    with pytest.raises(AndroidBackupDecodeError) as exc:
        _decode_data_payload(data_path, "correct")

    assert exc.value.phase == "zlib decompression failure"


def test_decode_data_payload_rejects_invalid_tar_payload(tmp_path: Path) -> None:
    data_path = tmp_path / "sample.data"
    data_path.write_bytes(_make_data_file_from_tar_payload(b"not a tar archive", password="correct"))

    with pytest.raises(AndroidBackupDecodeError) as exc:
        _decode_data_payload(data_path, "correct")

    assert exc.value.phase == "invalid TAR"


def test_decode_data_payload_accepts_legacy_password_encoding(tmp_path: Path) -> None:
    data_path = tmp_path / "sample.data"
    payload = _tar_payload()
    data_path.write_bytes(
        _make_data_file_from_tar_payload(
            payload,
            password="caf\xe9",
            user_key_encoding="legacy-8bit",
            checksum_encoding="legacy-8bit",
        )
    )

    decoded, meta = decode_android_backup_file(data_path, "caf\xe9")

    assert decoded == payload
    assert meta["user_key_encoding"] == "legacy-8bit"
    assert meta["checksum_encoding"] == "legacy-8bit"


def test_diagnostic_does_not_leak_credentials(tmp_path: Path) -> None:
    data_path = tmp_path / "sample.data"
    data_path.write_bytes(_make_data_file_from_tar_payload(_tar_payload(), password="secret-password"))

    inspection = inspect_android_backup_file(data_path, credential_candidates=["wrong-password"])
    public = str(inspection.public_dict())

    assert inspection.phase == "master-key padding failure"
    assert "wrong-password" not in public
    assert "secret-password" not in public


def test_safe_join_rejects_textual_prefix_escape(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()

    with pytest.raises(ValueError):
        _safe_join(root, "../out-escape/file.txt")


def test_safe_extract_tar_rejects_path_escape_and_special_member(tmp_path: Path) -> None:
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w") as tf:
        escape = tarfile.TarInfo("../out-escape/file.txt")
        escape.size = 4
        tf.addfile(escape, io.BytesIO(b"nope"))

        link = tarfile.TarInfo("safe/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/tmp/target"
        tf.addfile(link)

    extracted, warnings = _safe_extract_tar(payload.getvalue(), tmp_path / "out")

    assert extracted == 0
    assert len(warnings) == 2
    assert not (tmp_path / "out-escape" / "file.txt").exists()


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
        _make_data_file_from_tar_payload(_tar_payload(), password="user-secret")
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
        _make_data_file_from_tar_payload(_tar_payload(), password="metadata-secret")
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
        _make_data_file_from_tar_payload(_tar_payload(), password=dummy)
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
        _make_data_file_from_tar_payload(_tar_payload(), password="unavailable-secret")
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


def _tar_payload() -> bytes:
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w") as tf:
        info = tarfile.TarInfo("apps/com.example.app/_manifest")
        payload = b"manifest"
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    return tar_buf.getvalue()
