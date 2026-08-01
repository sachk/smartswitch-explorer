from __future__ import annotations

import io
import json
import sqlite3
import zipfile

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from smartswitch_core.crypto.common import derive_dummy_key
from smartswitch_core.messages.decode import decode_and_export_messages


def _encrypt_bk(payload: bytes) -> bytes:
    key = derive_dummy_key()
    iv = b"\x01" * 16
    ciphertext = AES.new(key, AES.MODE_CBC, iv).encrypt(pad(payload, 16))
    return iv + ciphertext

def _encrypt_rcs_edb(tmp_path: Path) -> bytes:
    db_path = tmp_path / "mmssms.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "CREATE TABLE im (_id INTEGER PRIMARY KEY, address TEXT, body TEXT, date INTEGER)"
        )
        connection.execute(
            "CREATE TABLE ft (_id INTEGER PRIMARY KEY, file_name TEXT, file_size INTEGER)"
        )
        connection.execute(
            "INSERT INTO im VALUES (?, ?, ?, ?)",
            (1, "+123", "RCS hello", 1700000000000),
        )
        connection.execute("INSERT INTO ft VALUES (?, ?, ?)", (2, "photo.jpg", 42))
        connection.commit()
    finally:
        connection.close()

    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(db_path, "/mmssms.db")
    return _encrypt_bk(archive_buffer.getvalue())


def test_decode_and_export_messages(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    msg_dir = backup / "MESSAGE"
    msg_dir.mkdir(parents=True)

    sms_rows = [{"body": "hello", "address": "+123"}]
    sms_json = json.dumps(sms_rows).encode("utf-8")
    (msg_dir / "!@ssm@!sms_restore.bk").write_bytes(_encrypt_bk(sms_json))

    attachment = msg_dir / "!@ssm@!PART_100_image000000.jpg"
    attachment.write_bytes(b"image-bytes")

    out = tmp_path / "out"
    result = decode_and_export_messages(
        backup,
        out,
        {"sms", "attachments"},
        include_decrypt=True,
        include_extract=True,
    )

    assert result.ok
    sms_path = out / "messages" / "sms.json"
    assert sms_path.exists()
    assert json.loads(sms_path.read_text(encoding="utf-8")) == sms_rows

    media_dir = out / "messages" / "media"
    assert media_dir.exists()
    assert any(p.name.endswith(".jpg") for p in media_dir.iterdir())


def test_decode_messages_csv_output(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    msg_dir = backup / "MESSAGE"
    msg_dir.mkdir(parents=True)

    sms_rows = [{"body": "hello", "address": "+123"}]
    (msg_dir / "!@ssm@!sms_restore.bk").write_bytes(_encrypt_bk(json.dumps(sms_rows).encode("utf-8")))

    out = tmp_path / "out"
    result = decode_and_export_messages(
        backup,
        out,
        {"sms"},
        message_format="csv",
        include_decrypt=True,
        include_extract=True,
    )

    assert result.ok
    csv_path = out / "messages" / "sms.csv"
    assert csv_path.exists()
    csv_text = csv_path.read_text(encoding="utf-8")
    assert "body" in csv_text
    assert "address" in csv_text
    assert "hello" in csv_text


def test_decode_messages_native_output(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    msg_dir = backup / "MESSAGE"
    msg_dir.mkdir(parents=True)

    raw = b"native-binary"
    (msg_dir / "!@ssm@!sms_restore.bk").write_bytes(raw)

    out = tmp_path / "out"
    result = decode_and_export_messages(
        backup,
        out,
        {"sms"},
        message_format="native",
        include_decrypt=False,
        include_extract=True,
    )

    assert result.ok
    native_path = out / "messages" / "native" / "!@ssm@!sms_restore.bk"
    assert native_path.exists()
    assert native_path.read_bytes() == raw



def test_decode_rcs_edb_to_json(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    msg_dir = backup / "MESSAGE"
    msg_dir.mkdir(parents=True)
    source = msg_dir / "!@ssm@!RCSMESSAGE!@ssm@!RcsMessage.edb"
    source.write_bytes(_encrypt_rcs_edb(tmp_path))

    out = tmp_path / "out"
    result = decode_and_export_messages(
        backup,
        out,
        {"rcs"},
        message_format="json",
        include_decrypt=True,
        include_extract=True,
    )

    assert result.ok
    assert not result.warnings
    rcs_path = out / "messages" / "rcs.json"
    payload = json.loads(rcs_path.read_text(encoding="utf-8"))
    assert payload["im"] == [
        {"_id": 1, "address": "+123", "body": "RCS hello", "date": 1700000000000}
    ]
    assert payload["ft"] == [{"_id": 2, "file_name": "photo.jpg", "file_size": 42}]
    assert not (out / "messages" / "rcs").exists()


def test_decode_rcs_edb_to_csv(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    msg_dir = backup / "MESSAGE"
    msg_dir.mkdir(parents=True)
    source = msg_dir / "!@ssm@!RCSMESSAGE!@ssm@!RcsMessage.edb"
    source.write_bytes(_encrypt_rcs_edb(tmp_path))

    out = tmp_path / "out"
    result = decode_and_export_messages(
        backup,
        out,
        {"rcs"},
        message_format="csv",
        include_decrypt=True,
        include_extract=True,
    )

    assert result.ok
    assert not result.warnings
    assert "RCS hello" in (out / "messages" / "rcs_im.csv").read_text(encoding="utf-8")
    assert "photo.jpg" in (out / "messages" / "rcs_ft.csv").read_text(encoding="utf-8")