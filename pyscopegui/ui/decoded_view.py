# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The Decoded buses pane: everything read off the channels decoded -- CAN
frames, serial lines' characters, SPI and I2C transfers -- in one list.

Above it, the buses: each can be paused -- kept, with what it read, but not
decoded and not listed until it is ticked again -- or removed, and more added.
Below, a row for each thing read, every bus's in the order they came, and the
time each started on the plot's axis. Clicking one puts the first cursor on it, and brings it
into view. One read wrong -- a stuff error, a parity error, a word cut short --
is a row of its own, said in red: what a bus did is the point, the bad as much
as the good.

The list is what started in view on the plot, or between its two cursors when
there are two, as the Data pane's rows are: zoom in to a moment and the list is
what was read there, however much the history holds. A row is made only when it
is drawn, so a stretch of hundreds of thousands costs no more than a few. The
list follows the newest as they come, unless it has been scrolled up to read;
then it stays where it was put.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pyscopegui.core.decoding import (
    CAN,
    I2C,
    PARALLEL,
    PROTOCOLS,
    SOURCES,
    SPI,
    UART,
    Decoding,
)
from pyscopegui.ui import fonts, icons
from pyscopegui.ui.can_dialog import bitrate_text
from pyscopegui.ui.column_widths import ColumnWidths
from pyscopegui.ui.scope_view import ScopeView, time_text

#: How often the list is read again while the pane is on screen, in milliseconds.
REFRESH_MS = 250
HEADINGS = ("Time (s)", "Bus", "ID / address", "Type", "Data", "ACK", "Problem")
TIME, BUS, ID, TYPE, DATA, ACK, PROBLEM = range(len(HEADINGS))
#: What is read wrong is said in.
WRONG = QColor("#d04040")
NOTHING_DECODED = (
    "No channel is decoded. Add... decodes one, as does right-clicking a channel "
    "in the plot's list and choosing Decode as."
)
BUSES_TIP = (
    "The buses decoded. Untick one to pause it: what it read is kept, and\n"
    "nothing more is decoded or listed until it is ticked again."
)
ADD_TIP = "Decode a channel: choose it, and then what it carries."
REMOVE_TIP = "Stop decoding the bus chosen above, and forget what it read."
#: The most buses shown at once in the list above the table; more scroll.
BUSES_SHOWN = 4
DECODED_TIP = (
    "What was read off the channels decoded, in view on the plot or between\n"
    "its two cursors. Click a row to put the first cursor on it. Select rows\n"
    "and press Ctrl+C to copy them."
)
#: The most rows made and kept at once, as they are drawn.
ROWS_HELD = 512


@dataclass(frozen=True)
class Row:
    """Something read off a bus, with which bus and when, on the plot's axis."""

    seconds: float
    bus: str
    decoding: Decoding
    item: object


def _hex(values, bits: int = 8) -> str:
    width = (bits + 3) // 4
    return " ".join(f"{value:0{width}X}" for value in values)


def _text(values) -> str:
    """Characters as they read, where they are printable: "Hello"."""
    if not values or not all(32 <= v < 127 or v in (9, 10, 13) for v in values):
        return ""
    shown = "".join(chr(v) for v in values).replace("\r", "\\r").replace("\n", "\\n")
    return f'  "{shown}"'


def texts(row: Row) -> list[str]:
    """What a row says, column by column."""
    item, protocol = row.item, row.decoding.setup.protocol
    identifier = kind = data = ack = ""
    if protocol == CAN:
        identifier = f"{item.identifier:08X}" if item.extended else f"{item.identifier:03X}"
        kind = f"{'Remote' if item.remote else 'Data'}, DLC {item.dlc}"
        kind += ", 29-bit" if item.extended else ""
        data = _hex(item.data)
        ack = "yes" if item.acked else "no"
    elif protocol == UART:
        kind = f"{len(item.values)} character{'s' if len(item.values) != 1 else ''}"
        data = _hex(item.values, row.decoding.setup.bits) + _text(item.values)
    elif protocol == SPI:
        bits = row.decoding.setup.bits
        words = max(len(item.mosi), len(item.miso))
        kind = f"{words} word{'s' if words != 1 else ''}"
        sides = [("MOSI", item.mosi), ("MISO", item.miso)]
        data = "   ".join(f"{name} {_hex(values, bits)}" for name, values in sides if values)
    elif protocol == PARALLEL:
        setup = row.decoding.setup
        words = len(item.words)
        kind = f"{words} word{'s' if words != 1 else ''}"
        if item.streams:
            # A channel select: each channel's words together, A first.
            sides = sorted((setup.stream_name(s), item.of(s)) for s in (0, 1))
            data = "   ".join(
                f"{name} {_hex(values, setup.width)}" for name, values in sides if values
            )
        else:
            data = _hex(item.words, setup.width)
    elif protocol == I2C:
        if item.address is not None:
            identifier = f"0x{item.address:03X}" if item.ten_bit else f"0x{item.address:02X}"
        kind = "Read" if item.read else "Write"
        kind += ", 10-bit" if item.ten_bit else ""
        data = _hex(item.data)
        if item.nacked:
            ack = "no: nobody there"
        elif all(item.acks) or (item.read and all(item.acks[:-1])):
            ack = "yes"  # a read ends with the controller not acknowledging the last
        else:
            ack = f"no, at byte {item.acks.index(False)}"
    return [f"{row.seconds:.6f}", row.bus, identifier, kind, data, ack, item.error]


