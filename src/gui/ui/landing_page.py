from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from smartswitch_core.scan import discover_backup_roots, find_backups


class LandingPage(QWidget):
    backup_selected = Signal(Path)

    def __init__(self) -> None:
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("SmartSwitch Explorer")
        title.setObjectName("title")
        title.setStyleSheet("font-size: 24px; font-weight: 600;")
        layout.addWidget(title)

        subtitle = QLabel("Open a backup folder or choose from automatically detected backups.")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        buttons = QHBoxLayout()
        self.open_button = QPushButton("Open Folder")
        self.refresh_button = QPushButton("Refresh")
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.refresh_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.backup_list = QListWidget()
        self.backup_list.setAlternatingRowColors(True)
        layout.addWidget(self.backup_list, 1)

        hint = QLabel("Double-click a backup to open it.")
        hint.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(hint)

        self.open_button.clicked.connect(self._open_folder)
        self.refresh_button.clicked.connect(self.refresh)
        self.backup_list.itemDoubleClicked.connect(self._open_list_item)

    def refresh(self) -> None:
        self.backup_list.clear()
        for root in discover_backup_roots():
            for backup in find_backups(root):
                item = QListWidgetItem(f"{backup.backup_id}  ({backup.path})")
                item.setData(Qt.ItemDataRole.UserRole, str(backup.path))
                self.backup_list.addItem(item)

    def _open_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Backup Folder")
        if not path:
            return
        self.backup_selected.emit(Path(path))

    def _open_list_item(self, item: QListWidgetItem) -> None:
        raw = item.data(Qt.ItemDataRole.UserRole)
        if raw:
            self.backup_selected.emit(Path(raw))
