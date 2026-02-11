from __future__ import annotations

from pathlib import Path

from smartswitch_core.models import TreeItem


HANDLED_TOP_LEVEL = {
    "MESSAGE",
    "APKFILE",
    "PHOTO_ORIGIN",
    "VIDEO_ORIGIN",
    "GALAXYWATCH_CURRENT",
    "GALAXYWATCH_BACKUP",
    "CONTACT",
    "CALLLOG",
}


def _prettify(name: str) -> str:
    return name.replace("_", " ")


def detect_other_entries(backup_dir: Path) -> TreeItem | None:
    children: list[TreeItem] = []
    try:
        entries = sorted(backup_dir.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return None

    for entry in entries:
        name = entry.name
        if name.startswith("."):
            continue
        if name in HANDLED_TOP_LEVEL:
            continue
        children.append(
            TreeItem(
                id=f"other:{name}",
                kind="other_entry",
                label=_prettify(name),
                source_path=entry,
                package_id=name,
            )
        )

    if not children:
        return None

    return TreeItem(
        id="other",
        kind="other_root",
        label="Other Backup Data",
        source_path=backup_dir,
        children=children,
    )
