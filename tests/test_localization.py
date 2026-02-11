from __future__ import annotations

import pytest

QtCore = pytest.importorskip("PySide6.QtCore", exc_type=ImportError)
QCoreApplication = QtCore.QCoreApplication

from gui.localization import translate_tree_header, translate_tree_label


def _app() -> QCoreApplication:
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


def test_translate_tree_label_known_kinds() -> None:
    _app()
    assert translate_tree_label("storage_root", "Storage") == "Storage"
    assert translate_tree_label("settings_root", "Settings") == "Settings"
    assert translate_tree_label("other_root", "Other Backup Data") == "Other Backup Data"


def test_translate_tree_header() -> None:
    _app()
    assert translate_tree_header("Backup Items") == "Backup Items"
