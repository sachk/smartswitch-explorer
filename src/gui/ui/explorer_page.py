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
from smartswitch_core.sizes import format_bytes
from gui.localization import tr
from gui.ui.export_options_dialog import ExportOptionsDialog
from gui.ui.tree_model import InventoryTreeModel, TreeFilterProxyModel


class ExplorerPage(QWidget):
    back_requested = Signal()
    run_action_requested = Signal(dict, list, Path)

    def __init__(self) -> None:
        super().__init__()
        self._current_inventory: Inventory | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        self.back_button = QPushButton(tr("ExplorerPage", "Back to Backups"))
        self.total_size_label = QLabel(tr("ExplorerPage", "Backup size: --"))
        header.addWidget(self.back_button)
        header.addStretch(1)
        header.addWidget(self.total_size_label)
        layout.addLayout(header)

        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("ExplorerPage", "Search applications and messages..."))
        self.destination = QLineEdit()
        self.destination.setPlaceholderText(tr("ExplorerPage", "Destination folder"))
        self.pick_destination = QToolButton()
        self.pick_destination.setText("...")
        self.pick_destination.setToolTip(tr("ExplorerPage", "Pick destination folder"))
        top.addWidget(QLabel(tr("ExplorerPage", "Search")))
        top.addWidget(self.search, 2)
        top.addWidget(QLabel(tr("ExplorerPage", "Destination")))
        top.addWidget(self.destination, 2)
        top.addWidget(self.pick_destination)
        layout.addLayout(top)

        tools = QHBoxLayout()
        self.expand_all_button = QPushButton(tr("ExplorerPage", "Expand All"))
        self.collapse_all_button = QPushButton(tr("ExplorerPage", "Collapse All"))
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
        layout.addWidget(self.tree, 1)

        actions = QHBoxLayout()
        self.export_button = QPushButton(tr("ExplorerPage", "Export Selected"))
        self.export_button.setMinimumHeight(40)
        actions.addWidget(self.export_button)
        layout.addLayout(actions)

        self.search.textChanged.connect(self._apply_search)
        self.pick_destination.clicked.connect(self._pick_destination)
        self.expand_all_button.clicked.connect(self.tree.expandAll)
        self.collapse_all_button.clicked.connect(self.tree.collapseAll)

        self.export_button.clicked.connect(self._emit_action)
        self.back_button.clicked.connect(self.back_requested.emit)

        clear_action = QAction(tr("ExplorerPage", "Clear"), self)
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

    def apply_sizes(self, sizes: dict[str, int]) -> None:
        self.model.apply_sizes(sizes)

    def set_size_pending(self) -> None:
        self.total_size_label.setText(tr("ExplorerPage", "Backup size: calculating..."))

    def set_total_size(self, total_bytes: int) -> None:
        template = tr("ExplorerPage", "Backup size: {size}")
        self.total_size_label.setText(template.replace("{size}", format_bytes(total_bytes)))

    def set_busy(self, busy: bool) -> None:
        self.export_button.setDisabled(busy)

    def select_leaf_ids(self, item_ids: set[str]) -> set[str]:
        chosen = {item_id for item_id in item_ids if item_id in self.model.item_ids()}
        if chosen:
            self.model.set_checked_leaf_ids(chosen)
        return chosen

    def select_message_parts(self, preferred_parts: set[str] | None = None) -> bool:
        part_to_id = {
            "sms": "messages:sms",
            "mms": "messages:mms",
            "attachments": "messages:attachments",
            "rcs": "messages:rcs",
        }
        available_ids = self.model.item_ids()
        selectable = {item_id for item_id in part_to_id.values() if item_id in available_ids}
        if not selectable:
            return False

        chosen: set[str] = set()
        if preferred_parts:
            for part in preferred_parts:
                item_id = part_to_id.get(part)
                if item_id and item_id in selectable:
                    chosen.add(item_id)

        if not chosen:
            chosen = set(selectable)

        applied = self.select_leaf_ids(chosen)
        return bool(applied)

    def open_export_prompt(self) -> None:
        self._emit_action()

    def _apply_search(self, text: str) -> None:
        self.proxy.setFilterFixedString(text)
        if text.strip():
            self._expand_search_matches()
            return
        self.tree.collapseAll()

    def _pick_destination(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr("ExplorerPage", "Select Destination Folder"))
        if path:
            self.destination.setText(path)

    def _emit_action(self) -> None:
        selected = self.model.checked_leaf_nodes()
        if not selected:
            QMessageBox.information(
                self,
                tr("ExplorerPage", "Nothing selected"),
                tr("ExplorerPage", "Select at least one item to export."),
            )
            return

        has_messages = any(node["kind"] == "message_subitem" for node in selected)
        has_app_data = any(node["kind"] == "app_data" for node in selected)
        has_contacts = any(node["kind"] == "contacts" for node in selected)
        has_calllog = any(node["kind"] == "calllog" for node in selected)

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