@dataclass(frozen=True)
class Stretch:
    """What one bus read in the stretch listed: those it keeps, by number, from
    ``lo`` up to but not including ``hi``."""

    decoding: Decoding
    bus: str
    origin: float
    lo: int
    hi: int

    def seconds(self) -> np.ndarray:
        """When each started, on the plot's axis."""
        return self.decoding.items.starts(self.lo, self.hi) / self.decoding.rate - self.origin


class Listed:
    """The rows listed: every bus's, in the order they started, each made only
    when it is asked for. The order is worked out once, as numbers."""

    def __init__(self, stretches: list[Stretch] | None = None) -> None:
        self.stretches = [s for s in stretches or [] if s.hi > s.lo]
        each = [s.seconds() for s in self.stretches]
        self.seconds = np.concatenate(each) if each else np.zeros(0)
        #: For more than one bus: whose each row is, and which of its.
        self._whose: np.ndarray | None = None
        self._which: np.ndarray | None = None
        if len(self.stretches) > 1:
            order = np.argsort(self.seconds, kind="stable")
            self.seconds = self.seconds[order]
            whose = np.repeat(np.arange(len(each)), [len(s) for s in each])
            which = np.concatenate([np.arange(s.lo, s.hi) for s in self.stretches])
            self._whose, self._which = whose[order], which[order]
        self._made: dict[int, Row] = {}

    def __len__(self) -> int:
        return len(self.seconds)

    def __bool__(self) -> bool:
        return len(self) > 0

    def __iter__(self):
        return (self[n] for n in range(len(self)))

    def __getitem__(self, number: int) -> Row:
        if number < 0:
            number += len(self)
        if not 0 <= number < len(self):
            raise IndexError("no such row")
        if (row := self._made.get(number)) is not None:
            return row
        if self._whose is None:
            stretch, which = self.stretches[0], self.stretches[0].lo + number
        else:
            stretch, which = self.stretches[self._whose[number]], int(self._which[number])
        item = stretch.decoding.items[which]
        row = Row(float(self.seconds[number]), stretch.bus, stretch.decoding, item)
        if len(self._made) >= ROWS_HELD:
            self._made.clear()
        self._made[number] = row
        return row

    def near(self, seconds: float) -> int:
        """The first row that started at or after this time."""
        return int(np.searchsorted(self.seconds, seconds))


