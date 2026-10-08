"""Small field adapters for the existing, tested controller contract."""
from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QComboBox, QCheckBox, QLabel, QSpinBox, QDoubleSpinBox


class Field:
    def __init__(self, widget):
        self.widget = widget

    def get(self):
        if isinstance(self.widget, QComboBox):
            return self.widget.currentText()
        if isinstance(self.widget, QCheckBox):
            return self.widget.isChecked()
        if isinstance(self.widget, (QSpinBox, QDoubleSpinBox)):
            return str(self.widget.value())
        return self.widget.text()

    def set(self, value):
        if isinstance(self.widget, QComboBox):
            self.widget.setCurrentText(str(value))
        elif isinstance(self.widget, QCheckBox):
            self.widget.setChecked(bool(value))
        elif isinstance(self.widget, QSpinBox):
            self.widget.setValue(int(value))
        elif isinstance(self.widget, QDoubleSpinBox):
            self.widget.setValue(float(value))
        else:
            self.widget.setText(str(value))


class Scheduler(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self._timers = set()

    def after(self, milliseconds, callback):
        timer = QTimer(self)
        timer.setSingleShot(True)
        self._timers.add(timer)

        def fire():
            self._timers.discard(timer)
            timer.deleteLater()
            callback()
        timer.timeout.connect(fire)
        timer.start(milliseconds)
        return timer

    def after_cancel(self, timer):
        if timer in self._timers:
            timer.stop()
            timer.deleteLater()
            self._timers.remove(timer)

    def destroy(self):
        for timer in tuple(self._timers):
            self.after_cancel(timer)
        self.window._close_authorized = True
        self.window.close()
