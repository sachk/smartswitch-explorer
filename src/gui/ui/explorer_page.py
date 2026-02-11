from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from smartswitch_core.models import EnrichmentPatch, Inventory
from gui.ui.tree_model import InventoryTreeModel, TreeFilterProxyModel


class ExplorerPage(QWidget):
    run_action_requested = Signal(str, list, Path)

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
        layout.addWidget(self.tree, 1)

        actions = QHBoxLayout()
        self.decrypt_button = QPushButton("Decrypt Selected")
        self.extract_button = QPushButton("Extract Selected")
        self.both_button = QPushButton("Decrypt + Extract Selected")
        actions.addWidget(self.decrypt_button)
        actions.addWidget(self.extract_button)
        actions.addWidget(self.both_button)
        layout.addLayout(actions)

        self.search.textChanged.connect(self._apply_search)
        self.pick_destination.clicked.connect(self._pick_destination)
        self.expand_all_button.clicked.connect(self.tree.expandAll)
        self.collapse_all_button.clicked.connect(self.tree.collapseAll)

        self.decrypt_button.clicked.connect(lambda: self._emit_action("decrypt"))
        self.extract_button.clicked.connect(lambda: self._emit_action("extract"))
        self.both_button.clicked.connect(lambda: self._emit_action("both"))

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
        self.decrypt_button.setDisabled(busy)
        self.extract_button.setDisabled(busy)
        self.both_button.setDisabled(busy)

    def _apply_search(self, text: str) -> None:
        self.proxy.setFilterFixedString(text)

    def _pick_destination(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Destination Folder")
        if path:
            self.destination.setText(path)

    def _emit_action(self, mode: str) -> None:
        selected = self.model.checked_leaf_nodes()
        self.run_action_requested.emit(mode, selected, self.destination_path())
