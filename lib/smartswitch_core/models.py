from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class BackupInfo:
    backup_id: str
    path: Path
    display_name: str = ""
    timestamp: str = ""


@dataclass(slots=True)
class TreeItem:
    id: str
    kind: str
    label: str
    source_path: Path | None = None
    package_id: str = ""
    icon_path: Path | None = None
    children: list["TreeItem"] = field(default_factory=list)


@dataclass(slots=True)
class Inventory:
    backup: BackupInfo
    roots: list[TreeItem]


@dataclass(slots=True)
class ItemUpdate:
    item_id: str
    label: str | None = None
    icon_path: Path | None = None


@dataclass(slots=True)
class EnrichmentPatch:
    backup_display_name: str | None = None
    backup_timestamp: str | None = None
    updates: list[ItemUpdate] = field(default_factory=list)


@dataclass(slots=True)
class ExportResult:
    ok: bool
    outputs: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
