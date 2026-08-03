from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath


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


def safe_output_path(root: Path, relative: str) -> Path:
    root_resolved = root.resolve(strict=False)
    candidate = root_resolved.joinpath(*safe_relative_parts(relative)).resolve(strict=False)
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("Unsafe output path") from exc
    return candidate
