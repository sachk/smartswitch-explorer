from __future__ import annotations

from pathlib import Path

from smartswitch_core.scan import build_inventory
from smartswitch_core.sizes import compute_inventory_sizes, format_bytes


def _write_file(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_compute_inventory_sizes_parts_and_total(tmp_path: Path) -> None:
    backup = tmp_path / "backup"

    _write_file(backup / "MESSAGE" / "sms_restore.bk", 10)
    _write_file(backup / "MESSAGE" / "mms_restore.bk", 20)
    _write_file(backup / "MESSAGE" / "PART_001.bin", 30)
    _write_file(backup / "MESSAGE" / "RCSMESSAGE_001.bin", 40)

    _write_file(backup / "APKFILE" / "com.example.app.data", 50)
    _write_file(backup / "APKFILE" / "com.example.app.penc", 60)

    _write_file(backup / "Photo" / "IMG_0001.jpg", 70)
    _write_file(backup / "Video" / "VID_0001.mp4", 80)

    _write_file(backup / "GALAXYWATCH_CURRENT" / "watch_payload.bin", 90)
    _write_file(backup / "CONTACT" / "contacts.json", 100)
    _write_file(backup / "CALLLOG" / "CALLLOG.zip", 110)

    inventory = build_inventory(backup)
    result = compute_inventory_sizes(backup, inventory)

    assert result.item_sizes["messages:sms"] == 10
    assert result.item_sizes["messages:mms"] == 20
    assert result.item_sizes["messages:attachments"] == 30
    assert result.item_sizes["messages:rcs"] == 40
    assert result.item_sizes["messages"] == 100

    assert result.item_sizes["applications_data"] == 50
    assert result.item_sizes["applications_apks"] == 60
    assert result.item_sizes["media"] == 150
    assert result.item_sizes["watch:current"] == 90
    assert result.item_sizes["watch"] == 90
    assert result.item_sizes["contacts"] == 100
    assert result.item_sizes["calllog"] == 110
    assert result.total_bytes == 660


def test_format_bytes() -> None:
    assert format_bytes(0) == "0 B"
    assert format_bytes(1024) == "1.0 KB"
    assert format_bytes(5 * 1024 * 1024) == "5.0 MB"
