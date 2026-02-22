from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from gui.localization import tr


class ExportOptionsDialog(QDialog):
    def __init__(
        self,
        has_messages: bool,
        has_app_data: bool,
        has_contacts: bool,
        has_calllog: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("ExportOptionsDialog", "Export Options"))
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        intro = QLabel(tr("ExportOptionsDialog", "Choose output format by data type:"))
        layout.addWidget(intro)

        self.messages_combo: QComboBox | None = None
        self.app_data_combo: QComboBox | None = None
        self.contacts_combo: QComboBox | None = None
        self.calllog_combo: QComboBox | None = None

        if has_messages:
            self.messages_combo = QComboBox()
            self.messages_combo.setMinimumHeight(34)
            self.messages_combo.addItem("JSON", "json")
            self.messages_combo.addItem("CSV", "csv")
            self.messages_combo.addItem(tr("ExportOptionsDialog", "Native (.bk / raw)"), "native")
            self._add_option_row(layout, tr("ExportOptionsDialog", "Messages"), self.messages_combo)

        if has_app_data:
            self.app_data_combo = QComboBox()
            self.app_data_combo.setMinimumHeight(34)
            self.app_data_combo.addItem(tr("ExportOptionsDialog", "Extracted Files"), "extract")
            self.app_data_combo.addItem(tr("ExportOptionsDialog", "Decrypted Tar"), "decrypt")
            self.app_data_combo.addItem(tr("ExportOptionsDialog", "Both"), "both")
            self._add_option_row(layout, tr("ExportOptionsDialog", "Application Data"), self.app_data_combo)

        if has_contacts:
            self.contacts_combo = QComboBox()
            self.contacts_combo.setMinimumHeight(34)
            self.contacts_combo.addItem("CSV", "csv")
            self.contacts_combo.addItem(tr("ExportOptionsDialog", "Native Files"), "native")
            self._add_option_row(layout, tr("ExportOptionsDialog", "Contacts"), self.contacts_combo)

        if has_calllog:
            self.calllog_combo = QComboBox()
            self.calllog_combo.setMinimumHeight(34)
            self.calllog_combo.addItem("CSV", "csv")
            self.calllog_combo.addItem(tr("ExportOptionsDialog", "Native (encrypted zip)"), "native")
            self._add_option_row(layout, tr("ExportOptionsDialog", "Call Log"), self.calllog_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("ExportOptionsDialog", "Export"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_option_row(self, parent_layout: QVBoxLayout, label: str, combo: QComboBox) -> None:
        row = QVBoxLayout()
        row.setSpacing(6)
        title = QLabel(label)
        row.addWidget(title)
        row.addWidget(combo)
        parent_layout.addLayout(row)

    def options(self) -> dict:
        out: dict[str, str] = {}
        if self.messages_combo is not None:
            out["messages_format"] = str(self.messages_combo.currentData())
        if self.app_data_combo is not None:
            out["app_data_mode"] = str(self.app_data_combo.currentData())
        if self.contacts_combo is not None:
            out["contacts_format"] = str(self.contacts_combo.currentData())
        if self.calllog_combo is not None:
            out["calllog_format"] = str(self.calllog_combo.currentData())
        return out
