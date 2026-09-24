"""SDI-style plots on the QtAgg backend; raw data and cursor queries use C++."""
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Dict, Iterable
from PySide6.QtCore import QTimer, QPoint
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QComboBox, QLineEdit, QLabel, QFileDialog, QMessageBox, QApplication, QMenu, QStyle
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from .fields import Field
from .common import menu_command

PALETTE = ("#0072bd", "#d95319", "#77ac30", "#7e2f8e", "#4dbeee", "#a2142f", "#c09a00")
LAYOUTS = {"1 x 1": (1, 1), "2 x 1": (2, 1), "2 x 2": (2, 2)}
DISPLAY_MODES = {"line": "曲线", "points": "采样点"}
CURSOR_COLORS = ("#536578", "#a2142f")

@dataclass
class SignalDisplay:
    color: str
    visible: bool = True
    subplot: int = 0

class PlotState:
    def __init__(self):
        self.signals: Dict[str, SignalDisplay] = {}
        self.layout = "1 x 1"
        self.cursors = (0.0, 1.0)
        self.display_mode = "line"

    @property
    def subplot_count(self) -> int:
        rows, columns = LAYOUTS[self.layout]
        return rows * columns

    def ensure_signals(self, names: Iterable[str]) -> None:
        for name in names:
            if name not in self.signals:
                self.signals[name] = SignalDisplay(PALETTE[len(self.signals) % len(PALETTE)])

    def set_layout(self, layout: str) -> None:
        if layout not in LAYOUTS:
            raise ValueError("Unsupported subplot layout: {}".format(layout))
        self.layout = layout
        for style in self.signals.values():
            if style.subplot >= self.subplot_count:
                style.subplot = 0

    def assign(self, name: str, subplot: int) -> None:
        if not 0 <= subplot < self.subplot_count:
            raise ValueError("Subplot is outside the current layout")
        self.ensure_signals((name,))
        self.signals[name].subplot = subplot

    def set_display_mode(self, mode: str) -> None:
        if mode not in DISPLAY_MODES:
            raise ValueError("Unsupported signal display mode: {}".format(mode))
        self.display_mode = mode

class NavigationToolbar(NavigationToolbar2QT):
    toolitems = (
        ("Home", "适应全部数据", "home", "home"),
        ("Back", "上一视图", "back", "back"),
        ("Forward", "下一视图", "forward", "forward"),
        (None, None, None, None),
        ("Pan", "平移", "move", "pan"),
        ("Zoom", "框选缩放", "zoom_to_rect", "zoom"),
        ("Save", "导出 PNG 图像", "filesave", "save_figure"),
    )

    def __init__(self, canvas, parent, chart):
        self.chart = chart
        super().__init__(canvas, parent, coordinates=False)
        self.setMovable(False)
        self.setFloatable(False)

    def set_message(self, message):
        # Coordinate text would displace the compact toolbar at the minimum window size.
        pass

    def home(self, *args):
        self.chart.fit_view()

    def back(self, *args):
        self.chart.follow_var.set(False)
        super().back(*args)

    def forward(self, *args):
        self.chart.follow_var.set(False)
        super().forward(*args)

    def pan(self, *args):
        self.chart.follow_var.set(False)
        self.chart.set_cursors_enabled(False)
        super().pan(*args)

    def zoom(self, *args):
        self.chart.follow_var.set(False)
        self.chart.set_cursors_enabled(False)
        super().zoom(*args)

    def save_figure(self, *args):
        self.chart.save_png()

    def press_pan(self, event):
        if event.button == 1:
            super().press_pan(event)

    def press_zoom(self, event):
        if event.button == 1:
            super().press_zoom(event)

