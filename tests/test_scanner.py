from __future__ import annotations

import json
from pathlib import Path
import zipfile

from smartswitch_core.metadata import enrich_inventory
from smartswitch_core.scan import build_inventory, find_backups


def test_find_backups_and_build_inventory(tmp_path: Path) -> None:
    backup = tmp_path / "SM-F946B_20260201210657"
    message = backup / "MESSAGE"
    apk = backup / "APKFILE"
    message.mkdir(parents=True)
    apk.mkdir(parents=True)

    (message / "!@ssm@!sms_restore.bk").write_bytes(b"x")
    (message / "!@ssm@!mms_restore.bk").write_bytes(b"x")
    (message / "!@ssm@!PART_123_image000000.jpg").write_bytes(b"x")
    (message / "!@ssm@!RCSMESSAGE!@ssm@!RcsMessage.edb").write_bytes(b"x")

    (apk / "com.example.app.penc").write_bytes(b"x")
    (apk / "com.example.app.data").write_bytes(b"x")

    backups = find_backups(tmp_path)
    assert len(backups) == 1
    inv = build_inventory(backups[0].path)

    labels = {root.label: root for root in inv.roots}
    assert set(labels) == {"Messages", "Application Data", "Application APKs"}

    msg_children = {child.label for child in labels["Messages"].children}
    assert msg_children == {"SMS", "MMS", "Attachments", "RCS"}

    assert len(labels["Application Data"].children) == 1
    assert len(labels["Application APKs"].children) == 1


def test_message_subitems_detected_from_smem_only(tmp_path: Path) -> None:
    backup = tmp_path / "SM-F946B_20260201210657"
    message = backup / "MESSAGE"
    message.mkdir(parents=True)

    with zipfile.ZipFile(message / "Message.smem", mode="w") as zf:
        zf.writestr("!@ssm@!sms_restore.bk", b"x")
        zf.writestr("!@ssm@!mms_restore.bk", b"x")
        zf.writestr("!@ssm@!PART_1_image000000.jpg", b"x")
        zf.writestr("!@ssm@!RCSMESSAGE!@ssm@!RcsMessage.edb", b"x")

    inv = build_inventory(backup)
    msg_children = {child.label for child in inv.roots[0].children}
    assert msg_children == {"SMS", "MMS", "Attachments", "RCS"}


def test_metadata_enrichment(tmp_path: Path) -> None:
    backup = tmp_path / "SM-F946B_20260201210657"
    apk = backup / "APKFILE"
    apk.mkdir(parents=True)

    (apk / "com.example.app.penc").write_bytes(b"x")
    (apk / "com.example.app.png").write_bytes(b"png")

    (apk / "AppList.json").write_text(
        json.dumps({"Apks": [{"ApkPkgName": "com.example.app", "ApkName": "Example App"}]})
    )
    (backup / "SmartSwitchBackup.json").write_text(
        json.dumps({"DisplayName": "Phone Backup", "SavedTime": "2026-02-01T21:49:02"})
    )

    inv = build_inventory(backup)
    patch = enrich_inventory(backup, inv)

    assert patch.backup_display_name == "Phone Backup"
    assert patch.backup_timestamp == "2026-02-01T21:49:02"
    assert any(update.label == "Example App (com.example.app)" for update in patch.updates)
