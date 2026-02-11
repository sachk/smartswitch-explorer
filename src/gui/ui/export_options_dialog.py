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
    def __init__(self, has_messages: bool, has_apps: bool, parent=None) -> None:
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
        self.apps_combo: QComboBox | None = None

        if has_messages:
            row.addWidget(QLabel("Messages"))
            self.messages_combo = QComboBox()
            self.messages_combo.addItem("JSON", "json")
            self.messages_combo.addItem("CSV", "csv")
            self.messages_combo.addItem("Native (.bk / raw)", "native")
            row.addWidget(self.messages_combo, 1)

        if has_apps:
            row.addWidget(QLabel("Applications"))
            self.apps_combo = QComboBox()
            self.apps_combo.addItem("Extracted Files", "extract")
            self.apps_combo.addItem("Decrypted Binaries", "decrypt")
            self.apps_combo.addItem("Both", "both")
            row.addWidget(self.apps_combo, 1)

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
        if self.apps_combo is not None:
            out["apps_mode"] = str(self.apps_combo.currentData())
        return out
