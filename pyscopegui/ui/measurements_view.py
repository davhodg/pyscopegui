# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The Measurements pane: each channel's levels, and how often it repeats.

Measured between the plot's two cursors when there are two, and over what is
in view when there are not -- what the line above the table says -- and
again a few times a second, and as soon as a cursor is moved. What each
number is, and how the frequency is found, is in ``pyscopegui.core.measure``.

A logic channel has no levels worth a column: it is 0 or 1. Its frequency,
period and duty cycle are what is said of it.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from pyscopegui.backends.base import ANALOG
from pyscopegui.core.measure import Measured
from pyscopegui.ui import fonts
from pyscopegui.ui.column_widths import ColumnWidths
from pyscopegui.ui.scope_view import ScopeView, frequency_text, reading_width, time_text

#: How often the numbers are measured again while nothing is moved, at the most,
#: and less often where measuring takes long, so that it never takes more than
#: a share of the time.
MEASURE_MS = 250
#: Measuring takes no more than one part in this of the time between.
MEASURE_SHARE = 5
HEADINGS = ("Channel", "Min", "Max", "Peak to peak", "Mean", "RMS", "Frequency", "Period", "Duty")
NONE = "\u2014"
MEASURES_TIP = (
    "Each channel shown on the plot, measured between its two cursors -- or,\n"
    "with fewer, over what is in view. Frequency is found where the signal\n"
    "rises through the middle of its range, and needs two rising edges.\n"
    "While it runs, a long stretch is measured from a share of its samples, and\n"
    "the numbers are close; stopped, they are exact."
)


def amount(value: float, unit: str) -> str:
    """A level, in the unit that suits it: 0.0123 V -> "12.30 mV"."""
    size = abs(value)
    for scale, prefix in ((1.0, ""), (1e-3, "m"), (1e-6, "\u00b5")):
        if size >= scale or prefix == "\u00b5":
            return f"{value / scale:.4g} {prefix}{unit}".strip()
    return f"0 {unit}".strip()


def texts(measured: Measured | None, unit: str, analog: bool) -> list[str]:
    """A row of the table, past the channel's name."""
    if measured is None:
        return [""] * (len(HEADINGS) - 1)
    levels = (
        [amount(v, unit) for v in (measured.minimum, measured.maximum, measured.peak_to_peak)]
        + [amount(measured.mean, unit), amount(measured.rms, unit)]
        if analog
        else [""] * 5
    )
    repeats = [
        frequency_text(measured.frequency) if measured.frequency else NONE,
        time_text(measured.period) if measured.period else NONE,
        f"{measured.duty * 100:.1f} %" if measured.duty is not None else NONE,
    ]
    return levels + repeats


class MeasurementsView(QWidget):
    def __init__(self, scope: ScopeView) -> None:
        super().__init__()
        self.scope = scope
        self.over = QLabel()
        self.table = QTreeWidget()
        self.table.setHeaderLabels(list(HEADINGS))
        self.table.setRootIsDecorated(False)
        self.table.setUniformRowHeights(True)
        self.table.setToolTip(MEASURES_TIP)
        ctx = scope._ctx
        #: The numbers are as wide as the longest they get, so that they do
        #: not jump about four times a second as they change.
        self.widths = ColumnWidths(
            self.table,
            ctx.settings if ctx is not None else None,
            "measurements",
            fixed=dict.fromkeys(range(1, len(HEADINGS)), reading_width()),
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.over)
        layout.addWidget(self.table)
        self._timer = QTimer(self, interval=MEASURE_MS, timeout=self.refresh)
        self._timer.start()
        scope.cursors_moved.connect(self.refresh)

    def refresh(self) -> None:
        """Measure every channel shown again, if the pane is to be seen."""
        if not self.isVisible():
            return
        began = time.perf_counter()
        scope = self.scope
        t_from, t_to, cursors = scope.span()
        width = time_text(t_to - t_from)
        over = f"Between the cursors: {width}" if cursors else f"Over what is in view: {width}"
        close = False
        shown = scope.shown_channels()
        if self.table.topLevelItemCount() != len(shown):
            self.table.clear()
            for _key, _name in shown:
                item = QTreeWidgetItem([""] * len(HEADINGS))
                for column in range(1, len(HEADINGS)):
                    item.setFont(column, fonts.mono())
                    item.setTextAlignment(column, Qt.AlignRight | Qt.AlignVCenter)
                self.table.addTopLevelItem(item)
        for row, (key, name) in enumerate(shown):
            item = self.table.topLevelItem(row)
            unit, own = scope._owners[key]
            record = unit.capture.records.get(own)
            channel = record.channel if record is not None else None
            analog = channel is None or channel.kind == ANALOG
            measured = scope.measure(key)
            close = close or (measured is not None and not measured.exact)
            for column, text in enumerate(
                [name, *texts(measured, channel.unit if channel else "", analog)]
            ):
                if item.text(column) != text:
                    item.setText(column, text)
        self.over.setText(f"{over}, close while it runs" if close else over)
        took_ms = (time.perf_counter() - began) * 1000
        self._timer.setInterval(max(MEASURE_MS, round(MEASURE_SHARE * took_ms)))

    def row(self, name: str) -> dict[str, str]:
        """What the table says of a channel, by heading: for reading it back."""
        for index in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(index)
            if item.text(0) == name:
                return {heading: item.text(i) for i, heading in enumerate(HEADINGS)}
        raise KeyError(name)
