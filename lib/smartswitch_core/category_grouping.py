from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class GroupedEntry:
    name: str
    path: Path
    label: str


def _normalize(name: str) -> str:
    return "".join(ch for ch in name.upper() if ch.isalnum())


CORE_HANDLED_TOP_LEVEL = {
    "MESSAGE",
    "APKFILE",
    "GALAXYWATCH_CURRENT",
    "GALAXYWATCH_BACKUP",
    "CONTACT",
    "CALLLOG",
}

MEDIA_SOURCE_TOP_LEVEL = {
    "PHOTO_ORIGIN",
    "VIDEO_ORIGIN",
    "Photo",
    "Video",
}

STORAGE_TOP_LEVEL = {
    "Docs",
    "Downloads",
    "Download",
    "DOCUMENT",
    "ETCFILE",
    "ETCFOLDER",
    "MYFILES",
    "Music",
    "MUSIC",
}

SETTINGS_TOP_LEVEL = {
    "CONTACTSETTING",
    "CALLOGSETTING",
    "DIALERSETTING",
    "GLOBALSETTINGS",
    "DISPLAYMANAGER",
    "NOTIFICATION",
    "DEFAULTAPPS",
    "DISABLEDAPPS",
    "WALLPAPER_SETTING",
    "PHOTO_EDITOR_SETTING",
    "VIDEO_PLAYER_SETTING",
    "SAFETYSETTING",
    "HOTSPOTSETTING",
    "WIFICONFIG",
    "RUNTIMEPERMISION",
    "QUICKPANEL",
    "TOOLSEDGEPANEL",
    "TASKEDGEPANEL",
    "APPSEDGEPANEL",
    "DEVICECONTROLS",
    "PEOPLESTRIPE",
    "COCKTAILBARSERVICE",
    "SHORTCUT",
    "RINGTONE",
    "EMERGENCYSOS",
    "VIDEO_CALL_EFFECTS",
    "VOLUME_MONITOR",
    "PHOTO_SCREEN_SAVER",
    "DUALCLOCKWIDGET",
    "WEATHERSERVICE",
    "GALLERYSETTING",
}

PRETTY_NAME_OVERRIDES = {
    "CONTACTSETTING": "Contacts Settings",
    "CALLOGSETTING": "Call Log Settings",
    "DIALERSETTING": "Dialer Settings",
    "GLOBALSETTINGS": "Global Settings",
    "DISPLAYMANAGER": "Display Settings",
    "WALLPAPER_SETTING": "Wallpaper Settings",
    "PHOTO_EDITOR_SETTING": "Photo Editor Settings",
    "VIDEO_PLAYER_SETTING": "Video Player Settings",
    "SAFETYSETTING": "Safety Settings",
    "HOTSPOTSETTING": "Hotspot Settings",
    "WIFICONFIG": "Wi-Fi Settings",
    "RUNTIMEPERMISION": "Runtime Permissions",
    "QUICKPANEL": "Quick Panel Settings",
    "TOOLSEDGEPANEL": "Tools Edge Panel",
    "TASKEDGEPANEL": "Tasks Edge Panel",
    "APPSEDGEPANEL": "Apps Edge Panel",
    "DEVICECONTROLS": "Device Controls",
    "PEOPLESTRIPE": "People Stripe",
    "COCKTAILBARSERVICE": "Edge Panels Service",
    "SHORTCUT": "Shortcuts",
    "RINGTONE": "Ringtones",
    "EMERGENCYSOS": "Emergency SOS",
    "VIDEO_CALL_EFFECTS": "Video Call Effects",
    "VOLUME_MONITOR": "Volume Monitor",
    "PHOTO_SCREEN_SAVER": "Photo Screen Saver",
    "DUALCLOCKWIDGET": "Dual Clock Widget",
    "WEATHERSERVICE": "Weather Service",
    "GALLERYSETTING": "Gallery Settings",
    "DEFAULTAPPS": "Default Apps",
    "DISABLEDAPPS": "Disabled Apps",
    "APKDENYLIST": "APK Deny List",
    "BIXBYVISION": "Bixby Vision",
    "APPSEDGEPANEL": "Apps Edge Panel",
    "TOOLSEDGEPANEL": "Tools Edge Panel",
    "TASKEDGEPANEL": "Tasks Edge Panel",
    "CALENDER": "Calendar",
    "ALARM": "Alarm",
    "CAMERA": "Camera",
    "NOTIFICATION": "Notifications",
    "DOCUMENT": "Documents",
    "DOCS": "Documents",
    "ETCFILE": "Internal Storage Files",
    "ETCFOLDER": "External Storage Files",
    "MYFILES": "My Files",
    "MUSIC": "Music",
}

