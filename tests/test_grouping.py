from __future__ import annotations

from pathlib import Path

from smartswitch_core.category_grouping import group_unstructured_entries, prettify_category_name


def test_group_unstructured_entries_storage_settings_and_other(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    backup.mkdir(parents=True)
    (backup / "MESSAGE").mkdir()
    (backup / "APKFILE").mkdir()
    (backup / "PHOTO_ORIGIN").mkdir()
    (backup / "Photo").mkdir()
    (backup / "Docs").mkdir()
    (backup / "DIALERSETTING").mkdir()
    (backup / "ALARM").mkdir()

    storage, settings, other = group_unstructured_entries(backup)

    assert {entry.name for entry in storage} == {"Docs"}
    assert {entry.name for entry in settings} == {"DIALERSETTING"}
    assert {entry.name for entry in other} == {"ALARM"}


def test_group_unstructured_entries_dedupes_other_by_normalized_name(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    backup.mkdir(parents=True)
    (backup / "foo").mkdir()
    (backup / "FOO").mkdir()

    storage, settings, other = group_unstructured_entries(backup)
    assert not storage
    assert not settings
    assert len(other) == 1


def test_prettify_category_name_overrides_and_fallback() -> None:
    assert prettify_category_name("DIALERSETTING") == "Dialer Settings"
    assert prettify_category_name("WIFICONFIG") == "Wi-Fi Settings"
    assert prettify_category_name("UNKNOWN_ITEM") == "Unknown Item"
