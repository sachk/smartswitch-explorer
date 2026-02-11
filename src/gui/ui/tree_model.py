from __future__ import annotations

from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtGui import QIcon, QStandardItem, QStandardItemModel

from smartswitch_core.models import EnrichmentPatch, Inventory, TreeItem
from gui.localization import translate_tree_header, translate_tree_label

ROLE_ID = Qt.ItemDataRole.UserRole + 1
ROLE_KIND = Qt.ItemDataRole.UserRole + 2
ROLE_PACKAGE = Qt.ItemDataRole.UserRole + 3


class TreeFilterProxyModel(QSortFilterProxyModel):
    def __init__(self) -> None:
        super().__init__()
        self.setRecursiveFilteringEnabled(True)

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:  # type: ignore[override]
        model = self.sourceModel()
        if model is None:
            return False

        index = model.index(source_row, 0, source_parent)
        if not index.isValid():
            return False

        text = (index.data() or "").lower()
        needle = self.filterRegularExpression().pattern().lower()
        if not needle:
            return True
        if needle in text:
            return True

        rows = model.rowCount(index)
        for child_row in range(rows):
            if self.filterAcceptsRow(child_row, index):
                return True
        return False


class InventoryTreeModel(QStandardItemModel):
    def __init__(self) -> None:
        super().__init__()
        self.setHorizontalHeaderLabels([translate_tree_header("Backup Items")])
        self._item_by_id: dict[str, QStandardItem] = {}
        self._suspend = False
        self.itemChanged.connect(self._on_item_changed)

    def load_inventory(self, inventory: Inventory) -> None:
        self.clear()
        self.setHorizontalHeaderLabels([translate_tree_header("Backup Items")])
        self._item_by_id.clear()

        for root in inventory.roots:
            self.appendRow(self._to_item(root))

    def checked_leaf_nodes(self) -> list[dict]:
        checked: list[dict] = []
        for item_id, item in self._item_by_id.items():
            if item.hasChildren():
                continue
            if item.checkState() != Qt.CheckState.Checked:
                continue
            checked.append(
                {
                    "id": item_id,
                    "kind": item.data(ROLE_KIND),
                    "label": item.text(),
                    "package_id": item.data(ROLE_PACKAGE) or "",
                }
            )
        return checked

    def apply_patch(self, patch: EnrichmentPatch) -> None:
        for update in patch.updates:
            item = self._item_by_id.get(update.item_id)
            if item is None:
                continue
            if update.label:
                item.setText(update.label)
            if update.icon_path:
                item.setIcon(QIcon(str(update.icon_path)))

    def _to_item(self, node: TreeItem) -> QStandardItem:
        item = QStandardItem(translate_tree_label(node.kind, node.label))
        item.setCheckable(True)
        item.setEditable(False)
        item.setData(node.id, ROLE_ID)
        item.setData(node.kind, ROLE_KIND)
        item.setData(node.package_id, ROLE_PACKAGE)
        item.setCheckState(Qt.CheckState.Unchecked)
        if node.icon_path:
            item.setIcon(QIcon(str(node.icon_path)))

        self._item_by_id[node.id] = item

        for child in node.children:
            item.appendRow(self._to_item(child))

        return item

    def _on_item_changed(self, item: QStandardItem) -> None:
        if self._suspend:
            return

        self._suspend = True
        try:
            state = item.checkState()
            self._propagate_to_children(item, state)
            self._update_parents(item)
        finally:
            self._suspend = False

    def _propagate_to_children(self, item: QStandardItem, state: Qt.CheckState) -> None:
        for row in range(item.rowCount()):
            child = item.child(row)
            child.setCheckState(state)
            self._propagate_to_children(child, state)

    def _update_parents(self, item: QStandardItem) -> None:
        parent = item.parent()
        while parent is not None:
            child_states = [parent.child(i).checkState() for i in range(parent.rowCount())]
            if all(state == Qt.CheckState.Checked for state in child_states):
                parent.setCheckState(Qt.CheckState.Checked)
            elif all(state == Qt.CheckState.Unchecked for state in child_states):
                parent.setCheckState(Qt.CheckState.Unchecked)
            else:
                parent.setCheckState(Qt.CheckState.PartiallyChecked)
            parent = parent.parent()
