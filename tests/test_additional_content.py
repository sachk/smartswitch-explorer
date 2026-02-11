from __future__ import annotations

import zipfile
from pathlib import Path

from Crypto.Cipher import AES

from smartswitch_core.additional_export import (
    export_call_log,
    export_contacts,
    export_media_directory,
    export_watch_backup,
)
from smartswitch_core.crypto.common import derive_dummy_key
from smartswitch_core.scan import build_inventory


def _encrypt_calllog_xml(xml_payload: bytes) -> bytes:
    iv = b"\x11" * 16
    pad_len = (16 - (len(xml_payload) % 16)) % 16
    padded = xml_payload + (b"\x00" * pad_len)
    ct = AES.new(derive_dummy_key(), AES.MODE_CBC, iv).encrypt(padded)
    return iv + ct


def test_inventory_detects_media_watch_contacts_and_calllog(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    (backup / "PHOTO_ORIGIN").mkdir(parents=True)
    (backup / "VIDEO_ORIGIN").mkdir(parents=True)
    (backup / "GALAXYWATCH_CURRENT").mkdir(parents=True)
    (backup / "CONTACT").mkdir(parents=True)
    (backup / "CALLLOG").mkdir(parents=True)

    (backup / "PHOTO_ORIGIN" / "photo1").write_bytes(b"p")
    (backup / "VIDEO_ORIGIN" / "video1").write_bytes(b"v")
    (backup / "GALAXYWATCH_CURRENT" / "watch1.encp").write_bytes(b"w")
    (backup / "CONTACT" / "Contact.csv").write_text("Name,Number\nAlice,123\n", encoding="utf-8")
    (backup / "CALLLOG" / "CALLLOG.zip").write_bytes(b"zip")

    inventory = build_inventory(backup)
    labels = {root.label for root in inventory.roots}

    assert "Media" in labels
    assert "Galaxy Watch Backups" in labels
    assert "Contacts" in labels
    assert "Call Log" in labels


def test_export_media_watch_and_contacts(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    (backup / "PHOTO_ORIGIN").mkdir(parents=True)
    (backup / "VIDEO_ORIGIN").mkdir(parents=True)
    (backup / "GALAXYWATCH_CURRENT").mkdir(parents=True)
    (backup / "CONTACT").mkdir(parents=True)

    (backup / "PHOTO_ORIGIN" / "photo1").write_bytes(b"p")
    (backup / "VIDEO_ORIGIN" / "video1").write_bytes(b"v")
    (backup / "GALAXYWATCH_CURRENT" / "watch1.encp").write_bytes(b"w")
    (backup / "CONTACT" / "Contact.csv").write_text("Name,Number\nAlice,123\n", encoding="utf-8")

    out = tmp_path / "out"
    photos = export_media_directory("photos", backup, out)
    videos = export_media_directory("videos", backup, out)
    watch = export_watch_backup("current", backup, out)
    contacts = export_contacts(backup, out, output_format="csv")

    assert photos.ok and videos.ok and watch.ok and contacts.ok
    assert (out / "media" / "photos" / "photo1").exists()
    assert (out / "media" / "videos" / "video1").exists()
    assert (out / "galaxy_watch" / "current" / "watch1.encp").exists()
    assert (out / "contacts" / "csv" / "Contact.csv").exists()


def test_export_calllog_to_csv(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    calllog_dir = backup / "CALLLOG"
    calllog_dir.mkdir(parents=True)

    xml_payload = (
        b'<?xml version="1.0" encoding="UTF-8"?><CallLogs>'
        b'<CallLog Number="+123" Duration="45" Type="INCOMING" />'
        b"</CallLogs>"
    )
    encrypted = _encrypt_calllog_xml(xml_payload)

    with zipfile.ZipFile(calllog_dir / "CALLLOG.zip", mode="w") as zf:
        zf.writestr("/call_log.exml", encrypted)

    out = tmp_path / "out"
    result = export_call_log(backup, out, output_format="csv")

    assert result.ok
    csv_path = out / "call_log" / "call_log.csv"
    xml_path = out / "call_log" / "call_log.xml"
    assert csv_path.exists()
    assert xml_path.exists()
    csv_text = csv_path.read_text(encoding="utf-8")
    assert "Number" in csv_text
    assert "+123" in csv_text
