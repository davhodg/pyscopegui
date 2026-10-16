# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The Data pane: the samples themselves, as a table.

One instrument at a time: its channels are sampled together, at one rate, so
a row is one moment and every channel has a value in it. Two instruments'
samples are taken at moments of their own, and a row of both would be made up.

The rows are the same stretch the Measurements pane measures: between the
plot's two cursors when there are two, and what is in view when there are
not. The rows at the cursors are tinted their colour.

Nothing is copied to fill the table. A row is a sample's number, and what is
in it is read from the history when the row is drawn: a stretch of millions
of samples costs only the rows on screen. A sample the history has since let
go of is shown empty.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFontMetrics, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from pyscopegui.backends.base import ANALOG
from pyscopegui.core.capture import Record
from pyscopegui.core.export import ANALOG_FORMAT, time_format
from pyscopegui.ui import fonts
from pyscopegui.ui.column_widths import ColumnWidths
from pyscopegui.ui.scope_view import CURSOR_COLOURS, ScopeView, time_text

#: How often the table is read again while the pane is on screen, in milliseconds.
REFRESH_MS = 250
#: The most rows the table has. Past this Qt's scroll bar runs out of room --
#: a row a pixel high is still millions of them -- and nobody reads that many.
MOST_ROWS = 10_000_000
#: The most rows that Copy puts on the clipboard at once.
MOST_COPIED = 1_000_000
#: The first columns, before the channels'.
SAMPLE, TIME = 0, 1
#: How strongly a cursor's row is tinted with its colour, out of 255.
TINT = 70

DATA_TIP = (
    "The samples of one instrument, a row for each: between the cursors\n"
    "when there are two, and what is in view when there are not. Select rows\n"
    "and press Ctrl+C to copy them, to paste into a spreadsheet."
)


@dataclass(frozen=True)
class Column:
    """A channel's column: what it is headed, and where its samples are held."""

    heading: str
    record: Record


