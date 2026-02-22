from __future__ import annotations

from dataclasses import dataclass
import json
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal, QThreadPool
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

from gui.localization import tr
from gui.ui.workers import FunctionWorker
from smartswitch_core.scan import discover_backup_roots, expand_input_path, find_backups


class BackupListWidget(QListWidget):
    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if self.itemAt(event.pos()) is None:
            self.clearSelection()
            self.setCurrentItem(None)
        super().mousePressEvent(event)


@dataclass(frozen=True)
class BackupRowModel:
    backup_path: Path
    display_name: str
    model_name: str
    icon_path: Path | None


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve(strict=False)).casefold()
    except OSError:
        return str(path).casefold()


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


def _build_backup_row(backup_dir: Path) -> BackupRowModel:
    display_name, model_name = _backup_title_and_model(backup_dir)
    return BackupRowModel(
        backup_path=backup_dir,
        display_name=display_name,
        model_name=model_name,
        icon_path=_backup_icon_path(backup_dir),
    )


def _discover_backup_rows(
    recent_hints: list[Path],
    *,
    progress=None,
    set_status=None,
    cancel_token=None,
) -> list[BackupRowModel]:
    roots: list[Path] = []
    seen_roots: set[str] = set()

    for hint in recent_hints:
        if not hint.exists():
            continue
        key = _path_key(hint)
        if key in seen_roots:
            continue
        seen_roots.add(key)
        roots.append(hint)

    for root in discover_backup_roots():
        key = _path_key(root)
        if key in seen_roots:
            continue
        seen_roots.add(key)
        roots.append(root)

    backups: list[Path] = []
    seen_backups: set[str] = set()
    total_roots = max(1, len(roots))
    for index, root in enumerate(roots, start=1):
        if set_status is not None:
            set_status(f"Scanning {root}")
        if progress is not None:
            progress(
                {
                    "operation": "listing",
                    "phase_key": "scan_roots",
                    "phase_label": "Scanning backup roots",
                    "current": index,
                    "total": total_roots,
                    "unit": "roots",
                    "detail": str(root),
                }
            )
        for backup in find_backups(root):
            key = _path_key(backup.path)
            if key in seen_backups:
                continue
            seen_backups.add(key)
            backups.append(backup.path)

    rows: list[BackupRowModel] = []
    total_backups = max(1, len(backups))
    for index, backup in enumerate(backups, start=1):
        row = _build_backup_row(backup)
        rows.append(row)
        if set_status is not None:
            set_status(f"Preparing {backup.name}")
        if progress is not None:
            progress(
                {
                    "operation": "listing",
                    "phase_key": "build_rows",
                    "phase_label": "Preparing backup cards",
                    "current": index,
                    "total": total_backups,
                    "unit": "backups",
                    "detail": row.display_name,
                }
            )

    if not rows and progress is not None:
        progress(
            {
                "operation": "listing",
                "phase_key": "build_rows",
                "phase_label": "Preparing backup cards",
                "current": 1,
                "total": 1,
                "unit": "backups",
                "detail": "No backups detected",
            }
        )

    return rows


class BackupListItemWidget(QWidget):
    def __init__(self, row_data: BackupRowModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        backup_dir = row_data.backup_path
        display_name = row_data.display_name
        model_name = row_data.model_name
        title = f"{display_name} ({model_name})" if model_name else display_name

        outer = QHBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(10)

        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_path = row_data.icon_path
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
    listing_started = Signal()
    listing_progress = Signal(object)
    listing_status = Signal(str)
    listing_finished = Signal()
    listing_error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._recent_backup_hints: list[Path] = []
        self._refresh_running = False
        self._refresh_pending = False
        self._thread_pool = QThreadPool(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.setSpacing(12)

        title = QLabel(tr("LandingPage", "SmartSwitch Explorer"))
        title.setObjectName("title")
        title.setStyleSheet("font-size: 25px; font-weight: 700;")
        header_row.addWidget(title, alignment=Qt.AlignmentFlag.AlignVCenter)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)
        header_row.addWidget(divider)

        subtitle = QLabel(tr("LandingPage", "Open a backup folder or choose from automatically detected backups."))
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
        self.path_input.setPlaceholderText(tr("LandingPage", "Select a backup folder"))
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
        self.open_folder_button.setToolTip(tr("LandingPage", "Open folder chooser"))
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

        self.backup_group = QGroupBox(tr("LandingPage", "Detected Backups"))
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

        self.empty_label = QLabel(tr("LandingPage", "No backups detected"))
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
        self.refresh_button.setToolTip(tr("LandingPage", "Refresh detected backups"))
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
        self._recent_backup_hints = [expand_input_path(path) for path in paths]

    def set_path_text(self, path: Path) -> None:
        self.path_input.setText(str(expand_input_path(path)))

    def _add_recent_hint(self, path: Path) -> None:
        expanded = expand_input_path(path)
        deduped = [expanded]
        deduped.extend([hint for hint in self._recent_backup_hints if hint != expanded])
        self._recent_backup_hints = deduped[:6]

    def refresh(self) -> None:
        if self._refresh_running:
            self._refresh_pending = True
            return
        self._refresh_running = True
        self.listing_started.emit()
        worker = FunctionWorker(
            _discover_backup_rows,
            list(self._recent_backup_hints),
            enable_progress=True,
        )
        worker.signals.progress.connect(self.listing_progress.emit)
        worker.signals.status.connect(self.listing_status.emit)
        worker.signals.result.connect(self._on_refresh_result)
        worker.signals.error.connect(self._on_refresh_error)
        self._thread_pool.start(worker)

    def _on_refresh_result(self, rows: list[BackupRowModel]) -> None:
        self.backup_list.clear()
        for row_data in rows:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, str(row_data.backup_path))
            row = BackupListItemWidget(row_data, self.backup_list)
            item.setSizeHint(QSize(row.sizeHint().width(), max(80, row.sizeHint().height())))
            self.backup_list.addItem(item)
            self.backup_list.setItemWidget(item, row)

        if not rows:
            self.backup_list.hide()
            self.empty_state.show()
        else:
            self.empty_state.hide()
            self.backup_list.show()

        self._refresh_running = False
        self.listing_finished.emit()
        if self._refresh_pending:
            self._refresh_pending = False
            self.refresh()

    def _on_refresh_error(self, message: str) -> None:
        self._refresh_running = False
        self.listing_error.emit(message)
        self.listing_finished.emit()
        if self._refresh_pending:
            self._refresh_pending = False
            self.refresh()

    def _open_folder_dialog(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr("LandingPage", "Select Backup Folder"))
        if not path:
            return
        selected = expand_input_path(path)
        self.path_input.setText(str(selected))
        self._add_recent_hint(selected)
        self.refresh()

    def _open_path_from_input(self) -> None:
        raw_path = self.path_input.text().strip()
        if not raw_path:
            return
        selected = expand_input_path(raw_path)
        self.path_input.setText(str(selected))
        self._add_recent_hint(selected)
        self.refresh()

    def _open_list_item(self, item: QListWidgetItem) -> None:
        raw = item.data(Qt.ItemDataRole.UserRole)
        if raw:
            self.backup_selected.emit(Path(raw))
