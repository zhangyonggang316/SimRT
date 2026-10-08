"""Qt calibration table retaining explicit pending-write and recovery semantics."""
import math
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QTableWidgetItem, QMenu, QApplication, QStyle
from .common import command, table, attr, menu_command
from .catalog_tree import CatalogTree


def parse_raw_value(text):
    try:
        return int(text.strip(), 0)
    except ValueError:
        try:
            value = float(text)
            if not math.isfinite(value):
                raise ValueError
            return value
        except ValueError:
            raise ValueError('标定值必须是有限的整数或浮点数。')


class CalibrationTab(QWidget):
    def __init__(self, parent, on_refresh, on_write, on_restore, edit_value, report_error):
        super().__init__(parent)
        self._items, self._new_values, self._current_values, self._statuses = {}, {}, {}, {}
        self._selected = set()
        self._editing_enabled = False
        self._edit_value, self._report_error = edit_value, report_error
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel('搜索'))
        self.search = QLineEdit()
        self.search.setMaximumWidth(260)
        row.addWidget(self.search)
        row.addWidget(QLabel('数值模式：A2L 原始值'))
        row.addStretch()
        self.refresh_button = command('刷新', on_refresh, icon=QStyle.StandardPixmap.SP_BrowserReload)
        self.write_button = command('写入所选', on_write, role='primary', icon=QStyle.StandardPixmap.SP_DialogApplyButton)
        self.restore_button = command('恢复本次会话', on_restore, icon=QStyle.StandardPixmap.SP_ArrowBack)
        for button in (self.refresh_button, self.write_button, self.restore_button):
            row.addWidget(button)
        layout.addLayout(row)
        heading = QHBoxLayout()
        heading.addWidget(QLabel('CHARACTERISTIC'))
        self.count = QLabel('0 个标定量')
        heading.addStretch()
        heading.addWidget(self.count)
        layout.addLayout(heading)
        self.tree = CatalogTree(('写入', '名称', '地址', '类型', '当前原始值', '新原始值', '状态'))
        for column, width in enumerate((54, 245, 110, 100, 125, 125, 150)):
            self.tree.setColumnWidth(column, width)
        layout.addWidget(self.tree)
        self.tree.checksChanged.connect(self._set_selected)
        self.tree.itemDoubleClicked.connect(lambda item, column: self._edit_name(self.tree.name(item)) if column != 0 else None)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context)
        self.search.textChanged.connect(self._render)

    def set_calibrations(self, items):
        self._items = {str(attr(item, 'name')): item for item in items}
        self._selected.intersection_update(self._items)
        for store in (self._new_values, self._current_values, self._statuses):
            for key in list(store):
                if key not in self._items:
                    del store[key]
        self._render()

    def pending_changes(self):
        return {name: parse_raw_value(self._new_values[name]) for name in self._items
                if name in self._selected and self._new_values.get(name, '').strip()}

    def update_current_values(self, values, status='已读取'):
        for name, value in values.items():
            if name in self._items:
                self._current_values[name], self._statuses[name] = value, status
        self._render()

    def mark_status(self, names, status):
        for name in names:
            if name in self._items:
                self._statuses[name] = status
        self._render()

    def clear_pending(self, names=()):
        for name in tuple(names) or tuple(self._new_values):
            self._new_values.pop(name, None)
            self._selected.discard(name)
        self._render()

    def _edit_name(self, name):
        if not self._editing_enabled or name not in self._items:
            return
        value = self._edit_value(name, self._new_values.get(name, str(self._current_values.get(name, ''))))
        if value is None:
            return
        try:
            parse_raw_value(value)
        except ValueError as error:
            self._report_error(str(error))
            return
        self._new_values[name] = value
        self._statuses[name] = '待写入'
        self._selected.add(name)
        self._render()

    def _selection(self):
        return self.tree.selected_names()

    def _set_selected(self, names, checked):
        if not self._editing_enabled:
            return
        for name in names:
            if checked:
                self._selected.add(name)
            else:
                self._selected.discard(name)
        self._render()

    def _context(self, position):
        item = self.tree.itemAt(position)
        if item is not None and not item.isSelected():
            self.tree.select_item(item)
        names = self._selection()
        visible = self.tree.filtered_names()
        menu = QMenu(self)
        icons = QStyle.StandardPixmap
        menu_command(menu, '编辑新值', lambda: self._edit_name(names[0]), icons.SP_FileDialogDetailedView,
                     self._editing_enabled and len(names) == 1)
        for text, selected, checked in (('勾选所选行', names, True), ('取消勾选所选行', names, False),
                                       ('勾选筛选结果', visible, True), ('取消勾选筛选结果', visible, False)):
            changed = any((name in self._selected) != checked for name in selected)
            menu_command(menu, text, lambda n=selected, c=checked: self._set_selected(n, c),
                         icons.SP_DialogApplyButton if checked else icons.SP_DialogCancelButton,
                         self._editing_enabled and changed)
        menu_command(menu, '撤销所选待写值', lambda: self.clear_pending(names), icons.SP_ArrowBack,
                     self._editing_enabled and any(name in self._new_values for name in names))
        menu.addSeparator()
        for button in (self.refresh_button, self.write_button, self.restore_button):
            text = '写入勾选项' if button is self.write_button else button.text()
            enabled = button.isEnabled()
            if button is self.write_button:
                enabled = enabled and bool(self.pending_changes())
            elif button is self.refresh_button:
                enabled = enabled and bool(self._items)
            action = menu_command(menu, text, button.click, icons.SP_FileIcon, enabled)
            action.setIcon(button.icon())
        menu.addSeparator()
        menu_command(menu, '复制名称', lambda: QApplication.clipboard().setText('\n'.join(names)), icons.SP_FileIcon, bool(names))
        menu_command(menu, '复制名称和当前值', lambda: QApplication.clipboard().setText('\n'.join(f'{name}\t{self._current_values.get(name, "--")}' for name in names)),
                     icons.SP_FileDialogDetailedView, bool(names))
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def set_policy(self, policy):
        changed = self._editing_enabled != policy.calibration_enabled
        self._editing_enabled = policy.calibration_enabled
        for button in (self.refresh_button, self.write_button, self.restore_button):
            button.setEnabled(self._editing_enabled)
        self.search.setEnabled(self._editing_enabled or policy.observation_select_enabled)
        if changed:
            self._render()

    def _render(self, *_):
        rows = {name: ('', name, f'0x{attr(entry, "address", 0):08X}', attr(entry, 'data_type', '--'),
                      self._current_values.get(name, '--'), self._new_values.get(name, ''),
                      self._statuses.get(name, '待读取')) for name, entry in self._items.items()}
        self.tree.set_catalog(self._items, rows, self._selected, self._editing_enabled)
        self.tree.set_filter(self.search.text())
        self.count.setText(f'{len(self._items)} 个标定量 / 待写 {len(self.pending_changes())}')