class SignalChart(QWidget):
    def __init__(self, parent, buffer):
        super().__init__(parent)
        self.buffer = buffer
        self.state = PlotState()
        self.on_display_changed = self.on_cursors_changed = None
        self._destroyed = False
        self._plot_dirty = False
        self._draw_after_id = None
        self._drag_cursor = None
        self._cursor_lines, self._cursor_annotations = [], []
        self._cursor_markers, self._cursor_snapshot = {}, {}
        self._context_time = None
        self.lines, self.axes = {}, []
        self._selected_signals = None
        self.active_subplot = 0
        self.figure = Figure(figsize=(5.8, 3.2), dpi=100, facecolor="white")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setMinimumSize(280, 160)
        self.follow = QCheckBox("跟随")
        self.follow.setChecked(True)
        self.cursor = QComboBox()
        self.cursor.addItems(('关闭游标', '单游标', '双游标'))
        self.cursor.setToolTip('游标模式')
        self.layout_box, self.display_mode_box = QComboBox(), QComboBox()
        self.layout_box.addItems(LAYOUTS)
        self.display_mode_box.addItems(DISPLAY_MODES.values())
        self.follow_var = Field(self.follow)
        self.layout_var, self.display_mode_var = Field(self.layout_box), Field(self.display_mode_box)
        self.toolbar = NavigationToolbar(self.canvas, self, self)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        self._top_row = QHBoxLayout()
        self._top_row.addWidget(self.toolbar)
        self._control_widget = QWidget()
        controls = QHBoxLayout(self._control_widget)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addStretch()
        for widget in (self.cursor, self.follow, self.display_mode_box, self.layout_box):
            controls.addWidget(widget)
        self._top_row.addWidget(self._control_widget, 1)
        root.addLayout(self._top_row)
        self._compact_controls = False
        self.cursor_bar = QWidget()
        row = QHBoxLayout(self.cursor_bar)
        row.setContentsMargins(8, 0, 8, 0)
        a, b = QLineEdit("0"), QLineEdit("1")
        self._second_cursor_widgets = []
        for name, edit in (("t1", a), ("t2", b)):
            edit.setMaximumWidth(100)
            label, unit = QLabel(name), QLabel('s')
            row.addWidget(label)
            row.addWidget(edit)
            row.addWidget(unit)
            if name == 't2':
                self._second_cursor_widgets.extend((label, edit, unit))
            edit.editingFinished.connect(self._apply_cursor_entries)
        delta = QLabel("dt = 1 s")
        row.addWidget(delta)
        self._second_cursor_widgets.append(delta)
        row.addStretch()
        self.cursor_a_var, self.cursor_b_var, self.delta_var = Field(a), Field(b), Field(delta)
        root.addWidget(self.cursor_bar)
        self.cursor_bar.hide()
        root.addWidget(self.canvas, 1)
        self.follow.clicked.connect(self._follow_changed)
        self.cursor.currentIndexChanged.connect(self.set_cursor_mode)
        self.layout_box.activated.connect(lambda _: self.set_layout(self.layout_var.get()))
        self.display_mode_box.activated.connect(self._display_mode_selected)
        self._draw_timer = QTimer(self)
        self._draw_timer.setSingleShot(True)
        self._draw_timer.timeout.connect(self._flush_draw)
        for event, callback in (("button_press_event", self._mouse_down), ("motion_notify_event", self._mouse_move),
                                ("button_release_event", self._mouse_up), ("scroll_event", self._scroll_zoom),
                                ("resize_event", self._view_limits_changed)):
            self.canvas.mpl_connect(event, callback)
        self._build_axes()

    def _fit_limits(self):
        extrema = self.buffer.stats()
        spans = []
        for index, axis in enumerate(self.axes):
            selected = [name for name, style in self.state.signals.items() if self.is_selected(name) and style.visible and style.subplot == index and name in extrema]
            if not selected:
                axis.set_ylim(-1, 1)
                continue
            low = min(extrema[name][1] for name in selected)
            high = max(extrema[name][2] for name in selected)
            padding = max(abs(low) * .08, .1) if math.isclose(low, high) else (high - low) * .08
            axis.set_ylim(low - padding, high + padding)
            for name in selected:
                spans.extend(point.elapsed_seconds for point in self.buffer.plot_points(name, 2))
        low, high = (min(spans), max(spans)) if spans else (0, 1)
        self.axes[0].set_xlim(low, high if high > low else low + 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.width() < 610
        if hasattr(self, '_control_widget') and compact != self._compact_controls:
            self._compact_controls = compact
            if compact:
                self.layout().insertWidget(1, self._control_widget)
            else:
                self._top_row.addWidget(self._control_widget, 1)

    def _show_context_menu(self, event):
        self._context_time = event.xdata
        menu = QMenu(self)
        icons = QStyle.StandardPixmap
        menu_command(menu, "适应全部数据", self.fit_view, icons.SP_DesktopIcon, len(self.buffer) > 0)
        action = menu_command(menu, "跟随最新数据", lambda: (self.follow_var.set(not self.follow_var.get()), self._follow_changed()), icons.SP_MediaSkipForward)
        action.setCheckable(True)
        action.setChecked(self.follow_var.get())
        for count, label in enumerate(('关闭游标', '单游标', '双游标')):
            action = menu_command(menu, label, lambda n=count: self.set_cursor_mode(0 if n == self.cursor_count else n), icons.SP_ArrowLeft)
            action.setCheckable(True)
            action.setChecked(count == self.cursor_count)
        for index in range(2):
            menu_command(menu, f"将游标 {index + 1} 移到此处", lambda i=index: self._cursor_at_context(i),
                         icons.SP_ArrowDown, event.inaxes in self.axes and event.xdata is not None)
        for title, values, call in (("显示方式", DISPLAY_MODES, self.set_display_mode), ("子图布局", LAYOUTS, self.set_layout)):
            sub = menu.addMenu(title)
            sub.setIcon(self.style().standardIcon(icons.SP_FileDialogListView))
            for value in values:
                label = DISPLAY_MODES[value] if title == "显示方式" else value
                action = menu_command(sub, label, lambda v=value, cb=call: cb(v), icons.SP_FileDialogContentsView)
                action.setCheckable(True)
                action.setChecked(value == (self.state.display_mode if title == "显示方式" else self.state.layout))
        menu_command(menu, "导出 PNG 图像", lambda: self.save_png(), icons.SP_DialogSaveButton)
        ratio = self.canvas.devicePixelRatioF()
        point = QPoint(round(event.x / ratio), round(self.canvas.height() - event.y / ratio))
        menu.exec(self.canvas.mapToGlobal(point))

    def save_png(self, path=None):
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "导出观测图像", "", "PNG (*.png)")
        if not path:
            return None
        output = Path(path)
        try:
            self._layout_cursor_annotations()
            self.figure.savefig(str(output), format="png", dpi=150, facecolor="white")
        except OSError as error:
            QMessageBox.critical(self, "导出图像失败", str(error))
            return None
        return output

    def request_draw(self):
        if not self._destroyed and not self._draw_timer.isActive():
            self._draw_timer.start(60)

    def dispose(self):
        self._destroyed = True
        self._draw_timer.stop()
        self.canvas.close()

    def _display_mode_selected(self, _event=None):
        for mode, label in DISPLAY_MODES.items():
            if label == self.display_mode_var.get():
                self.set_display_mode(mode)
                break

    def set_display_mode(self, mode):
        self.state.set_display_mode(mode)
        self.display_mode_var.set(DISPLAY_MODES[mode])
        self.draw()
        self._notify_display()

    def ensure_signals(self, names):
        self.state.ensure_signals(names)

    def set_layout(self, layout):
        if self.toolbar.mode:
            if str(self.toolbar.mode) == "pan/zoom":
                self.toolbar.pan()
            else:
                self.toolbar.zoom()
        self.state.set_layout(layout)
        self.layout_var.set(layout)
        self.active_subplot = min(self.active_subplot, self.state.subplot_count - 1)
        self._build_axes()
        self.draw()
        self.fit_view()
        self._notify_display()

    def set_signal_display(self, name, visible=None, color=None, subplot=None):
        self.ensure_signals((name,))
        style = self.state.signals[name]
        if visible is not None:
            style.visible = bool(visible)
        if color is not None:
            from matplotlib.colors import to_hex
            style.color = to_hex(color)
        if subplot is not None:
            self.state.assign(name, int(subplot))
        self.draw()
        self._notify_display()

    def _notify_display(self):
        if self.on_display_changed:
            self.on_display_changed()
        if self.on_cursors_changed:
            self.on_cursors_changed()

    def _build_axes(self):
        self.figure.clear()
        self.axes = []
        self.lines.clear()
        self._cursor_lines = []
        self._cursor_annotations = []
        self._cursor_markers = {}
        rows, columns = LAYOUTS[self.state.layout]
        self.figure.subplots_adjust(left=0.105 if columns == 1 else 0.11, right=0.975, top=0.91, bottom=0.16, hspace=0.62, wspace=0.42)
        for index in range(rows * columns):
            axis = self.figure.add_subplot(rows, columns, index + 1, sharex=self.axes[0] if self.axes else None)
            axis.set_facecolor("white")
            axis.grid(True, color="#e4eaf0", linewidth=0.65)
            axis.tick_params(labelsize=8, colors="#526578", pad=3)
            axis.set_xlabel("Time (s)", fontsize=8, color="#526578", labelpad=4)
            axis.set_title("Plot {}".format(index + 1), loc="left", fontsize=9, color="#354d66", pad=7)
            axis.set_xlim(0, 1)
            axis.set_ylim(-1, 1)
            self.axes.append(axis)
            axis.callbacks.connect("xlim_changed", self._view_limits_changed)
            axis.callbacks.connect("ylim_changed", self._view_limits_changed)
        self._highlight_axes()
        self.toolbar.update()
        self._sync_cursor_lines()
        self.request_draw()

    def _highlight_axes(self):
        for index, axis in enumerate(self.axes):
            for spine in axis.spines.values():
                spine.set_edgecolor("#0072bd" if index == self.active_subplot else "#b8c5d2")
                spine.set_linewidth(1.2 if index == self.active_subplot else 0.7)

    def append(self, elapsed_seconds: float, values: Mapping[str, float]):
        self.buffer.append(elapsed_seconds, values)
        self.ensure_signals(values)
        self.draw()

    def clear(self):
        self.buffer.clear()
        self.toolbar.update()
        self.draw()

    def draw(self):
        if self._destroyed:
            return
        self._plot_dirty = False
        budget = max(100, min(4000, self.canvas.width() * 2))
        time_range = None if self.follow_var.get() else self.axes[0].get_xlim()
        snapshot = {name: self.buffer.plot_points(name, budget, time_range=time_range) if style.visible and self.is_selected(name) else []
                    for name, style in self.state.signals.items()}
        self.ensure_signals(snapshot)
        for name in tuple(self.lines):
            style = self.state.signals[name]
            line = self.lines[name]
            if name not in snapshot or line.axes is not self.axes[style.subplot]:
                line.remove()
                del self.lines[name]
        for name, points in snapshot.items():
            style = self.state.signals[name]
            line = self.lines.get(name)
            if line is None:
                line, = self.axes[style.subplot].plot([], [], linewidth=1.5, color=style.color)
                self.lines[name] = line
            line.set_data([point.elapsed_seconds for point in points], [point.value for point in points])
            line.set_color(style.color)
            line.set_visible(style.visible and self.is_selected(name) and bool(points))
            line.set_linestyle("-" if self.state.display_mode == "line" else "None")
            line.set_marker("None" if self.state.display_mode == "line" else ".")
            line.set_markersize(4)
        if self.follow_var.get():
            self._fit_limits()
        self._sync_cursor_lines()
        self.request_draw()
        if self.on_cursors_changed:
            self.on_cursors_changed()

    def fit_view(self):
        if self._destroyed:
            return
        self.toolbar.push_current()
        self._fit_limits()
        self.toolbar.push_current()
        self.draw()

    def _follow_changed(self):
        if self.follow_var.get():
            if self.toolbar.mode:
                if str(self.toolbar.mode) == "pan/zoom":
                    self.toolbar.pan()
                else:
                    self.toolbar.zoom()
                self.follow_var.set(True)
            self.fit_view()

    @property
    def cursor_count(self):
        return self.cursor.currentIndex()

    def is_selected(self, name):
        return self._selected_signals is None or name in self._selected_signals

    def is_plotted(self, name):
        line = self.lines.get(name)
        return bool(line is not None and line.get_visible() and len(line.get_xdata()) and self.is_selected(name))

    def set_selected_signals(self, names):
        self._selected_signals = set(names)
        self.draw()

    def set_cursors_enabled(self, enabled):
        self.set_cursor_mode(2 if enabled else 0)

    def set_cursor_mode(self, count):
        if count not in (0, 1, 2):
            raise ValueError('Cursor count must be 0, 1 or 2')
        if count and self.toolbar.mode:
            if str(self.toolbar.mode) == "pan/zoom":
                self.toolbar.pan()
            else:
                self.toolbar.zoom()
        self.cursor.blockSignals(True)
        self.cursor.setCurrentIndex(count)
        self.cursor.blockSignals(False)
        if count:
            self.follow_var.set(False)
            low, high = self.axes[0].get_xlim()
            if not all(low <= stamp <= high for stamp in self.state.cursors):
                self.state.cursors = (low + (high - low) / 3.0, low + (high - low) * 2.0 / 3.0)
            self.cursor_bar.show()
        else:
            self._drag_cursor = None
            self.cursor_bar.hide()
        for widget in self._second_cursor_widgets:
            widget.setVisible(count == 2)
        self._sync_cursor_lines(update_entries=True)
        self.request_draw()
        if self.on_cursors_changed:
            self.on_cursors_changed()

    def set_cursors(self, first, second):
        first, second = float(first), float(second)
        if not math.isfinite(first) or not math.isfinite(second):
            raise ValueError("Cursor times must be finite")
        self.state.cursors = (first, second)
        self._sync_cursor_lines(update_entries=True)
        self.request_draw()
        if self.on_cursors_changed:
            self.on_cursors_changed()

    def _apply_cursor_entries(self, _event=None):
        try:
            self.set_cursors(self.cursor_a_var.get(), self.cursor_b_var.get())
        except ValueError:
            QApplication.beep()
            self._sync_cursor_lines(update_entries=True)

    def _sync_cursor_lines(self, update_entries=False):
        if not self._cursor_lines:
            for axis in self.axes:
                self._cursor_lines.append((
                    axis.axvline(self.state.cursors[0], color=CURSOR_COLORS[0], linewidth=1, linestyle="--"),
                    axis.axvline(self.state.cursors[1], color=CURSOR_COLORS[1], linewidth=1, linestyle="--"),
                ))
                pair = []
                for index, color in enumerate(CURSOR_COLORS):
                    annotation = axis.annotate(
                        "", xy=(self.state.cursors[index], 1.0 if index == 0 else 0.0),
                        xycoords=axis.get_xaxis_transform(), xytext=(5, -5 if index == 0 else 5),
                        textcoords="offset points", ha="left", va="top" if index == 0 else "bottom",
                        fontsize=8, linespacing=1.25, color="#24384b", zorder=8,
                        bbox={"boxstyle": "square,pad=0.3", "facecolor": "white", "edgecolor": color, "alpha": 0.95},
                        annotation_clip=True,
                    )
                    annotation.set_in_layout(False)
                    pair.append(annotation)
                self._cursor_annotations.append(tuple(pair))
        for pair in self._cursor_lines:
            for index, line in enumerate(pair):
                line.set_xdata([self.state.cursors[index], self.state.cursors[index]])
                line.set_visible(index < self.cursor_count)
        self._cursor_snapshot = {name: () for name in self.state.signals if self.is_plotted(name)}
        self.ensure_signals(self._cursor_snapshot)
        self._sync_cursor_markers()
        self._layout_cursor_annotations()
        first, second = self.state.cursors
        if update_entries:
            self.cursor_a_var.set("{:.8g}".format(first))
            self.cursor_b_var.set("{:.8g}".format(second))
        self.delta_var.set("dt = {:.8g} s".format(second - first))

    def _sync_cursor_markers(self):
        for name in tuple(self._cursor_markers):
            style = self.state.signals[name]
            pair = self._cursor_markers[name]
            if name not in self._cursor_snapshot or pair[0].axes is not self.axes[style.subplot]:
                for marker in pair:
                    marker.remove()
                del self._cursor_markers[name]
        for name, points in self._cursor_snapshot.items():
            style = self.state.signals[name]
            pair = self._cursor_markers.get(name)
            if pair is None:
                pair = tuple(self.axes[style.subplot].plot([], [], linestyle="None", marker="o", markersize=4, zorder=7)[0] for _ in range(2))
                self._cursor_markers[name] = pair
            for index, marker in enumerate(pair):
                value, _interpolated = self.buffer.value_at(name, self.state.cursors[index])
                marker.set_data([self.state.cursors[index]], [value] if value is not None else [math.nan])
                marker.set_color(style.color)
                marker.set_visible(index < self.cursor_count and self.is_plotted(name) and value is not None)

    @staticmethod
    def _elide_label(text, available_width, renderer, font):
        if renderer.get_text_width_height_descent(text, font, False)[0] <= available_width:
            return text
        for count in range(len(text) - 1, -1, -1):
            left = count // 2
            shortened = text[:left] + "..." + (text[-(count - left):] if count > left else "")
            if renderer.get_text_width_height_descent(shortened, font, False)[0] <= available_width:
                return shortened
        return "..."

    def _layout_cursor_annotations(self):
        if not self._cursor_annotations or self._destroyed:
            return
        renderer = self.canvas.get_renderer()
        for subplot, (axis, pair) in enumerate(zip(self.axes, self._cursor_annotations)):
            bounds = axis.bbox
            low, high = sorted(axis.get_xlim())
            for index, annotation in enumerate(pair):
                stamp = self.state.cursors[index]
                visible = index < self.cursor_count and low <= stamp <= high and bounds.width >= 65 and bounds.height >= 45
                annotation.set_visible(visible)
                if not visible:
                    continue
                font = annotation.get_fontproperties()
                line_height = renderer.points_to_pixels(font.get_size_in_points()) * 1.25
                max_rows = max(1, int((bounds.height / 2.0 - 12) / line_height))
                width = max(45, min(270, bounds.width - 16))
                values = []
                for name, points in self._cursor_snapshot.items():
                    style = self.state.signals[name]
                    if not self.is_plotted(name) or style.subplot != subplot:
                        continue
                    value, interpolated = self.buffer.value_at(name, stamp)
                    suffix = ": --" if value is None else ": {:.7g}{}".format(value, "*" if interpolated else "")
                    values.append((name, suffix))
                heading = "t{} = {:.7g} s".format(index + 1, stamp)
                labels = []
                for row, (name, suffix) in enumerate(values[:max_rows - 1]):
                    if row == max_rows - 2 and len(values) > max_rows - 1:
                        suffix += " (+{})".format(len(values) - max_rows + 1)
                    name_width = width - renderer.get_text_width_height_descent(suffix, font, False)[0]
                    labels.append(self._elide_label(name, name_width, renderer, font) + suffix)
                if max_rows == 1 and values:
                    heading += "; y" + values[0][1]
                    if len(values) > 1:
                        heading += " (+{})".format(len(values) - 1)
                heading = self._elide_label(heading, width, renderer, font)
                annotation.set_text("\n".join([heading] + labels))
                annotation.xy = (stamp, 1.0 if index == 0 else 0.0)
                text_width = max(renderer.get_text_width_height_descent(line, font, False)[0] for line in annotation.get_text().splitlines())
                cursor_x = axis.transData.transform((stamp, 0))[0]
                left = min(max(cursor_x + 7, bounds.x0 + 7), bounds.x1 - text_width - 7)
                annotation.set_position(((left - cursor_x) * 72.0 / self.figure.dpi, -6 if index == 0 else 6))

    def _view_limits_changed(self, _axis):
        if not self.follow_var.get():
            self._plot_dirty = True
            self.request_draw()
        self._layout_cursor_annotations()

    def _cursor_at_context(self, index):
        if self._context_time is None:
            return
        self.set_cursor_mode(max(self.cursor_count, index + 1))
        cursors = list(self.state.cursors)
        cursors[index] = self._context_time
        self.set_cursors(*cursors)

    def _mouse_down(self, event):
        if event.button == 3:
            if event.inaxes in self.axes:
                self.active_subplot = self.axes.index(event.inaxes)
                self._highlight_axes()
                self._notify_display()
                self.request_draw()
            self._show_context_menu(event)
            return
        if event.inaxes not in self.axes or event.button != 1:
            return
        self.active_subplot = self.axes.index(event.inaxes)
        self._highlight_axes()
        self.request_draw()
        self._notify_display()
        if not self.cursor_count or self.toolbar.mode or event.xdata is None:
            return
        locations = [event.inaxes.transData.transform((stamp, 0))[0] for stamp in self.state.cursors]
        self._drag_cursor = min(range(self.cursor_count), key=lambda index: abs(locations[index] - event.x))
        self._move_cursor(event.xdata)

    def _move_cursor(self, stamp):
        if self._drag_cursor is None:
            return
        cursors = list(self.state.cursors)
        cursors[self._drag_cursor] = float(stamp)
        self.set_cursors(*cursors)

    def _mouse_move(self, event):
        if event.inaxes in self.axes and event.xdata is not None:
            self._move_cursor(event.xdata)

    def _mouse_up(self, _event):
        self._drag_cursor = None

    def _scroll_zoom(self, event):
        if event.inaxes not in self.axes or event.xdata is None or event.ydata is None:
            return
        self.follow_var.set(False)
        self.toolbar.push_current()
        axis = event.inaxes
        factor = 0.8 if event.button == "up" else 1.25
        for limits, center, setter in ((axis.get_xlim(), event.xdata, axis.set_xlim), (axis.get_ylim(), event.ydata, axis.set_ylim)):
            setter(center + (limits[0] - center) * factor, center + (limits[1] - center) * factor)
        self.toolbar.push_current()
        self._layout_cursor_annotations()
        self.request_draw()

    def _flush_draw(self):
        self._draw_after_id = None
        if not self._destroyed:
            if self._plot_dirty:
                self.draw()
                self._draw_timer.stop()
            self._layout_cursor_annotations()
            self.canvas.draw_idle()
