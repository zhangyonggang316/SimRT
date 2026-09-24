"""Model tree stability and checked-curve cursor behavior."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from qt_host.calibration import CalibrationTab
from qt_host.observation import ObservationTab


class HierarchyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.observation = ObservationTab(None, lambda: None, lambda: None, lambda: None, lambda: None, max_points=100)
        self.calibration = CalibrationTab(None, lambda: None, lambda: None, lambda: None, lambda *_: '2', lambda _: None)
        self.items = [dict(name='flat_C_name', model_path=('Plant', 'Drive / Front', 'Feedback')),
                      dict(name='other', model_path=('Plant', 'Controller')),
                      dict(name='ungrouped_identifier')]
        self.observation._selection_enabled = True
        self.calibration._editing_enabled = True
        self.observation.set_measurements(self.items)
        self.calibration.set_calibrations(self.items)

    def tearDown(self):
        self.observation.dispose()
        for widget in (self.observation, self.calibration):
            widget.close()
            widget.deleteLater()
        self.app.processEvents()

    def test_real_segments_and_group_checks_in_both_catalogs(self):
        for widget in (self.observation, self.calibration):
            tree = widget.tree
            self.assertEqual(tree.leaves['flat_C_name'].parent().text(1), 'Feedback')
            self.assertEqual(tree.leaves['flat_C_name'].parent().parent().text(1), 'Drive / Front')
            self.assertIsNone(tree.leaves['ungrouped_identifier'].parent())
            tree.groups[('Plant',)].setCheckState(0, Qt.CheckState.Checked)
            self.assertEqual(widget._selected, {'flat_C_name', 'other'})
            tree.groups[('Plant', 'Controller')].setCheckState(0, Qt.CheckState.Unchecked)
            self.assertEqual(widget._selected, {'flat_C_name'})
            self.assertEqual(tree.groups[('Plant',)].checkState(0), Qt.CheckState.PartiallyChecked)

    def test_updates_preserve_objects_selection_and_expansion(self):
        for widget in (self.observation, self.calibration):
            tree = widget.tree
            group = tree.groups[('Plant', 'Drive / Front')]
            leaf = tree.leaves['other']
            group.setExpanded(False)
            tree.select_item(leaf)
            for value in range(5):
                if widget is self.observation:
                    widget.append_values(value, {'other': value})
                else:
                    widget.update_current_values({'other': value})
            self.assertIs(tree.leaves['other'], leaf)
            self.assertIs(tree.groups[('Plant', 'Drive / Front')], group)
            self.assertEqual(tree.selected_names(), ['other'])
            self.assertFalse(group.isExpanded())
            widget.search.setText('Drive / Front')
            self.assertEqual(tree.filtered_names(), ['flat_C_name'])
            self.assertTrue(group.isExpanded())
            widget.search.clear()
            self.assertFalse(group.isExpanded())

    def test_single_and_dual_only_measure_checked_plotted_curves(self):
        widget = self.observation
        chart = widget.chart
        widget._set_selected(['flat_C_name', 'other'], True)
        widget.append_values(0, {'flat_C_name': 1., 'other': 10.})
        widget.append_values(1, {'flat_C_name': 3., 'other': 20.})
        chart.set_cursor_mode(1)
        chart.set_cursors(.5, 1.)
        self.assertEqual(chart.cursor_count, 1)
        self.assertEqual(widget.cursor_tree.rowCount(), 2)
        self.assertTrue(widget.cursor_tree.isColumnHidden(2))
        self.assertEqual(widget.cursor_tree.item(0, 1).text(), '2*')
        self.assertTrue(all(pair[0].get_visible() and not pair[1].get_visible() for pair in chart._cursor_lines))
        widget._set_selected(['other'], False)
        self.assertEqual(widget.cursor_tree.rowCount(), 1)
        self.assertEqual(set(chart._cursor_snapshot), {'flat_C_name'})
        self.assertEqual(widget.buffer.stats()['other'][3], 2)
        chart.set_signal_display('flat_C_name', visible=False)
        self.assertEqual(widget.cursor_tree.rowCount(), 0)
        chart.set_signal_display('flat_C_name', visible=True)
        chart.set_cursor_mode(2)
        self.assertFalse(widget.cursor_tree.isColumnHidden(2))
        self.assertEqual(widget.cursor_tree.item(0, 3).text(), '1')
        self.assertTrue(all(all(line.get_visible() for line in pair) for pair in chart._cursor_lines))
        chart.set_cursor_mode(0)
        self.assertEqual(widget.cursor_tree.rowCount(), 0)


if __name__ == '__main__':
    unittest.main()
