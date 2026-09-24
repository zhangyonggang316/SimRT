"""Qt observation workspace with native raw history and QtAgg plots."""
import math
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox, QDoubleSpinBox, QCheckBox, QSplitter, QTabWidget, QTableWidgetItem, QMenu, QColorDialog, QApplication, QStyle
from .common import command, table, attr, menu_command
from .fields import Field
from .native import DEFAULT_HISTORY_POINTS, NativeBuffer
from .chart import SignalChart
from .catalog_tree import CatalogTree


class ObservationTab(QWidget):
    def __init__(self, parent, on_start, on_stop, on_export, on_native_sdi, max_points=DEFAULT_HISTORY_POINTS):
        super().__init__(parent)
        self.buffer = NativeBuffer(max_points)
        self._items, self._selected = {}, set()
        self._selection_enabled = False
        self._last_policy = None
        self.daq_metadata = {}
        self._cursors_were_enabled = False
        layout = QVBoxLayout(self)
        tools = QHBoxLayout()
        tools.addWidget(QLabel('搜索'))
        self.search = QLineEdit()
        self.search.setMaximumWidth(160)
        tools.addWidget(self.search)
        self.acquisition = QComboBox()
        self.acquisition.addItems(('DAQ', '轮询'))
        self.acquisition_var = Field(self.acquisition)
        tools.addWidget(self.acquisition)
        tools.addWidget(QLabel('周期 (s)'))
        self.interval = QDoubleSpinBox()
        self.interval.setRange(.02, 60)
        self.interval.setValue(.2)
        self.interval.setSingleStep(.01)
        self.interval_var = Field(self.interval)
        self.daq_period = QLineEdit('--')
        self.daq_period.setReadOnly(True)
        self.daq_period.setMaximumWidth(90)
        self.daq_period_var = Field(self.daq_period)
        tools.addWidget(self.interval)
        tools.addWidget(self.daq_period)
        tools.addStretch()
        self.native_sdi_button = command('MATLAB SDI', on_native_sdi)
        self.start_button = command('开始', on_start, role='primary', icon=QStyle.StandardPixmap.SP_MediaPlay)
        self.stop_button = command('停止', on_stop, role='danger', icon=QStyle.StandardPixmap.SP_MediaStop)
        self.clear_button = command('清空', self.clear_samples, icon=QStyle.StandardPixmap.SP_DialogResetButton)
        self.export_button = command('导出 CSV', on_export, icon=QStyle.StandardPixmap.SP_DialogSaveButton)
        for button in (self.native_sdi_button, self.start_button, self.stop_button, self.clear_button, self.export_button):
            tools.addWidget(button)
        layout.addLayout(tools)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter, 1)
        left, right = QWidget(), QWidget()
        left.setMinimumWidth(260)
        right.setMinimumWidth(400)
        self.splitter.addWidget(left)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([300, 980])
        catalog, plot = QVBoxLayout(left), QVBoxLayout(right)
        catalog.setContentsMargins(0, 0, 8, 0)
        plot.setContentsMargins(4, 0, 0, 0)
        heading = QHBoxLayout()
        heading.addWidget(QLabel('信号'))
        self.count = QLabel('0 个测量量')
        heading.addStretch()
        heading.addWidget(self.count)
        catalog.addLayout(heading)
        self.tree = CatalogTree(('采集', '名称', '最新值'))
        self.tree.setColumnWidth(0, 44)
        self.tree.setColumnWidth(1, 170)
        catalog.addWidget(self.tree, 1)
        self.signal_name = QLabel('--')
        self.signal_name.setWordWrap(True)
        self.signal_name.setObjectName('sectionHeading')
        self.signal_details = QLabel('--')
        self.signal_details.setWordWrap(True)
        catalog.addWidget(self.signal_name)
        catalog.addWidget(self.signal_details)
        editor = QHBoxLayout()
        self.visible = QCheckBox('显示')
        self.color = command('', self._color)
        self.color.setFixedSize(32, 25)
        self.color.setToolTip('信号颜色')
        self.color.setAccessibleName('信号颜色')
        self.subplot = QComboBox()
        self.subplot.addItem('1')
        editor.addWidget(self.visible)
        editor.addStretch()
        editor.addWidget(QLabel('子图'))
        editor.addWidget(self.subplot)
        editor.addWidget(self.color)
        catalog.addLayout(editor)
        self.chart = SignalChart(right, self.buffer)
        self.chart.on_display_changed = self._sync_editor
        self.chart.on_cursors_changed = self._render_cursors
        plot.addWidget(self.chart, 1)
        self.details = QTabWidget()
        self.details.setMaximumHeight(170)
        self.stats_tree = table(('测量量', '最新', '最小', '最大', '样本数'))
        self.cursor_tree = table(('信号', '值 @ t1', '值 @ t2', '值差'))
        for detail in (self.stats_tree, self.cursor_tree):
            detail.setColumnWidth(0, 180)
            for column in range(1, detail.columnCount()):
                detail.setColumnWidth(column, 120)
        self.cursor_tree.setToolTip('* 表示线性插值；-- 表示超出已采样范围')
        self.details.addTab(self.stats_tree, '统计')
        self.details.addTab(self.cursor_tree, '游标值')
        plot.addWidget(self.details)
        self.tree.checksChanged.connect(self._set_selected)
        self.tree.itemSelectionChanged.connect(self._sync_editor)
        self.tree.itemDoubleClicked.connect(lambda item, column: self._toggle(item) if column != 0 else None)
        self.search.textChanged.connect(self._render_catalog)
        self.acquisition.currentTextChanged.connect(self._mode_changed)
        self.visible.clicked.connect(lambda value: self._display(visible=value))
        self.subplot.activated.connect(lambda index: self._display(subplot=index))
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context)
        for detail in (self.stats_tree, self.cursor_tree):
            detail.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            detail.customContextMenuRequested.connect(lambda point, t=detail: self._detail_menu(t, point))
        self._mode_changed()
        self._sync_editor()

    def selected_names(self):
        return [name for name in self._items if name in self._selected]

    def sample_interval(self):
        return self.interval.value()

    def set_measurements(self, items):
        self._items = {str(attr(item, 'name')): item for item in items}
        self._selected.intersection_update(self._items)
        capacity = self.buffer.max_points
        self.buffer.close()
        self.buffer = NativeBuffer(capacity)
        self.chart.buffer = self.buffer
        self.chart.state.signals.clear()
        self.chart.ensure_signals(self._items)
        self.chart._build_axes()
        self.chart.set_selected_signals(self._selected)
        self._render_catalog()
        self._render_stats()

    def set_daq_metadata(self, metadata):
        data = dict(metadata or {})
        period = data.get('period_seconds')
        if period is not None and (not math.isfinite(float(period)) or float(period) <= 0):
            raise ValueError('DAQ 模型周期必须是有限的正数。')
        self.daq_metadata = data
        self.daq_period_var.set('--' if period is None else f'{float(period):.8g}')

    def append_values(self, timestamp, values):
        self.buffer.append(timestamp, values)
        self._refresh_samples()

    def append_samples(self, samples, offset=0):
        rows = [(float(sample.timestamp_seconds) + float(offset), sample.values) for sample in samples]
        self.buffer.append_batch(rows)
        if rows:
            self._refresh_samples()
        return len(rows)

    def _refresh_samples(self):
        self.chart.draw()
        stats = self.buffer.stats()
        for name, item in self.tree.leaves.items():
            if name in stats:
                item.setText(2, f'{stats[name][0]:.8g}')
        self._render_stats()
        if self._last_policy:
            self.set_policy(self._last_policy)

    def clear_samples(self):
        self.chart.clear()
        self._render_catalog()
        self._render_stats()
        if self._last_policy:
            self.set_policy(self._last_policy)

    def _mode_changed(self, *_):
        daq = self.acquisition.currentText() == 'DAQ'
        self.interval.setVisible(not daq)
        self.daq_period.setVisible(daq)
        self.interval.setEnabled(self._selection_enabled and not daq)

    def set_policy(self, policy):
        changed = self._selection_enabled != policy.observation_select_enabled
        self._last_policy = policy
        self._selection_enabled = policy.observation_select_enabled
        self.search.setEnabled(self._selection_enabled)
        self.acquisition.setEnabled(self._selection_enabled)
        self._mode_changed()
        self.start_button.setEnabled(policy.observation_start_enabled)
        self.stop_button.setEnabled(policy.observation_stop_enabled)
        has_samples = len(self.buffer) > 0
        self.clear_button.setEnabled(has_samples)
        self.export_button.setEnabled(has_samples)
        self.native_sdi_button.setEnabled(has_samples and (policy.observation_select_enabled or policy.endpoint_enabled))
        if changed:
            self._render_catalog()

    def _selection(self):
        return self.tree.selected_names()

    def _toggle(self, item):
        name = self.tree.name(item)
        if name is not None:
            self._set_selected([name], name not in self._selected)

    def _set_selected(self, names, checked):
        if self._selection_enabled:
            for name in names:
                if checked:
                    self._selected.add(name)
                else:
                    self._selected.discard(name)
            self._render_catalog()
            self.chart.set_selected_signals(self._selected)

    def _display(self, **settings):
        self._display_names(self._selection(), **settings)

    def _display_names(self, names, **settings):
        for name in names:
            self.chart.set_signal_display(name, **settings)

    def _color(self, names=None):
        names = self._selection() if names is None else names
        if not names:
            return
        color = QColorDialog.getColor(QColor(self.chart.state.signals[names[0]].color), self, '信号颜色')
        if color.isValid():
            self._display_names(names, color=color.name())

    def _sync_editor(self):
        names = self._selection()
        for widget in (self.visible, self.color, self.subplot):
            widget.setEnabled(bool(names))
        if not names:
            self.signal_name.setText('--')
            self.signal_details.setText('--')
            return
        name = names[0]
        style = self.chart.state.signals[name]
        item = self._items[name]
        self.signal_name.setText(name)
        self.signal_details.setText(f'0x{attr(item, "address", 0):08X} | {attr(item, "data_type", "--")}')
        self.visible.setChecked(style.visible)
        self.subplot.clear()
        self.subplot.addItems([str(i + 1) for i in range(self.chart.state.subplot_count)])
        self.subplot.setCurrentIndex(style.subplot)
        self.color.setStyleSheet(f'background: {style.color}; border-radius: 4px;')

    def _render_catalog(self, *_):
        stats = self.buffer.stats()
        rows = {name: ('', name, f'{stats[name][0]:.8g}' if name in stats else '--') for name in self._items}
        self.tree.set_catalog(self._items, rows, self._selected, self._selection_enabled)
        self.tree.set_filter(self.search.text())
        self.count.setText(f'{len(self._items)} / 已选 {len(self._selected)}')
        self._sync_editor()

    def _render_stats(self):
        rows = [(name, f'{latest:.8g}', f'{low:.8g}', f'{high:.8g}', count) for name, (latest, low, high, count) in self.buffer.stats().items()]
        self._fill(self.stats_tree, rows)

    def _render_cursors(self):
        if not hasattr(self, 'cursor_tree'):
            return
        rows = []
        if self.chart.cursor_count:
            for name, style in self.chart.state.signals.items():
                if name not in self._selected or not self.chart.is_plotted(name):
                    continue
                a, ia = self.buffer.value_at(name, self.chart.state.cursors[0])
                b, ib = self.buffer.value_at(name, self.chart.state.cursors[1]) if self.chart.cursor_count == 2 else (None, False)
                fmt = lambda value, interpolated=False: '--' if value is None else f'{value:.8g}' + ('*' if interpolated else '')
                rows.append((name, fmt(a, ia), fmt(b, ib), fmt(None if a is None or b is None else b - a)))
        self._fill(self.cursor_tree, rows)
        self.cursor_tree.setColumnHidden(2, self.chart.cursor_count != 2)
        self.cursor_tree.setColumnHidden(3, self.chart.cursor_count != 2)
        enabled = self.chart.cursor_count > 0
        if enabled != self._cursors_were_enabled:
            self.details.setCurrentIndex(1 if enabled else 0)
            self._cursors_were_enabled = enabled

    @staticmethod
    def _fill(widget, rows):
        selected = {widget.item(index.row(), 0).text() for index in widget.selectionModel().selectedRows()
                    if widget.item(index.row(), 0) is not None}
        widget.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                item = widget.item(row, column)
                if item is None:
                    item = QTableWidgetItem()
                    widget.setItem(row, column, item)
                item.setText(str(value))
                item.setSelected(str(values[0]) in selected)

    def _context(self, position):
        item = self.tree.itemAt(position)
        if item and not item.isSelected():
            self.tree.select_item(item)
        names = self._selection()
        filtered = self.tree.filtered_names()
        menu = QMenu(self)
        icons = QStyle.StandardPixmap
        for text, selected, checked in (('采集所选行', names, True), ('取消采集所选行', names, False), ('采集筛选结果', filtered, True), ('取消采集筛选结果', filtered, False)):
            changed = any((name in self._selected) != checked for name in selected)
            menu_command(menu, text, lambda n=selected, c=checked: self._set_selected(n, c),
                         icons.SP_DialogApplyButton if checked else icons.SP_DialogCancelButton,
                         self._selection_enabled and changed)
        menu.addSeparator()
        menu_command(menu, '显示所选曲线', lambda: self._display_names(names, visible=True), icons.SP_DialogYesButton,
                     any(not self.chart.state.signals[name].visible for name in names))
        menu_command(menu, '隐藏所选曲线', lambda: self._display_names(names, visible=False), icons.SP_DialogNoButton,
                     any(self.chart.state.signals[name].visible for name in names))
        color_action = menu_command(menu, '设置颜色', lambda: self._color(names), icons.SP_DialogResetButton, bool(names))
        if names:
            swatch = QPixmap(16, 16)
            swatch.fill(QColor(self.chart.state.signals[names[0]].color))
            color_action.setIcon(QIcon(swatch))
        submenu = menu.addMenu('移到子图')
        submenu.setEnabled(bool(names))
        submenu.setIcon(self.style().standardIcon(icons.SP_FileDialogListView))
        for index in range(self.chart.state.subplot_count):
            menu_command(submenu, str(index + 1), lambda i=index: self._display_names(names, subplot=i),
                         icons.SP_ArrowRight, any(self.chart.state.signals[name].subplot != index for name in names))
        menu.addSeparator()
        menu_command(menu, '复制名称', lambda: QApplication.clipboard().setText('\n'.join(names)), icons.SP_FileIcon, bool(names))
        menu_command(menu, '复制名称和最新值', lambda: self._copy_latest(names), icons.SP_FileDialogDetailedView, bool(names))
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def _copy_latest(self, names):
        stats = self.buffer.stats()
        QApplication.clipboard().setText('\n'.join(name + '\t' + (f'{stats[name][0]:.8g}' if name in stats else '--') for name in names))

    @staticmethod
    def _detail_menu(widget, position):
        item = widget.itemAt(position)
        if item is not None and not item.isSelected():
            widget.selectRow(item.row())
        rows = sorted({index.row() for index in widget.selectedIndexes()})
        text = '\n'.join('\t'.join(widget.item(row, column).text() if widget.item(row, column) else ''
                                  for column in range(widget.columnCount())) for row in rows)
        menu = QMenu(widget)
        menu_command(menu, '复制所选行', lambda: QApplication.clipboard().setText(text), QStyle.StandardPixmap.SP_FileIcon, bool(rows))
        menu_command(menu, '选择全部', widget.selectAll, QStyle.StandardPixmap.SP_DialogApplyButton, widget.rowCount() > 0)
        menu.exec(widget.viewport().mapToGlobal(position))

    def dispose(self):
        self.chart.dispose()
        self.buffer.close()
