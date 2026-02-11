from __future__ import annotations

import json
from pathlib import Path

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from smartswitch_core.crypto.common import derive_dummy_key
from smartswitch_core.messages.decode import decode_and_export_messages


def _encrypt_bk(payload: bytes) -> bytes:
    key = derive_dummy_key()
    iv = b"\x01" * 16
    ciphertext = AES.new(key, AES.MODE_CBC, iv).encrypt(pad(payload, 16))
    return iv + ciphertext


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
