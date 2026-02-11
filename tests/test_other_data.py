from __future__ import annotations

import zipfile
from pathlib import Path

from smartswitch_core.other_export import export_other_entry
from smartswitch_core.scan import build_inventory


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
