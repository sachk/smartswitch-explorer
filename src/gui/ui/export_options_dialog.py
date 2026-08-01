from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from gui.localization import tr


class ExportOptionsDialog(QDialog):
    def __init__(
        self,
        has_messages: bool,
        has_app_data: bool,
        has_contacts: bool,
        has_calllog: bool,
        has_encrypted_other: bool,
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
        self.app_data_password: QLineEdit | None = None
        self.calllog_combo: QComboBox | None = None

        if has_messages:
            messages_combo = QComboBox()
            messages_combo.setMinimumHeight(34)
            messages_combo.addItem("JSON", "json")
            messages_combo.addItem("CSV", "csv")
            messages_combo.addItem(tr("ExportOptionsDialog", "Native (.bk / raw)"), "native")
            self.messages_combo = messages_combo
            self._add_option_row(layout, tr("ExportOptionsDialog", "Messages"), messages_combo)

        if has_app_data:
            app_data_combo = QComboBox()
            app_data_combo.setMinimumHeight(34)
            app_data_combo.addItem(tr("ExportOptionsDialog", "Extracted Files"), "extract")
            app_data_combo.addItem(tr("ExportOptionsDialog", "Decrypted Tar"), "decrypt")
            app_data_combo.addItem(tr("ExportOptionsDialog", "Both"), "both")
            self.app_data_combo = app_data_combo
            self._add_option_row(layout, tr("ExportOptionsDialog", "Application Data"), app_data_combo)


        if has_app_data or has_messages or has_calllog or has_encrypted_other:
            app_data_password = QLineEdit()
            app_data_password.setEchoMode(QLineEdit.EchoMode.Password)
            app_data_password.setPlaceholderText(
                tr("ExportOptionsDialog", "Optional; only if a backup password was configured")
            )
            self.app_data_password = app_data_password
            self._add_option_row(
                layout,
                tr("ExportOptionsDialog", "Backup Password"),
                app_data_password,
            )

        if has_contacts:
            contacts_combo = QComboBox()
            contacts_combo.setMinimumHeight(34)
            contacts_combo.addItem("CSV", "csv")
            contacts_combo.addItem(tr("ExportOptionsDialog", "Native Files"), "native")
            self.contacts_combo = contacts_combo
            self._add_option_row(layout, tr("ExportOptionsDialog", "Contacts"), contacts_combo)

        if has_calllog:
            calllog_combo = QComboBox()
            calllog_combo.setMinimumHeight(34)
            calllog_combo.addItem("CSV", "csv")
            calllog_combo.addItem(tr("ExportOptionsDialog", "Native (encrypted zip)"), "native")
            self.calllog_combo = calllog_combo
            self._add_option_row(layout, tr("ExportOptionsDialog", "Call Log"), calllog_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("ExportOptionsDialog", "Export"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_option_row(self, parent_layout: QVBoxLayout, label: str, control: QWidget) -> None:
        row = QVBoxLayout()
        row.setSpacing(6)
        title = QLabel(label)
        row.addWidget(title)
        row.addWidget(control)
        parent_layout.addLayout(row)

    def options(self) -> dict:
        out: dict[str, str] = {}
        if self.messages_combo is not None:
            out["messages_format"] = str(self.messages_combo.currentData())
        if self.app_data_combo is not None:
            out["app_data_mode"] = str(self.app_data_combo.currentData())
        if self.app_data_password is not None and self.app_data_password.text():
            out["app_data_password"] = self.app_data_password.text()
        if self.contacts_combo is not None:
            out["contacts_format"] = str(self.contacts_combo.currentData())
        if self.calllog_combo is not None:
            out["calllog_format"] = str(self.calllog_combo.currentData())
        return out
