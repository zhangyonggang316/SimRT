"""Model hierarchy shared by observation and calibration catalogs."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QAbstractItemView, QHeaderView, QStyle
from .common import attr


class CatalogTree(QTreeWidget):
    checksChanged = Signal(object, bool)

    def __init__(self, headers, parent=None):
        super().__init__(parent)
        self.setColumnCount(len(headers))
        self.setHeaderLabels(headers)
        self.setTreePosition(1)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.header().setStretchLastSection(True)
        self.setUniformRowHeights(True)
        self.leaves, self.groups = {}, {}
        self._signature = ()
        self._query = ''
        self._filter_expansion = None
        self._checkable = False
        self.itemChanged.connect(self._checked)

    @staticmethod
    def name(item):
        return item.data(1, Qt.ItemDataRole.UserRole) if item else None

    def names_under(self, item):
        name = self.name(item)
        if name is not None:
            return [name]
        return [name for index in range(item.childCount()) for name in self.names_under(item.child(index))]

    def selected_names(self):
        chosen = {name for item in self.selectedItems() for name in self.names_under(item)}
        return [name for name in self.leaves if name in chosen]

    def filtered_names(self):
        return [name for name, item in self.leaves.items() if not item.isHidden()]

    def select_item(self, item):
        self.clearSelection()
        self.setCurrentItem(item)
        item.setSelected(True)

    def _checked(self, item, column):
        if column == 0 and self._checkable:
            self.checksChanged.emit(self.names_under(item), item.checkState(0) == Qt.CheckState.Checked)

    def set_catalog(self, items, rows, checked, checkable):
        signature = tuple((name, tuple(attr(entry, 'model_path', ()) or ())) for name, entry in items.items())
        selected = set(self.selected_names())
        expanded = {path: item.isExpanded() for path, item in self.groups.items()}
        vertical, horizontal = self.verticalScrollBar().value(), self.horizontalScrollBar().value()
        self.blockSignals(True)
        self.setUpdatesEnabled(False)
        try:
            if signature != self._signature:
                self.clear()
                self.leaves, self.groups = {}, {}
                for name, path in signature:
                    parent = self.invisibleRootItem()
                    for length in range(1, len(path) + 1):
                        prefix = path[:length]
                        if prefix not in self.groups:
                            group = QTreeWidgetItem(parent)
                            group.setText(1, prefix[-1])
                            group.setToolTip(1, '/'.join(prefix))
                            group.setIcon(1, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
                            self.groups[prefix] = group
                            group.setExpanded(expanded.get(prefix, True))
                        parent = self.groups[prefix]
                    leaf = QTreeWidgetItem(parent)
                    leaf.setData(1, Qt.ItemDataRole.UserRole, name)
                    leaf.setToolTip(1, '/'.join(path + (name,)))
                    leaf.setIcon(1, self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
                    leaf.setSelected(name in selected)
                    self.leaves[name] = leaf
                self._signature = signature
            for name, values in rows.items():
                item = self.leaves[name]
                for column, value in enumerate(values):
                    if item.text(column) != str(value):
                        item.setText(column, str(value))
            self._checkable = bool(checkable)
            flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            if checkable:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
            for name, item in self.leaves.items():
                item.setFlags(flags)
                item.setCheckState(0, Qt.CheckState.Checked if name in checked else Qt.CheckState.Unchecked)
            for item in self.groups.values():
                names = self.names_under(item)
                count = sum(name in checked for name in names)
                item.setFlags(flags)
                state = Qt.CheckState.Unchecked if not count else Qt.CheckState.Checked if count == len(names) else Qt.CheckState.PartiallyChecked
                item.setCheckState(0, state)
            self._filter_items()
        finally:
            self.setUpdatesEnabled(True)
            self.blockSignals(False)
        self.verticalScrollBar().setValue(vertical)
        self.horizontalScrollBar().setValue(horizontal)

    def set_filter(self, query):
        query = query.casefold().strip()
        if query and not self._query:
            self._filter_expansion = {path: item.isExpanded() for path, item in self.groups.items()}
        self._query = query
        self._filter_items()
        if not query and self._filter_expansion is not None:
            for path, expanded in self._filter_expansion.items():
                if path in self.groups:
                    self.groups[path].setExpanded(expanded)
            self._filter_expansion = None

    def _filter_items(self):
        for name, item in self.leaves.items():
            item.setHidden(self._query not in item.toolTip(1).casefold())
        for path, item in reversed(tuple(self.groups.items())):
            visible = any(not item.child(index).isHidden() for index in range(item.childCount()))
            item.setHidden(not visible)
            if visible and self._query:
                item.setExpanded(True)
