from __future__ import annotations

import json
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPalette, QPixmap
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
    QSpacerItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QStyle,
)

from smartswitch_core.scan import discover_backup_roots, find_backups


class BackupListWidget(QListWidget):
    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if self.itemAt(event.pos()) is None:
            self.clearSelection()
            self.setCurrentItem(None)
        super().mousePressEvent(event)


def _backup_title_and_model(backup_dir: Path) -> tuple[str, str]:
    display_name = ""
    model_name = ""

    json_path = backup_dir / "SmartSwitchBackup.json"
    if json_path.exists():
        try:
            obj = json.loads(json_path.read_text(encoding="utf-8"))
            display_name = str(obj.get("DisplayName") or obj.get("BrandName") or "").strip()
            model_name = str(obj.get("ModelName") or "").strip()
        except (OSError, ValueError):
            pass

    if not display_name or not model_name:
        xml_path = backup_dir / "backupHistoryInfo.xml"
        if xml_path.exists():
            try:
                root = ET.fromstring(xml_path.read_text(encoding="utf-8"))
                ns = {"k": "Kies.Common.Data"}
                if not display_name:
                    display_name = (root.findtext(".//k:UserInputName", namespaces=ns) or "").strip()
                if not model_name:
                    model_name = (root.findtext(".//k:ModelName", namespaces=ns) or "").strip()
            except (OSError, ValueError, ET.ParseError):
                pass

    if not display_name:
        display_name = backup_dir.name
    return display_name, model_name


