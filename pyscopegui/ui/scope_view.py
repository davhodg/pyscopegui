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

There can be one cursor or two: lines down both plots, dragged to a moment,
at which the channel list says what every channel read. With none the list
has no readings at all, and is narrower, so that the plot has the room. A
cursor is a time on the axis and stays at it, so it is left behind when the
plot moves on; two give the time between them, and how far each channel
moved in it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QPalette
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pyscopegui.backends.base import ANALOG, DIGITAL
from pyscopegui.core import capture_file, export
from pyscopegui.core.acquire import AUTO, AUTO_S, SINGLE, STOP, Acquisition
from pyscopegui.core.capture import Capture, min_max
from pyscopegui.core.context import Context
from pyscopegui.core.maths import Maths
from pyscopegui.core.measure import Measured, measure
from pyscopegui.core.session import Session, Unit
from pyscopegui.ui import fonts
from pyscopegui.ui.column_widths import ColumnWidths
from pyscopegui.ui.maths_dialog import MathsDialog
from pyscopegui.ui.persist import remember
from pyscopegui.ui.spin import SequenceSpin

# Enough for a channel's name and how it is set, which is all there is to
# list with no cursor; the plot takes whatever is left.
LIST_WIDTH = 280

#: For a channel whose instrument says no colour for it: the first channel
#: of an instrument the first of these, the next the next, whatever else is open.
COLOURS = ("#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#17becf")
#: How much of its colour a reference trace is drawn with: enough to be
#: told apart, little enough to be behind what is live.
REFERENCE_ALPHA = 100
#: Below every live trace, which are at nought.
REFERENCE_Z = -10
#: Under this and an instrument's name, its maths channels, kept in the workspace.
MATHS_KEY = "maths"
#: Channel id -> a colour chosen for it here, kept in the workspace, for every plot.
CHOSEN_COLOURS = "channel.colours"
COLOUR_TIP = "Right-click a channel to choose the colour it is drawn in."

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
#: What the voltage axis shows: fitted to the signal, the range the channels
#: are set to, or wherever it was zoomed or dragged to.
Y_AUTO, Y_RANGE = "Auto", "Range"
Y_CHOICES = (Y_AUTO, Y_RANGE, MANUAL)
Y_TIP = (
    "What the voltage axis shows. Zooming or dragging it chooses Manual;\n"
    "right-click the plot > Y axis to type where it goes."
)
Y_ITEM_TIPS = (
    "Fit the axis to what is being measured.",
    "The range the channels are set to, offset and all, as a scope's screen is:\n"
    "a small signal on a large range is then drawn small.",
    "Hold the axis where it is, until it is zoomed or dragged.",
)
#: Above and below the range when the axis is the range, as a share of the
#: whole of it, so a signal at full scale is not drawn on the edge of the plot.
RANGE_MARGIN = 0.05

EXPORT_TIP = (
    "Write what the plot shows as CSV: every sample of the channels that are\n"
    "ticked, in the stretch of time in view. One file for each instrument.\n"
    "Choose All beside Time first to write everything that is held."
)
PICTURE_TIP = "Save a picture of this plot and its channel list, as they look now."
#: Where the last export went, kept so the next one starts there.
EXPORT_FOLDER = "export.folder"
PICK_TIP = "How the channel is set up. Click it to change that in the Instrument pane."
#: Thirty redraws a second: smooth, and each one is a few thousand points.
REDRAW_MS = 33
#: The latest value of each channel is for reading, so it changes more slowly.
VALUES_MS = 250
#: How much of a lane a digital channel's high level fills.
LANE_HEIGHT = 0.7
#: The channel list's columns. The two in the middle are for a second cursor
#: and the difference between the two, and are put away without one.
NAME, VALUE, SECOND, DIFFERENCE, DETAIL = 0, 1, 2, 3, 4
#: How many cursors -> what each column of readings is headed. With none
#: there is nothing to read, and no column: the room is the plot's.
HEADINGS = {
    0: ("", "", ""),
    1: ("At cursor", "", ""),
    2: ("Cursor 1", "Cursor 2", "2 \u2212 1"),
}
CURSOR_CHOICES = ("None", "1", "2")
#: The cursors' colours: unlike each other's, and unlike the yellow, cyan,
#: magenta, blue, red and green the scopes draw their channels in.
CURSOR_COLOURS = ("#ff8c1a", "#a066ff")
#: How close to either edge of the plot, as a share of its width, a cursor
#: counts as out of sight and is brought back when cursors are chosen.
EDGE = 0.02
CURSORS_TIP = (
    "Lines down the plot, dragged to a moment: the channel list then says what\n"
    "each channel read there, to the nearest sample. Two also give the time\n"
    "between them and how far each channel moved in it.\n"
    "A cursor stays at its time when the plot moves on. Choosing here again\n"
    "brings any that are out of sight back into view."
)
#: Said in place of a reading where nothing is held: before the oldest
#: sample, after the newest, or in a gap.
NOTHING_HELD = "\u2014"


