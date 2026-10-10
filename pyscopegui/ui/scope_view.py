# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Channels and Plot in one pane.

The two belong together: the tick that shows a channel lives in the channel
list, so as separate docks Qt would happily tab them and hide the list behind
the plot. In one pane with a splitter between them, both are always visible,
and the list can be dragged shut when only the plot is wanted.

Analog channels share one plot and digital ones are stacked in lanes under
it, on the same time axis: dragging or zooming either moves both, which is
the whole point of having them in one window.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPalette
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pyscopegui.backends.base import ANALOG, DIGITAL
from pyscopegui.core.capture import Capture, min_max
from pyscopegui.core.context import Context
from pyscopegui.ui import fonts
from pyscopegui.ui.persist import remember

# Enough for a channel name and its value; the plot takes whatever is left.
LIST_WIDTH = 220

COLOURS = ("#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#17becf")

FOLLOW, ALL, MANUAL = "Follow", "All", "Manual"
TIME_CHOICES = (FOLLOW, ALL, MANUAL)
TIME_TIP = (
    "Which stretch of time is in view. Dragging or zooming the plot\n"
    "chooses Manual; choose Follow to go back to the newest samples."
)
TIME_ITEM_TIPS = (
    "Keep the newest samples in view, as they arrive.",
    "Show everything that is held, and keep it all in view as more arrives.",
    "Stay where the plot was dragged or zoomed to.",
)
WINDOW_TIP = "How many seconds Follow keeps in view."

#: Thirty redraws a second: smooth, and each one is a few thousand points.
REDRAW_MS = 33
#: The latest value of each channel is for reading, so it changes more slowly.
VALUES_MS = 250
#: How much of a lane a digital channel's high level fills.
LANE_HEIGHT = 0.7
NAME, VALUE = 0, 1


class ChannelList(QTreeWidget):
    """Every channel, a tick to show it, and what it reads now."""

    #: Channel key, and whether it is to be shown.
    shown_changed = Signal(str, bool)

    def __init__(self) -> None:
        super().__init__()
        self.setHeaderLabels(["Channel", "Value"])
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self._items: dict[str, QTreeWidgetItem] = {}
        self.itemChanged.connect(self._on_changed)

    def fill(self, channels, colours: dict[str, str], hidden: set[str]) -> None:
        self.blockSignals(True)
        self.clear()
        self._items = {}
        for channel in channels:
            item = QTreeWidgetItem([channel.name, ""])
            item.setData(NAME, Qt.UserRole, channel.key)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(NAME, Qt.Unchecked if channel.key in hidden else Qt.Checked)
            item.setForeground(NAME, QBrush(QColor(colours[channel.key])))
            item.setFont(VALUE, fonts.mono())
            item.setTextAlignment(VALUE, Qt.AlignRight | Qt.AlignVCenter)
            self.addTopLevelItem(item)
            self._items[channel.key] = item
        self.blockSignals(False)
        self.resizeColumnToContents(NAME)

    def _on_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column == NAME:
            self.shown_changed.emit(
                item.data(NAME, Qt.UserRole), item.checkState(NAME) == Qt.Checked
            )

    def set_value(self, key: str, text: str) -> None:
        if (item := self._items.get(key)) is not None and item.text(VALUE) != text:
            item.setText(VALUE, text)


