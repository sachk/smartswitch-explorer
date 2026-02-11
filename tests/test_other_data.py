from __future__ import annotations

import zipfile
from pathlib import Path

from Crypto.Cipher import AES

from smartswitch_core.crypto.common import derive_dummy_key
from smartswitch_core.other_export import export_other_entry, export_settings_entry, export_storage_entry
from smartswitch_core.scan import build_inventory


def _encrypt_ivprefix(payload: bytes, *, iv: bytes = b"\x22" * 16) -> bytes:
    pad_len = (16 - (len(payload) % 16)) % 16
    padded = payload + (b"\x00" * pad_len)
    ct = AES.new(derive_dummy_key(), AES.MODE_CBC, iv).encrypt(padded)
    return iv + ct


def test_scanner_adds_other_backup_data_root(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    (backup / "MESSAGE").mkdir(parents=True)
    (backup / "MESSAGE" / "Message.smem").write_bytes(b"x")
    (backup / "ALARM").mkdir(parents=True)
    (backup / "ALARM" / "ALARM.zip").write_bytes(b"y")
    (backup / "ReqItemsInfo.json").write_text("{}", encoding="utf-8")

    inventory = build_inventory(backup)
    labels = {root.label for root in inventory.roots}
    assert "Other Backup Data" in labels

    other = next(root for root in inventory.roots if root.label == "Other Backup Data")
    child_names = {child.package_id for child in other.children}
    assert "ALARM" in child_names
    assert "ReqItemsInfo.json" in child_names


def test_scanner_moves_storage_and_settings_out_of_other(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    (backup / "MESSAGE").mkdir(parents=True)
    (backup / "MESSAGE" / "Message.smem").write_bytes(b"x")
    (backup / "Docs").mkdir(parents=True)
    (backup / "Docs" / "file.txt").write_text("hello", encoding="utf-8")
    (backup / "DIALERSETTING").mkdir(parents=True)
    (backup / "DIALERSETTING" / "DIALERSETTING.zip").write_bytes(b"zip")
    (backup / "ALARM").mkdir(parents=True)
    (backup / "ALARM" / "ALARM.zip").write_bytes(b"zip")

    inventory = build_inventory(backup)
    roots = {root.label: root for root in inventory.roots}

    assert "Storage" in roots
    assert "Settings" in roots
    assert "Other Backup Data" in roots

    storage_children = {child.package_id for child in roots["Storage"].children}
    settings_children = {child.package_id for child in roots["Settings"].children}
    other_children = {child.package_id for child in roots["Other Backup Data"].children}

    assert "Docs" in storage_children
    assert "DIALERSETTING" in settings_children
    assert "Docs" not in other_children
    assert "DIALERSETTING" not in other_children
    assert "ALARM" in other_children


def test_export_other_directory_copies_and_extracts_zip(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    alarm_dir = backup / "ALARM"
    alarm_dir.mkdir(parents=True)
    with zipfile.ZipFile(alarm_dir / "ALARM.zip", mode="w") as zf:
        zf.writestr("alarm/data.txt", b"beep")

    out = tmp_path / "out"
    result = export_other_entry(backup, "ALARM", out)

    assert result.ok
    assert (out / "other_data" / "ALARM" / "raw" / "ALARM.zip").exists()
    assert (out / "other_data" / "ALARM" / "extracted" / "ALARM" / "alarm" / "data.txt").exists()


def test_export_other_file_copies_and_extracts_zip(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    backup.mkdir(parents=True)
    with zipfile.ZipFile(backup / "MYFILES.zip", mode="w") as zf:
        zf.writestr("notes.txt", b"hello")

    out = tmp_path / "out"
    result = export_other_entry(backup, "MYFILES.zip", out)

    assert result.ok
    assert (out / "other_data" / "MYFILES.zip" / "raw" / "MYFILES.zip").exists()
    assert (out / "other_data" / "MYFILES.zip" / "extracted" / "MYFILES" / "notes.txt").exists()


def test_export_storage_and_settings_entries(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    docs = backup / "Docs"
    dialer = backup / "DIALERSETTING"
    docs.mkdir(parents=True)
    dialer.mkdir(parents=True)
    (docs / "a.txt").write_text("a", encoding="utf-8")
    (dialer / "DIALERSETTING.zip").write_bytes(b"x")

    out = tmp_path / "out"
    storage = export_storage_entry(backup, "Docs", out)
    settings = export_settings_entry(backup, "DIALERSETTING", out)

    assert storage.ok
    assert settings.ok
    assert (out / "storage" / "Docs" / "raw" / "a.txt").exists()
    assert (out / "settings" / "DIALERSETTING" / "raw" / "DIALERSETTING.zip").exists()


def test_export_other_entry_decodes_encrypted_zip_member(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    alarm_dir = backup / "ALARM"
    alarm_dir.mkdir(parents=True)
    encrypted_xml = _encrypt_ivprefix(b"<?xml version='1.0'?><Alarm><Item id='1'/></Alarm>")
    with zipfile.ZipFile(alarm_dir / "ALARM.zip", mode="w") as zf:
        zf.writestr("/alarm.exml", encrypted_xml)

    out = tmp_path / "out"
    result = export_other_entry(backup, "ALARM", out)

    assert result.ok
    decoded = out / "other_data" / "ALARM" / "decoded" / "ALARM" / "alarm.xml"
    assert decoded.exists()
    assert "<Alarm>" in decoded.read_text(encoding="utf-8")
