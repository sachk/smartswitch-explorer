from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QStyle,
)

from smartswitch_core.scan import discover_backup_roots, find_backups


class LandingPage(QWidget):
    backup_selected = Signal(Path)

    def __init__(self) -> None:
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(8)

        title = QLabel("SmartSwitch Explorer")
        title.setObjectName("title")
        title.setStyleSheet("font-size: 32px; font-weight: 700;")
        layout.addWidget(title)

        subtitle = QLabel("Open a backup folder or choose from automatically detected backups.")
        subtitle.setWordWrap(False)
        subtitle.setStyleSheet("font-size: 16px;")
        layout.addWidget(subtitle)

        self.open_button = QPushButton("Open Folder")
        self.open_button.setMinimumHeight(52)
        self.open_button.setStyleSheet("font-size: 15px; font-weight: 600;")
        self.open_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.open_button.setMinimumWidth(220)
        layout.addWidget(self.open_button, alignment=Qt.AlignmentFlag.AlignLeft)

        self.backup_group = QGroupBox("Detected Backups")
        group_layout = QVBoxLayout(self.backup_group)
        group_layout.setContentsMargins(10, 10, 10, 10)
        group_layout.setSpacing(0)

        self.list_host = QWidget(self.backup_group)
        host_layout = QGridLayout(self.list_host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)

        self.backup_list = QListWidget(self.list_host)
        self.backup_list.setAlternatingRowColors(True)
        host_layout.addWidget(self.backup_list, 0, 0)

        self.empty_state = QWidget(self.list_host)
        self.empty_state.setStyleSheet("background: transparent;")
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setContentsMargins(0, 0, 0, 0)
        empty_layout.setSpacing(0)
        empty_layout.addStretch(1)

        empty_row = QHBoxLayout()
        empty_row.setContentsMargins(0, 0, 0, 0)
        empty_row.addStretch(15)

        self.empty_label = QLabel("No backups detected")
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("font-size: 24px; font-weight: 600; color: white;")
        self.empty_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        empty_row.addWidget(self.empty_label, 70)

        empty_row.addStretch(15)
        empty_layout.addLayout(empty_row)
        empty_layout.addStretch(1)
        host_layout.addWidget(self.empty_state, 0, 0)

        self.refresh_button = QToolButton()
        icon = QIcon.fromTheme("view-refresh")
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        self.refresh_button.setIcon(icon)
        self.refresh_button.setIconSize(QSize(22, 22))
        self.refresh_button.setFixedSize(QSize(42, 42))
        self.refresh_button.setAutoRaise(False)
        self.refresh_button.setStyleSheet(
            "QToolButton {"
            "  border: 1px solid palette(mid);"
            "  border-radius: 12px;"
            "  background-color: palette(base);"
            "}"
            "QToolButton:hover {"
            "  background-color: palette(alternate-base);"
            "}"
            "QToolButton:pressed {"
            "  background-color: palette(midlight);"
            "}"
        )
        self.refresh_button.setToolTip("Refresh detected backups")
        host_layout.addWidget(
            self.refresh_button,
            0,
            0,
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
        )

        group_layout.addWidget(self.list_host, 1)
        self.empty_state.hide()

        layout.addWidget(self.backup_group, 1)

        self.open_button.clicked.connect(self._open_folder)
        self.refresh_button.clicked.connect(self.refresh)
        self.backup_list.itemDoubleClicked.connect(self._open_list_item)

    def refresh(self) -> None:
        self.backup_list.clear()
        count = 0
        for root in discover_backup_roots():
            for backup in find_backups(root):
                item = QListWidgetItem(f"{backup.backup_id}  ({backup.path})")
                item.setData(Qt.ItemDataRole.UserRole, str(backup.path))
                self.backup_list.addItem(item)
                count += 1

        if count == 0:
            self.backup_list.hide()
            self.empty_state.show()
            return

        self.empty_state.hide()
        self.backup_list.show()

    def _open_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Backup Folder")
        if not path:
            return
        self.backup_selected.emit(Path(path))

    def _open_list_item(self, item: QListWidgetItem) -> None:
        raw = item.data(Qt.ItemDataRole.UserRole)
        if raw:
            self.backup_selected.emit(Path(raw))
