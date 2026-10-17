# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Making a maths channel: a channel, what to do with it, and another where it
takes two, of the same instrument."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from pyscopegui.core.maths import ONE, TWO, Maths
from pyscopegui.ui.trigger_dialog import parse_time, time_text

#: What each operation is called in the list, the two-channel ones first.
NAMES = {
    "+": "+  add",
    "-": "\u2212  take away",
    "*": "\u00d7  multiply",
    "/": "\u00f7  divide",
    "neg": "\u2212A  invert",
    "abs": "|A|  absolute value",
    "sq": "A\u00b2  square",
    "sqrt": "\u221aA  square root",
    "scale": "k\u00d7A + c  scale and offset",
    "ddt": "dA/dt  rate of change",
    "int": "\u222bA dt  integral",
    "avg": "Average  over a time",
}
EXPLAINED = (
    "A channel worked out from this instrument's, sample by sample: from two,\n"
    "or from one. It is drawn, measured and exported as any other."
)


class MathsDialog(QDialog):
    def __init__(self, channels: list[tuple[str, str]], first: str, parent=None) -> None:
        """``channels`` are (key, what it is called), of one instrument; ``first``
        is the one the dialog starts with."""
        super().__init__(parent)
        self.setWindowTitle("Maths channel")
        self.a, self.b = QComboBox(), QComboBox()
        for box in (self.a, self.b):
            for key, name in channels:
                box.addItem(name, key)
        self.a.setCurrentIndex(max(self.a.findData(first), 0))
        # The other one, to start with: a channel less itself is nought.
        others = [i for i in range(self.b.count()) if self.b.itemData(i) != first]
        self.b.setCurrentIndex(others[0] if others else 0)
        self.op = QComboBox()
        for op in TWO:
            self.op.addItem(NAMES[op], op)
        self.op.insertSeparator(self.op.count())
        for op in ONE:
            self.op.addItem(NAMES[op], op)
        if len(channels) < 2:
            # With one channel, only what is done to one.
            for op in TWO:
                self.op.model().item(self.op.findData(op)).setEnabled(False)
            self.op.setCurrentIndex(self.op.findData("neg"))
        else:
            self.op.setCurrentIndex(self.op.findData("-"))
        self.op.currentIndexChanged.connect(self._show_usable)
        row = QHBoxLayout()
        for widget in (self.a, self.op, self.b):
            row.addWidget(widget)
        # What a scale and an average need beyond a channel.
        self.k = QDoubleSpinBox(decimals=6, minimum=-1e9, maximum=1e9, value=1.0)
        self.c = QDoubleSpinBox(decimals=6, minimum=-1e9, maximum=1e9, value=0.0)
        self.unit = QLineEdit()
        self.unit.setPlaceholderText("the channel's own")
        self.unit.setToolTip("What it is measured in once scaled: A, say, for a current.")
        self.span = QLineEdit(time_text(1e-3))
        self.span.setToolTip("Each sample the mean of this long before it: 1 ms, 20 us, 2e-6.")
        self.scale_rows = QWidget()
        scale = QFormLayout(self.scale_rows)
        scale.setContentsMargins(0, 0, 0, 0)
        scale.addRow("Multiplied by (k):", self.k)
        scale.addRow("Then add (c):", self.c)
        scale.addRow("Measured in:", self.unit)
        self.span_rows = QWidget()
        spans = QFormLayout(self.span_rows)
        spans.setContentsMargins(0, 0, 0, 0)
        spans.addRow("Over:", self.span)
        self.problem = QLabel()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(EXPLAINED))
        layout.addLayout(row)
        layout.addWidget(self.scale_rows)
        layout.addWidget(self.span_rows)
        layout.addWidget(self.problem)
        layout.addWidget(buttons)
        self._show_usable()

    def _show_usable(self) -> None:
        op = self.op.currentData()
        self.b.setEnabled(op in TWO)
        self.scale_rows.setVisible(op == "scale")
        self.span_rows.setVisible(op == "avg")
        self.problem.clear()
        self.adjustSize()

    def accept(self) -> None:
        if self.op.currentData() == "avg" and not (parse_time(self.span.text()) or 0) > 0:
            self.problem.setText(f"{self.span.text()!r} is not a time: 1 ms or 20 us, say.")
            return
        super().accept()

    def maths(self) -> Maths:
        op = self.op.currentData()
        if op in TWO:
            return Maths(self.a.currentData(), op, self.b.currentData())
        if op == "scale":
            return Maths(
                self.a.currentData(), op, k=self.k.value(), c=self.c.value(), unit=self.unit.text()
            )
        if op == "avg":
            return Maths(self.a.currentData(), op, span=parse_time(self.span.text()) or 1e-3)
        return Maths(self.a.currentData(), op)
