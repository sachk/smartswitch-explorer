from __future__ import annotations

from dataclasses import dataclass, field
import json
import shutil
import tempfile
from pathlib import Path

from smartswitch_core.file_signatures import (
    DirectFileKind,
    MESSAGE_ITEM_IDS,
    MESSAGE_PART_KIND_TO_KEY,
    classify_direct_file,
    expected_backup_areas_for_kind,
    message_item_ids_from_filename,
)
from smartswitch_core.scan import find_backups, is_backup_dir

SECONDARY_MARKERS_FOR_SCORING: tuple[str, ...] = (
    "MESSAGE",
    "CONTACT",
    "CALLLOG",
    "APKFILE",
    "Photo",
    "PHOTO_ORIGIN",
    "Video",
    "VIDEO_ORIGIN",
    "GALAXYWATCH_CURRENT",
    "GALAXYWATCH_BACKUP",
    "SmartSwitchBackup.json",
    "backupHistoryInfo.xml",
)

__all__ = [
    "DirectImportPlan",
    "DirectImportPlanningResult",
    "cleanup_staged_backup_dirs",
    "fallback_package_from_apk_filename",
    "infer_package_from_apk_filename",
    "map_direct_file_to_item_ids",
    "message_item_ids_from_filename",
    "path_key",
    "plan_direct_import",
    "resolve_backup_for_direct_file",
    "stage_direct_files_as_backup",
]


@dataclass(slots=True)
class DirectImportPlan:
    backup_dir: Path
    backup_files: list[Path]
    staged_backup_dir: Path | None = None
    notices: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DirectImportPlanningResult:
    plan: DirectImportPlan | None
    notices: list[str] = field(default_factory=list)


def path_key(path: Path) -> str:
    try:
        return str(path.resolve(strict=False)).casefold()
    except OSError:
        return str(path).casefold()


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


def _distance_between_paths(left: Path, right: Path) -> int:
    try:
        left_parts = left.resolve(strict=False).parts
    except OSError:
        left_parts = left.parts
    try:
        right_parts = right.resolve(strict=False).parts
    except OSError:
        right_parts = right.parts

    shared = 0
    for lpart, rpart in zip(left_parts, right_parts):
        if lpart.casefold() != rpart.casefold():
            break
        shared += 1
    return (len(left_parts) - shared) + (len(right_parts) - shared)


def _ancestor_distance(file_path: Path, candidate_backup: Path) -> int | None:
    try:
        relative = file_path.resolve(strict=False).relative_to(candidate_backup.resolve(strict=False))
    except ValueError:
        return None
    return max(0, len(relative.parts) - 1)


def _candidate_marker_count(candidate_backup: Path) -> int:
    return sum(1 for marker in SECONDARY_MARKERS_FOR_SCORING if (candidate_backup / marker).exists())


def _candidate_has_expected_area(candidate_backup: Path, kind: DirectFileKind) -> bool:
    areas = expected_backup_areas_for_kind(kind)
    if not areas:
        return False
    return any((candidate_backup / area).exists() for area in areas)