def _backup_icon_path(backup_dir: Path) -> Path | None:
    candidates = [
        backup_dir / "CATEGORY_ICON" / "com.sec.android.easyMover",
        backup_dir / "CATEGORY_ICON" / "com.samsung.android.messaging",
        backup_dir / "APKFILE" / "com.sec.android.easyMover.png",
        backup_dir / "APKFILE" / "com.samsung.android.messaging.png",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


class BackupListItemWidget(QWidget):
    def __init__(self, backup_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        display_name, model_name = _backup_title_and_model(backup_dir)
        title = f"{display_name} ({model_name})" if model_name else display_name

        outer = QHBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(10)

        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_path = _backup_icon_path(backup_dir)
        raw_icon = QPixmap(str(icon_path)) if icon_path else QPixmap()
        if not raw_icon.isNull():
            self._icon_source = raw_icon
        else:
            fallback = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
            self._icon_source = fallback.pixmap(128, 128)

        icon_col = QVBoxLayout()
        icon_col.setContentsMargins(0, 0, 0, 0)
        icon_col.setSpacing(0)
        icon_col.addStretch(1)
        icon_col.addWidget(self.icon_label, alignment=Qt.AlignmentFlag.AlignCenter)
        icon_col.addStretch(1)
        outer.addLayout(icon_col)

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(2)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 16px; font-weight: 700;")
        content.addWidget(title_label)

        path_label = QLabel(textwrap.fill(str(backup_dir), width=80))
        path_label.setWordWrap(True)
        path_label.setStyleSheet("font-size: 12px;")
        content.addWidget(path_label)
        content.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        outer.addLayout(content, 1)
        self._apply_icon_size()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._apply_icon_size()

    def _apply_icon_size(self) -> None:
        size = max(28, int(self.height() * 0.7))
        self.icon_label.setFixedSize(size, size)
        self.icon_label.setPixmap(
            self._icon_source.scaled(
                size - 4,
                size - 4,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


class LandingPage(QWidget):
    backup_selected = Signal(Path)

    def __init__(self) -> None:
        super().__init__()
        self._recent_backup_hints: list[Path] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.setSpacing(12)

        title = QLabel("SmartSwitch Explorer")
        title.setObjectName("title")
        title.setStyleSheet("font-size: 25px; font-weight: 700;")
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

        selector_divider = QFrame()
        selector_divider.setFrameShape(QFrame.Shape.HLine)
        selector_divider.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(selector_divider)

        picker_host = QWidget()
        picker_row = QHBoxLayout(picker_host)
        picker_row.setContentsMargins(10, 0, 10, 0)
        picker_row.setSpacing(0)

        self.path_picker = QFrame()
        self.path_picker.setObjectName("pathPicker")
        self.path_picker.setStyleSheet(self._path_picker_stylesheet())
        path_picker_layout = QHBoxLayout(self.path_picker)
        path_picker_layout.setContentsMargins(0, 0, 0, 0)
        path_picker_layout.setSpacing(0)

        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Select a backup folder")
        self.path_input.setMinimumHeight(42)
        self.path_input.setFrame(False)
        self.path_input.setStyleSheet("font-size: 14px; padding-left: 12px; padding-right: 8px;")
        self.path_input.returnPressed.connect(self._open_path_from_input)
        path_picker_layout.addWidget(self.path_input, 1)

        self.open_folder_button = QToolButton()
        self.open_folder_button.setFixedSize(QSize(42, 42))
        self.open_folder_button.setIcon(
            self._icon_for_button(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon), QSize(20, 20))
        )
        self.open_folder_button.setIconSize(QSize(20, 20))
        self.open_folder_button.setToolTip("Open folder chooser")
        self.open_folder_button.setAutoRaise(False)
        self.open_folder_button.setStyleSheet(
            "QToolButton {"
            "  border: none;"
            "  border-left: 1px solid palette(dark);"
            "  border-top-right-radius: 10px;"
            "  border-bottom-right-radius: 10px;"
            "  background-color: palette(highlight);"
            "  color: palette(highlighted-text);"
            "}"
            "QToolButton:hover {"
            "  border-left: 1px solid palette(highlighted-text);"
            "}"
            "QToolButton:pressed {"
            "  background-color: palette(shadow);"
            "}"
        )
        path_picker_layout.addWidget(self.open_folder_button)
        picker_row.addWidget(self.path_picker, 1)
        layout.addWidget(picker_host)

        self.backup_group = QGroupBox("Detected Backups")
        self.backup_group.setStyleSheet(
            "QGroupBox { font-size: 20px; font-weight: 600; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"
        )
        group_layout = QVBoxLayout(self.backup_group)
        group_layout.setContentsMargins(10, 10, 10, 10)
        group_layout.setSpacing(0)

        self.list_host = QWidget(self.backup_group)
        host_layout = QGridLayout(self.list_host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)

        self.backup_list = BackupListWidget(self.list_host)
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
        self.empty_label.setStyleSheet("font-size: 24px; font-weight: 600; color: palette(text);")
        self.empty_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        empty_row.addWidget(self.empty_label, 70)

        empty_row.addStretch(15)
        empty_layout.addLayout(empty_row)
        empty_layout.addStretch(1)
        host_layout.addWidget(self.empty_state, 0, 0)

        self.refresh_button = QToolButton()
        self.refresh_button.setIcon(
            self._icon_for_button(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload), QSize(22, 22))
        )
        self.refresh_button.setIconSize(QSize(22, 22))
        self.refresh_button.setFixedSize(QSize(42, 42))
        self.refresh_button.setAutoRaise(False)
        self.refresh_button.setStyleSheet(self._contrast_button_stylesheet(radius=6))
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

        self.open_folder_button.clicked.connect(self._open_folder_dialog)
        self.refresh_button.clicked.connect(self.refresh)
        self.backup_list.itemDoubleClicked.connect(self._open_list_item)

    def _contrast_button_stylesheet(self, radius: int) -> str:
        return (
            "QToolButton {"
            "  border: 1px solid palette(dark);"
            f"  border-radius: {radius}px;"
            "  background-color: rgba(128, 128, 128, 88);"
            "  color: palette(highlighted-text);"
            "}"
            "QToolButton:hover {"
            "  background-color: rgba(128, 128, 128, 128);"
            "  border-color: palette(light);"
            "}"
            "QToolButton:pressed {"
            "  background-color: rgba(128, 128, 128, 168);"
            "}"
        )

    def _path_picker_stylesheet(self) -> str:
        return (
            "QFrame#pathPicker {"
            "  border: 1px solid palette(dark);"
            "  border-radius: 10px;"
            "  background-color: palette(base);"
            "}"
        )

    def _icon_for_button(self, base_icon: QIcon, size: QSize) -> QIcon:
        base = base_icon.pixmap(size)
        if base.isNull():
            return base_icon

        tinted = QPixmap(base.size())
        tinted.fill(Qt.GlobalColor.transparent)

        painter = QPainter(tinted)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(0, 0, base)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(tinted.rect(), self.palette().color(QPalette.ColorRole.HighlightedText))
        painter.end()
        return QIcon(tinted)

    def set_recent_backups(self, paths: list[Path]) -> None:
        self._recent_backup_hints = [path.expanduser() for path in paths]

    def set_path_text(self, path: Path) -> None:
        self.path_input.setText(str(path.expanduser()))

    def _add_recent_hint(self, path: Path) -> None:
        expanded = path.expanduser()
        deduped = [expanded]
        deduped.extend([hint for hint in self._recent_backup_hints if hint != expanded])
        self._recent_backup_hints = deduped[:6]

    def refresh(self) -> None:
        self.backup_list.clear()
        count = 0
        seen: set[Path] = set()

        for hint in self._recent_backup_hints:
            if not hint.exists():
                continue
            for backup in find_backups(hint):
                resolved = backup.path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, str(backup.path))
                row = BackupListItemWidget(backup.path, self.backup_list)
                item.setSizeHint(QSize(row.sizeHint().width(), max(80, row.sizeHint().height())))
                self.backup_list.addItem(item)
                self.backup_list.setItemWidget(item, row)
                count += 1

        for root in discover_backup_roots():
            for backup in find_backups(root):
                resolved = backup.path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, str(backup.path))
                row = BackupListItemWidget(backup.path, self.backup_list)
                item.setSizeHint(QSize(row.sizeHint().width(), max(80, row.sizeHint().height())))
                self.backup_list.addItem(item)
                self.backup_list.setItemWidget(item, row)
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
        selected = Path(path).expanduser()
        self.path_input.setText(str(selected))
        self._add_recent_hint(selected)
        self.refresh()

    def _open_path_from_input(self) -> None:
        raw_path = self.path_input.text().strip()
        if not raw_path:
            return
        selected = Path(raw_path).expanduser()
        self._add_recent_hint(selected)
        self.refresh()

    def _open_list_item(self, item: QListWidgetItem) -> None:
        raw = item.data(Qt.ItemDataRole.UserRole)
        if raw:
            self.backup_selected.emit(Path(raw))
