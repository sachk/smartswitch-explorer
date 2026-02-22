from __future__ import annotations

import os
import re
from pathlib import Path

from smartswitch_core.additional_detect import (
    detect_call_log_root,
    detect_contacts_root,
    detect_media_root,
    detect_settings_root,
    detect_storage_root,
    detect_watch_root,
)
from smartswitch_core.applications.detect import detect_applications
from smartswitch_core.category_grouping import group_unstructured_entries
from smartswitch_core.messages.detect import detect_message_subitems
from smartswitch_core.models import BackupInfo, Inventory, TreeItem
from smartswitch_core.other_detect import detect_other_entries


MAX_DISCOVERY_DEPTH = 4
SMARTSWITCH_TRAVERSAL_CHAINS: tuple[tuple[str, ...], ...] = (
    ("Samsung", "SmartSwitch"),
    ("Documents", "Samsung", "SmartSwitch"),
    ("Documents", "SmartSwitch"),
)
BACKUP_DIR_NAMES: tuple[str, ...] = ("backup", "Backups")
WINDOWS_ENV_VAR_PATTERN = re.compile(r"%([^%/\\]+)%")
SECONDARY_BACKUP_MARKERS: tuple[str, ...] = (
    "MESSAGE",
    "CONTACT",
    "CALLLOG",
    "Photo",
    "PHOTO_ORIGIN",
    "Video",
    "VIDEO_ORIGIN",
    "GALAXYWATCH_CURRENT",
    "GALAXYWATCH_BACKUP",
    "ReqItemsInfo.json",
)


