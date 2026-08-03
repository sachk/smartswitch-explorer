from __future__ import annotations

import re
from pathlib import Path
from typing import Any


# Paths may contain spaces, so redact from an absolute-path marker to the end of
# its diagnostic line. This deliberately favors privacy over preserving suffixes.
_WINDOWS_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![\w])(?:[A-Z]:[\\/]|\\\\)[^\r\n]*",
    re.IGNORECASE,
)
_POSIX_ABSOLUTE_PATH_RE = re.compile(r"(?<![\w./])/(?![/\s])[^\r\n]*")


def redact_absolute_paths(text: str) -> str:
    sanitized = _WINDOWS_ABSOLUTE_PATH_RE.sub("<path>", str(text))
    return _POSIX_ABSOLUTE_PATH_RE.sub("<path>", sanitized)


def sanitize_manifest_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_absolute_paths(value)
    if isinstance(value, Path):
        return "<path>"
    if isinstance(value, dict):
        return {key: sanitize_manifest_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [sanitize_manifest_value(child) for child in value]
    if isinstance(value, tuple):
        return [sanitize_manifest_value(child) for child in value]
    return value
