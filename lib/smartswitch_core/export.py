from __future__ import annotations

import json
from pathlib import Path

from smartswitch_core.privacy import sanitize_manifest_value


def make_export_root(destination: Path, backup_id: str) -> Path:
    root = destination / backup_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def write_manifest(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sanitize_manifest_value(payload), indent=2), encoding="utf-8")
