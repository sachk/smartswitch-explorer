from __future__ import annotations

from pathlib import Path


def path_key(path: Path) -> str:
    try:
        return str(path.resolve(strict=False)).casefold()
    except OSError:
        return str(path).casefold()


def message_item_ids_from_filename(file_name: str) -> set[str]:
    lower = file_name.casefold()
    out: set[str] = set()
    if lower.endswith("sms_restore.bk"):
        out.add("messages:sms")
    if lower.endswith("mms_restore.bk"):
        out.add("messages:mms")
    if "part_" in lower:
        out.add("messages:attachments")
    if "rcsmessage" in lower:
        out.add("messages:rcs")
    return out


def infer_package_from_apk_filename(file_name: str, app_packages: set[str]) -> str | None:
    if not app_packages:
        return None

    stem = Path(file_name).stem
    if stem in app_packages:
        return stem

    split_marker = "_split"
    if split_marker in stem:
        prefix = stem.split(split_marker, 1)[0]
        if prefix in app_packages:
            return prefix

    for package_id in sorted(app_packages, key=len, reverse=True):
        if stem.startswith(f"{package_id}_") or stem.startswith(f"{package_id}-") or stem.startswith(f"{package_id}."):
            return package_id
    return None


def map_direct_file_to_item_ids(
    file_path: Path,
    backup_dir: Path,
    available_ids: set[str],
) -> tuple[set[str], str]:
    all_message_ids = {"messages:sms", "messages:mms", "messages:attachments", "messages:rcs"}
    lower_name = file_path.name.casefold()

    # Allow opening .smem from anywhere once it is associated with a backup.
    if lower_name.endswith(".smem"):
        selected = {item_id for item_id in all_message_ids if item_id in available_ids}
        if selected:
            return selected, ""
        return set(), "no message parts were detected in this backup"

    try:
        rel_parts = file_path.resolve(strict=False).relative_to(backup_dir.resolve(strict=False)).parts
    except ValueError:
        rel_parts = ()
    top = rel_parts[0].casefold() if rel_parts else ""
    parent = file_path.parent.name.casefold()

    in_message = top == "message" or parent == "message"
    in_apkfile = top == "apkfile" or parent == "apkfile"
    in_contact = top == "contact" or parent == "contact"
    in_calllog = top == "calllog" or parent == "calllog"

    if in_message:
        if lower_name == "message.smem":
            selected = {item_id for item_id in all_message_ids if item_id in available_ids}
            if selected:
                return selected, ""
            return set(), "no message parts were detected in this backup"

        selected = message_item_ids_from_filename(file_path.name) & available_ids
        if selected:
            return selected, ""
        if message_item_ids_from_filename(file_path.name):
            return set(), "matching message item was not detected in this backup"
        return set(), "unsupported file for MESSAGE (expected .smem, sms/mms .bk, PART_, or RCSMESSAGE files)"

    if in_apkfile:
        if lower_name.endswith(".data"):
            item_id = f"app_data:{file_path.stem}"
            if item_id in available_ids:
                return {item_id}, ""
            return set(), "application data item was not detected for this package"

        if lower_name.endswith(".penc"):
            item_id = f"app_apk:{file_path.stem}"
            if item_id in available_ids:
                return {item_id}, ""
            return set(), "application APK item was not detected for this package"

        if lower_name.endswith(".apk"):
            app_packages = {
                item_id.split(":", 1)[1] for item_id in available_ids if item_id.startswith("app_apk:")
            }
            package_id = infer_package_from_apk_filename(file_path.name, app_packages)
            if package_id is None:
                return set(), "could not map APK split file to an application package in this backup"
            return {f"app_apk:{package_id}"}, ""

        return set(), "unsupported file for APKFILE (expected .data, .penc, or .apk)"

    if in_contact:
        if lower_name.endswith(".csv") or lower_name == "contact.spbm":
            if "contacts" in available_ids:
                return {"contacts"}, ""
            return set(), "contacts item is not available in this backup"
        return set(), "unsupported file for CONTACT (expected CSV or Contact.spbm)"

    if in_calllog:
        if lower_name == "calllog.zip":
            if "calllog" in available_ids:
                return {"calllog"}, ""
            return set(), "call log item is not available in this backup"
        return set(), "unsupported file for CALLLOG (expected CALLLOG.zip)"

    return set(), "file is not in a supported backup area (MESSAGE/APKFILE/CONTACT/CALLLOG)"
