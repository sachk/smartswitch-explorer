from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QModelIndex, QRect, Signal, Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionViewItem,
)

from smartswitch_core.models import EnrichmentPatch, Inventory
from gui.ui.export_options_dialog import ExportOptionsDialog
from gui.ui.tree_model import InventoryTreeModel, TreeFilterProxyModel


class ModernTreeCheckDelegate(QStyledItemDelegate):
    def _checkbox_rect(self, option: QStyleOptionViewItem) -> QRect:
        size = max(16, min(option.rect.height() - 8, 20))
        y = option.rect.center().y() - (size // 2)
        return QRect(option.rect.x() + 8, y, size, size)

    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, opt, painter, opt.widget)

        check_state = index.data(Qt.ItemDataRole.CheckStateRole)
        has_check = check_state is not None
        text_x = opt.rect.x() + 8
        if has_check:
            check_rect = self._checkbox_rect(opt)
            base = opt.palette.color(opt.palette.ColorRole.Base)
            text = opt.palette.color(opt.palette.ColorRole.Text)
            is_dark = base.lightness() < 128

            fill = QColor(text)
            border = QColor(text)
            if is_dark:
                fill.setAlpha(235)
                border.setAlpha(180)
            else:
                fill.setAlpha(215)
                border.setAlpha(165)
            if check_state == Qt.CheckState.Checked:
                fill = opt.palette.color(opt.palette.ColorRole.Highlight)
                border = opt.palette.color(opt.palette.ColorRole.HighlightedText)
            elif check_state == Qt.CheckState.PartiallyChecked:
                fill = QColor(opt.palette.color(opt.palette.ColorRole.Highlight))
                fill.setAlpha(170)
                border = QColor(opt.palette.color(opt.palette.ColorRole.HighlightedText))
                border.setAlpha(190)

            painter.save()
            painter.setRenderHint(painter.RenderHint.Antialiasing, True)
            painter.setPen(border)
            painter.setBrush(fill)
            painter.drawRoundedRect(check_rect, 4, 4)

            if check_state == Qt.CheckState.Checked:
                pen = opt.palette.color(opt.palette.ColorRole.HighlightedText)
                painter.setPen(pen)
                painter.drawLine(check_rect.left() + 4, check_rect.center().y(), check_rect.left() + 8, check_rect.bottom() - 4)
                painter.drawLine(check_rect.left() + 8, check_rect.bottom() - 4, check_rect.right() - 3, check_rect.top() + 4)
            elif check_state == Qt.CheckState.PartiallyChecked:
                pen = opt.palette.color(opt.palette.ColorRole.Text)
                painter.setPen(pen)
                painter.drawLine(check_rect.left() + 4, check_rect.center().y(), check_rect.right() - 4, check_rect.center().y())
            painter.restore()
            text_x = check_rect.right() + 8

        icon_x = text_x
        if not opt.icon.isNull():
            icon_size = max(16, min(opt.rect.height() - 8, 20))
            icon_rect = QRect(icon_x, opt.rect.center().y() - (icon_size // 2), icon_size, icon_size)
            opt.icon.paint(painter, icon_rect)
            text_x = icon_rect.right() + 6

        text_rect = QRect(text_x, opt.rect.y(), opt.rect.right() - text_x - 6, opt.rect.height())
        if opt.state & QStyle.StateFlag.State_Selected:
            painter.setPen(opt.palette.color(opt.palette.ColorRole.HighlightedText))
        else:
            painter.setPen(opt.palette.color(opt.palette.ColorRole.Text))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, opt.text)

    def editorEvent(self, event, model, option, index) -> bool:  # type: ignore[override]
        if not (index.flags() & Qt.ItemFlag.ItemIsUserCheckable):
            return super().editorEvent(event, model, option, index)

        if event.type() == QEvent.Type.MouseButtonRelease:
            check_rect = self._checkbox_rect(option)
            if check_rect.contains(event.pos()):
                state = index.data(Qt.ItemDataRole.CheckStateRole)
                next_state = Qt.CheckState.Unchecked if state == Qt.CheckState.Checked else Qt.CheckState.Checked
                return bool(model.setData(index, next_state, Qt.ItemDataRole.CheckStateRole))

        if event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Select):
            state = index.data(Qt.ItemDataRole.CheckStateRole)
            next_state = Qt.CheckState.Unchecked if state == Qt.CheckState.Checked else Qt.CheckState.Checked
            return bool(model.setData(index, next_state, Qt.ItemDataRole.CheckStateRole))

        return super().editorEvent(event, model, option, index)


