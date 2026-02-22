from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

MESSAGE_ITEM_IDS = {"messages:sms", "messages:mms", "messages:attachments", "messages:rcs"}


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


def fallback_package_from_apk_filename(file_name: str) -> str:
    stem = Path(file_name).stem
    split_marker = "_split"
    if split_marker in stem:
        prefix = stem.split(split_marker, 1)[0]
        if prefix:
            return prefix
    return stem or "unknown.app"


def _classify_direct_file(file_path: Path) -> str:
    lower = file_path.name.casefold()
    if lower.endswith(".smem"):
        return "message_smem"
    if message_item_ids_from_filename(file_path.name):
        return "message_part"
    if lower.endswith(".data"):
        return "app_data"
    if lower.endswith(".penc"):
        return "app_penc"
    if lower.endswith(".apk"):
        return "app_apk_split"
    if lower == "contact.spbm" or lower.endswith(".csv"):
        return "contacts"
    if lower == "calllog.zip" or (lower.endswith(".zip") and file_path.parent.name.casefold() == "calllog"):
        return "calllog_zip"
    return "unsupported"


def _unique_name(destination_dir: Path, name: str) -> str:
    candidate = name
    stem = Path(name).stem
    suffix = Path(name).suffix
    index = 1
    while (destination_dir / candidate).exists():
        candidate = f"{stem}_{index}{suffix}"
        index += 1
    return candidate


def _copy_file(source: Path, target: Path, warnings: list[str]) -> bool:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return True
    except OSError as exc:
        warnings.append(f"{source.name}: failed to copy file ({exc})")
        return False


def stage_direct_files_as_backup(files: list[Path]) -> tuple[Path, list[str]]:
    root = Path(tempfile.mkdtemp(prefix="smartswitch-explorer-direct-"))
    warnings: list[str] = []

    message_dir = root / "MESSAGE"
    apk_dir = root / "APKFILE"
    contact_dir = root / "CONTACT"
    calllog_dir = root / "CALLLOG"
    apk_dir.mkdir(parents=True, exist_ok=True)

    try:
        (root / "SmartSwitchBackup.json").write_text(
            json.dumps(
                {
                    "DisplayName": "Direct File Import",
                    "SourceFiles": [str(path) for path in files],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass

    explicit_packages = {
        path.stem for path in files if path.name.casefold().endswith(".data") or path.name.casefold().endswith(".penc")
    }
    app_state: dict[str, dict[str, int | bool]] = {}
    have_calllog_zip = False
    have_primary_smem = False

    for file_path in files:
        kind = _classify_direct_file(file_path)

        if kind == "message_smem":
            message_dir.mkdir(parents=True, exist_ok=True)
            if not have_primary_smem:
                have_primary_smem = _copy_file(file_path, message_dir / "Message.smem", warnings)
            else:
                warnings.append(f"{file_path.name}: skipped extra .smem file (only one is used)")
            continue

        if kind == "message_part":
            message_dir.mkdir(parents=True, exist_ok=True)
            target_name = _unique_name(message_dir, file_path.name)
            _copy_file(file_path, message_dir / target_name, warnings)
            continue

        if kind == "app_data":
            package_id = file_path.stem
            app_state.setdefault(package_id, {"has_data": False, "has_penc": False, "apk_files": 0})
            target = apk_dir / f"{package_id}.data"
            if target.exists():
                warnings.append(f"{file_path.name}: duplicate app data file for package {package_id}")
                continue
            if _copy_file(file_path, target, warnings):
                app_state[package_id]["has_data"] = True
            continue

        if kind == "app_penc":
            package_id = file_path.stem
            app_state.setdefault(package_id, {"has_data": False, "has_penc": False, "apk_files": 0})
            target = apk_dir / f"{package_id}.penc"
            if target.exists():
                warnings.append(f"{file_path.name}: duplicate app payload file for package {package_id}")
                continue
            if _copy_file(file_path, target, warnings):
                app_state[package_id]["has_penc"] = True
            continue

        if kind == "app_apk_split":
            known_packages = explicit_packages | set(app_state.keys())
            package_id = infer_package_from_apk_filename(file_path.name, known_packages)
            if package_id is None:
                package_id = fallback_package_from_apk_filename(file_path.name)
            app_state.setdefault(package_id, {"has_data": False, "has_penc": False, "apk_files": 0})
            target_name = _unique_name(apk_dir, file_path.name)
            if _copy_file(file_path, apk_dir / target_name, warnings):
                app_state[package_id]["apk_files"] = int(app_state[package_id]["apk_files"]) + 1
            continue

        if kind == "contacts":
            contact_dir.mkdir(parents=True, exist_ok=True)
            target_name = _unique_name(contact_dir, file_path.name)
            _copy_file(file_path, contact_dir / target_name, warnings)
            continue

        if kind == "calllog_zip":
            calllog_dir.mkdir(parents=True, exist_ok=True)
            if have_calllog_zip:
                warnings.append(f"{file_path.name}: skipped extra call log zip (already have CALLLOG.zip)")
                continue
            if _copy_file(file_path, calllog_dir / "CALLLOG.zip", warnings):
                have_calllog_zip = True
            continue

        warnings.append(f"{file_path.name}: unsupported direct file type")

    for package_id, state in app_state.items():
        if int(state["apk_files"]) <= 0:
            continue
        if bool(state["has_penc"]):
            continue
        placeholder = apk_dir / f"{package_id}.penc"
        if placeholder.exists():
            continue
        try:
            placeholder.write_bytes(b"")
        except OSError as exc:
            warnings.append(f"{package_id}: failed to create placeholder .penc ({exc})")

    return root, warnings


def map_direct_file_to_item_ids(
    file_path: Path,
    backup_dir: Path,
    available_ids: set[str],
) -> tuple[set[str], str]:
    lower_name = file_path.name.casefold()

    # Allow opening message files from anywhere once associated with a backup.
    if lower_name.endswith(".smem"):
        selected = {item_id for item_id in MESSAGE_ITEM_IDS if item_id in available_ids}
        if selected:
            return selected, ""
        return set(), "no message parts were detected in this backup"

    message_ids = message_item_ids_from_filename(file_path.name)
    if message_ids:
        selected = message_ids & available_ids
        if selected:
            return selected, ""
        return set(), "matching message item was not detected in this backup"

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
        app_packages = {item_id.split(":", 1)[1] for item_id in available_ids if item_id.startswith("app_apk:")}
        package_id = infer_package_from_apk_filename(file_path.name, app_packages)
        if package_id is None and len(app_packages) == 1:
            package_id = next(iter(app_packages))
        if package_id is None:
            fallback = fallback_package_from_apk_filename(file_path.name)
            candidate = f"app_apk:{fallback}"
            if candidate in available_ids:
                return {candidate}, ""
            return set(), "could not map APK split file to an application package in this backup"
        return {f"app_apk:{package_id}"}, ""

    if lower_name == "contact.spbm" or lower_name.endswith(".csv"):
        if "contacts" in available_ids:
            return {"contacts"}, ""
        return set(), "contacts item is not available in this backup"

    if lower_name == "calllog.zip" or (lower_name.endswith(".zip") and file_path.parent.name.casefold() == "calllog"):
        if "calllog" in available_ids:
            return {"calllog"}, ""
        return set(), "call log item is not available in this backup"

    return set(), "unsupported direct file (expected message/app/contact/calllog payloads)"
