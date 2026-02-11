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

    has_csv = any(contact_dir.glob("*.csv"))
    has_archive = (contact_dir / "Contact.spbm").exists()
    has_other = _dir_has_files(contact_dir)

    children: list[TreeItem] = []
    if has_csv:
        children.append(
            TreeItem(
                id="contacts:csv",
                kind="contacts_csv",
                label="Contacts CSV",
                source_path=contact_dir,
            )
        )
    if has_archive:
        children.append(
            TreeItem(
                id="contacts:archive",
                kind="contacts_archive",
                label="Contacts Archive",
                source_path=contact_dir / "Contact.spbm",
            )
        )
    if not children and has_other:
        children.append(
            TreeItem(
                id="contacts:files",
                kind="contacts_files",
                label="Contact Files",
                source_path=contact_dir,
            )
        )

    if not children:
        return None
    return TreeItem(
        id="contacts",
        kind="contacts_root",
        label="Contacts",
        source_path=contact_dir,
        children=children,
    )


def detect_call_log_root(backup_dir: Path) -> TreeItem | None:
    call_log_zip = backup_dir / "CALLLOG" / "CALLLOG.zip"
    if not call_log_zip.exists():
        return None
    return TreeItem(
        id="calllog",
        kind="calllog_root",
        label="Call Log",
        source_path=call_log_zip.parent,
        children=[
            TreeItem(
                id="calllog:entries",
                kind="calllog_entries",
                label="Call Logs",
                source_path=call_log_zip,
            )
        ],
    )