_ACRONYMS = {"APK", "USB", "RCS", "MMS", "SMS", "UI", "SOS", "WIFI"}
_METADATA_STORAGE_TYPES = {"DOCUMENT", "ETCFILE", "ETCFOLDER", "MUSIC", "MYFILES"}
_METADATA_SETTINGS_TYPES = {
    "CONTACTSETTING",
    "CALLOGSETTING",
    "DIALERSETTING",
    "GLOBALSETTINGS",
    "WALLPAPERSETTING",
    "WALLPAPERSETTING",
    "WIFICONFIG",
    "HOTSPOTSETTING",
    "DISPLAYMANAGER",
}
_STORAGE_NORMALIZED = {_normalize(name) for name in STORAGE_TOP_LEVEL}
_SETTINGS_NORMALIZED = {_normalize(name) for name in SETTINGS_TOP_LEVEL}
_METADATA_STORAGE_NORMALIZED = {_normalize(name) for name in _METADATA_STORAGE_TYPES}
_METADATA_SETTINGS_NORMALIZED = {_normalize(name) for name in _METADATA_SETTINGS_TYPES}


def _split_identifier(name: str) -> list[str]:
    if "_" in name:
        return [part for part in name.split("_") if part]
    if name.isupper():
        return [name]
    return [part for part in re.split(r"(?<!^)(?=[A-Z])", name) if part]


def prettify_category_name(name: str) -> str:
    key = name.upper()
    if key in PRETTY_NAME_OVERRIDES:
        return PRETTY_NAME_OVERRIDES[key]

    tokens = _split_identifier(name)
    out: list[str] = []
    for token in tokens:
        token_up = token.upper()
        if token_up in _ACRONYMS:
            out.append(token_up)
        elif token_up.endswith("SETTING") and token_up != "SETTING":
            base = token_up[:-7]
            if base:
                out.append(base.title())
            out.append("Settings")
        else:
            out.append(token.capitalize())
    return " ".join(out).replace("  ", " ").strip() or name


def _load_req_item_types(backup_dir: Path) -> set[str]:
    path = backup_dir / "ReqItemsInfo.json"
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    items = payload.get("ListItems")
    if not isinstance(items, list):
        return set()
    out: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = item.get("Type")
        if isinstance(item_type, str) and item_type:
            out.add(_normalize(item_type))
    return out


def _is_storage(name: str, normalized: str, req_types: set[str]) -> bool:
    if name in STORAGE_TOP_LEVEL:
        return True
    if normalized in _STORAGE_NORMALIZED:
        return True
    if normalized in req_types and normalized in _METADATA_STORAGE_NORMALIZED:
        return True
    return False


def _is_settings(name: str, normalized: str, req_types: set[str]) -> bool:
    if name in SETTINGS_TOP_LEVEL:
        return True
    if normalized in _SETTINGS_NORMALIZED:
        return True
    if "SETTING" in normalized or "CONFIG" in normalized or "PERMISION" in normalized or "PERMISSION" in normalized:
        return True
    if normalized in req_types and normalized in _METADATA_SETTINGS_NORMALIZED:
        return True
    return False


def group_unstructured_entries(backup_dir: Path) -> tuple[list[GroupedEntry], list[GroupedEntry], list[GroupedEntry]]:
    try:
        entries = sorted((entry for entry in backup_dir.iterdir() if not entry.name.startswith(".")), key=lambda p: p.name.lower())
    except OSError:
        return [], [], []

    req_types = _load_req_item_types(backup_dir)
    core_norms = {_normalize(name) for name in CORE_HANDLED_TOP_LEVEL}
    media_norms = {_normalize(name) for name in MEDIA_SOURCE_TOP_LEVEL}

    storage: list[GroupedEntry] = []
    settings: list[GroupedEntry] = []
    other: list[GroupedEntry] = []
    seen_other: set[str] = set()

    for entry in entries:
        name = entry.name
        normalized = _normalize(name)
        if normalized in core_norms or normalized in media_norms:
            continue

        label = prettify_category_name(name)
        grouped = GroupedEntry(name=name, path=entry, label=label)

        if _is_storage(name, normalized, req_types):
            storage.append(grouped)
            continue

        if _is_settings(name, normalized, req_types):
            settings.append(grouped)
            continue

        # Drop near-duplicates in "Other Backup Data" by normalized key.
        if normalized in seen_other:
            continue
        seen_other.add(normalized)
        other.append(grouped)

    return storage, settings, other
