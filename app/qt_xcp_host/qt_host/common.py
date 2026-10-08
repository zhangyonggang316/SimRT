"""Shared Qt controls and GUI-thread completion dispatch."""
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QObject, Signal, Slot, Qt
from PySide6.QtWidgets import QApplication, QPushButton, QStyle, QTableWidget, QAbstractItemView, QHeaderView


class AsyncWorker(QObject):
    busyChanged = Signal(bool)
    _completed = Signal(object, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='qt-xcp-worker')
        self.busy = False
        self._closed = False
        self._completed.connect(self._deliver, Qt.ConnectionType.QueuedConnection)

    def submit(self, label, call, on_success=None, on_error=None):
        if self.busy or self._closed:
            return False
        self.busy = True
        self.busyChanged.emit(True)
        future = self._executor.submit(call)

        def completed(result):
            try:
                value = result.result()
            except BaseException as error:
                self._completed.emit(on_error, error, True)
            else:
                self._completed.emit(on_success, value, False)
        future.add_done_callback(completed)
        return True

    @Slot(object, object, object)
    def _deliver(self, callback, value, failed):
        self.busy = False
        # Complete ownership/state updates before another job may be accepted.
        try:
            if callback is not None:
                callback(value)
        finally:
            self.busyChanged.emit(self.busy)

    def shutdown(self):
        if self.busy:
            return False
        self._closed = True
        self._executor.shutdown(wait=False)
        return True


def command(text, callback, parent=None, icon=None, role=''):
    widget = QPushButton(text, parent)
    if icon is not None:
        widget.setIcon(widget.style().standardIcon(icon))
    if role:
        widget.setProperty('role', role)
    widget.clicked.connect(lambda _checked=False: callback())
    return widget


def menu_command(menu, text, callback, icon, enabled=True):
    action = menu.addAction(text)
    action.setIcon(menu.style().standardIcon(icon))
    action.setEnabled(enabled)
    # QAction.triggered supplies a boolean, not the captured command arguments.
    action.triggered.connect(lambda _checked=False: callback())
    return action


def table(headers, parent=None):
    from PySide6.QtGui import QKeySequence, QShortcut
    from PySide6.QtWidgets import QApplication
    widget = QTableWidget(0, len(headers), parent)
    widget.setHorizontalHeaderLabels(headers)
    widget.verticalHeader().hide()
    widget.verticalHeader().setDefaultSectionSize(30)
    widget.setAlternatingRowColors(True)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    widget.horizontalHeader().setStretchLastSection(True)
    widget.setShowGrid(False)
    def copy_rows():
        rows = sorted({index.row() for index in widget.selectedIndexes()})
        QApplication.clipboard().setText('\n'.join('\t'.join(
            widget.item(row, column).text() if widget.item(row, column) else ''
            for column in range(widget.columnCount())) for row in rows))
    shortcut = QShortcut(QKeySequence.StandardKey.Copy, widget)
    shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
    shortcut.activated.connect(copy_rows)
    return widget


def attr(value, key, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def apply_theme(app):
    app.setStyle('Fusion')
    app.setStyleSheet('''
    QWidget { font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 12px;
              color: #243444; background: #f5f7fa; }
    QMainWindow { background: #f5f7fa; }
    QFrame#appHeader { background: #1264b2; border: 0; }
    QFrame#appHeader QLabel { color: #ffffff; background: transparent; }
    QLabel#appTitle { font-size: 15px; font-weight: 600; }
    QLabel#sectionHeading { color: #155b9a; font-weight: 600; }
    QLabel#statusValue { font-weight: 600; }
    QTabWidget::pane { border: 1px solid #d7e0ea; background: #ffffff; }
    QTabBar::tab { padding: 9px 24px; background: #e8eef5; border: 0; min-width: 65px; }
    QTabBar::tab:selected { background: #ffffff; color: #1264b2; }
    QTabWidget#mainTabs > QTabBar::tab { padding: 11px 34px; font-size: 13px; font-weight: 600; }
    QTabWidget#mainTabs > QTabBar::tab:selected { background: #1264b2; color: #ffffff; }
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: #ffffff; border: 1px solid #cbd6e2;
                 border-radius: 4px; padding: 5px 7px; min-height: 20px; }
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: #1264b2; }
    QLineEdit:read-only { background: #edf2f7; }
    QPushButton { background: #ffffff; border: 1px solid #cbd6e2; border-radius: 4px; padding: 6px 12px; min-height: 20px; }
    QPushButton:hover, QToolButton:hover { background: #e5f1ff; border-color: #86b7e8; }
    QPushButton:pressed, QToolButton:pressed { background: #d1e7fc; }
    QPushButton[role="primary"] { background: #1264b2; color: white; border-color: #1264b2; }
    QPushButton[role="danger"] { color: #bc343b; }
    QPushButton:disabled, QToolButton:disabled { color: #93a0b0; background: #edf1f5; border-color: #d9e1e9; }
    QWidget#targetWorkspace QPushButton { padding: 4px 6px; min-height: 18px; }
    QToolButton { background: transparent; border: 1px solid transparent; border-radius: 4px; padding: 4px; }
    QToolButton:checked { background: #d9ebff; border-color: #91b9e5; }
    QTableWidget, QTableView, QPlainTextEdit { background: #ffffff; alternate-background-color: #f5f8fc;
              border: 1px solid #d7e0ea; border-radius: 4px; selection-background-color: #d8eaff; selection-color: #164d85; }
    QHeaderView::section { background: #edf2f8; border: 0; border-bottom: 1px solid #d7e0ea; padding: 7px 8px; font-weight: 600; }
    QTableWidget::item { padding: 3px 6px; }
    QSplitter::handle { background: #e0e7ef; width: 4px; height: 4px; }
    QProgressBar { border: 0; border-radius: 3px; background: #e4ebf3; min-height: 6px; max-height: 9px; }
    QProgressBar::chunk { background: #178f82; border-radius: 3px; }
    QMenu { background: white; border: 1px solid #cbd6e2; padding: 4px; }
    QMenu::item { padding: 6px 22px; }
    QMenu::item:selected { background: #e5f1ff; }
    QToolTip { background: #243444; color: #ffffff; border: none; padding: 5px; }
    ''')
