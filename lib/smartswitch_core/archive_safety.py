from __future__ import annotations

from dataclasses import dataclass

MAX_ARCHIVE_MEMBERS = 100_000
MAX_ARCHIVE_OUTPUT_BYTES = 4 * 1024 * 1024 * 1024


class ArchiveLimitError(ValueError):
    pass


@dataclass(slots=True)
class ArchiveBudget:
    max_members: int = MAX_ARCHIVE_MEMBERS
    max_bytes: int = MAX_ARCHIVE_OUTPUT_BYTES
    members: int = 0
    bytes: int = 0

    def add(self, size: int) -> None:
        if size < 0:
            raise ArchiveLimitError("Archive member has a negative size")
        if self.members >= self.max_members:
            raise ArchiveLimitError(
                f"Archive contains more than {self.max_members:,} members"
            )
        if size > self.max_bytes - self.bytes:
            raise ArchiveLimitError(f"Archive expands beyond {self.max_bytes:,} bytes")
        self.members += 1
        self.bytes += size