class Samples(QAbstractTableModel):
    """A stretch of one instrument's samples, a row for each, read as they are drawn."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.columns: list[Column] = []
        #: The number of the sample in the first row, and how many rows.
        self.first = 0
        self.count = 0
        self.rate = 1.0
        #: The instrument's own time that the plot's axis calls nought.
        self.origin = 0.0
        self._time = time_format(1.0)
        #: Sample number -> the colour its row is tinted, for each cursor.
        self.tinted: dict[int, QColor] = {}
        # Worked out once: Qt asks for them for every cell it draws.
        self._font = fonts.mono()
        self._right = int(Qt.AlignRight | Qt.AlignVCenter)

    def show(self, columns: list[Column], first: int, count: int, rate: float, origin: float):
        """These columns and rows from now on: the table is laid out again only
        when they are not the ones it has already."""
        same = [(c.heading, id(c.record)) for c in columns] == [
            (c.heading, id(c.record)) for c in self.columns
        ] and (first, count, rate, origin) == (self.first, self.count, self.rate, self.origin)
        if same:
            # The same samples by number, but a sweep read again is new ones.
            self._changed()
            return
        self.beginResetModel()
        self.columns, self.first, self.count = columns, first, count
        self.rate, self.origin = rate, origin
        self._time = time_format(rate)
        self.endResetModel()

    def _changed(self) -> None:
        if self.count and self.columns:
            self.dataChanged.emit(
                self.index(0, 0), self.index(self.count - 1, self.columnCount() - 1)
            )

    def set_tinted(self, tinted: dict[int, QColor]) -> None:
        if tinted != self.tinted:
            self.tinted = tinted
            self._changed()

    # --- what Qt asks -------------------------------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else self.count

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else TIME + 1 + len(self.columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation != Qt.Horizontal or role != Qt.DisplayRole:
            return None
        if section == SAMPLE:
            return "Sample"
        if section == TIME:
            return "Time (s)"
        return self.columns[section - TIME - 1].heading

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return self.text(self.first + index.row(), index.column())
        if role == Qt.TextAlignmentRole:
            return self._right
        if role == Qt.FontRole:
            return self._font
        if role == Qt.BackgroundRole:
            return self.tinted.get(self.first + index.row())
        return None

    def text(self, number: int, column: int) -> str:
        """What a cell says: a sample's number, its time, or a channel's value."""
        if column == SAMPLE:
            return str(number)
        if column == TIME:
            return self._time % (number / self.rate - self.origin)
        record = self.columns[column - TIME - 1].record
        if not record.first <= number < record.total:
            return ""  # let go of since, or not arrived yet
        value = record.view()[number - record.first]
        if record.channel.kind != ANALOG:
            return str(int(value))
        return "" if math.isnan(value) else ANALOG_FORMAT % value

    def rows_as_text(self, rows: list[int]) -> str:
        """These rows, headed, a tab between the columns: what a spreadsheet pastes."""
        columns = range(self.columnCount())
        lines = ["\t".join(self.headerData(c, Qt.Horizontal) for c in columns)]
        lines += ["\t".join(self.text(self.first + r, c) for c in columns) for r in rows]
        return "\n".join(lines) + "\n"


class DataView(QWidget):
    def __init__(self, scope: ScopeView) -> None:
        super().__init__()
        self.scope = scope
        self.instrument = QComboBox()
        self.instrument.setToolTip("Whose samples: an instrument's channels share their moments.")
        self.instrument.activated.connect(lambda _i: self.refresh())
        self.over = QLabel()
        self.samples = Samples(self)
        self.table = QTableView()
        self.table.setModel(self.samples)
        self.table.setToolTip(DATA_TIP)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setWordWrap(False)
        # Every row the same height, and no row numbers down the side: the
        # sample's number is a column, and measuring millions of rows is not.
        rows = self.table.verticalHeader()
        rows.setSectionResizeMode(QHeaderView.Fixed)
        rows.setDefaultSectionSize(QFontMetrics(fonts.mono()).height() + 4)
        rows.hide()
        # Fitting a column to what is in it looks at the rows on screen, and
        # not at millions of them.
        self.table.horizontalHeader().setResizeContentsPrecision(0)
        copy = QAction("Copy", self.table)
        copy.setShortcut(QKeySequence.Copy)
        copy.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        copy.triggered.connect(self.copy)
        self.table.addAction(copy)
        ctx = scope._ctx
        #: Every column as wide as the longest it gets: they are numbers.
        self.widths = ColumnWidths(
            self.table, ctx.settings if ctx is not None else None, "data", last_stretches=False
        )
        top = QHBoxLayout()
        top.addWidget(QLabel("Instrument:"))
        top.addWidget(self.instrument)
        top.addWidget(self.over, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(top)
        layout.addWidget(self.table)
        self._timer = QTimer(self, interval=REFRESH_MS, timeout=self.refresh)
        self._timer.start()
        scope.cursors_moved.connect(self.refresh)

    # --- which instrument ---------------------------------------------------------------
    def _units(self) -> dict[str, tuple]:
        """Each instrument with a channel ticked on the plot: its name -> the unit,
        and its channels shown, as (the plot's id, its own key, what it is called)."""
        found: dict[str, tuple] = {}
        for key, name in self.scope.shown_channels():
            unit, own = self.scope._owners[key]
            found.setdefault(unit.name, (unit, []))[1].append((key, own, name))
        return found

    def _choose_from(self, units: dict[str, tuple]) -> str | None:
        """List the instruments there are, keeping the one chosen if it is there."""
        names = list(units)
        chosen = self.instrument.currentData()
        listed = [self.instrument.itemData(i) for i in range(self.instrument.count())]
        if listed != names:
            self.instrument.blockSignals(True)
            self.instrument.clear()
            for name in names:
                self.instrument.addItem(units[name][0].short or name, name)
            self.instrument.setCurrentIndex(max(self.instrument.findData(chosen), 0))
            self.instrument.blockSignals(False)
        return self.instrument.currentData()

    # --- what is shown ------------------------------------------------------------------
    def refresh(self) -> None:
        if not self.isVisible():
            return
        units = self._units()
        name = self._choose_from(units)
        if name is None:
            self.over.setText("Nothing is shown on the plot.")
            self.samples.show([], 0, 0, 1.0, 0.0)
            return
        unit, shown = units[name]
        columns = [
            Column(self._heading(record, said), record)
            for _key, own, said in shown
            if (record := unit.capture.records.get(own)) is not None and record.count
        ]
        if not columns:
            self.over.setText("Nothing has been read yet.")
            self.samples.show([], 0, 0, 1.0, 0.0)
            return
        rate = columns[0].record.rate
        origin = self.scope.origin_of(unit.name)
        t_from, t_to, cursors = self.scope.span()
        # The stretch every channel has: they are read together.
        first = max(max(c.record.first for c in columns), int(np.floor((t_from + origin) * rate)))
        stop = min(min(c.record.total for c in columns), int(np.ceil((t_to + origin) * rate)) + 1)
        count = max(stop - first, 0)
        where = "Between the cursors" if cursors else "In view"
        said = f"{where}: {time_text(t_to - t_from)}, {count:,} samples"
        if count > MOST_ROWS:
            said += f" -- the first {MOST_ROWS:,} of them here: zoom in, or use the cursors"
            count = MOST_ROWS
        self.over.setText(said)
        old = (self.samples.first, self.samples.count)
        top = self.table.rowAt(0)
        self.samples.show(columns, first, count, rate, origin)
        if (first, count) != old:
            self._fit_columns()
            # The same sample at the top as before, where it is still here.
            if top >= 0 and first <= old[0] + top < first + count:
                self.table.scrollTo(self.samples.index(old[0] + top - first, 0))
        self._tint(origin, rate)

    def _heading(self, record: Record, name: str) -> str:
        unit = record.channel.unit if record.channel.kind == ANALOG else ""
        return f"{name} ({unit})" if unit else name

    def _tint(self, origin: float, rate: float) -> None:
        """The rows at the cursors, tinted their colours."""
        tinted = {}
        for number in range(self.scope.cursor_count()):
            colour = QColor(CURSOR_COLOURS[number])
            colour.setAlpha(TINT)
            tinted[round((self.scope.cursor_time(number) + origin) * rate)] = colour
        self.samples.set_tinted(tinted)

    def _fit_columns(self) -> None:
        """Each column as wide as the longest it gets, in Automatic, and to
        begin with in Manual: the widest sample number and time there are, and
        a value with all its figures."""
        metrics = QFontMetrics(fonts.mono())
        samples = self.samples
        last = samples.first + max(samples.count - 1, 0)
        widest = {
            SAMPLE: metrics.horizontalAdvance(f" {last} "),
            TIME: metrics.horizontalAdvance(f" {samples.text(last, TIME)} "),
        }
        value = metrics.horizontalAdvance(" -1.23456e-05 ")
        header = self.table.horizontalHeader()
        for column in range(TIME + 1, samples.columnCount()):
            heading = header.fontMetrics().horizontalAdvance(
                f"  {samples.headerData(column, Qt.Horizontal)}  "
            )
            widest[column] = max(value, heading)
        self.widths.set_fixed(widest)

    # --- copied -------------------------------------------------------------------------
    def copy(self) -> None:
        """The rows selected, onto the clipboard: a header, then a row of each."""
        rows = sorted({index.row() for index in self.table.selectionModel().selectedIndexes()})
        if not rows:
            return
        QApplication.clipboard().setText(self.samples.rows_as_text(rows[:MOST_COPIED]))
