from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QModelIndex, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
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
)

from smartswitch_core.models import EnrichmentPatch, Inventory
from gui.ui.export_options_dialog import ExportOptionsDialog
from gui.ui.tree_model import InventoryTreeModel, TreeFilterProxyModel


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
        self.tree.setStyleSheet(
            "QTreeView::indicator {"
            "  width: 18px;"
            "  height: 18px;"
            "  border: 1px solid palette(light);"
            "  border-radius: 4px;"
            "  background: palette(base);"
            "}"
            "QTreeView::indicator:checked {"
            "  border-color: palette(highlighted-text);"
            "  background: palette(highlight);"
            "}"
        )
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
        has_app_apk = any(node["kind"] == "app_apk" for node in selected)

        dialog = ExportOptionsDialog(
            has_messages=has_messages,
            has_app_data=has_app_data,
            has_app_apk=has_app_apk,
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
