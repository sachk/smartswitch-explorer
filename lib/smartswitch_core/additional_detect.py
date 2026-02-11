from __future__ import annotations

import os
from pathlib import Path

from smartswitch_core.models import TreeItem


def _dir_has_files(path: Path) -> bool:
    if not path.is_dir():
        return False
    for _root, _dirs, files in os.walk(path):
        if files:
            return True
    return False


def detect_media_root(backup_dir: Path) -> TreeItem | None:
    photos_dir = backup_dir / "PHOTO_ORIGIN"
    videos_dir = backup_dir / "VIDEO_ORIGIN"

    children: list[TreeItem] = []
    if _dir_has_files(photos_dir):
        children.append(
            TreeItem(
                id="media:photos",
                kind="media_photos",
                label="Photos",
                source_path=photos_dir,
            )
        )
    if _dir_has_files(videos_dir):
        children.append(
            TreeItem(
                id="media:videos",
                kind="media_videos",
                label="Videos",
                source_path=videos_dir,
            )
        )

    if not children:
        return None
    return TreeItem(
        id="media",
        kind="media_root",
        label="Media",
        source_path=backup_dir,
        children=children,
    )


def detect_watch_root(backup_dir: Path) -> TreeItem | None:
    watch_current = backup_dir / "GALAXYWATCH_CURRENT"
    watch_backup = backup_dir / "GALAXYWATCH_BACKUP"

    children: list[TreeItem] = []
    if _dir_has_files(watch_current):
        children.append(
            TreeItem(
                id="watch:current",
                kind="watch_current",
                label="Current Watch Backup",
                source_path=watch_current,
            )
        )
    if _dir_has_files(watch_backup):
        children.append(
            TreeItem(
                id="watch:backup",
                kind="watch_backup",
                label="Older Watch Backup",
                source_path=watch_backup,
            )
        )

    if not children:
        return None
    return TreeItem(
        id="watch",
        kind="watch_root",
        label="Galaxy Watch Backups",
        source_path=backup_dir,
        children=children,
    )


def detect_contacts_root(backup_dir: Path) -> TreeItem | None:
    contact_dir = backup_dir / "CONTACT"
    if not contact_dir.exists():
        return None

    if not _dir_has_files(contact_dir):
        return None

    return TreeItem(
        id="contacts",
        kind="contacts",
        label="Contacts",
        source_path=contact_dir,
    )


def detect_call_log_root(backup_dir: Path) -> TreeItem | None:
    call_log_zip = backup_dir / "CALLLOG" / "CALLLOG.zip"
    if not call_log_zip.exists():
        return None
    return TreeItem(
        id="calllog",
        kind="calllog",
        label="Call Log",
        source_path=call_log_zip.parent,
    )
