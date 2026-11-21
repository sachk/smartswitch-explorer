from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

_WINDOWS_INVALID_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_TRAILING_CHARACTERS = " ."
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


def safe_relative_parts(relative: str) -> tuple[str, ...]:
    normalized = relative.replace("\\", "/")
    if not normalized:
        raise ValueError("Empty output path")

    windows_path = PureWindowsPath(relative)
    if windows_path.drive or windows_path.is_absolute():
        raise ValueError("Absolute output path")

    posix_path = PurePosixPath(normalized)
    if posix_path.is_absolute():
        raise ValueError("Absolute output path")

    parts = posix_path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Unsafe output path")
    return tuple(str(part) for part in parts)


def sanitize_windows_component(part: str) -> str:
    """Return *part* as a name the Windows file APIs can create.

    NTFS cannot store ``< > : " / \\ | ? *`` or control characters, silently
    drops trailing dots and spaces, and reserves device names such as ``CON`` or
    ``COM1``.  Archive members from Android application data can legitimately
    contain those characters (Firebase identifiers are a common source), so the
    name is rewritten deterministically before it reaches the file system.
    """
    cleaned = _WINDOWS_INVALID_CHARACTERS.sub("_", part).rstrip(
        _WINDOWS_TRAILING_CHARACTERS
    )
    if not cleaned or cleaned in {".", ".."}:
        cleaned = "_"
    if cleaned.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned


def _with_collision_suffix(name: str, suffix: int) -> str:
    stem, dot, extension = name.rpartition(".")
    if not dot or not stem:
        return f"{name}~{suffix}"
    return f"{stem}~{suffix}.{extension}"


def safe_output_path(
    root: Path,
    relative: str,
    *,
    sanitize_windows_names: bool | None = None,
) -> Path:
    """Resolve *relative* below *root*, rejecting traversal and absolute paths.

    On Windows, names the file system cannot create are sanitized first; pass
    ``sanitize_windows_names=False`` to keep the raw name or ``True`` to force
    sanitization on another platform (used by tests).
    """
    parts = safe_relative_parts(relative)
    if sanitize_windows_names is None:
        sanitize_windows_names = os.name == "nt"
    if sanitize_windows_names:
        parts = tuple(sanitize_windows_component(part) for part in parts)
    try:
        root_resolved = root.resolve(strict=False)
        candidate = root_resolved.joinpath(*parts).resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ValueError("Output path could not be resolved safely") from exc
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("Unsafe output path") from exc
    return candidate


class SafeOutputPaths:
    """Allocate distinct output paths for archive members.

    ``path_for`` applies the same validation and Windows sanitization as
    :func:`safe_output_path`.  When two different member names resolve to the
    same file, the later one receives a ``~2``, ``~3``... suffix instead of
    overwriting the earlier file.  ``mapping`` records every renamed member so
    an export manifest can preserve the original name.
    """

    def __init__(
        self,
        root: Path,
        *,
        sanitize_windows_names: bool | None = None,
    ) -> None:
        self._root = Path(root)
        if sanitize_windows_names is None:
            sanitize_windows_names = os.name == "nt"
        self._sanitize = sanitize_windows_names
        self._assigned: dict[str, str] = {}
        self._directories: dict[tuple[str, ...], str] = {(): ""}
        self._claimed: dict[str, set[str]] = {"": set()}
        self.mapping: dict[str, str] = {}

    def path_for(self, relative: str, *, is_directory: bool = False) -> Path:
        raw_parts = safe_relative_parts(relative)
        raw_key = "/".join(raw_parts)
        assigned = self._assigned.get(raw_key)
        if assigned is None and raw_parts in self._directories:
            assigned = self._directories[raw_parts]
            self._assigned[raw_key] = assigned
            if assigned != raw_key:
                self.mapping[relative] = assigned
        if assigned is None:
            assigned_parts: list[str] = []
            for index, raw_part in enumerate(raw_parts):
                raw_prefix = raw_parts[: index + 1]
                if raw_prefix in self._directories:
                    assigned_parts = self._directories[raw_prefix].split("/")
                    continue
                assigned_parent = self._directories[raw_parts[:index]]
                name = (
                    sanitize_windows_component(raw_part)
                    if self._sanitize
                    else raw_part
                )
                assigned_part = self._claim(assigned_parent, name)
                assigned_parts.append(assigned_part)
                if index < len(raw_parts) - 1 or is_directory:
                    self._directories[raw_prefix] = "/".join(assigned_parts)
            assigned = "/".join(assigned_parts)
            self._assigned[raw_key] = assigned
            if assigned != raw_key:
                self.mapping[relative] = assigned
        return safe_output_path(
            self._root,
            assigned,
            sanitize_windows_names=False,
        )

    def _claim(self, assigned_parent: str, name: str) -> str:
        claimed = self._claimed.setdefault(assigned_parent, set())
        candidate = name
        suffix = 1
        key = candidate.casefold() if self._sanitize else candidate
        while key in claimed:
            suffix += 1
            candidate = _with_collision_suffix(name, suffix)
            key = candidate.casefold() if self._sanitize else candidate
        claimed.add(key)
        return candidate
