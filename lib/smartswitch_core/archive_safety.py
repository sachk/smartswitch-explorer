from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

MAX_ARCHIVE_MEMBERS = 100_000
MAX_APK_OUTPUT_BYTES = 4 * 1024 * 1024 * 1024
MIN_FREE_DISK_BYTES = 512 * 1024 * 1024
DISK_CHECK_INTERVAL_BYTES = 64 * 1024 * 1024


class ArchiveLimitError(ValueError):
    pass


@dataclass(slots=True)
class ArchiveBudget:
    max_members: int = MAX_ARCHIVE_MEMBERS
    max_bytes: int | None = None
    members: int = field(init=False, default=0)
    bytes: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        if self.max_members <= 0:
            raise ValueError("max_members must be positive")
        if self.max_bytes is not None and self.max_bytes < 0:
            raise ValueError("max_bytes must not be negative")

    def add(self, size: int) -> None:
        if size < 0:
            raise ArchiveLimitError("Archive member has a negative size")
        if self.members >= self.max_members:
            raise ArchiveLimitError(
                f"Archive contains more than {self.max_members:,} members"
            )
        if self.max_bytes is not None and size > self.max_bytes - self.bytes:
            raise ArchiveLimitError(f"Archive expands beyond {self.max_bytes:,} bytes")
        self.members += 1
        self.bytes += size


@dataclass(slots=True)
class DiskSpaceGuard:
    directory: Path
    reserve_bytes: int = MIN_FREE_DISK_BYTES
    check_interval_bytes: int = DISK_CHECK_INTERVAL_BYTES
    _available_bytes: int = field(init=False, repr=False)
    _bytes_since_check: int = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.reserve_bytes < 0:
            raise ValueError("reserve_bytes must not be negative")
        if self.check_interval_bytes <= 0:
            raise ValueError("check_interval_bytes must be positive")
        self._refresh()

    def _refresh(self) -> None:
        free = shutil.disk_usage(self.directory).free
        self._available_bytes = max(0, free - self.reserve_bytes)
        self._bytes_since_check = 0

    def consume(self, size: int) -> None:
        if size < 0:
            raise ArchiveLimitError("Output size must not be negative")
        if (
            self._bytes_since_check >= self.check_interval_bytes
            or size > self._available_bytes
        ):
            self._refresh()
        if size > self._available_bytes:
            raise ArchiveLimitError(
                f"Output would use the final {self.reserve_bytes:,} bytes of free disk space"
            )
        self._available_bytes -= size
        self._bytes_since_check += size
