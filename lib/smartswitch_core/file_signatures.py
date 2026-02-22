from __future__ import annotations

from enum import StrEnum
from pathlib import Path

MESSAGE_PART_SMS = "sms"
MESSAGE_PART_MMS = "mms"
MESSAGE_PART_ATTACHMENTS = "attachments"
MESSAGE_PART_RCS = "rcs"

MESSAGE_PART_TO_ITEM_ID = {
    MESSAGE_PART_SMS: "messages:sms",
    MESSAGE_PART_MMS: "messages:mms",
    MESSAGE_PART_ATTACHMENTS: "messages:attachments",
    MESSAGE_PART_RCS: "messages:rcs",
}
MESSAGE_ITEM_IDS = set(MESSAGE_PART_TO_ITEM_ID.values())


class DirectFileKind(StrEnum):
    MESSAGE_SMEM = "message_smem"
    MESSAGE_PART_SMS = "message_part_sms"
    MESSAGE_PART_MMS = "message_part_mms"
    MESSAGE_PART_ATTACHMENTS = "message_part_attachments"
    MESSAGE_PART_RCS = "message_part_rcs"
    APP_DATA = "app_data"
    APP_PENC = "app_penc"
    APP_APK_SPLIT = "app_apk_split"
    CONTACTS_SPBM = "contacts_spbm"
    CONTACTS_CSV = "contacts_csv"
    CALLLOG_ZIP = "calllog_zip"
    UNSUPPORTED = "unsupported"


MESSAGE_PART_KIND_TO_KEY = {
    DirectFileKind.MESSAGE_PART_SMS: MESSAGE_PART_SMS,
    DirectFileKind.MESSAGE_PART_MMS: MESSAGE_PART_MMS,
    DirectFileKind.MESSAGE_PART_ATTACHMENTS: MESSAGE_PART_ATTACHMENTS,
    DirectFileKind.MESSAGE_PART_RCS: MESSAGE_PART_RCS,
}


def message_part_keys_from_filename(file_name: str) -> set[str]:
    lower = file_name.casefold()
    out: set[str] = set()
    if lower.endswith("sms_restore.bk"):
        out.add(MESSAGE_PART_SMS)
    if lower.endswith("mms_restore.bk"):
        out.add(MESSAGE_PART_MMS)
    if "part_" in lower:
        out.add(MESSAGE_PART_ATTACHMENTS)
    if "rcsmessage" in lower:
        out.add(MESSAGE_PART_RCS)
    return out


def message_item_ids_from_filename(file_name: str) -> set[str]:
    return {MESSAGE_PART_TO_ITEM_ID[key] for key in message_part_keys_from_filename(file_name)}


def is_contacts_spbm_filename(file_name: str) -> bool:
    return file_name.casefold() == "contact.spbm"


def is_contacts_csv_filename(file_name: str) -> bool:
    lower = file_name.casefold()
    if not lower.endswith(".csv"):
        return False
    stem = Path(lower).stem
    normalized = "".join(ch for ch in stem if ch.isalnum())
    return normalized.startswith("contact")


def is_calllog_zip_path(file_path: Path) -> bool:
    lower = file_path.name.casefold()
    if lower == "calllog.zip":
        return True
    return lower.endswith(".zip") and file_path.parent.name.casefold() == "calllog"


def classify_direct_file(file_path: Path) -> DirectFileKind:
    lower = file_path.name.casefold()
    if lower.endswith(".smem"):
        return DirectFileKind.MESSAGE_SMEM

    parts = message_part_keys_from_filename(file_path.name)
    if MESSAGE_PART_SMS in parts:
        return DirectFileKind.MESSAGE_PART_SMS
    if MESSAGE_PART_MMS in parts:
        return DirectFileKind.MESSAGE_PART_MMS
    if MESSAGE_PART_ATTACHMENTS in parts:
        return DirectFileKind.MESSAGE_PART_ATTACHMENTS
    if MESSAGE_PART_RCS in parts:
        return DirectFileKind.MESSAGE_PART_RCS

    if lower.endswith(".data"):
        return DirectFileKind.APP_DATA
    if lower.endswith(".penc"):
        return DirectFileKind.APP_PENC
    if lower.endswith(".apk"):
        return DirectFileKind.APP_APK_SPLIT
    if is_contacts_spbm_filename(file_path.name):
        return DirectFileKind.CONTACTS_SPBM
    if is_contacts_csv_filename(file_path.name):
        return DirectFileKind.CONTACTS_CSV
    if is_calllog_zip_path(file_path):
        return DirectFileKind.CALLLOG_ZIP
    return DirectFileKind.UNSUPPORTED


def expected_backup_areas_for_kind(kind: DirectFileKind) -> tuple[str, ...]:
    if kind in {
        DirectFileKind.MESSAGE_SMEM,
        DirectFileKind.MESSAGE_PART_SMS,
        DirectFileKind.MESSAGE_PART_MMS,
        DirectFileKind.MESSAGE_PART_ATTACHMENTS,
        DirectFileKind.MESSAGE_PART_RCS,
    }:
        return ("MESSAGE",)
    if kind in {DirectFileKind.APP_DATA, DirectFileKind.APP_PENC, DirectFileKind.APP_APK_SPLIT}:
        return ("APKFILE",)
    if kind in {DirectFileKind.CONTACTS_SPBM, DirectFileKind.CONTACTS_CSV}:
        return ("CONTACT",)
    if kind == DirectFileKind.CALLLOG_ZIP:
        return ("CALLLOG",)
    return ()
