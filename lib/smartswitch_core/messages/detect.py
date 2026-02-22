from __future__ import annotations

import zipfile
from pathlib import Path, PurePosixPath

from smartswitch_core.file_signatures import (
    MESSAGE_PART_ATTACHMENTS,
    MESSAGE_PART_MMS,
    MESSAGE_PART_RCS,
    MESSAGE_PART_SMS,
    message_part_keys_from_filename,
)
from smartswitch_core.models import TreeItem


def _entry_names_from_smem(smem_path: Path) -> list[str]:
    if not smem_path.exists() or not zipfile.is_zipfile(smem_path):
        return []
    try:
        with zipfile.ZipFile(smem_path) as zf:
            return [PurePosixPath(info.filename).name for info in zf.infolist()]
    except (OSError, zipfile.BadZipFile):
        return []


def detect_message_subitems(backup_dir: Path) -> list[TreeItem]:
    message_dir = backup_dir / "MESSAGE"
    if not message_dir.exists():
        return []

    local_names = {p.name for p in message_dir.iterdir() if p.is_file()}
    smem_path = message_dir / "Message.smem"
    if smem_path.exists():
        local_names.update(_entry_names_from_smem(smem_path))

    detected_parts: set[str] = set()
    for name in local_names:
        detected_parts.update(message_part_keys_from_filename(name))

    has_sms = MESSAGE_PART_SMS in detected_parts
    has_mms = MESSAGE_PART_MMS in detected_parts
    has_attachments = MESSAGE_PART_ATTACHMENTS in detected_parts
    has_rcs = MESSAGE_PART_RCS in detected_parts

    items: list[TreeItem] = []
    if has_sms:
        items.append(
            TreeItem(
                id="messages:sms",
                kind="message_subitem",
                label="SMS",
                source_path=message_dir,
            )
        )
    if has_mms:
        items.append(
            TreeItem(
                id="messages:mms",
                kind="message_subitem",
                label="MMS",
                source_path=message_dir,
            )
        )
    if has_attachments:
        items.append(
            TreeItem(
                id="messages:attachments",
                kind="message_subitem",
                label="Attachments",
                source_path=message_dir,
            )
        )
    if has_rcs:
        items.append(
            TreeItem(
                id="messages:rcs",
                kind="message_subitem",
                label="RCS",
                source_path=message_dir,
            )
        )

    return items
