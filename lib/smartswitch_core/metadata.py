from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from smartswitch_core.models import EnrichmentPatch, Inventory, ItemUpdate


def _parse_app_names(backup_dir: Path) -> dict[str, str]:
    app_list = backup_dir / "APKFILE" / "AppList.json"
    if not app_list.exists():
        return {}
    try:
        obj = json.loads(app_list.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

    names: dict[str, str] = {}
    for row in obj.get("Apks", []):
        pkg = row.get("ApkPkgName")
        name = row.get("ApkName")
        if pkg and name:
            names[pkg] = name
    return names


def _parse_backup_display_name(backup_dir: Path) -> tuple[str | None, str | None]:
    json_path = backup_dir / "SmartSwitchBackup.json"
    if json_path.exists():
        try:
            obj = json.loads(json_path.read_text(encoding="utf-8"))
            display = obj.get("DisplayName") or obj.get("ModelName")
            timestamp = obj.get("SavedTime")
            if display or timestamp:
                return display, timestamp
        except (OSError, ValueError):
            pass

    xml_path = backup_dir / "backupHistoryInfo.xml"
    if not xml_path.exists():
        return None, None

    try:
        root = ET.fromstring(xml_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, ET.ParseError):
        return None, None

    ns = {"k": "Kies.Common.Data"}
    display = root.findtext(".//k:UserInputName", namespaces=ns)
    timestamp = root.findtext(".//k:SavedTime", namespaces=ns)
    return display, timestamp


def enrich_inventory(backup_dir: Path, inventory: Inventory) -> EnrichmentPatch:
    patch = EnrichmentPatch()

    app_names = _parse_app_names(backup_dir)
    display_name, timestamp = _parse_backup_display_name(backup_dir)
    patch.backup_display_name = display_name
    patch.backup_timestamp = timestamp

    apk_dir = backup_dir / "APKFILE"

    for root in inventory.roots:
        for item in root.children:
            if not item.package_id:
                continue
            pretty = app_names.get(item.package_id)
            icon_path = apk_dir / f"{item.package_id}.png"
            label = f"{pretty} ({item.package_id})" if pretty else item.package_id
            patch.updates.append(
                ItemUpdate(
                    item_id=item.id,
                    label=label,
                    icon_path=icon_path if icon_path.exists() else None,
                )
            )

    return patch
