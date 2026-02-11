from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)


class ExportOptionsDialog(QDialog):
    def __init__(self, has_messages: bool, has_app_data: bool, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export Options")
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        intro = QLabel("Choose output format by data type:")
        layout.addWidget(intro)

        row = QHBoxLayout()
        row.setSpacing(10)

        self.messages_combo: QComboBox | None = None
        self.app_data_combo: QComboBox | None = None

        if has_messages:
            row.addWidget(QLabel("Messages"))
            self.messages_combo = QComboBox()
            self.messages_combo.addItem("JSON", "json")
            self.messages_combo.addItem("CSV", "csv")
            self.messages_combo.addItem("Native (.bk / raw)", "native")
            row.addWidget(self.messages_combo, 1)

        if has_app_data:
            row.addWidget(QLabel("Application Data"))
            self.app_data_combo = QComboBox()
            self.app_data_combo.addItem("Extracted Files", "extract")
            self.app_data_combo.addItem("Decrypted Tar", "decrypt")
            self.app_data_combo.addItem("Both", "both")
            row.addWidget(self.app_data_combo, 1)

        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Export")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def options(self) -> dict:
        out: dict[str, str] = {}
        if self.messages_combo is not None:
            out["messages_format"] = str(self.messages_combo.currentData())
        if self.app_data_combo is not None:
            out["app_data_mode"] = str(self.app_data_combo.currentData())
        return out