def time_text(seconds: float) -> str:
    """A time for reading: 0.0123 -> "12.3 ms"."""
    size = abs(seconds)
    for scale, unit in ((1.0, "s"), (1e-3, "ms"), (1e-6, "\u00b5s"), (1e-9, "ns")):
        if size >= scale or unit == "ns":
            return f"{seconds / scale:.4g} {unit}"
    return "0 s"


def frequency_text(hertz: float) -> str:
    for scale, unit in ((1e6, "MHz"), (1e3, "kHz"), (1.0, "Hz")):
        if hertz >= scale or unit == "Hz":
            return f"{hertz / scale:.4g} {unit}"
    return ""


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
    #: Asked to choose a channel's colour, or (with "") to go back to its own.
    colour_asked = Signal(str, str)
    #: Asked to make a maths channel starting from this channel, or to remove
    #: this maths channel: its id.
    maths_asked = Signal(str)
    maths_removed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setColumnCount(DETAIL + 1)
        self.set_cursors(0)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self._items: dict[str, QTreeWidgetItem] = {}
        self.itemChanged.connect(self._on_changed)
        self.itemClicked.connect(
            lambda item, _column: self.picked.emit(item.data(NAME, Qt.UserRole))
        )
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def _menu(self, at) -> None:
        """Colour..., and back to the instrument's own, for the channel right-clicked."""
        item = self.itemAt(at)
        if item is None:
            return
        key = item.data(NAME, Qt.UserRole)
        menu = QMenu(self)
        menu.addAction("Colour...", lambda: self.colour_asked.emit(key, "choose"))
        back = menu.addAction("Its own colour", lambda: self.colour_asked.emit(key, ""))
        back.setEnabled(bool(item.data(NAME, Qt.UserRole + 1)))
        menu.addSeparator()
        menu.addAction("Maths channel...", lambda: self.maths_asked.emit(key))
        if ":maths:" in key or key.startswith("maths:"):
            menu.addAction("Remove this maths channel", lambda: self.maths_removed.emit(key))
        menu.exec(self.viewport().mapToGlobal(at))

    def set_cursors(self, count: int) -> None:
        """Head the readings for this many cursors, with a column for each."""
        self.setHeaderLabels(["Channel", *HEADINGS[count], "Settings"])
        self.setColumnHidden(VALUE, count < 1)
        for column in (SECOND, DIFFERENCE):
            self.setColumnHidden(column, count < 2)

    def fill(
        self,
        names: dict[str, str],
        colours: dict[str, str],
        hidden: set[str],
        details: dict[str, str] | None = None,
        chosen: set[str] | None = None,
    ) -> None:
        """List these channels: id -> what to call it, and how each is set up.
        ``chosen`` are those whose colour was chosen here, and not the instrument's."""
        self.blockSignals(True)
        self.clear()
        self._items = {}
        for key, name in names.items():
            item = QTreeWidgetItem([name, "", "", "", (details or {}).get(key, "")])
            item.setToolTip(DETAIL, PICK_TIP)
            item.setData(NAME, Qt.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(NAME, Qt.Unchecked if key in hidden else Qt.Checked)
            item.setForeground(NAME, QBrush(QColor(colours[key])))
            item.setToolTip(NAME, COLOUR_TIP)
            item.setData(NAME, Qt.UserRole + 1, key in (chosen or set()))
            for column in (VALUE, SECOND, DIFFERENCE):
                item.setFont(column, fonts.mono())
                item.setTextAlignment(column, Qt.AlignRight | Qt.AlignVCenter)
            self.addTopLevelItem(item)
            self._items[key] = item
        self.blockSignals(False)

    def _on_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column == NAME:
            self.shown_changed.emit(
                item.data(NAME, Qt.UserRole), item.checkState(NAME) == Qt.Checked
            )

    def set_values(self, key: str, texts: tuple[str, str, str]) -> None:
        """What a channel reads: now or at the cursor, at the second cursor, and
        the difference between the two."""
        if (item := self._items.get(key)) is None:
            return
        for column, text in zip((VALUE, SECOND, DIFFERENCE), texts, strict=True):
            if item.text(column) != text:
                item.setText(column, text)


def reading_width() -> int:
    """Room for the longest a reading gets, so that its column does not jump
    about as the reading changes."""
    return QFontMetrics(fonts.mono()).horizontalAdvance(" -000.000 mV ")


class ScopeView(QWidget):
    #: A channel was clicked in the list: whose it is, by the instrument's
    #: name, and the group its settings are under.
    channel_picked = Signal(str, str)
    #: A cursor was put somewhere else, or there are more or fewer of them.
    cursors_moved = Signal()

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
        #: The axis changed what it is measured from, or has not been placed
        #: yet, so the cursors' times are not where anything is.
        self._cursors_adrift = True
        #: The ends of the sweeps on the time axis, while every instrument is
        #: sending sweeps: all of them is what there is to show.
        self._sweep_ends: tuple[float, float] | None = None
        #: Where everything held is on the time axis, of every instrument:
        #: what All shows.
        self._everything: tuple[float, float] | None = None
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
        #: Fitted, or fitted until dragged: Tools > Settings > Column widths.
        #: The readings are as wide as the longest they get either way.
        self.channel_widths = ColumnWidths(
            self.channel_list,
            ctx.settings if ctx is not None else None,
            "channels",
            fixed=dict.fromkeys((VALUE, SECOND, DIFFERENCE), reading_width()),
        )
        self.channel_list.shown_changed.connect(self._on_shown)
        self.channel_list.picked.connect(self._on_picked)
        self.channel_list.colour_asked.connect(self._on_colour_asked)
        self.channel_list.maths_asked.connect(self._on_maths_asked)
        self.channel_list.maths_removed.connect(self._on_maths_removed)

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
        self.y_mode = QComboBox()
        self.y_mode.addItems(Y_CHOICES)
        self.y_mode.setToolTip(Y_TIP)
        for index, tip in enumerate(Y_ITEM_TIPS):
            self.y_mode.setItemData(index, tip, Qt.ToolTipRole)
        self.y_mode.currentTextChanged.connect(self._place_y)
        # Its right-click menu can stop it fitting too, with no drag to say so.
        self.analog.getViewBox().sigStateChanged.connect(self._on_y_state)
        clear = QPushButton("Clear history")
        clear.setToolTip("Throw away the samples collected so far, for every channel")
        clear.clicked.connect(self.session.clear)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Time:"))
        bar.addWidget(self.time)
        bar.addWidget(self.window_s)
        bar.addWidget(QLabel("Y:"))
        bar.addWidget(self.y_mode)
        self.state = QLabel()
        bar.addWidget(self.state)
        self.cursors = QComboBox()
        self.cursors.addItems(CURSOR_CHOICES)
        self.cursors.setToolTip(CURSORS_TIP)
        #: Where the cursors are and how far apart: on a line of its own under
        #: the controls, which have no room for it, and only while there are any.
        self.cursor_times = QLabel()
        self.cursor_times.hide()
        #: Each cursor's time on the axis, and its line on each plot. A line
        #: has its number at its top on the analog plot.
        self._cursor_at = [0.0, 0.0]
        self._cursor_lines = [
            [
                pg.InfiniteLine(
                    angle=90,
                    movable=True,
                    pen=pg.mkPen(colour, width=1),
                    hoverPen=pg.mkPen(colour, width=3),
                    label=str(number + 1) if plot == 0 else None,
                    labelOpts={"position": 0.96, "color": colour},
                )
                for plot in range(2)
            ]
            for number, colour in enumerate(CURSOR_COLOURS)
        ]
        for number, lines in enumerate(self._cursor_lines):
            for line in lines:
                line.sigPositionChanged.connect(lambda moved, n=number: self._on_cursor(n, moved))
        # Pressing it writes CSV, which is what it is mostly for; its arrow
        # has the other thing a plot can be saved as.
        self.export_button = QToolButton()
        self.export_button.setText("Export CSV...")
        self.export_button.setToolTip(EXPORT_TIP)
        self.export_button.setPopupMode(QToolButton.MenuButtonPopup)
        self.export_button.clicked.connect(self.ask_export)
        self.export_menu = QMenu(self.export_button)
        self.export_menu.setToolTipsVisible(True)
        self.export_menu.addAction("Export CSV...", self.ask_export).setToolTip(EXPORT_TIP)
        self.export_menu.addAction("Export PNG...", self.ask_picture).setToolTip(PICTURE_TIP)
        self.export_button.setMenu(self.export_menu)
        bar.addStretch()
        bar.addWidget(QLabel("Cursors:"))
        bar.addWidget(self.cursors)
        bar.addWidget(self.export_button)
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
        column.addWidget(self.cursor_times)
        column.addWidget(self.plots, 1)

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
        # The row of controls above the plot has a least width of its own,
        # which would otherwise be the least the plot's side can be, and so
        # the most the list can: it is cut short before the list is.
        right.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.splitter.setSizes([LIST_WIDTH, 4 * LIST_WIDTH])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

        if ctx is not None:
            remember(ctx, f"{key}.window_s", self.window_s)
            # Auto Y unticked, from before there was a choice of three, is Range.
            if ctx.settings.get(f"{key}.y") is None and ctx.settings.get(f"{key}.auto_y") is False:
                self.y_mode.setCurrentText(Y_RANGE)
            remember(ctx, f"{key}.y", self.y_mode)
            remember(ctx, f"{key}.cursors", self.cursors)
        # After what was chosen last time is put back, which is not a choice.
        self.cursors.currentIndexChanged.connect(self._on_cursor_count)
        # activated as well: choosing what is chosen already brings them back.
        self.cursors.activated.connect(lambda _index: self.bring_cursors())
        self.channel_list.set_cursors(self.cursor_count())
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
        chosen = self._chosen_colours()
        self._colours = {}
        place: dict[str, int] = {}
        for key, unit, record in entries:
            # Which of its instrument's channels it is, not of everything open:
            # opening another instrument does not change anybody's colour.
            number = place[unit.name] = place.get(unit.name, -1) + 1
            self._colours[key] = (
                chosen.get(key) or record.channel.colour or COLOURS[number % len(COLOURS)]
            )
        self._names = {key: self.session.name_of(unit, r.channel) for key, unit, r in entries}
        #: What each is drawn in: its colour, or that faded for a reference.
        drawn: dict[str, str] = {}
        for key, unit, record in entries:
            reference = unit.instrument is not None and unit.instrument.reference
            colour = QColor(self._colours[key])
            if reference:
                colour.setAlpha(REFERENCE_ALPHA)
            drawn[key] = colour.name(QColor.HexArgb)
            pen = pg.mkPen(colour, width=1)
            if record.channel.kind == ANALOG:
                curve = self.analog.plot(pen=pen)
            else:
                # Held until the next sample, which is what a logic level does.
                curve = self.digital.plot(pen=pen, stepMode="left")
            if reference:
                curve.setZValue(REFERENCE_Z)
            self._curves[key] = curve
            self._owners[key] = (unit, record.channel.key)
        channels = [record.channel for _key, _unit, record in entries]
        units = {c.unit for c in channels if c.kind == ANALOG and c.unit}
        self.analog.setLabel("left", units=units.pop() if len(units) == 1 else None)
        details = {key: record.channel.detail for key, _unit, record in entries}
        self.channel_list.fill(self._names, drawn, self._hidden, details, set(chosen))
        # Cleared with everything else, so put back: left out of the fitting
        # of the axes, or the voltage axis would always stretch to the level.
        while len(self._level_lines) < len(self.session.shown()):
            self._level_lines.append(pg.InfiniteLine(angle=0, movable=False, pen=self._dashed))
        for line in self._level_lines:
            self.analog.addItem(line, ignoreBounds=True)
        for plot, line in zip((self.analog, self.digital), self.trigger_lines, strict=True):
            plot.addItem(line, ignoreBounds=True)
        for lines in self._cursor_lines:
            for plot, line in zip((self.analog, self.digital), lines, strict=True):
                plot.addItem(line, ignoreBounds=True)
        self._show_cursors()
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
        """Fit the voltage axis to the signal, set it to the channels' range, or
        leave it where it is.

        The range covers every analog channel shown, since they share the one
        axis: each reads full scale either side of its middle, which an offset
        moves away from nought. Where none of them has a range to speak of,
        Range fits the axis instead: there is nothing else to set it to.
        """
        choice = self.y_mode.currentText()
        if choice == MANUAL:
            # Held where it is now, whatever put it there.
            self.analog.getViewBox().disableAutoRange(axis=pg.ViewBox.YAxis)
            return
        reaches = [
            (channel.middle - channel.full_scale, channel.middle + channel.full_scale)
            for key, record in self._records()
            if (channel := record.channel).kind == ANALOG
            and key not in self._hidden
            and channel.full_scale > 0
        ]
        if choice == Y_AUTO or not reaches:
            self.analog.enableAutoRange(axis=pg.ViewBox.YAxis)
        else:
            low = min(low for low, _high in reaches)
            high = max(high for _low, high in reaches)
            self.analog.setYRange(low, high, padding=RANGE_MARGIN)

    # --- colours ---------------------------------------------------------------------------
    def _chosen_colours(self) -> dict[str, str]:
        saved = self._ctx.settings.get(CHOSEN_COLOURS) if self._ctx is not None else None
        if not isinstance(saved, dict):
            return {}
        return {str(k): v for k, v in saved.items() if isinstance(v, str) and QColor(v).isValid()}

    def colour_of(self, key: str) -> str:
        """The colour a channel is drawn in, by its id."""
        return self._colours.get(key, "")

    def set_colour(self, key: str, colour: str) -> None:
        """Draw this channel in this colour, on every plot, from now on; or with
        "" in the instrument's own colour again."""
        if self._ctx is None:
            return
        chosen = self._chosen_colours()
        if colour:
            chosen[key] = QColor(colour).name()
        else:
            chosen.pop(key, None)
        self._ctx.settings.set(CHOSEN_COLOURS, chosen)
        # Every plot draws its channels again, in the colours there are now.
        self.session.channels_changed.emit()

    # --- maths channels -----------------------------------------------------------------------
    def add_maths(self, unit: Unit, maths: Maths) -> None:
        """Give an instrument this maths channel, and keep it in the workspace."""
        unit.capture.set_maths([*unit.capture.maths, maths])
        self._save_maths(unit)

    def remove_maths(self, unit: Unit, key: str) -> None:
        unit.capture.set_maths([m for m in unit.capture.maths if m.key != key])
        self._save_maths(unit)

    def _save_maths(self, unit: Unit) -> None:
        if self._ctx is not None and unit.name:
            saved = [m.as_saved() for m in unit.capture.maths]
            self._ctx.settings.set(f"{MATHS_KEY}.{unit.name}", saved)

    def _on_maths_asked(self, key: str) -> None:
        unit, own = self._owners[key]
        channels = [
            (record.channel.key, record.channel.name)
            for record in unit.capture.records.values()
            if record.channel.kind == ANALOG and not record.channel.key.startswith("maths:")
        ]
        if len(channels) < 2:
            self._say("A maths channel needs two analog channels of one instrument.", problem=True)
            return
        dialog = MathsDialog(channels, own, self)
        if dialog.exec() == MathsDialog.Accepted:
            self.add_maths(unit, dialog.maths())

    def _on_maths_removed(self, key: str) -> None:
        unit, own = self._owners[key]
        self.remove_maths(unit, own)

    def _on_colour_asked(self, key: str, how: str) -> None:
        if not how:
            self.set_colour(key, "")
            return
        picked = QColorDialog.getColor(
            QColor(self.colour_of(key)), self, f"Colour of {self._names.get(key, key)}"
        )
        if picked.isValid():
            self.set_colour(key, picked.name())

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
    def _on_y_state(self, *_args) -> None:
        """Auto that has stopped fitting -- the right-click menu's Y axis, set by
        hand -- is Manual now: held where it was put."""
        fitting = self.analog.getViewBox().autoRangeEnabled()[1]
        if self.y_mode.currentText() == Y_AUTO and not fitting:
            self.y_mode.setCurrentText(MANUAL)

    def _on_dragged(self, mask=None) -> None:
        """The plot was zoomed or dragged: whichever axis moved stays where it was put.
        ``mask`` is which axes, time and voltage, as pyqtgraph says."""
        moved = list(mask) if isinstance(mask, list | tuple) and len(mask) == 2 else [True, True]
        if moved[0]:
            self.time.setCurrentText(MANUAL)
        if moved[1] and self.sender() is self.analog.getViewBox():
            self.y_mode.setCurrentText(MANUAL)

    def _show_time(self, *_args) -> None:
        # A sweep is shown whole: how much to show is not asked.
        wanted = self._sweep_ends is None and (self.time.currentText() == FOLLOW or self._relative)
        if self.window_s.isEnabled() != wanted:
            self.window_s.setEnabled(wanted)

    # --- cursors --------------------------------------------------------------------------
    def cursor_count(self) -> int:
        return self.cursors.currentIndex()

    def cursor_time(self, number: int) -> float:
        """Where a cursor is, in seconds on the time axis: 0 is the first of them."""
        return self._cursor_at[number]

    def set_cursor(self, number: int, seconds: float) -> None:
        """Put a cursor at this time on the axis, as dragging it there does."""
        self._cursor_at[number] = float(seconds)
        for line in self._cursor_lines[number]:
            if line.value() != seconds:
                line.blockSignals(True)
                line.setValue(seconds)
                line.blockSignals(False)
        self._show_values()
        self.cursors_moved.emit()

    def _on_cursor(self, number: int, moved) -> None:
        self.set_cursor(number, moved.value())

    def _on_cursor_count(self, *_args) -> None:
        self.cursors_moved.emit()
        self.channel_list.set_cursors(self.cursor_count())
        self._show_cursors()
        self.bring_cursors()
        self._fit_list()

    def _fit_list(self) -> None:
        """Make the channel list as wide as the columns it has now: wider for a
        reading at each of two cursors, and narrower with none, so that the
        plot has the room. A list dragged shut is left shut."""
        tree = self.channel_list
        have, plot = self.splitter.sizes()
        if not tree.isVisible() or have == 0:
            return
        readings = (NAME, VALUE, SECOND, DIFFERENCE)
        needed = sum(tree.columnWidth(c) for c in readings if not tree.isColumnHidden(c))
        settings = max(tree.sizeHintForColumn(DETAIL), tree.header().sectionSizeHint(DETAIL))
        needed += settings + 24
        if needed != have:
            self.splitter.setSizes([needed, max(plot + have - needed, 0)])

    def _show_cursors(self) -> None:
        for number, lines in enumerate(self._cursor_lines):
            for line in lines:
                line.setVisible(number < self.cursor_count())

    def bring_cursors(self, every: bool = False) -> None:
        """Put the cursors that are out of sight -- or every one -- back in view:
        a third of the way across, and two thirds. One on the very edge counts
        as out of sight: it is under the axis there, or cut off."""
        (x_from, x_to), _y = self.analog.getViewBox().viewRange()
        margin = (x_to - x_from) * EDGE
        for number in range(self.cursor_count()):
            if every or not x_from + margin <= self._cursor_at[number] <= x_to - margin:
                self.set_cursor(number, x_from + (x_to - x_from) * (number + 1) / 3)
        self._show_values()

    # --- what is measured -------------------------------------------------------------------
    def span(self) -> tuple[float, float, bool]:
        """The stretch of time measurements are over: between the two cursors when
        there are two, or what is in view. And whether it is the cursors'."""
        if self.cursor_count() == 2:
            first, second = sorted(self._cursor_at)
            return first, second, True
        (low, high), _y = self.analog.getViewBox().viewRange()
        return low, high, False

    def shown_channels(self) -> list[tuple[str, str]]:
        """Every channel ticked to be shown, as (its id, what it is called)."""
        return [(key, self._names[key]) for key in self._curves if key not in self._hidden]

    def origin_of(self, name: str) -> float:
        """The time, in this instrument's own seconds, that the axis calls nought."""
        timing = self._timings.get(name)
        return timing.origin if timing is not None else 0.0

    def samples_between(self, key: str, t_from: float, t_to: float):
        """A channel's samples in this stretch of the time axis, the record they are
        of, and the rate. None for a channel with nothing there."""
        unit, channel = self._owners[key]
        record = unit.capture.records.get(channel)
        if record is None or not record.count:
            return None
        timing = self._timings.get(unit.name)
        origin = timing.origin if timing is not None else 0.0
        _first, samples = record.between(t_from + origin, t_to + origin)
        return samples, record

    def measure(self, key: str) -> Measured | None:
        """What a channel measures over the span: see ``span``."""
        t_from, t_to, _cursors = self.span()
        found = self.samples_between(key, t_from, t_to)
        if found is None:
            return None
        samples, record = found
        return measure(samples, record.rate)

    def _reading(self, key: str, seconds: float) -> float | None:
        """What a channel read at this time on the axis: the sample nearest to
        it. None where nothing is held there."""
        unit, channel = self._owners[key]
        record = unit.capture.records.get(channel)
        timing = self._timings.get(unit.name)
        if record is None or not record.count:
            return None
        origin = timing.origin if timing is not None else 0.0
        at = round((seconds + origin) * record.rate)
        if not record.first <= at < record.total:
            return None
        value = float(record.view()[at - record.first])
        return None if np.isnan(value) else value

    @staticmethod
    def _value_text(record, value: float | None, difference: bool = False) -> str:
        if value is None:
            return NOTHING_HELD
        if record.channel.kind == DIGITAL:
            # How far a logic level moved is not a number worth a column.
            return "" if difference else str(int(value))
        sign = "+" if difference and value > 0 else ""
        return f"{sign}{value:.3f} {record.channel.unit}".rstrip()

    def _show_cursor_times(self) -> None:
        count = self.cursor_count()
        first, second = (time_text(at) for at in self._cursor_at)
        if count == 0:
            text = ""
        elif count == 1:
            text = f"Cursor at {first}"
        else:
            between = self._cursor_at[1] - self._cursor_at[0]
            text = f"Cursor 1 at {first}, cursor 2 at {second}: \u0394 {time_text(between)}"
            if between:
                text += f", {frequency_text(1 / abs(between))}"
        if self.cursor_times.text() != text:
            self.cursor_times.setText(text)
        if self.cursor_times.isHidden() == bool(count):
            self.cursor_times.setVisible(bool(count))

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
                # Read as it is, an instrument triggers on what it was set to
                # itself, which is not the level here.
                and not (unit.instrument is not None and unit.instrument.reads_as_is)
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
        #: Where each instrument's samples are on the axis: all of a sweep,
        #: and all that is held of a stream. What All shows.
        spans: list[tuple[float, float]] = []
        for unit in units:
            timing = self._timings.setdefault(unit.name, _Timing())
            origin, state, is_relative, sweep_ends = self._find_origin(unit, timing, several)
            origins[unit.name] = origin
            relative = relative or is_relative
            if sweep_ends is None:
                streams = True
                held = (unit.capture.oldest(), unit.capture.newest())
                if origin is not None and None not in held:
                    spans.append((held[0] - origin, held[1] - origin))
            else:
                ends.append(sweep_ends)
                spans.append(sweep_ends)
            if origin is not None:
                timing.origin = origin
            if unit.doing and unit.running:
                # A slow instrument says what it is at, so that it is not taken for stuck.
                state = f"{state} ({unit.doing})" if state else unit.doing.capitalize()
            if state:
                states.append(f"{unit.short or unit.name}: {state}" if several else state)
        # Two instruments have no time in common but their triggers.
        self._relative = relative or several
        if ends and not streams:
            self._sweep_ends = (min(e[0] for e in ends), max(e[1] for e in ends))
        else:
            self._sweep_ends = None
        self._everything = (min(s[0] for s in spans), max(s[1] for s in spans)) if spans else None
        return origins, "   ".join(states)

    def show_all(self) -> None:
        """Show everything held: what a snapshot of a scope's screen wants, where
        Follow's stretch of time around the trigger would cut it short."""
        self.time.setCurrentText(ALL)

    def _show_relative(self, was_relative: bool) -> None:
        """Take up a change between time from the start and time from a trigger."""
        if was_relative == self._relative:
            return
        # A stretch chosen by hand on one axis means nothing on the other.
        self.time.setCurrentText(FOLLOW)
        self._show_time()
        # Nor does a cursor's time: they are put back in view once it is placed.
        self._cursors_adrift = True
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
            # All is everything held, of every instrument: a sweep beside a
            # stream is all of the sweep, and as much of the stream as there is.
            if choice == ALL and self._everything is not None:
                self.analog.setXRange(*self._everything, padding=0)
                return
            # Follow is the stretch asked for around the trigger, which is at nought.
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
        if self._cursors_adrift:
            self._cursors_adrift = False
            self.bring_cursors(every=True)
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

    # --- writing it out -------------------------------------------------------------------
    def _ask_where(self, title: str, name: str, kinds: str) -> Path | None:
        """Ask for a file to write, starting where the last one went."""
        folder = self._ctx.settings.get(EXPORT_FOLDER) if self._ctx is not None else None
        start = str(Path(folder) / name) if isinstance(folder, str) else name
        chosen, _filter = QFileDialog.getSaveFileName(self, title, start, kinds)
        if not chosen:
            return None
        path = Path(chosen)
        if self._ctx is not None:
            self._ctx.settings.set(EXPORT_FOLDER, str(path.parent))
        return path

    def ask_export(self) -> None:
        """Ask where to, and write what the plot shows as CSV."""
        path = self._ask_where("Export CSV", "capture.csv", "Comma-separated values (*.csv)")
        if path is not None:
            self.export_csv(path)

    def ask_picture(self) -> None:
        """Ask where to, and save a picture of the plot."""
        path = self._ask_where("Export PNG", "capture.png", "PNG picture (*.png)")
        if path is not None:
            self.export_png(path)

    def save_captures(self, path: Path) -> list[Path]:
        """Save everything held, of every instrument on the plot, as pyscopegui's own
        file: one for each instrument, as Export CSV writes. The files written."""
        self.redraw()  # so that time is measured from where the plot has it now
        units = [unit for unit in self.session.shown() if unit.capture.stored()]
        if path.suffix.lower() != capture_file.SUFFIX:
            path = path.with_name(path.name + capture_file.SUFFIX)
        files = export.paths_for(path, [unit.short or unit.name or "capture" for unit in units])
        written = []
        for unit in units:
            records = [r for r in unit.capture.records.values() if r.count]
            # What every channel has: they arrive together.
            first = max(r.first for r in records)
            last = min(r.total for r in records)
            rate = records[0].rate
            timing = self._timings.get(unit.name)
            zero = round((timing.origin if timing is not None else 0.0) * rate) - first
            loaded = capture_file.Loaded(
                [r.channel for r in records],
                rate,
                {r.channel.key: r.view()[first - r.first : last - r.first].copy() for r in records},
                zero if 0 <= zero < last - first else None,
            )
            where = files[unit.short or unit.name or "capture"]
            try:
                capture_file.save(where, loaded, unit.name)
            except OSError as exc:
                self._say(f"{unit.short or 'The capture'} was not saved: {exc}.", problem=True)
                continue
            written.append(where)
            self._say(f"Saved {last - first:,} samples of {len(records)} channels to {where}.")
        if not units:
            self._say("There is nothing on the plot to save.", problem=True)
        return written

    def export_png(self, path: Path) -> bool:
        """Save a picture of the pane as it looks now: the plot, and the channel
        list that says what is on it. Says where it went, or that it did not."""
        self.redraw()  # so that what is saved is what there is now
        if path.suffix.lower() != ".png":
            path = path.with_name(path.name + ".png")
        # What it says it is doing was written a moment ago, and is given its
        # room only when the pane is next laid out: now, not after the picture.
        QCoreApplication.sendPostedEvents(None, QEvent.LayoutRequest)
        picture = self.grab()
        if not picture.save(str(path), "PNG"):
            self._say(f"The picture could not be saved to {path}.", problem=True)
            return False
        self._say(
            f"Saved a picture of the plot, {picture.width()} by {picture.height()}, to {path}."
        )
        return True

    def export_csv(self, path: Path) -> list[export.Written]:
        """Write the channels that are ticked, in the stretch of time in view:
        one file for each instrument. Says what was written, or why not."""
        self.redraw()  # so that what is written is what is on the screen now
        (t_from, t_to), _y = self.analog.getViewBox().viewRange()
        wanted: dict[str, dict] = {}
        for key, (unit, channel) in self._owners.items():
            record = unit.capture.records.get(channel)
            if key not in self._hidden and record is not None and record.count:
                wanted.setdefault(unit.name, {})[record.channel.name] = record
        units = {unit.name: unit for unit in self.session.shown()}
        files = export.paths_for(path, [units[name].short or name for name in wanted])
        written = []
        for name, records in wanted.items():
            unit = units[name]
            timing = self._timings.get(name)
            origin = timing.origin if timing is not None else 0.0
            try:
                done = export.write_csv(files[unit.short or name], records, origin, t_from, t_to)
            except (OSError, ValueError) as exc:
                self._say(f"{unit.short or 'The capture'} was not exported: {exc}.", problem=True)
                continue
            written.append(done)
            self._say(
                f"Exported {done.rows:,} samples of {done.channels} "
                f"{'channel' if done.channels == 1 else 'channels'} to {done.path}."
            )
        if not wanted:
            self._say("There is nothing on the plot to export.", problem=True)
        return written

    def _say(self, message: str, problem: bool = False) -> None:
        if self._ctx is None:
            return
        if problem:
            self._ctx.warn(message)
        else:
            self._ctx.log(message)

    def _show_values(self) -> None:
        """What each channel reads: now, with no cursor; at the cursor, with one;
        at each and the difference between them, with two."""
        if not self.isVisible():
            return
        count = self.cursor_count()
        self._show_cursor_times()
        for key, record in self._records():
            if not record.count:
                texts = ("", "", "")
            elif count == 0:
                texts = ("", "", "")  # nothing to read, and no column to read it in
            else:
                first = self._reading(key, self._cursor_at[0])
                texts = (self._value_text(record, first), "", "")
                if count == 2:
                    second = self._reading(key, self._cursor_at[1])
                    apart = None if first is None or second is None else second - first
                    texts = (
                        texts[0],
                        self._value_text(record, second),
                        self._value_text(record, apart, difference=True),
                    )
            self.channel_list.set_values(key, texts)

    # --- layout, saved with the rest of the window state ---------------------
    def save_state(self):
        return self.splitter.saveState()

    def restore_state(self, state) -> None:
        if state is not None:
            self.splitter.restoreState(state)