class ExplorerPage(QWidget):
    run_action_requested = Signal(dict, list, Path)

    def __init__(self) -> None:
        super().__init__()
        self._current_inventory: Inventory | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search applications and messages...")
        self.destination = QLineEdit()
        self.destination.setPlaceholderText("Destination folder")
        self.pick_destination = QToolButton()
        self.pick_destination.setText("...")
        self.pick_destination.setToolTip("Pick destination folder")
        top.addWidget(QLabel("Search"))
        top.addWidget(self.search, 2)
        top.addWidget(QLabel("Destination"))
        top.addWidget(self.destination, 2)
        top.addWidget(self.pick_destination)
        layout.addLayout(top)

        tools = QHBoxLayout()
        self.expand_all_button = QPushButton("Expand All")
        self.collapse_all_button = QPushButton("Collapse All")
        tools.addWidget(self.expand_all_button)
        tools.addWidget(self.collapse_all_button)
        tools.addStretch(1)
        layout.addLayout(tools)

        self.model = InventoryTreeModel()
        self.proxy = TreeFilterProxyModel()
        self.proxy.setSourceModel(self.model)

        self.tree = QTreeView()
        self.tree.setModel(self.proxy)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setHeaderHidden(False)
        self.tree.setItemDelegate(ModernTreeCheckDelegate(self.tree))
        layout.addWidget(self.tree, 1)

        actions = QHBoxLayout()
        self.export_button = QPushButton("Export Selected")
        self.export_button.setMinimumHeight(40)
        actions.addWidget(self.export_button)
        layout.addLayout(actions)

        self.search.textChanged.connect(self._apply_search)
        self.pick_destination.clicked.connect(self._pick_destination)
        self.expand_all_button.clicked.connect(self.tree.expandAll)
        self.collapse_all_button.clicked.connect(self.tree.collapseAll)

        self.export_button.clicked.connect(self._emit_action)

        clear_action = QAction("Clear", self)
        clear_action.triggered.connect(lambda: self.search.setText(""))
        self.search.addAction(clear_action, QLineEdit.ActionPosition.TrailingPosition)

    def set_destination(self, path: Path) -> None:
        self.destination.setText(str(path))

    def destination_path(self) -> Path:
        raw = self.destination.text().strip()
        return Path(raw) if raw else Path.home()

    def load_inventory(self, inventory: Inventory) -> None:
        self._current_inventory = inventory
        self.model.load_inventory(inventory)
        self.tree.expandToDepth(0)
        self.tree.collapseAll()

    def apply_patch(self, patch: EnrichmentPatch) -> None:
        self.model.apply_patch(patch)

    def set_busy(self, busy: bool) -> None:
        self.export_button.setDisabled(busy)

    def _apply_search(self, text: str) -> None:
        self.proxy.setFilterFixedString(text)
        if text.strip():
            self._expand_search_matches()
            return
        self.tree.collapseAll()

    def _pick_destination(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Destination Folder")
        if path:
            self.destination.setText(path)

    def _emit_action(self) -> None:
        selected = self.model.checked_leaf_nodes()
        if not selected:
            QMessageBox.information(self, "Nothing selected", "Select at least one item to export.")
            return

        has_messages = any(node["kind"] == "message_subitem" for node in selected)
        has_app_data = any(node["kind"] == "app_data" for node in selected)
        has_contacts = any(
            node["kind"] in {"contacts_csv", "contacts_archive", "contacts_files"} for node in selected
        )
        has_calllog = any(node["kind"] == "calllog_entries" for node in selected)

        if not has_messages and not has_app_data and not has_contacts and not has_calllog:
            self.run_action_requested.emit({}, selected, self.destination_path())
            return

        dialog = ExportOptionsDialog(
            has_messages=has_messages,
            has_app_data=has_app_data,
            has_contacts=has_contacts,
            has_calllog=has_calllog,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self.run_action_requested.emit(dialog.options(), selected, self.destination_path())

    def _count_visible_rows(self, parent: QModelIndex = QModelIndex()) -> int:
        total = 0
        rows = self.proxy.rowCount(parent)
        for row in range(rows):
            child = self.proxy.index(row, 0, parent)
            if not child.isValid():
                continue
            total += 1
            total += self._count_visible_rows(child)
        return total

    def _expand_search_matches(self) -> None:
        self.tree.collapseAll()
        root = QModelIndex()
        top_rows = self.proxy.rowCount(root)
        for row in range(top_rows):
            idx = self.proxy.index(row, 0, root)
            if idx.isValid():
                self.tree.expand(idx)

        if self._count_visible_rows() < 5:
            self.tree.expandAll()
