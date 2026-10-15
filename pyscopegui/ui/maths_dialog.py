# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Making a maths channel: one channel, what to do, and another, of the same instrument."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QVBoxLayout

from pyscopegui.core.maths import OPERATIONS, Maths

NAMES = {"+": "+  add", "-": "\u2212  take away", "*": "\u00d7  multiply", "/": "\u00f7  divide"}


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
        for op in OPERATIONS:
            self.op.addItem(NAMES[op], op)
        self.op.setCurrentIndex(self.op.findData("-"))
        row = QHBoxLayout()
        for widget in (self.a, self.op, self.b):
            row.addWidget(widget)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "A channel worked out from two of this instrument's, sample by sample.\n"
                "It is drawn, measured and exported as any other."
            )
        )
        layout.addLayout(row)
        layout.addWidget(buttons)

    def maths(self) -> Maths:
        return Maths(self.a.currentData(), self.op.currentData(), self.b.currentData())
