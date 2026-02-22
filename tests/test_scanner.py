from __future__ import annotations

import json
from pathlib import Path
import zipfile

from smartswitch_core.metadata import enrich_inventory
from smartswitch_core.scan import build_inventory, discover_backup_roots, expand_input_path, find_backups


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


def test_expand_input_path_handles_windows_userprofile_vars(monkeypatch, tmp_path: Path) -> None:
    userprofile = tmp_path / "UserProfile"
    monkeypatch.setenv("USERPROFILE", str(userprofile))
    expanded = expand_input_path("%UserProfile%/Documents/Samsung/SmartSwitch")
    assert expanded == userprofile / "Documents" / "Samsung" / "SmartSwitch"


def test_discover_backup_roots_checks_userprofile_defaults(monkeypatch, tmp_path: Path) -> None:
    userprofile = tmp_path / "UserProfile"
    samsung_root = userprofile / "Samsung" / "SmartSwitch"
    docs_root = userprofile / "Documents" / "Samsung" / "SmartSwitch"
    (samsung_root / "backup").mkdir(parents=True)
    (docs_root / "backup").mkdir(parents=True)

    monkeypatch.setenv("USERPROFILE", str(userprofile))
    discovered = {path.resolve() for path in discover_backup_roots()}

    assert samsung_root.resolve() in discovered
    assert (samsung_root / "backup").resolve() in discovered
    assert docs_root.resolve() in discovered
    assert (docs_root / "backup").resolve() in discovered


def test_find_backups_drills_into_parent_folders(tmp_path: Path) -> None:
    userprofile = tmp_path / "UserProfile"
    samsung_backup = userprofile / "Samsung" / "SmartSwitch" / "backup" / "SM-Samsung"
    docs_backup = userprofile / "Documents" / "Samsung" / "SmartSwitch" / "backup" / "SM-Documents"

    for backup in (samsung_backup, docs_backup):
        message = backup / "MESSAGE"
        message.mkdir(parents=True)
        (message / "Message.smem").write_bytes(b"x")

    profile_hits = {result.path.resolve() for result in find_backups(userprofile)}
    assert samsung_backup.resolve() in profile_hits
    assert docs_backup.resolve() in profile_hits

    samsung_hits = {result.path.resolve() for result in find_backups(userprofile / "Samsung")}
    assert samsung_backup.resolve() in samsung_hits

    docs_hits = {result.path.resolve() for result in find_backups(userprofile / "Documents")}
    assert docs_backup.resolve() in docs_hits


def test_find_backups_ignores_appdata_metadata_noise_when_traversal_roots_exist(tmp_path: Path) -> None:
    userprofile = tmp_path / "UserProfile"
    real_backup = userprofile / "Samsung" / "SmartSwitch" / "backup" / "SM-Real"
    message = real_backup / "MESSAGE"
    message.mkdir(parents=True)
    (message / "Message.smem").write_bytes(b"x")

    picker_info = userprofile / "AppData" / "Roaming" / "Samsung" / "Smart Switch PC" / "PickerInfo"
    picker_info.mkdir(parents=True)
    (picker_info / "SmartSwitchBackup.json").write_text("{}", encoding="utf-8")

    found = {result.path.resolve() for result in find_backups(userprofile)}
    assert real_backup.resolve() in found
    assert picker_info.resolve() not in found


def test_metadata_only_directory_is_not_treated_as_backup(tmp_path: Path) -> None:
    metadata_only = tmp_path / "PickerInfo"
    metadata_only.mkdir(parents=True)
    (metadata_only / "SmartSwitchBackup.json").write_text("{}", encoding="utf-8")

    found = {result.path.resolve() for result in find_backups(tmp_path)}
    assert metadata_only.resolve() not in found


def test_metadata_plus_secondary_markers_still_detected(tmp_path: Path) -> None:
    backup = tmp_path / "LegacyBackup"
    backup.mkdir(parents=True)
    (backup / "SmartSwitchBackup.json").write_text("{}", encoding="utf-8")
    (backup / "CONTACT").mkdir()

    found = {result.path.resolve() for result in find_backups(tmp_path)}
    assert backup.resolve() in found