class ScopeView(QWidget):
    def __init__(self, capture: Capture, ctx: Context | None = None, key: str = "scope") -> None:
        super().__init__()
        self.capture = capture
        self._ctx = ctx
        self._key = key
        self._curves: dict[str, pg.PlotDataItem] = {}
        self._colours: dict[str, str] = {}
        #: Digital channel key -> the bottom of its lane.
        self._lanes: dict[str, float] = {}
        #: Channels unticked, kept by key so they stay hidden across a restart.
        saved = ctx.settings.get(f"{key}.hidden") if ctx is not None else None
        self._hidden: set[str] = {str(k) for k in saved} if isinstance(saved, list) else set()

        pg.setConfigOptions(antialias=False)
        self.analog = pg.PlotWidget()
        self.analog.showGrid(x=True, y=True, alpha=0.3)
        self.digital = pg.PlotWidget()
        self.digital.showGrid(x=True, y=False, alpha=0.3)
        self.digital.setLabel("bottom", "time", units="s")
        # One time axis for both: the reason they are in one pane.
        self.digital.setXLink(self.analog)
        # A lane is a place, not a measurement, so there is nothing to zoom.
        self.digital.setMouseEnabled(x=True, y=False)
        self.digital.getViewBox().setMenuEnabled(False)
        for plot in (self.analog, self.digital):
            plot.getViewBox().sigRangeChangedManually.connect(self._on_dragged)
            # The same width, so that the same time is at the same place in both.
            plot.getAxis("left").setWidth(60)

        self._follow_theme()

        self.channel_list = ChannelList()
        self.channel_list.shown_changed.connect(self._on_shown)

        self.time = QComboBox()
        self.time.addItems(TIME_CHOICES)
        self.time.setToolTip(TIME_TIP)
        for index, tip in enumerate(TIME_ITEM_TIPS):
            self.time.setItemData(index, tip, Qt.ToolTipRole)
        self.time.currentTextChanged.connect(self._show_time)
        self.window_s = QDoubleSpinBox()
        self.window_s.setDecimals(3)
        self.window_s.setRange(0.001, 3600)
        self.window_s.setValue(0.1)
        self.window_s.setSuffix(" s")
        self.window_s.setToolTip(WINDOW_TIP)
        clear = QPushButton("Clear history")
        clear.setToolTip("Throw away the samples collected so far, for every channel")
        clear.clicked.connect(capture.clear)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Time:"))
        bar.addWidget(self.time)
        bar.addWidget(self.window_s)
        bar.addStretch()
        bar.addWidget(clear)

        self.plots = QSplitter(Qt.Vertical)
        self.plots.addWidget(self.analog)
        self.plots.addWidget(self.digital)
        self.plots.setStretchFactor(0, 2)
        self.plots.setStretchFactor(1, 1)
        right = QWidget()
        column = QVBoxLayout(right)
        column.setContentsMargins(2, 2, 2, 2)
        column.addLayout(bar)
        column.addWidget(self.plots)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.channel_list)
        self.splitter.addWidget(right)
        # Either side may be dragged shut, and neither imposes a width of its
        # own, so the splitter shrinks rather than the pane growing scrollbars.
        self.splitter.setChildrenCollapsible(True)
        self.splitter.setHandleWidth(6)
        for i, widget in enumerate((self.channel_list, right)):
            widget.setMinimumWidth(0)
            self.splitter.setStretchFactor(i, i)  # the plot takes the extra room
        self.splitter.setSizes([LIST_WIDTH, 4 * LIST_WIDTH])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

        if ctx is not None:
            remember(ctx, f"{key}.window_s", self.window_s)
        capture.channels_changed.connect(self._rebuild)
        self._rebuild()
        self._show_time()
        self._timer = QTimer(self, interval=REDRAW_MS, timeout=self.redraw)
        self._timer.start()
        self._values_timer = QTimer(self, interval=VALUES_MS, timeout=self._show_values)
        self._values_timer.start()

    # --- colours ---------------------------------------------------------------------------
    def _follow_theme(self) -> None:
        """Draw the plots in the window's own colours: dark in a dark window.

        pyqtgraph has colours of its own, set once, and a white plot in a
        dark window is the brightest thing on the screen.
        """
        background = self.palette().color(QPalette.Base)
        text = self.palette().color(QPalette.Text)
        for plot in (self.analog, self.digital):
            plot.setBackground(background)
            for side in ("left", "bottom"):
                axis = plot.getAxis(side)
                axis.setPen(text)
                axis.setTextPen(text)

    def changeEvent(self, event) -> None:
        # The theme was changed under Tools > Settings, or by the system.
        if event.type() == QEvent.PaletteChange and hasattr(self, "digital"):
            self._follow_theme()
        super().changeEvent(event)

    # --- which channels -------------------------------------------------------------------
    def _rebuild(self) -> None:
        """Make a curve for every channel there is now, and lanes for the digital ones."""
        for plot in (self.analog, self.digital):
            plot.clear()
        self._curves = {}
        channels = [record.channel for record in self.capture.records.values()]
        self._colours = {c.key: COLOURS[i % len(COLOURS)] for i, c in enumerate(channels)}
        for channel in channels:
            pen = pg.mkPen(self._colours[channel.key], width=1)
            if channel.kind == ANALOG:
                curve = self.analog.plot(pen=pen)
            else:
                # Held until the next sample, which is what a logic level does.
                curve = self.digital.plot(pen=pen, stepMode="left")
            self._curves[channel.key] = curve
        units = {c.unit for c in channels if c.kind == ANALOG and c.unit}
        self.analog.setLabel("left", units=units.pop() if len(units) == 1 else None)
        self.channel_list.fill(channels, self._colours, self._hidden)
        self._arrange_lanes()

    def _arrange_lanes(self) -> None:
        """Stack the digital channels that are shown, the first of them on top."""
        shown = [
            r.channel
            for r in self.capture.records.values()
            if r.channel.kind == DIGITAL and r.channel.key not in self._hidden
        ]
        self._lanes = {c.key: float(len(shown) - 1 - i) for i, c in enumerate(shown)}
        ticks = [(self._lanes[c.key] + LANE_HEIGHT / 2, c.name) for c in shown]
        self.digital.getAxis("left").setTicks([ticks])
        self.digital.setYRange(-0.15, max(len(shown), 1), padding=0)
        for key, curve in self._curves.items():
            curve.setVisible(key not in self._hidden)
        self.digital.setVisible(bool(shown) or not self._curves)

    def _on_shown(self, key: str, on: bool) -> None:
        self._hidden.discard(key) if on else self._hidden.add(key)
        if self._ctx is not None:
            self._ctx.settings.set(f"{self._key}.hidden", sorted(self._hidden))
        self._arrange_lanes()
        self.redraw()

    def shown(self) -> list[str]:
        return [key for key in self._curves if key not in self._hidden]

    # --- which stretch of time ------------------------------------------------------------
    def _on_dragged(self, *_args) -> None:
        self.time.setCurrentText(MANUAL)

    def _show_time(self, *_args) -> None:
        self.window_s.setEnabled(self.time.currentText() == FOLLOW)

    def _place(self) -> None:
        """Move the time axis to where Follow or All says it should be."""
        choice = self.time.currentText()
        newest = self.capture.newest()
        if choice == MANUAL or newest is None:
            return
        if choice == FOLLOW:
            t_from = newest - self.window_s.value()
        else:
            t_from = self.capture.oldest() or 0.0
        self.analog.setXRange(t_from, newest, padding=0)

    # --- drawing --------------------------------------------------------------------------
    def redraw(self) -> None:
        if not self._curves or not self.isVisible():
            return
        self._place()
        (t_from, t_to), _y = self.analog.getViewBox().viewRange()
        columns = max(int(self.analog.getViewBox().width()), 1)
        for key, curve in self._curves.items():
            if key in self._hidden:
                continue
            record = self.capture.records.get(key)
            if record is None:
                continue
            first, samples = record.between(t_from, t_to)
            positions, values = min_max(samples, columns)
            times = (first + positions) / record.rate
            if key in self._lanes:
                values = values.astype(np.float32) * LANE_HEIGHT + self._lanes[key]
            curve.setData(times, values)

    def _show_values(self) -> None:
        if not self.isVisible():
            return
        for key, record in self.capture.records.items():
            if not record.count:
                text = ""
            elif record.channel.kind == DIGITAL:
                text = str(int(record.view()[-1]))
            else:
                text = f"{record.view()[-1]:.3f} {record.channel.unit}".rstrip()
            self.channel_list.set_value(key, text)

    # --- layout, saved with the rest of the window state ---------------------
    def save_state(self):
        return self.splitter.saveState()

    def restore_state(self, state) -> None:
        if state is not None:
            self.splitter.restoreState(state)