def expand_input_path(path: str | Path) -> Path:
    """Expand user/home and environment variables for a filesystem path."""
    raw = str(path)
    env_map = {key.casefold(): value for key, value in os.environ.items()}

    def _replace_windows_env(match: re.Match[str]) -> str:
        name = match.group(1).casefold()
        return env_map.get(name, match.group(0))

    expanded = WINDOWS_ENV_VAR_PATTERN.sub(_replace_windows_env, raw)
    expanded = os.path.expandvars(expanded)
    expanded = os.path.expanduser(expanded)
    return Path(expanded)


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve(strict=False)).casefold()
    except OSError:
        return str(path).casefold()


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = _path_key(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _find_child_dir(parent: Path, name: str) -> Path | None:
    if not parent.is_dir():
        return None
    direct = parent / name
    if direct.is_dir():
        return direct
    wanted = name.casefold()
    try:
        for child in parent.iterdir():
            if child.is_dir() and child.name.casefold() == wanted:
                return child
    except OSError:
        return None
    return None


def _follow_existing_segments(root: Path, segments: tuple[str, ...]) -> Path | None:
    if not root.is_dir():
        return None
    current = root
    for segment in segments:
        next_dir = _find_child_dir(current, segment)
        if next_dir is None:
            return None
        current = next_dir
    return current


def _chain_prefix_len(path: Path, chain: tuple[str, ...]) -> int:
    anchor = path.anchor
    parts = [part.casefold() for part in path.parts if part and part != anchor]
    chain_parts = [part.casefold() for part in chain]
    max_len = min(len(parts), len(chain_parts))
    for length in range(max_len, 0, -1):
        if parts[-length:] == chain_parts[:length]:
            return length
    return 0


def _resolve_chain_from_root(root: Path, chain: tuple[str, ...]) -> Path | None:
    prefix_len = _chain_prefix_len(root, chain)
    remaining = chain[prefix_len:] if prefix_len else chain
    return _follow_existing_segments(root, remaining)


def _discover_traversal_roots(root: Path) -> list[Path]:
    results: list[Path] = []
    for chain in SMARTSWITCH_TRAVERSAL_CHAINS:
        smartswitch_root = _resolve_chain_from_root(root, chain)
        if smartswitch_root is None:
            continue
        results.append(smartswitch_root)
        for backup_name in BACKUP_DIR_NAMES:
            backup_root = _find_child_dir(smartswitch_root, backup_name)
            if backup_root is not None:
                results.append(backup_root)
                break
    return _dedupe_paths(results)


def discover_backup_roots() -> list[Path]:
    anchors = _dedupe_paths([Path.home(), expand_input_path("%USERPROFILE%")])
    roots: list[Path] = []
    for anchor in anchors:
        roots.extend(_discover_traversal_roots(anchor))
    return _dedupe_paths([root for root in roots if root.exists()])


def _has_secondary_backup_markers(path: Path) -> bool:
    for marker in SECONDARY_BACKUP_MARKERS:
        candidate = path / marker
        if candidate.is_dir() or candidate.is_file():
            return True
    return False


def is_backup_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    has_items = (path / "MESSAGE" / "Message.smem").exists() or (path / "APKFILE").is_dir()
    if has_items:
        return True
    has_meta = (path / "SmartSwitchBackup.json").exists() or (path / "backupHistoryInfo.xml").exists()
    if not has_meta:
        return False
    return _has_secondary_backup_markers(path)


def _search_roots(root: Path) -> list[Path]:
    expanded = expand_input_path(root)
    traversal_roots = _discover_traversal_roots(expanded)
    if traversal_roots:
        # If a known SmartSwitch path is resolvable, avoid scanning the entire parent tree
        # (for example %USERPROFILE%) to reduce false positives from unrelated folders.
        candidates = list(traversal_roots)
        if is_backup_dir(expanded):
            candidates.append(expanded)
        return _dedupe_paths(candidates)
    return [expanded]


def _bounded_walk_dirs(root: Path, max_depth: int) -> list[Path]:
    if not root.is_dir():
        return []
    root = root.resolve()
    out: list[Path] = []
    for current, dirs, _files in os.walk(root):
        current_path = Path(current)
        rel_parts = len(current_path.relative_to(root).parts)
        if rel_parts > max_depth:
            dirs[:] = []
            continue
        out.append(current_path)
        if rel_parts == max_depth:
            dirs[:] = []
    return out


def find_backups(root: Path) -> list[BackupInfo]:
    seen: set[Path] = set()
    candidates: list[Path] = []

    for search_root in _search_roots(root):
        if is_backup_dir(search_root):
            candidates.append(search_root)

        for path in _bounded_walk_dirs(search_root, MAX_DISCOVERY_DEPTH):
            if is_backup_dir(path):
                candidates.append(path)

    backups: list[BackupInfo] = []
    for path in sorted(candidates):
        rpath = path.resolve(strict=False)
        if rpath in seen:
            continue
        seen.add(rpath)
        backups.append(BackupInfo(backup_id=path.name, path=path))
    return backups


def build_inventory(backup_dir: Path) -> Inventory:
    backup = BackupInfo(backup_id=backup_dir.name, path=backup_dir)

    message_children = detect_message_subitems(backup_dir)
    message_root = TreeItem(
        id="messages",
        kind="messages_root",
        label="Messages",
        source_path=backup_dir / "MESSAGE",
        children=message_children,
    )

    data_items, apk_items = detect_applications(backup_dir)
    app_data_root = TreeItem(
        id="applications_data",
        kind="applications_data_root",
        label="Application Data",
        source_path=backup_dir / "APKFILE",
        children=data_items,
    )
    app_apk_root = TreeItem(
        id="applications_apks",
        kind="applications_apk_root",
        label="Application APKs",
        source_path=backup_dir / "APKFILE",
        children=apk_items,
    )

    roots: list[TreeItem] = [message_root, app_data_root, app_apk_root]

    media_root = detect_media_root(backup_dir)
    if media_root:
        roots.append(media_root)

    watch_root = detect_watch_root(backup_dir)
    if watch_root:
        roots.append(watch_root)

    contacts_root = detect_contacts_root(backup_dir)
    if contacts_root:
        roots.append(contacts_root)

    call_log_root = detect_call_log_root(backup_dir)
    if call_log_root:
        roots.append(call_log_root)

    storage_entries, settings_entries, other_entries = group_unstructured_entries(backup_dir)

    storage_root = detect_storage_root(backup_dir, storage_entries)
    if storage_root:
        roots.append(storage_root)

    settings_root = detect_settings_root(backup_dir, settings_entries)
    if settings_root:
        roots.append(settings_root)

    other_root = detect_other_entries(backup_dir, other_entries)
    if other_root:
        roots.append(other_root)

    return Inventory(backup=backup, roots=roots)
