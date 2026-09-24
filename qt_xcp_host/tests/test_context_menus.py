"""APP-10: trigger real Qt menu actions and verify their observable effects."""
import os
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QMenu
from qt_host.calibration import CalibrationTab
from qt_host.observation import ObservationTab
from qt_host.window import DiagnosticsTab


class ContextMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widgets = []
        self.qt_errors = []
        hook = patch.object(sys, 'excepthook', lambda *error: self.qt_errors.append(error))
        hook.start()
        self.addCleanup(hook.stop)

    def tearDown(self):
        for widget in self.widgets:
            if hasattr(widget, 'dispose'):
                widget.dispose()
            widget.close()
            widget.deleteLater()
        self.app.processEvents()
        self.assertEqual(self.qt_errors, [], 'A QAction callback raised an exception')

    def menu(self, opener):
        menus = []
        class InspectMenu(QMenu):
            def exec(self, *_):
                menus.append(self)
        with ExitStack() as stack:
            for module in ('observation', 'calibration', 'chart', 'window'):
                stack.enter_context(patch(f'qt_host.{module}.QMenu', InspectMenu))
            opener()
        self.assertEqual(len(menus), 1)
        self.check_icons(menus[0])
        return menus[0]

    def check_icons(self, menu):
        for action in menu.actions():
            if action.isSeparator():
                continue
            self.assertFalse(action.icon().isNull(), action.text())
            if action.menu() is not None:
                self.check_icons(action.menu())

    def action(self, menu, *labels):
        for index, label in enumerate(labels):
            matches = [action for action in menu.actions() if action.text() == label]
            self.assertEqual(len(matches), 1, label)
            action = matches[0]
            if index < len(labels) - 1:
                menu = action.menu()
                self.assertIsNotNone(menu)
        return action

    def trigger(self, menu, *labels):
        action = self.action(menu, *labels)
        self.assertTrue(action.isEnabled(), labels)
        action.trigger()
        self.assertEqual(self.qt_errors, [], 'A QAction callback raised an exception')
        return action

    @staticmethod
    def point(table, row=0):
        if hasattr(table, 'leaves'):
            return table.visualItemRect(table.leaves[table.filtered_names()[row]]).center()
        return table.visualItemRect(table.item(row, 1)).center()

    def observation(self):
        widget = ObservationTab(None, lambda: None, lambda: None, lambda: None, lambda: None, max_points=100)
        self.widgets.append(widget)
        widget.resize(1200, 750)
        widget._selection_enabled = True
        widget.set_measurements([{'name': 'speed', 'address': 4096}, {'name': 'voltage', 'address': 4104}])
        widget.append_values(0., {'speed': 1., 'voltage': 10.})
        widget.append_values(1., {'speed': 2., 'voltage': 20.})
        return widget

    def observation_menu(self, widget, row=0):
        return self.menu(lambda: widget._context(self.point(widget.tree, row)))

    def test_observation_sampling_actions_keep_bound_names_and_boolean(self):
        widget = self.observation()
        self.trigger(self.observation_menu(widget, 1), '采集所选行')
        self.assertEqual(widget.selected_names(), ['voltage'])
        self.trigger(self.observation_menu(widget, 1), '取消采集所选行')
        self.assertEqual(widget.selected_names(), [])
        self.trigger(self.observation_menu(widget), '采集筛选结果')
        self.assertEqual(widget.selected_names(), ['speed', 'voltage'])
        self.trigger(self.observation_menu(widget), '取消采集筛选结果')
        self.assertEqual(widget.selected_names(), [])
        widget.search.setText('volt')
        self.trigger(self.observation_menu(widget), '采集筛选结果')
        self.assertEqual(widget.selected_names(), ['voltage'])
        widget._selection_enabled = False
        self.assertFalse(self.action(self.observation_menu(widget), '取消采集所选行').isEnabled())

    def test_observation_display_color_subplot_and_copy_target_clicked_signal(self):
        widget = self.observation()
        widget.chart.set_layout('2 x 2')
        self.trigger(self.observation_menu(widget, 1), '隐藏所选曲线')
        self.assertFalse(widget.chart.state.signals['voltage'].visible)
        self.assertTrue(widget.chart.state.signals['speed'].visible)
        self.trigger(self.observation_menu(widget, 1), '显示所选曲线')
        self.assertTrue(widget.chart.state.signals['voltage'].visible)
        with patch('qt_host.observation.QColorDialog.getColor', return_value=QColor('#123456')):
            self.trigger(self.observation_menu(widget, 1), '设置颜色')
        self.assertEqual(widget.chart.state.signals['voltage'].color, '#123456')
        for index in (1, 2, 3, 0):
            self.trigger(self.observation_menu(widget, 1), '移到子图', str(index + 1))
            self.assertEqual(widget.chart.state.signals['voltage'].subplot, index)
            self.assertIs(widget.chart.lines['voltage'].axes, widget.chart.axes[index])
        self.trigger(self.observation_menu(widget, 1), '复制名称')
        self.assertEqual(self.app.clipboard().text(), 'voltage')
        self.trigger(self.observation_menu(widget, 1), '复制名称和最新值')
        self.assertEqual(self.app.clipboard().text(), 'voltage\t20')
        menu = self.observation_menu(widget, 1)
        widget.tree.select_item(widget.tree.leaves['speed'])
        self.trigger(menu, '隐藏所选曲线')
        self.assertFalse(widget.chart.state.signals['voltage'].visible)
        self.assertTrue(widget.chart.state.signals['speed'].visible)

    def test_statistics_and_cursor_tables_select_clicked_row_and_preserve_copy_snapshot(self):
        widget = self.observation()
        widget._set_selected(('speed', 'voltage'), True)
        widget.chart.set_cursors_enabled(True)
        for table in (widget.stats_tree, widget.cursor_tree):
            with self.subTest(table=table):
                table.clearSelection()
                opener = lambda: widget._detail_menu(table, self.point(table, 1))
                menu = self.menu(opener)
                selected = [index.row() for index in table.selectionModel().selectedRows()]
                self.assertEqual(selected, [1])
                expected = '\t'.join(table.item(1, column).text() for column in range(table.columnCount()))
                widget.append_values(2., {'speed': 3., 'voltage': 30.})
                self.trigger(menu, '复制所选行')
                self.assertEqual(self.app.clipboard().text(), expected)
                self.assertEqual([index.row() for index in table.selectionModel().selectedRows()], [1])
                self.trigger(self.menu(opener), '选择全部')
                self.assertEqual(len(table.selectionModel().selectedRows()), 2)
        widget.set_measurements([])
        menu = self.menu(lambda: widget._detail_menu(widget.stats_tree, QPoint(1, 1)))
        self.assertFalse(self.action(menu, '复制所选行').isEnabled())
        self.assertFalse(self.action(menu, '选择全部').isEnabled())

    def calibration(self):
        calls = []
        widget = CalibrationTab(None, lambda: calls.append('refresh'),
                                lambda: calls.append(('write', widget.pending_changes())),
                                lambda: calls.append('restore'), lambda *_: '2.5',
                                lambda error: self.fail(error))
        self.widgets.append(widget)
        widget._editing_enabled = True
        widget.set_calibrations([{'name': 'gain', 'address': 4096}, {'name': 'offset', 'address': 4104}])
        widget.update_current_values({'gain': 1., 'offset': 0.})
        return widget, calls

    def calibration_menu(self, widget, row=0):
        return self.menu(lambda: widget._context(self.point(widget.tree, row)))

    def test_calibration_edit_write_refresh_restore_and_undo_actions(self):
        widget, calls = self.calibration()
        menu = self.calibration_menu(widget, 1)
        self.assertFalse(self.action(menu, '写入勾选项').isEnabled())
        self.assertFalse(self.action(menu, '撤销所选待写值').isEnabled())
        self.trigger(menu, '编辑新值')
        self.assertEqual(widget.pending_changes(), {'offset': 2.5})
        self.trigger(self.calibration_menu(widget, 1), '写入勾选项')
        self.assertEqual(calls[-1], ('write', {'offset': 2.5}))
        self.trigger(self.calibration_menu(widget, 1), '刷新')
        self.assertEqual(calls[-1], 'refresh')
        self.trigger(self.calibration_menu(widget, 1), '恢复本次会话')
        self.assertEqual(calls[-1], 'restore')
        self.trigger(self.calibration_menu(widget, 1), '复制名称')
        self.assertEqual(self.app.clipboard().text(), 'offset')
        self.trigger(self.calibration_menu(widget, 1), '复制名称和当前值')
        self.assertEqual(self.app.clipboard().text(), 'offset\t0.0')
        self.trigger(self.calibration_menu(widget, 1), '撤销所选待写值')
        self.assertEqual(widget.pending_changes(), {})
        self.assertEqual(widget._new_values, {})

    def test_calibration_selection_filter_and_disabled_state(self):
        widget, _ = self.calibration()
        self.trigger(self.calibration_menu(widget, 1), '勾选所选行')
        self.assertEqual(widget._selected, {'offset'})
        self.trigger(self.calibration_menu(widget, 1), '取消勾选所选行')
        self.assertEqual(widget._selected, set())
        self.trigger(self.calibration_menu(widget), '勾选筛选结果')
        self.assertEqual(widget._selected, {'gain', 'offset'})
        self.trigger(self.calibration_menu(widget), '取消勾选筛选结果')
        self.assertEqual(widget._selected, set())
        widget.search.setText('gain')
        self.trigger(self.calibration_menu(widget), '勾选筛选结果')
        self.assertEqual(widget._selected, {'gain'})
        widget.search.setText('no-match')
        menu = self.menu(lambda: widget._context(QPoint(1, 1)))
        for label in ('编辑新值', '勾选所选行', '取消勾选所选行', '勾选筛选结果', '取消勾选筛选结果', '撤销所选待写值'):
            self.assertFalse(self.action(menu, label).isEnabled(), label)

    def chart_menu(self, chart, stamp=.4, inside=True):
        event = SimpleNamespace(xdata=stamp, inaxes=chart.axes[0] if inside else None, x=100, y=100)
        return self.menu(lambda: chart._show_context_menu(event))

    def test_chart_cursor_actions_move_each_cursor_independently(self):
        chart = self.observation().chart
        self.trigger(self.chart_menu(chart), '双游标')
        self.assertEqual(chart.cursor_count, 2)
        self.trigger(self.chart_menu(chart, .7), '将游标 2 移到此处')
        self.assertAlmostEqual(chart.state.cursors[1], .7)
        self.trigger(self.chart_menu(chart, .2), '将游标 1 移到此处')
        self.assertEqual(chart.state.cursors, (.2, .7))
        self.trigger(self.chart_menu(chart), '双游标')
        self.assertEqual(chart.cursor_count, 0)
        menu = self.chart_menu(chart, None, inside=False)
        self.assertFalse(self.action(menu, '将游标 1 移到此处').isEnabled())
        self.assertFalse(self.action(menu, '将游标 2 移到此处').isEnabled())

    def test_chart_modes_layout_follow_fit_and_export(self):
        chart = self.observation().chart
        for label, mode in (('采样点', 'points'), ('曲线', 'line')):
            self.trigger(self.chart_menu(chart), '显示方式', label)
            self.assertEqual(chart.state.display_mode, mode)
        for layout, count in (('2 x 1', 2), ('2 x 2', 4), ('1 x 1', 1)):
            self.trigger(self.chart_menu(chart), '子图布局', layout)
            self.assertEqual(chart.state.layout, layout)
            self.assertEqual(len(chart.axes), count)
        self.trigger(self.chart_menu(chart), '跟随最新数据')
        self.assertFalse(chart.follow_var.get())
        chart.axes[0].set_xlim(30, 40)
        self.trigger(self.chart_menu(chart), '适应全部数据')
        self.assertEqual(tuple(chart.axes[0].get_xlim()), (0., 1.))
        self.trigger(self.chart_menu(chart), '跟随最新数据')
        self.assertTrue(chart.follow_var.get())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'chart.png'
            with patch('qt_host.chart.QFileDialog.getSaveFileName', return_value=(str(path), 'PNG (*.png)')):
                self.trigger(self.chart_menu(chart), '导出 PNG 图像')
            self.assertEqual(path.read_bytes()[:8], b'\x89PNG\r\n\x1a\n')

    def test_diagnostics_copy_select_clear_save_and_read_actions(self):
        saved = []
        widget = DiagnosticsTab(None, lambda: saved.append(widget.log_text_value()), lambda: widget.append_log('remote'))
        self.widgets.append(widget)
        widget.append_log('local')
        opener = lambda: widget._log_context_menu(QPoint(1, 1))
        menu = self.menu(opener)
        self.assertFalse(self.action(menu, '复制所选文本').isEnabled())
        self.assertFalse(self.action(menu, '读取运行日志').isEnabled())
        self.trigger(menu, '选择全部')
        self.trigger(self.menu(opener), '复制所选文本')
        self.assertEqual(self.app.clipboard().text(), 'local')
        widget.read_log_button.setEnabled(True)
        self.trigger(self.menu(opener), '读取运行日志')
        self.assertEqual(widget.log_text_value(), 'local\nremote')
        self.trigger(self.menu(opener), '复制全部')
        self.assertEqual(self.app.clipboard().text(), 'local\nremote')
        self.trigger(self.menu(opener), '保存日志')
        self.assertEqual(saved, ['local\nremote'])
        self.trigger(self.menu(opener), '清空显示')
        self.assertEqual(widget.log_text_value(), '')
        menu = self.menu(opener)
        for label in ('复制所选文本', '选择全部', '复制全部', '保存日志', '清空显示'):
            self.assertFalse(self.action(menu, label).isEnabled(), label)


if __name__ == '__main__':
    unittest.main()