class Items(QAbstractTableModel):
    """What was read, a row for each."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.rows = Listed()
        self._font = fonts.mono()
        self._right = int(Qt.AlignRight | Qt.AlignVCenter)

    def show(self, rows: Listed) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(HEADINGS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return HEADINGS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        row = self.rows[index.row()]
        if role == Qt.DisplayRole:
            return texts(row)[index.column()]
        if role == Qt.ForegroundRole and row.item.error:
            return WRONG
        if role == Qt.FontRole and index.column() in (TIME, ID, DATA):
            return self._font
        if role == Qt.TextAlignmentRole and index.column() == TIME:
            return self._right
        return None


class DecodedView(QWidget):
    def __init__(self, scope: ScopeView) -> None:
        super().__init__()
        self.scope = scope
        self.over = QLabel()
        self.over.setWordWrap(True)
        #: The buses, a tick to have each decoded, and what each has read.
        self.buses = QListWidget()
        self.buses.setToolTip(BUSES_TIP)
        self.buses.itemChanged.connect(self._on_ticked)
        self.buses.currentRowChanged.connect(lambda _row: self._show_usable())
        self.add = icons.beside(QToolButton(), icons.ADD)
        self.add.setText("Add...")
        self.add.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.add.setToolTip(ADD_TIP)
        self.add.setPopupMode(QToolButton.InstantPopup)
        self.add.setMenu(QMenu(self.add))
        self.add.menu().aboutToShow.connect(self._fill_add)
        self.remove = icons.beside(QPushButton("Remove"), icons.REMOVE)
        self.remove.setToolTip(REMOVE_TIP)
        self.remove.clicked.connect(self._remove)
        self.items = Items(self)
        self.table = QTableView()
        self.table.setModel(self.items)
        self.table.setToolTip(DECODED_TIP)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setWordWrap(False)
        rows = self.table.verticalHeader()
        rows.setSectionResizeMode(QHeaderView.Fixed)
        rows.hide()
        self.table.horizontalHeader().setResizeContentsPrecision(0)
        self.table.clicked.connect(lambda index: self.go_to(index.row()))
        copy = QAction("Copy", self.table)
        copy.setShortcut(QKeySequence.Copy)
        copy.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        copy.triggered.connect(self.copy)
        self.table.addAction(copy)
        ctx = scope._ctx
        self.widths = ColumnWidths(
            self.table, ctx.settings if ctx is not None else None, "decoded", stretch=PROBLEM
        )
        buttons = QVBoxLayout()
        buttons.addWidget(self.add)
        buttons.addWidget(self.remove)
        buttons.addStretch()
        top = QHBoxLayout()
        top.addWidget(self.buses, 1)
        top.addLayout(buttons)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.over)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        #: The buses listed, as (instrument, key, paused): rebuilt when that changes.
        self._listed: list[tuple[str, str, bool]] = []
        #: What was shown last: each bus's count and first item, so the list
        #: is laid out again only when there is something new.
        self._shown: tuple = ()
        self._timer = QTimer(self, interval=REFRESH_MS, timeout=self.refresh)
        self._timer.start()

    def _decodings(self) -> list[tuple[str, str, Decoding]]:
        """Every bus decoded: its instrument, what to call it, and it."""
        found = []
        session = self.scope.session
        for unit in session.shown():
            for decoding in unit.capture.decodings:
                names = []
                for key in decoding.setup.channels():
                    record = unit.capture.records.get(key)
                    names.append(session.name_of(unit, record.channel) if record else key)
                found.append((unit.name, ", ".join(names), decoding))
        return found

    # --- the buses ------------------------------------------------------------------------
    def _list_buses(self, decodings: list[tuple[str, str, Decoding]]) -> None:
        """A line for each bus, ticked unless it is paused, saying what it has read."""
        listed = [(unit, d.key, d.paused) for unit, _name, d in decodings]
        if listed != self._listed:
            chosen = self.buses.currentRow()
            self.buses.blockSignals(True)
            self.buses.clear()
            for unit, _name, decoding in decodings:
                item = QListWidgetItem()
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked if decoding.paused else Qt.Checked)
                item.setData(Qt.UserRole, (unit, decoding.key))
                self.buses.addItem(item)
            self.buses.setCurrentRow(min(chosen, self.buses.count() - 1))
            self.buses.blockSignals(False)
            self._listed = listed
            rows = min(max(len(listed), 1), BUSES_SHOWN)
            height = self.buses.sizeHintForRow(0) if listed else 0
            self.buses.setFixedHeight(rows * max(height, 1) + 2 * self.buses.frameWidth() + 2)
        self.buses.blockSignals(True)
        for row, (_unit, name, decoding) in enumerate(decodings):
            said = self._summary(name, decoding) + (", paused" if decoding.paused else "")
            if self.buses.item(row).text() != said:
                self.buses.item(row).setText(said)
        self.buses.blockSignals(False)
        self.buses.setVisible(bool(decodings))
        self._show_usable()

    def _show_usable(self) -> None:
        self.remove.setEnabled(self.buses.currentItem() is not None and self.buses.isVisible())

    def _unit_and_key(self, item: QListWidgetItem):
        unit_name, key = item.data(Qt.UserRole)
        return self.scope.session.units.get(unit_name), key

    def _on_ticked(self, item: QListWidgetItem) -> None:
        unit, key = self._unit_and_key(item)
        if unit is not None:
            self.scope.pause_decoding(unit, key, item.checkState() != Qt.Checked)
            self.refresh()

    def _remove(self) -> None:
        item = self.buses.currentItem()
        if item is None:
            return
        unit, key = self._unit_and_key(item)
        if unit is not None:
            self.scope.remove_bus(unit, key)
            self.refresh()

    def _fill_add(self) -> None:
        """Every channel there is, each with what it can be decoded as."""
        menu = self.add.menu()
        menu.clear()
        session = self.scope.session
        entries = list(session.entries())
        if not entries:
            menu.addAction("No channels: open an instrument first").setEnabled(False)
        for key, unit, record in entries:
            each = menu.addMenu(session.name_of(unit, record.channel))
            for protocol, said in PROTOCOLS.items():
                each.addAction(
                    f"{said}...", lambda k=key, p=protocol: self.scope.ask_decoding(k, p)
                )

    # --- what they read --------------------------------------------------------------------
    def refresh(self) -> None:
        if not self.isVisible():
            return
        decodings = self._decodings()
        self._list_buses(decodings)
        if not decodings:
            self.over.setText(NOTHING_DECODED)
            if self.items.rows:
                self.items.show(Listed())
            self._shown = ()
            return
        # A paused bus is kept, but not listed.
        decodings = [(u, n, d) for u, n, d in decodings if not d.paused]
        t_from, t_to, cursors = self.scope.span()
        stretches = []
        for unit_name, name, decoding in decodings:
            origin = self.scope.origin_of(unit_name)
            rate = decoding.rate
            lo, hi = decoding.items.between(
                int(np.floor((t_from + origin) * rate)), int(np.ceil((t_to + origin) * rate))
            )
            bus = f"{PROTOCOLS[decoding.setup.protocol]} {name}"
            stretches.append(Stretch(decoding, bus, origin, lo, hi))
        shown = tuple((id(s.decoding), s.decoding.items.version, s.lo, s.hi) for s in stretches)
        where = "Between the cursors" if cursors else "In view"
        listed = sum(s.hi - s.lo for s in stretches)
        self.over.setText(f"{where}: {time_text(t_to - t_from)}, {listed:,} read")
        if shown == self._shown:
            return
        self._shown = shown
        rows = Listed(stretches)
        bar = self.table.verticalScrollBar()
        following = bar.value() >= bar.maximum()
        top = self.table.rowAt(0)
        kept = self.items.rows[top].seconds if 0 <= top < len(self.items.rows) else None
        self.items.show(rows)
        if following:
            self.table.scrollToBottom()
        elif kept is not None and rows:
            at = self.items.index(min(rows.near(kept), len(rows) - 1), 0)
            self.table.scrollTo(at, QAbstractItemView.PositionAtTop)

    def _summary(self, name: str, decoding: Decoding) -> str:
        setup = decoding.setup
        protocol = setup.protocol
        said = f"{PROTOCOLS[protocol]} on {name}"
        if protocol == CAN:
            said += f" ({SOURCES[setup.source].split(':')[0]})"
        if decoding.problem:
            return f"{said}: {decoding.problem}"
        if protocol == CAN:
            if decoding.bitrate is None:
                return f"{said}: finding the bit rate"
            said += f", {bitrate_text(decoding.bitrate)}"
        elif protocol == UART:
            said += f", {setup.baud} baud"
        elif protocol == SPI:
            said += f", mode {setup.mode}, {setup.bits}-bit words"
        elif protocol == PARALLEL:
            said += f", {setup.width} bits"
            if setup.clock:
                said += f", read on {setup.edge} edges"
            if setup.mux:
                said += ", channels A and B"
        found, wrong = len(decoding.items), decoding.errors()
        tail = f", {wrong:,} with problems" if wrong else ""
        if getattr(setup, "share", ""):
            tail += f", sent on to {setup.share}"
        return f"{said}: {found:,} read{tail}"

    def go_to(self, number: int) -> None:
        """Put the first cursor on a row's start, and bring it into view."""
        if 0 <= number < len(self.items.rows):
            self.scope.go_to(self.items.rows[number].seconds)

    def copy(self) -> None:
        rows = sorted(
            {
                row
                for stretch in self.table.selectionModel().selection()
                for row in range(stretch.top(), stretch.bottom() + 1)
            }
        )
        if not rows:
            return
        lines = ["\t".join(HEADINGS)]
        lines += ["\t".join(texts(self.items.rows[r])) for r in rows]
        QApplication.clipboard().setText("\n".join(lines) + "\n")
