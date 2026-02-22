from __future__ import annotations

import os
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from smartswitch_core.file_signatures import (
    MESSAGE_PART_ATTACHMENTS,
    MESSAGE_PART_MMS,
    MESSAGE_PART_RCS,
    MESSAGE_PART_SMS,
    message_part_keys_from_filename,
)
from smartswitch_core.models import Inventory, TreeItem


@dataclass(slots=True)
class InventorySizeResult:
    total_bytes: int
    item_sizes: dict[str, int]


def format_bytes(value: int) -> str:
    amount = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.1f} {unit}"
        amount /= 1024.0
    return "0 B"


def _set_background_io_priority() -> None:
    # Windows supports explicit per-thread background priority (CPU + I/O).
    if sys.platform != "win32":
        return
    try:
        import ctypes

        THREAD_MODE_BACKGROUND_BEGIN = 0x00010000
        handle = ctypes.windll.kernel32.GetCurrentThread()
        ctypes.windll.kernel32.SetThreadPriority(handle, THREAD_MODE_BACKGROUND_BEGIN)
    except Exception:
        return


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve(strict=False)).casefold()
    except OSError:
        return str(path).casefold()


def _file_size(path: Path) -> int:
    try:
        if path.is_file():
            return int(path.stat().st_size)
    except OSError:
        return 0
    return 0


def _path_size(path: Path, cache: dict[str, int]) -> int:
    key = _path_key(path)
    if key in cache:
        return cache[key]

    if path.is_file():
        size = _file_size(path)
        cache[key] = size
        return size

    if not path.is_dir():
        cache[key] = 0
        return 0

    total = 0
    for root, _dirs, files in os.walk(path):
        root_path = Path(root)
        for name in files:
            total += _file_size(root_path / name)
    cache[key] = total
    return total


def _sum_paths(paths: list[Path], cache: dict[str, int]) -> int:
    total = 0
    seen: set[str] = set()
    for path in paths:
        key = _path_key(path)
        if key in seen:
            continue
        seen.add(key)
        total += _path_size(path, cache)
    return total


def _message_part_sizes(message_dir: Path) -> dict[str, int]:
    out = {"sms": 0, "mms": 0, "attachments": 0, "rcs": 0}
    if not message_dir.is_dir():
        return out

    def add_entry(name: str, size: int) -> None:
        parts = message_part_keys_from_filename(name)
        if MESSAGE_PART_SMS in parts:
            out["sms"] += size
        if MESSAGE_PART_MMS in parts:
            out["mms"] += size
        if MESSAGE_PART_ATTACHMENTS in parts:
            out["attachments"] += size
        if MESSAGE_PART_RCS in parts:
            out["rcs"] += size

    try:
        for path in message_dir.iterdir():
            if path.is_file():
                add_entry(path.name, _file_size(path))
    except OSError:
        pass

    smem_path = message_dir / "Message.smem"
    if smem_path.exists() and zipfile.is_zipfile(smem_path):
        try:
            with zipfile.ZipFile(smem_path) as archive:
                for info in archive.infolist():
                    add_entry(PurePosixPath(info.filename).name, int(info.file_size))
        except (OSError, zipfile.BadZipFile):
            pass

    return out


def _sum_children(item: TreeItem, item_sizes: dict[str, int], default: int = 0) -> int:
    if not item.children:
        return default
    return sum(item_sizes.get(child.id, 0) for child in item.children)


def _compute_item_size(
    item: TreeItem,
    backup_dir: Path,
    cache: dict[str, int],
    message_sizes: dict[str, int],
    app_data_total: int,
    app_apk_total: int,
    photo_total: int,
    video_total: int,
    item_sizes: dict[str, int],
) -> int:
    for child in item.children:
        _compute_item_size(
            child,
            backup_dir,
            cache,
            message_sizes,
            app_data_total,
            app_apk_total,
            photo_total,
            video_total,
            item_sizes,
        )

    kind = item.kind
    size = 0

    if kind == "message_subitem":
        part = item.id.split(":", 1)[1] if ":" in item.id else ""
        size = message_sizes.get(part, 0)
    elif kind == "messages_root":
        fallback = _path_size(backup_dir / "MESSAGE", cache)
        size = _sum_children(item, item_sizes, fallback)
    elif kind == "applications_data_root":
        size = _sum_children(item, item_sizes, app_data_total)
    elif kind == "applications_apk_root":
        size = _sum_children(item, item_sizes, app_apk_total)
    elif kind == "app_data":
        size = _file_size(item.source_path) if item.source_path else 0
    elif kind == "app_apk":
        size = _file_size(item.source_path) if item.source_path else 0
    elif kind == "media_photos":
        size = photo_total
    elif kind == "media_videos":
        size = video_total
    elif kind == "media_root":
        size = _sum_children(item, item_sizes, photo_total + video_total)
    elif kind in {"watch_root", "storage_root", "settings_root", "other_root"}:
        fallback = _path_size(item.source_path, cache) if item.source_path else 0
        size = _sum_children(item, item_sizes, fallback)
    elif kind == "watch_current":
        size = _path_size(backup_dir / "GALAXYWATCH_CURRENT", cache)
    elif kind == "watch_backup":
        size = _path_size(backup_dir / "GALAXYWATCH_BACKUP", cache)
    elif kind == "contacts":
        size = _path_size(backup_dir / "CONTACT", cache)
    elif kind == "calllog":
        size = _path_size(backup_dir / "CALLLOG", cache)
    else:
        if item.children:
            size = _sum_children(item, item_sizes)
        elif item.source_path is not None:
            size = _path_size(item.source_path, cache)

    item_sizes[item.id] = max(0, int(size))
    return item_sizes[item.id]


def compute_inventory_sizes(backup_dir: Path, inventory: Inventory) -> InventorySizeResult:
    _set_background_io_priority()

    cache: dict[str, int] = {}
    item_sizes: dict[str, int] = {}

    apk_dir = backup_dir / "APKFILE"
    app_data_total = _sum_paths(list(apk_dir.glob("*.data")), cache) if apk_dir.is_dir() else 0
    app_apk_total = _sum_paths(list(apk_dir.glob("*.penc")), cache) if apk_dir.is_dir() else 0

    photo_total = _sum_paths([backup_dir / "Photo", backup_dir / "PHOTO_ORIGIN"], cache)
    video_total = _sum_paths([backup_dir / "Video", backup_dir / "VIDEO_ORIGIN"], cache)
    message_sizes = _message_part_sizes(backup_dir / "MESSAGE")

    for root in inventory.roots:
        _compute_item_size(
            root,
            backup_dir,
            cache,
            message_sizes,
            app_data_total,
            app_apk_total,
            photo_total,
            video_total,
            item_sizes,
        )

    total_bytes = _path_size(backup_dir, cache)
    return InventorySizeResult(total_bytes=total_bytes, item_sizes=item_sizes)
