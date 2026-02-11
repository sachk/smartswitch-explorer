from __future__ import annotations

from pathlib import Path

from smartswitch_core.models import TreeItem


def detect_applications(backup_dir: Path) -> tuple[list[TreeItem], list[TreeItem]]:
    apk_dir = backup_dir / "APKFILE"
    if not apk_dir.exists():
        return [], []

    data_items: list[TreeItem] = []
    apk_items: list[TreeItem] = []

    for path in sorted(apk_dir.glob("*.data")):
        package_id = path.stem
        data_items.append(
            TreeItem(
                id=f"app_data:{package_id}",
                kind="app_data",
                label=package_id,
                package_id=package_id,
                source_path=path,
            )
        )

    for path in sorted(apk_dir.glob("*.penc")):
        package_id = path.stem
        apk_items.append(
            TreeItem(
                id=f"app_apk:{package_id}",
                kind="app_apk",
                label=package_id,
                package_id=package_id,
                source_path=path,
            )
        )

    return data_items, apk_items
