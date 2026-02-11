from __future__ import annotations

from pathlib import Path

from smartswitch_core.applications.detect import detect_applications
from smartswitch_core.messages.detect import detect_message_subitems
from smartswitch_core.models import BackupInfo, Inventory, TreeItem


MAX_DISCOVERY_DEPTH = 4


def discover_backup_roots() -> list[Path]:
    home = Path.home()
    candidates = [
        home / "Documents" / "SmartSwitch" / "backup",
        home / "Documents" / "Samsung" / "SmartSwitch" / "backup",
    ]
    return [path for path in candidates if path.exists()]


def is_backup_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    has_items = (path / "MESSAGE" / "Message.smem").exists() or (path / "APKFILE").is_dir()
    has_meta = (path / "SmartSwitchBackup.json").exists() or (path / "backupHistoryInfo.xml").exists()
    return has_items or has_meta


def _bounded_walk_dirs(root: Path, max_depth: int) -> list[Path]:
    root = root.resolve()
    out: list[Path] = []
    for current in root.rglob("*"):
        if not current.is_dir():
            continue
        rel_parts = len(current.relative_to(root).parts)
        if rel_parts <= max_depth:
            out.append(current)
    return out


def find_backups(root: Path) -> list[BackupInfo]:
    seen: set[Path] = set()
    candidates: list[Path] = []

    if is_backup_dir(root):
        candidates.append(root)

    for path in _bounded_walk_dirs(root, MAX_DISCOVERY_DEPTH):
        if is_backup_dir(path):
            candidates.append(path)

    backups: list[BackupInfo] = []
    for path in sorted(candidates):
        rpath = path.resolve()
        if rpath in seen:
            continue
        seen.add(rpath)
        backups.append(BackupInfo(backup_id=path.name, path=path))
    return backups


def build_inventory(backup_dir: Path) -> Inventory:
    backup = BackupInfo(backup_id=backup_dir.name, path=backup_dir)

    message_children = detect_message_subitems(backup_dir)
    message_root = TreeItem(
        id="messages",
        kind="messages_root",
        label="Messages",
        source_path=backup_dir / "MESSAGE",
        children=message_children,
    )

    data_items, apk_items = detect_applications(backup_dir)
    app_data_root = TreeItem(
        id="applications_data",
        kind="applications_data_root",
        label="Application Data",
        source_path=backup_dir / "APKFILE",
        children=data_items,
    )
    app_apk_root = TreeItem(
        id="applications_apks",
        kind="applications_apk_root",
        label="Application APKs",
        source_path=backup_dir / "APKFILE",
        children=apk_items,
    )

    return Inventory(backup=backup, roots=[message_root, app_data_root, app_apk_root])
