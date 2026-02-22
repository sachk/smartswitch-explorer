from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtCore", exc_type=ImportError)

from gui import config


class _DummyQStandardPaths:
    class StandardLocation:
        GenericConfigLocation = object()
        ConfigLocation = object()
        AppConfigLocation = object()

    def __init__(self, mapping: dict[object, str]) -> None:
        self._mapping = mapping

    def writableLocation(self, location: object) -> str:
        return self._mapping.get(location, "")


def _patch_paths(monkeypatch: pytest.MonkeyPatch, *, generic: Path, app: Path) -> None:
    dummy = _DummyQStandardPaths(
        {
            _DummyQStandardPaths.StandardLocation.GenericConfigLocation: str(generic),
            _DummyQStandardPaths.StandardLocation.ConfigLocation: str(generic),
            _DummyQStandardPaths.StandardLocation.AppConfigLocation: str(app),
        }
    )
    monkeypatch.setattr(config, "QStandardPaths", dummy)


def test_config_dir_uses_generic_base_with_single_app_suffix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    generic = tmp_path / ".config"
    legacy = generic / config.APP_NAME / config.APP_NAME
    _patch_paths(monkeypatch, generic=generic, app=legacy)

    cfg = config._config_dir()

    assert cfg == generic / config.APP_NAME
    assert cfg.exists()


def test_load_settings_reads_legacy_appconfig_path_when_new_file_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generic = tmp_path / ".config"
    legacy = generic / config.APP_NAME / config.APP_NAME
    _patch_paths(monkeypatch, generic=generic, app=legacy)

    legacy_settings = legacy / "settings.json"
    legacy_settings.parent.mkdir(parents=True, exist_ok=True)
    legacy_settings.write_text(
        json.dumps({"destination": str(tmp_path / "dest"), "last_backup": str(tmp_path / "backup")}),
        encoding="utf-8",
    )

    loaded = config.load_settings()

    assert loaded["destination"] == str(tmp_path / "dest")
    assert loaded["last_backup"] == str(tmp_path / "backup")


def test_save_settings_writes_to_single_app_suffix_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    generic = tmp_path / ".config"
    legacy = generic / config.APP_NAME / config.APP_NAME
    _patch_paths(monkeypatch, generic=generic, app=legacy)

    settings = {"destination": str(tmp_path / "dest"), "last_backup": str(tmp_path / "backup")}
    config.save_settings(settings)

    saved = config._settings_path()
    assert saved == generic / config.APP_NAME / "settings.json"
    assert json.loads(saved.read_text(encoding="utf-8")) == settings
