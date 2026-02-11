from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
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

        header_row = QHBoxLayout()
        header_row.setSpacing(12)

        title = QLabel("SmartSwitch Explorer")
        title.setObjectName("title")
        title.setStyleSheet("font-size: 32px; font-weight: 700;")
        header_row.addWidget(title, alignment=Qt.AlignmentFlag.AlignVCenter)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)
        header_row.addWidget(divider)

        subtitle = QLabel("Open a backup folder or choose from automatically detected backups.")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size: 16px;")
        subtitle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header_row.addWidget(subtitle, 1, alignment=Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(header_row)

        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Select a backup folder")
        self.path_input.setMinimumHeight(42)
        self.path_input.setStyleSheet("font-size: 14px; padding-right: 8px;")

        open_icon = QIcon.fromTheme("folder-open")
        if open_icon.isNull():
            open_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        self.open_action = QAction(open_icon, "Open folder", self.path_input)
        self.open_action.triggered.connect(self._open_folder_dialog)
        self.path_input.addAction(self.open_action, QLineEdit.ActionPosition.TrailingPosition)
        self.path_input.returnPressed.connect(self._open_path_from_input)
        layout.addWidget(self.path_input)

        self.backup_group = QGroupBox("Detected Backups")
        self.backup_group.setStyleSheet(
            "QGroupBox { font-size: 18px; font-weight: 600; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"
        )
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

    def _open_folder_dialog(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Backup Folder")
        if not path:
            return
        self.path_input.setText(path)
        self.backup_selected.emit(Path(path))

    def _open_path_from_input(self) -> None:
        raw_path = self.path_input.text().strip()
        if not raw_path:
            return
        self.backup_selected.emit(Path(raw_path).expanduser())

    def _open_list_item(self, item: QListWidgetItem) -> None:
        raw = item.data(Qt.ItemDataRole.UserRole)
        if raw:
            self.backup_selected.emit(Path(raw))
