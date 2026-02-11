from __future__ import annotations

from pathlib import Path

from smartswitch_core.category_grouping import GroupedEntry, group_unstructured_entries
from smartswitch_core.models import TreeItem


def detect_other_entries(backup_dir: Path, other_entries: list[GroupedEntry] | None = None) -> TreeItem | None:
    if other_entries is None:
        _storage_entries, _settings_entries, other_entries = group_unstructured_entries(backup_dir)
    children = [
        TreeItem(
            id=f"other:{entry.name}",
            kind="other_entry",
            label=entry.label,
            source_path=entry.path,
            package_id=entry.name,
        )
        for entry in other_entries
    ]
    if not children:
        return None

    return TreeItem(
        id="other",
        kind="other_root",
        label="Other Backup Data",
        source_path=backup_dir,
        children=children,
    )