def resolve_backup_for_direct_file(file_path: Path, kind: DirectFileKind) -> tuple[Path | None, str]:
    if kind == DirectFileKind.UNSUPPORTED:
        return None, "unsupported direct file type"

    candidate_backups: dict[str, Path] = {}

    current = file_path.parent
    for _ in range(4):
        if is_backup_dir(current):
            candidate_backups[path_key(current)] = current
        for backup_info in find_backups(current):
            candidate_backups[path_key(backup_info.path)] = backup_info.path
        parent = current.parent
        if parent == current:
            break
        current = parent

    if not candidate_backups:
        return None, "could not locate a Smart Switch backup nearby"

    scored: list[tuple[tuple[int, int, int, int, str], tuple[int, int, int, int], Path]] = []
    for candidate in candidate_backups.values():
        ancestor_distance = _ancestor_distance(file_path, candidate)
        topology_rank = 0 if ancestor_distance is not None else 1
        area_rank = 0 if _candidate_has_expected_area(candidate, kind) else 1
        proximity = (
            ancestor_distance if ancestor_distance is not None else (50 + _distance_between_paths(file_path.parent, candidate))
        )
        marker_rank = -_candidate_marker_count(candidate)
        ranking = (topology_rank, area_rank, proximity, marker_rank)
        scored.append(((*ranking, path_key(candidate)), ranking, candidate))

    scored.sort(key=lambda entry: entry[0])
    best_sort_key, best_rank, best_candidate = scored[0]
    del best_sort_key  # lexical path tiebreaker only used for deterministic ordering

    tied = [candidate for _sort_key, rank, candidate in scored if rank == best_rank]
    if len(tied) > 1:
        names = ", ".join(sorted(path.name for path in tied))
        return None, f"multiple nearby backups matched ({names})"

    return best_candidate, ""


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = path_key(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def plan_direct_import(files: list[Path]) -> DirectImportPlanningResult:
    notices: list[str] = []
    deduped_files = _dedupe_paths(files)

    invalid = [path for path in deduped_files if not path.exists() or not path.is_file()]
    valid_files = [path for path in deduped_files if path.exists() and path.is_file()]
    if not valid_files:
        if invalid:
            notices.extend(f"{path.name}: file does not exist or is not a regular file" for path in invalid)
        return DirectImportPlanningResult(
            plan=None,
            notices=notices or ["No valid files were selected."],
        )

    resolved_groups: dict[str, tuple[Path, list[Path]]] = {}
    supported_files: list[Path] = []
    unresolved_supported: list[tuple[Path, str]] = []

    for file_path in valid_files:
        kind = classify_direct_file(file_path)
        if kind == DirectFileKind.UNSUPPORTED:
            notices.append(f"{file_path.name}: unsupported direct file type")
            continue

        supported_files.append(file_path)
        backup_dir, reason = resolve_backup_for_direct_file(file_path, kind)
        if backup_dir is None:
            unresolved_supported.append((file_path, reason or "could not locate a Smart Switch backup nearby"))
            continue

        key = path_key(backup_dir)
        if key not in resolved_groups:
            resolved_groups[key] = (backup_dir, [])
        resolved_groups[key][1].append(file_path)

    notices.extend(f"{path.name}: file does not exist or is not a regular file" for path in invalid)
    if not supported_files:
        return DirectImportPlanningResult(
            plan=None,
            notices=notices or ["No supported files were selected."],
        )

    if len(resolved_groups) == 1:
        backup_dir, backup_files = next(iter(resolved_groups.values()))
        notices.extend(f"{path.name}: {reason}" for path, reason in unresolved_supported)
        plan = DirectImportPlan(
            backup_dir=backup_dir,
            backup_files=backup_files,
        )
        return DirectImportPlanningResult(plan=plan, notices=notices)

    if len(resolved_groups) > 1:
        staged_backup_dir, staging_warnings = stage_direct_files_as_backup(supported_files)
        plan = DirectImportPlan(
            backup_dir=staged_backup_dir,
            backup_files=supported_files,
            staged_backup_dir=staged_backup_dir,
            notices=[
                "Selected files appear to come from multiple backups; using a temporary import workspace.",
                *staging_warnings,
            ],
        )
        return DirectImportPlanningResult(
            plan=plan,
            notices=notices,
        )

    # No nearby backup found for supported files: stage everything so standalone files remain extractable.
    staged_backup_dir, staging_warnings = stage_direct_files_as_backup(supported_files)
    plan = DirectImportPlan(
        backup_dir=staged_backup_dir,
        backup_files=supported_files,
        staged_backup_dir=staged_backup_dir,
        notices=staging_warnings,
    )
    return DirectImportPlanningResult(
        plan=plan,
        notices=notices,
    )


def cleanup_staged_backup_dirs(paths: list[Path], *, keep: set[str] | None = None) -> list[str]:
    warnings: list[str] = []
    keep_keys = keep or set()
    for directory in _dedupe_paths(paths):
        key = path_key(directory)
        if key in keep_keys:
            continue
        if not directory.exists():
            continue
        if not directory.name.startswith("smartswitch-explorer-direct-"):
            continue
        try:
            shutil.rmtree(directory)
        except OSError as exc:
            warnings.append(f"{directory}: failed to remove temporary import folder ({exc})")
    return warnings


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
        kind = classify_direct_file(file_path)

        if kind == DirectFileKind.MESSAGE_SMEM:
            message_dir.mkdir(parents=True, exist_ok=True)
            if not have_primary_smem:
                have_primary_smem = _copy_file(file_path, message_dir / "Message.smem", warnings)
            else:
                warnings.append(f"{file_path.name}: skipped extra .smem file (only one is used)")
            continue

        if kind in MESSAGE_PART_KIND_TO_KEY:
            message_dir.mkdir(parents=True, exist_ok=True)
            target_name = _unique_name(message_dir, file_path.name)
            _copy_file(file_path, message_dir / target_name, warnings)
            continue

        if kind == DirectFileKind.APP_DATA:
            package_id = file_path.stem
            app_state.setdefault(package_id, {"has_data": False, "has_penc": False, "apk_files": 0})
            target = apk_dir / f"{package_id}.data"
            if target.exists():
                warnings.append(f"{file_path.name}: duplicate app data file for package {package_id}")
                continue
            if _copy_file(file_path, target, warnings):
                app_state[package_id]["has_data"] = True
            continue

        if kind == DirectFileKind.APP_PENC:
            package_id = file_path.stem
            app_state.setdefault(package_id, {"has_data": False, "has_penc": False, "apk_files": 0})
            target = apk_dir / f"{package_id}.penc"
            if target.exists():
                warnings.append(f"{file_path.name}: duplicate app payload file for package {package_id}")
                continue
            if _copy_file(file_path, target, warnings):
                app_state[package_id]["has_penc"] = True
            continue

        if kind == DirectFileKind.APP_APK_SPLIT:
            known_packages = explicit_packages | set(app_state.keys())
            package_id = infer_package_from_apk_filename(file_path.name, known_packages)
            if package_id is None:
                package_id = fallback_package_from_apk_filename(file_path.name)
            app_state.setdefault(package_id, {"has_data": False, "has_penc": False, "apk_files": 0})
            target_name = _unique_name(apk_dir, file_path.name)
            if _copy_file(file_path, apk_dir / target_name, warnings):
                app_state[package_id]["apk_files"] = int(app_state[package_id]["apk_files"]) + 1
            continue

        if kind in {DirectFileKind.CONTACTS_CSV, DirectFileKind.CONTACTS_SPBM}:
            contact_dir.mkdir(parents=True, exist_ok=True)
            target_name = _unique_name(contact_dir, file_path.name)
            _copy_file(file_path, contact_dir / target_name, warnings)
            continue

        if kind == DirectFileKind.CALLLOG_ZIP:
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
    del backup_dir  # intentionally unused in direct mapping
    kind = classify_direct_file(file_path)

    # Allow opening message files from anywhere once associated with a backup.
    if kind == DirectFileKind.MESSAGE_SMEM:
        selected = {item_id for item_id in MESSAGE_ITEM_IDS if item_id in available_ids}
        if selected:
            return selected, ""
        return set(), "no message parts were detected in this backup"

    message_item_ids = message_item_ids_from_filename(file_path.name)
    if message_item_ids:
        selected = message_item_ids & available_ids
        if selected:
            return selected, ""
        return set(), "matching message item was not detected in this backup"

    if kind == DirectFileKind.APP_DATA:
        item_id = f"app_data:{file_path.stem}"
        if item_id in available_ids:
            return {item_id}, ""
        return set(), "application data item was not detected for this package"

    if kind == DirectFileKind.APP_PENC:
        item_id = f"app_apk:{file_path.stem}"
        if item_id in available_ids:
            return {item_id}, ""
        return set(), "application APK item was not detected for this package"

    if kind == DirectFileKind.APP_APK_SPLIT:
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

    if kind in {DirectFileKind.CONTACTS_SPBM, DirectFileKind.CONTACTS_CSV}:
        if "contacts" in available_ids:
            return {"contacts"}, ""
        return set(), "contacts item is not available in this backup"

    if kind == DirectFileKind.CALLLOG_ZIP:
        if "calllog" in available_ids:
            return {"calllog"}, ""
        return set(), "call log item is not available in this backup"

    return set(), "unsupported direct file (expected message/app/contact/calllog payloads)"
