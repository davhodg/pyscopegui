# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The Decoded buses pane: everything read off the channels decoded -- CAN
frames, serial lines' characters, SPI and I2C transfers -- in one list.

A row for each, every bus's in the order they came, and the time each started
on the plot's axis. Clicking one puts the first cursor on it, and brings it
into view. One read wrong -- a stuff error, a parity error, a word cut short --
is a row of its own, said in red: what a bus did is the point, the bad as much
as the good.

The list follows the newest as they come, unless it has been scrolled up to
read; then it stays where it was put.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QLabel,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from pyscopegui.core.decoding import CAN, I2C, PROTOCOLS, SOURCES, SPI, UART, Decoding
from pyscopegui.ui import fonts
from pyscopegui.ui.can_dialog import bitrate_text
from pyscopegui.ui.column_widths import ColumnWidths
from pyscopegui.ui.scope_view import ScopeView

#: How often the list is read again while the pane is on screen, in milliseconds.
REFRESH_MS = 250
HEADINGS = ("Time (s)", "Bus", "ID / address", "Type", "Data", "ACK", "Problem")
TIME, BUS, ID, TYPE, DATA, ACK, PROBLEM = range(len(HEADINGS))
#: What is read wrong is said in.
WRONG = QColor("#d04040")
NOTHING_DECODED = (
    "No channel is decoded. Right-click a channel in the plot's list and choose Decode as."
)
DECODED_TIP = (
    "Everything read off the channels decoded. Click a row to put the first\n"
    "cursor on it. Select rows and press Ctrl+C to copy them."
)


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


class Items(QAbstractTableModel):
    """What was read, a row for each."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.rows: list[Row] = []
        self._font = fonts.mono()
        self._right = int(Qt.AlignRight | Qt.AlignVCenter)

    def show(self, rows: list[Row]) -> None:
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.over)
        layout.addWidget(self.table)
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

    def refresh(self) -> None:
        if not self.isVisible():
            return
        decodings = self._decodings()
        if not decodings:
            self.over.setText(NOTHING_DECODED)
            if self.items.rows:
                self.items.show([])
            self._shown = ()
            return
        self.over.setText("    |    ".join(self._summary(name, d) for _u, name, d in decodings))
        shown = tuple(
            (id(d), len(d.items), d.items[0].start if d.items else -1) for _u, _n, d in decodings
        )
        if shown == self._shown:
            return
        self._shown = shown
        rows = []
        for unit_name, name, decoding in decodings:
            origin = self.scope.origin_of(unit_name)
            rate = decoding.rate
            bus = f"{PROTOCOLS[decoding.setup.protocol]} {name}"
            rows += [Row(i.start / rate - origin, bus, decoding, i) for i in decoding.items]
        rows.sort(key=lambda row: row.seconds)
        bar = self.table.verticalScrollBar()
        following = bar.value() >= bar.maximum()
        top = self.table.rowAt(0)
        kept = self.items.rows[top].item if 0 <= top < len(self.items.rows) else None
        self.items.show(rows)
        if following:
            self.table.scrollToBottom()
        elif kept is not None:
            for number, row in enumerate(rows):
                if row.item is kept:
                    at = self.items.index(number, 0)
                    self.table.scrollTo(at, QAbstractItemView.PositionAtTop)
                    break

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
        rows = sorted({index.row() for index in self.table.selectionModel().selectedIndexes()})
        if not rows:
            return
        lines = ["\t".join(HEADINGS)]
        lines += ["\t".join(texts(self.items.rows[r])) for r in rows]
        QApplication.clipboard().setText("\n".join(lines) + "\n")
