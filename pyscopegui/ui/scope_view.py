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

With a trigger chosen the time axis is measured from the trigger, which
stays where it is on the screen while each new one is drawn over the last.
With none it is measured from when the instrument started, and the plot
follows the newest samples.

With more than one instrument, each keeps time for itself, and nought on the
axis is each one's own trigger: see pyscopegui.core.session.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
from pyscopegui.core.acquire import AUTO, AUTO_S, SINGLE, STOP, Acquisition
from pyscopegui.core.capture import Capture, min_max
from pyscopegui.core.context import Context
from pyscopegui.core.session import Session, Unit
from pyscopegui.ui import fonts
from pyscopegui.ui.persist import remember
from pyscopegui.ui.spin import SequenceSpin

# Enough for a channel's name, how it is set and its value; the plot takes
# whatever is left.
LIST_WIDTH = 360

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
WINDOW_TIP = (
    "How many seconds Follow keeps in view: the newest, or with a trigger\n"
    "chosen, the stretch drawn around each trigger."
)
#: What the plot is doing about the trigger, said beside the time controls.
STOPPED, WAITING, TRIGGERED, FREE = "Stopped", "Waiting for trigger", "Triggered", "Auto"
AUTO_Y_TIP = (
    "Fit the voltage axis to what is being measured. Unticked, the axis is the\n"
    "range the channels are set to, as a scope's screen is: a small signal on\n"
    "a large range is then drawn small."
)
#: Above and below the range when the axis is the range, as a share of the
#: whole of it, so a signal at full scale is not drawn on the edge of the plot.
RANGE_MARGIN = 0.05

PICK_TIP = "How the channel is set up. Click it to change that in the Instrument pane."
#: Thirty redraws a second: smooth, and each one is a few thousand points.
REDRAW_MS = 33
#: The latest value of each channel is for reading, so it changes more slowly.
VALUES_MS = 250
#: How much of a lane a digital channel's high level fills.
LANE_HEIGHT = 0.7
NAME, VALUE, DETAIL = 0, 1, 2


@dataclass
class _Timing:
    """Where one instrument's time is measured from on this plot."""

    #: The trigger last drawn around, kept while the next is waited for.
    held: int | None = None
    generation: int = -1
    #: Where its time was last measured from, in seconds.
    origin: float = 0.0


