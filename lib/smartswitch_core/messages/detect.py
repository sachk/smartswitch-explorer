from __future__ import annotations

import zipfile
from pathlib import Path, PurePosixPath

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
    if not local_names and (message_dir / "Message.smem").exists():
        local_names = set(_entry_names_from_smem(message_dir / "Message.smem"))

    has_sms = any(name.endswith("sms_restore.bk") for name in local_names)
    has_mms = any(name.endswith("mms_restore.bk") for name in local_names)
    has_attachments = any("PART_" in name for name in local_names)
    has_rcs = any(("RCSMESSAGE" in name) or ("RcsMessage" in name) for name in local_names)

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
