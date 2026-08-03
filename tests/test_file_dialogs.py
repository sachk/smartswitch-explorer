from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog

from gui.ui import file_dialogs


class _FakeFileDialog:
    AcceptMode = QFileDialog.AcceptMode
    FileMode = QFileDialog.FileMode
    Option = QFileDialog.Option

    selected_path: Path | None = None
    instance: "_FakeFileDialog | None" = None

    def __init__(self, parent: object, caption: str, initial_directory: str) -> None:
        self.parent = parent
        self.caption = caption
        self.initial_directory = initial_directory
        self.accept_mode = None
        self.file_mode = None
        self.options: dict[QFileDialog.Option, bool] = {}
        type(self).instance = self

    def setAcceptMode(self, mode: QFileDialog.AcceptMode) -> None:
        self.accept_mode = mode

    def setFileMode(self, mode: QFileDialog.FileMode) -> None:
        self.file_mode = mode

    def setOption(self, option: QFileDialog.Option, enabled: bool) -> None:
        self.options[option] = enabled

    def exec(self) -> int:
        return 1 if self.selected_path is not None else 0

    def selectedFiles(self) -> list[str]:
        if self.selected_path is None:
            return []
        return [str(self.selected_path)]


def test_select_existing_directory_uses_qt_directory_mode_on_linux(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _FakeFileDialog.selected_path = tmp_path
    monkeypatch.setattr(file_dialogs, "QFileDialog", _FakeFileDialog)
    monkeypatch.setattr(file_dialogs.sys, "platform", "linux")

    selected = file_dialogs.select_existing_directory(None, "Pick folder", "/start")  # type: ignore[arg-type]

    dialog = _FakeFileDialog.instance
    assert selected == tmp_path
    assert dialog is not None
    assert dialog.initial_directory == "/start"
    assert dialog.accept_mode == QFileDialog.AcceptMode.AcceptOpen
    assert dialog.file_mode == QFileDialog.FileMode.Directory
    assert dialog.options[QFileDialog.Option.ShowDirsOnly]
    assert dialog.options[QFileDialog.Option.DontUseNativeDialog]


def test_select_existing_directory_rejects_a_file(monkeypatch, tmp_path: Path) -> None:
    selected_file = tmp_path / "backup.data"
    selected_file.write_bytes(b"data")
    _FakeFileDialog.selected_path = selected_file
    monkeypatch.setattr(file_dialogs, "QFileDialog", _FakeFileDialog)

    assert file_dialogs.select_existing_directory(None, "Pick folder") is None  # type: ignore[arg-type]


def test_select_existing_directory_returns_none_when_cancelled(monkeypatch) -> None:
    _FakeFileDialog.selected_path = None
    monkeypatch.setattr(file_dialogs, "QFileDialog", _FakeFileDialog)

    assert file_dialogs.select_existing_directory(None, "Pick folder") is None  # type: ignore[arg-type]