class ChannelList(QTreeWidget):
    """Every channel, a tick to show it, and what it reads now."""

    #: Channel key, and whether it is to be shown.
    shown_changed = Signal(str, bool)
    #: A channel was clicked: its key.
    picked = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setHeaderLabels(["Channel", "Value", "Settings"])
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self._items: dict[str, QTreeWidgetItem] = {}
        self.itemChanged.connect(self._on_changed)
        self.itemClicked.connect(
            lambda item, _column: self.picked.emit(item.data(NAME, Qt.UserRole))
        )

    def fill(
        self,
        names: dict[str, str],
        colours: dict[str, str],
        hidden: set[str],
        details: dict[str, str] | None = None,
    ) -> None:
        """List these channels: id -> what to call it, and how each is set up."""
        self.blockSignals(True)
        self.clear()
        self._items = {}
        for key, name in names.items():
            item = QTreeWidgetItem([name, "", (details or {}).get(key, "")])
            item.setToolTip(DETAIL, PICK_TIP)
            item.setData(NAME, Qt.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(NAME, Qt.Unchecked if key in hidden else Qt.Checked)
            item.setForeground(NAME, QBrush(QColor(colours[key])))
            item.setFont(VALUE, fonts.mono())
            item.setTextAlignment(VALUE, Qt.AlignRight | Qt.AlignVCenter)
            self.addTopLevelItem(item)
            self._items[key] = item
        self.blockSignals(False)
        self.resizeColumnToContents(NAME)
        # Room for the longest a value gets, so the column does not jump about
        # as the reading changes, and the settings have what is left.
        self.setColumnWidth(VALUE, QFontMetrics(fonts.mono()).horizontalAdvance(" -000.000 V "))

    def _on_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column == NAME:
            self.shown_changed.emit(
                item.data(NAME, Qt.UserRole), item.checkState(NAME) == Qt.Checked
            )

    def set_value(self, key: str, text: str) -> None:
        if (item := self._items.get(key)) is not None and item.text(VALUE) != text:
            item.setText(VALUE, text)


class ScopeView(QWidget):
    #: A channel was clicked in the list: whose it is, by the instrument's
    #: name, and the group its settings are under.
    channel_picked = Signal(str, str)

    def __init__(
        self,
        source: Session | Capture,
        ctx: Context | None = None,
        key: str = "scope",
        acquisition: Acquisition | None = None,
    ) -> None:
        super().__init__()
        #: Every instrument in use and what it has sent. A capture by itself
        #: is shown as a session of the one.
        self.session = source if isinstance(source, Session) else Session.of(source, acquisition)
        #: Instrument name -> where its time is measured from here.
        self._timings: dict[str, _Timing] = {}
        #: Where time is measured from on the axis now, in seconds, for the
        #: first instrument there is: a trigger, or zero with none.
        self._origin = 0.0
        #: Whether the axis is measured from a trigger at the moment.
        self._relative = False
        #: The ends of the sweeps on the time axis, while every instrument is
        #: sending sweeps: all of them is what there is to show.
        self._sweep_ends: tuple[float, float] | None = None
        self._ctx = ctx
        self._key = key
        self._curves: dict[str, pg.PlotDataItem] = {}
        #: Channel id -> whose it is, and its key there.
        self._owners: dict[str, tuple[Unit, str]] = {}
        self._names: dict[str, str] = {}
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
        dashed = pg.mkPen("#888888", width=1, style=Qt.DashLine)
        #: The trigger's level, across the analog plot, and its moment, down both.
        self.level_line = pg.InfiniteLine(angle=0, movable=False, pen=dashed)
        #: One level for each instrument: the first is the one above.
        self._level_lines = [self.level_line]
        self._dashed = dashed
        self.trigger_lines = [
            pg.InfiniteLine(pos=0, angle=90, movable=False, pen=dashed) for _ in range(2)
        ]
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
        self.channel_list.picked.connect(self._on_picked)

        self.time = QComboBox()
        self.time.addItems(TIME_CHOICES)
        self.time.setToolTip(TIME_TIP)
        for index, tip in enumerate(TIME_ITEM_TIPS):
            self.time.setItemData(index, tip, Qt.ToolTipRole)
        self.time.currentTextChanged.connect(self._show_time)
        # Its arrows go 1, 2, 5, 10: a fixed step is wrong at every size but one.
        self.window_s = SequenceSpin()
        self.window_s.setDecimals(3)
        self.window_s.setRange(0.001, 3600)
        self.window_s.setValue(0.1)
        self.window_s.setSuffix(" s")
        self.window_s.setToolTip(WINDOW_TIP)
        self.auto_y = QCheckBox("Auto Y")
        self.auto_y.setToolTip(AUTO_Y_TIP)
        self.auto_y.setChecked(True)
        self.auto_y.toggled.connect(self._place_y)
        clear = QPushButton("Clear history")
        clear.setToolTip("Throw away the samples collected so far, for every channel")
        clear.clicked.connect(self.session.clear)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Time:"))
        bar.addWidget(self.time)
        bar.addWidget(self.window_s)
        bar.addWidget(self.auto_y)
        self.state = QLabel()
        bar.addWidget(self.state)
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
            remember(ctx, f"{key}.auto_y", self.auto_y)
        self.session.channels_changed.connect(self._rebuild)
        self.session.trigger_changed.connect(self._show_trigger)
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
    def _records(self):
        """Every channel there is: its id and what is held of it."""
        return [(key, record) for key, _unit, record in self.session.entries()]

    def _rebuild(self) -> None:
        """Make a curve for every channel there is now, and lanes for the digital ones."""
        for plot in (self.analog, self.digital):
            plot.clear()
        self._curves, self._owners = {}, {}
        entries = self.session.entries()
        self._colours = {key: COLOURS[i % len(COLOURS)] for i, (key, _u, _r) in enumerate(entries)}
        self._names = {key: self.session.name_of(unit, r.channel) for key, unit, r in entries}
        for key, unit, record in entries:
            pen = pg.mkPen(self._colours[key], width=1)
            if record.channel.kind == ANALOG:
                curve = self.analog.plot(pen=pen)
            else:
                # Held until the next sample, which is what a logic level does.
                curve = self.digital.plot(pen=pen, stepMode="left")
            self._curves[key] = curve
            self._owners[key] = (unit, record.channel.key)
        channels = [record.channel for _key, _unit, record in entries]
        units = {c.unit for c in channels if c.kind == ANALOG and c.unit}
        self.analog.setLabel("left", units=units.pop() if len(units) == 1 else None)
        details = {key: record.channel.detail for key, _unit, record in entries}
        self.channel_list.fill(self._names, self._colours, self._hidden, details)
        # Cleared with everything else, so put back: left out of the fitting
        # of the axes, or the voltage axis would always stretch to the level.
        while len(self._level_lines) < len(self.session.shown()):
            self._level_lines.append(pg.InfiniteLine(angle=0, movable=False, pen=self._dashed))
        for line in self._level_lines:
            self.analog.addItem(line, ignoreBounds=True)
        for plot, line in zip((self.analog, self.digital), self.trigger_lines, strict=True):
            plot.addItem(line, ignoreBounds=True)
        self._arrange_lanes()
        self._show_trigger()

    def _arrange_lanes(self) -> None:
        """Stack the digital channels that are shown, the first of them on top."""
        shown = [
            key
            for key, record in self._records()
            if record.channel.kind == DIGITAL and key not in self._hidden
        ]
        self._lanes = {key: float(len(shown) - 1 - i) for i, key in enumerate(shown)}
        ticks = [(self._lanes[key] + LANE_HEIGHT / 2, self._names[key]) for key in shown]
        self.digital.getAxis("left").setTicks([ticks])
        self.digital.setYRange(-0.15, max(len(shown), 1), padding=0)
        for key, curve in self._curves.items():
            curve.setVisible(key not in self._hidden)
        self.digital.setVisible(bool(shown) or not self._curves)
        self._place_y()

    def _place_y(self, *_args) -> None:
        """Fit the voltage axis to the signal, or set it to the channels' range.

        The range is the largest of the analog channels shown, since they
        share the one axis. Where none of them has a range to speak of, the
        axis is fitted whatever the tick says: there is nothing else to set it to.
        """
        most = max(
            (
                record.channel.full_scale
                for key, record in self._records()
                if record.channel.kind == ANALOG and key not in self._hidden
            ),
            default=0.0,
        )
        if self.auto_y.isChecked() or most <= 0:
            self.analog.enableAutoRange(axis=pg.ViewBox.YAxis)
        else:
            self.analog.setYRange(-most, most, padding=RANGE_MARGIN)

    def _on_picked(self, key: str) -> None:
        if (owner := self._owners.get(key)) is None:
            return
        unit, channel = owner
        record = unit.capture.records.get(channel)
        if record is not None and record.channel.group:
            self.channel_picked.emit(unit.name, record.channel.group)

    def _on_shown(self, key: str, on: bool) -> None:
        self._hidden.discard(key) if on else self._hidden.add(key)
        if self._ctx is not None:
            self._ctx.settings.set(f"{self._key}.hidden", sorted(self._hidden))
        self._arrange_lanes()
        self._show_trigger()
        self.redraw()

    def shown(self) -> list[str]:
        return [key for key in self._curves if key not in self._hidden]

    # --- which stretch of time ------------------------------------------------------------
    def _on_dragged(self, *_args) -> None:
        self.time.setCurrentText(MANUAL)

    def _show_time(self, *_args) -> None:
        # A sweep is shown whole: how much to show is not asked.
        wanted = self._sweep_ends is None and (self.time.currentText() == FOLLOW or self._relative)
        if self.window_s.isEnabled() != wanted:
            self.window_s.setEnabled(wanted)

    # --- the trigger ----------------------------------------------------------------------
    def _show_trigger(self) -> None:
        """Draw each trigger's level where its settings say it is, if it is on this plot."""
        units = self.session.shown()
        for index, line in enumerate(self._level_lines):
            unit = units[index] if index < len(units) else None
            record = unit.acquisition.record() if unit is not None else None
            on_plot = (
                record is not None
                and record.channel.kind == ANALOG
                and unit.id(record.channel.key) not in self._hidden
            )
            line.setVisible(on_plot)
            if on_plot:
                line.setValue(unit.acquisition.level)

    def _find_origin(
        self, unit: Unit, timing: _Timing, several: bool
    ) -> tuple[float | None, str, bool, tuple[float, float] | None]:
        """Where to measure one instrument's time from, in seconds, and what
        to say it is doing; whether that is a trigger; and the ends of its
        sweep, if it sends sweeps.

        None for the origin means leave what is drawn of it as it is: a
        trigger is being waited for, and what was drawn last is what there
        is to show.
        """
        acquisition, capture = unit.acquisition, unit.capture
        sweep = acquisition.sweep
        held = next(iter(capture.records.values()), None)
        if sweep is not None and held is not None:
            # The instrument triggered, and says where: nothing to find here.
            relative = sweep.trigger is not None
            if relative:
                at = sweep.trigger
            else:
                # With no trigger, beside another instrument's: where one would have been.
                at = round(acquisition.position * sweep.length) if several else 0
            origin = at / held.rate
            ends = (-origin, sweep.length / held.rate - origin)
            if acquisition.mode == STOP:
                return origin, STOPPED, relative, ends
            if not relative:
                return origin, "", relative, ends
            return origin, TRIGGERED if sweep.triggered else FREE, relative, ends
        window = self.window_s.value()
        record = acquisition.record()
        if record is None:
            stopped = acquisition.mode == STOP and self._curves and capture.stored()
            state = STOPPED if stopped else ""
            if not several:
                return 0.0, state, False, None
            # Beside another instrument's trigger: its newest, as they arrive.
            newest = capture.newest()
            if newest is None:
                return None, state, False, None
            return newest - (1 - acquisition.position) * window, state, False, None
        if acquisition.generation != timing.generation:
            timing.held, timing.generation = None, acquisition.generation
        after = round((1 - acquisition.position) * window * record.rate)
        if acquisition.mode == STOP:
            if acquisition.frozen is not None:
                timing.held = acquisition.frozen
            if timing.held is None:
                return (timing.origin if record.count else None), STOPPED, True, None
            return timing.held / record.rate, STOPPED, True, None
        found = acquisition.trigger_for(after)
        if acquisition.mode == AUTO and (
            found is None or acquisition.quiet_for(max(AUTO_S, window))
        ):
            # Nothing to hold still on, so what there is, as it arrives.
            timing.held = None
            return (record.total - after) / record.rate, FREE, True, None
        if found is not None:
            timing.held = found
        if timing.held is None:
            return None, WAITING, True, None
        state = WAITING if acquisition.mode == SINGLE else TRIGGERED
        return timing.held / record.rate, state, True, None

    def _find_origins(self) -> tuple[dict[str, float | None], str]:
        """Every instrument's origin, by its name, and what to say is going on."""
        units = self.session.shown()
        several = len(units) > 1
        origins: dict[str, float | None] = {}
        states, ends, relative, streams = [], [], False, False
        for unit in units:
            timing = self._timings.setdefault(unit.name, _Timing())
            origin, state, is_relative, sweep_ends = self._find_origin(unit, timing, several)
            origins[unit.name] = origin
            relative = relative or is_relative
            if sweep_ends is None:
                streams = True
            else:
                ends.append(sweep_ends)
            if origin is not None:
                timing.origin = origin
            if state:
                states.append(f"{unit.short or unit.name}: {state}" if several else state)
        # Two instruments have no time in common but their triggers.
        self._relative = relative or several
        if ends and not streams:
            self._sweep_ends = (min(e[0] for e in ends), max(e[1] for e in ends))
        else:
            self._sweep_ends = None
        return origins, "   ".join(states)

    def _show_relative(self, was_relative: bool) -> None:
        """Take up a change between time from the start and time from a trigger."""
        if was_relative == self._relative:
            return
        # A stretch chosen by hand on one axis means nothing on the other.
        self.time.setCurrentText(FOLLOW)
        self._show_time()
        self.digital.setLabel(
            "bottom", "time from trigger" if self._relative else "time", units="s"
        )

    def _place(self) -> None:
        """Move the time axis to where Follow or All says it should be."""
        choice = self.time.currentText()
        if choice == MANUAL:
            return
        if self._sweep_ends is not None:
            self.analog.setXRange(*self._sweep_ends, padding=0)
            return
        if self._relative:
            # Around the trigger, which is at nought: All has no meaning of
            # its own here, and is the same as Follow.
            window = self.window_s.value()
            before = self.session.shown()[0].acquisition.position * window
            self.analog.setXRange(-before, window - before, padding=0)
            return
        capture = self.session.shown()[0].capture
        newest = capture.newest()
        if newest is None:
            return
        if choice == FOLLOW:
            t_from = newest - self.window_s.value()
        else:
            t_from = capture.oldest() or 0.0
        self.analog.setXRange(t_from, newest, padding=0)

    # --- drawing --------------------------------------------------------------------------
    def redraw(self) -> None:
        if not self._curves or not self.isVisible():
            return
        was_relative = self._relative
        origins, state = self._find_origins()
        self._show_relative(was_relative)
        self._show_time()
        if self.state.text() != state:
            self.state.setText(state)
        known = [origin for origin in origins.values() if origin is not None]
        for line in self.trigger_lines:
            line.setVisible(self._relative and bool(known))
        if not known:
            return  # waiting for a trigger: what was drawn last stays
        self._origin = known[0]
        self._place()
        (x_from, x_to), _y = self.analog.getViewBox().viewRange()
        columns = max(int(self.analog.getViewBox().width()), 1)
        for key, curve in self._curves.items():
            if key in self._hidden:
                continue
            unit, channel = self._owners[key]
            record = unit.capture.records.get(channel)
            origin = origins.get(unit.name)
            if record is None or origin is None:
                continue
            first, samples = record.between(x_from + origin, x_to + origin)
            positions, values = min_max(samples, columns)
            times = (first + positions) / record.rate - origin
            if key in self._lanes:
                values = values.astype(np.float32) * LANE_HEIGHT + self._lanes[key]
            curve.setData(times, values)

    def _show_values(self) -> None:
        if not self.isVisible():
            return
        for key, record in self._records():
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
