# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Decoding a serial line, an SPI bus or an I2C bus: which channels are its
lines, and how it is set.

The lines are chosen from the instrument's own channels -- a bus's lines are
read together, so they have to be one instrument's -- starting from the
channel that was right-clicked, and guessing the others from their names:
SDA, MOSI, CS. An analog channel is read as logic at the threshold.

CAN has a dialog of its own: pyscopegui.ui.can_dialog.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from pyscopegui.core.decoding import LOGIC_THRESHOLD, I2cSetup, SpiSetup, UartSetup
from pyscopegui.core.uart_decode import BAUDS, EVEN, NONE, ODD

#: For a line that is not there: SPI's chip select, one of its data lines.
NO_LINE = "None"
THRESHOLD_TIP = (
    "Where low and high divide on an analog channel, in volts. 1.4 V suits\n"
    "both 3.3 V and 5 V logic. A logic channel is read as it is."
)
#: What each line is likely to be called, to start the dialog with it.
NAMES = {
    "sda": ("SDA",),
    "scl": ("SCL",),
    "sclk": ("SCLK", "SCK", "CLK"),
    "mosi": ("MOSI", "SDO", "DOUT", "COPI"),
    "miso": ("MISO", "SDI", "DIN", "CIPO"),
    "cs": ("CS", "SS", "NSS", "CE"),
}


class BusDialog(QDialog):
    """The lines of a bus, picked from an instrument's channels, and a threshold."""

    title = ""

    def __init__(self, channels: list[tuple[str, str, bool]], start: str, parent=None) -> None:
        """``channels`` are the instrument's: (its key, what it is called, whether
        it is analog). ``start`` is the one right-clicked."""
        super().__init__(parent)
        self.setWindowTitle(self.title)
        self._channels = channels
        self._start = start
        self._analog = {key: analog for key, _name, analog in channels}
        self.lines: dict[str, QComboBox] = {}
        self.form = QFormLayout()
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(-50.0, 50.0)
        self.threshold.setDecimals(2)
        self.threshold.setSingleStep(0.1)
        self.threshold.setSuffix(" V")
        self.threshold.setValue(LOGIC_THRESHOLD)
        self.threshold.setToolTip(THRESHOLD_TIP)
        self.problem = QLabel()
        self.problem.setStyleSheet("color: #d08000;")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(self.problem)
        layout.addWidget(buttons)

    # --- the lines -------------------------------------------------------------------------
    def add_line(self, role: str, label: str, optional: bool = False) -> QComboBox:
        box = QComboBox()
        if optional:
            box.addItem(NO_LINE, "")
        for key, name, _analog in self._channels:
            box.addItem(name, key)
        box.setCurrentIndex(max(box.findData(self._guess(role, optional)), 0))
        box.currentIndexChanged.connect(self._show_threshold)
        self.lines[role] = box
        self.form.addRow(f"{label}:", box)
        return box

    def _guess(self, role: str, optional: bool) -> str:
        """The channel this line most likely is: the one right-clicked for the
        first line, one called for it, or the next not taken."""
        if not self.lines:
            return self._start
        taken = {box.currentData() for box in self.lines.values()}
        for key, name, _analog in self._channels:
            if key not in taken and any(said in name.upper() for said in NAMES.get(role, ())):
                return key
        if optional:
            return ""
        keys = [key for key, _name, _analog in self._channels]
        after = keys.index(self._start) + 1 if self._start in keys else 0
        for key in keys[after:] + keys[:after]:
            if key not in taken:
                return key
        return self._start

    def line(self, role: str) -> str:
        return self.lines[role].currentData() or ""

    def add_threshold(self) -> None:
        self.form.addRow("Threshold:", self.threshold)
        self._show_threshold()

    def _show_threshold(self, *_args) -> None:
        self.threshold.setEnabled(
            any(self._analog.get(box.currentData(), False) for box in self.lines.values())
        )

    def chosen_threshold(self) -> float | None:
        """The threshold, or None where it is the usual."""
        value = round(self.threshold.value(), 3)
        return None if abs(value - LOGIC_THRESHOLD) < 1e-9 else value

    def show_setup(self, setup) -> None:
        """Start from how the bus is decoded already."""
        for role, box in self.lines.items():
            index = box.findData(getattr(setup, role))
            if index >= 0:
                box.setCurrentIndex(index)
        if setup.threshold is not None:
            self.threshold.setValue(setup.threshold)

    def accept(self) -> None:
        chosen = [self.line(role) for role in self.lines if self.line(role)]
        if len(chosen) != len(set(chosen)):
            self.problem.setText("Each line has to be a channel of its own.")
            return
        if problem := self.check():
            self.problem.setText(problem)
            return
        super().accept()

    def check(self) -> str:
        """What is wrong with what was chosen, or "" for nothing."""
        return ""


class UartDialog(BusDialog):
    title = "Decode as UART"

    def __init__(self, channels, start, setup: UartSetup | None = None, parent=None) -> None:
        super().__init__(channels, start, parent)
        self.add_line("line", "Line")
        self.baud = QComboBox()
        self.baud.setEditable(True)
        for baud in BAUDS:
            self.baud.addItem(f"{baud} baud", baud)
        self.baud.setCurrentIndex(self.baud.findData(115200))
        self.baud.setToolTip("Bits a second, as the line is set. One not listed can be typed.")
        self.bits = QSpinBox()
        self.bits.setRange(5, 9)
        self.bits.setValue(8)
        self.parity = QComboBox()
        for parity, said in ((NONE, "None"), (EVEN, "Even"), (ODD, "Odd")):
            self.parity.addItem(said, parity)
        self.stop_bits = QComboBox()
        for stop in (1, 1.5, 2):
            self.stop_bits.addItem(f"{stop:g}", stop)
        self.msb_first = QCheckBox("Most significant bit first")
        self.inverted = QCheckBox("Inverted: RS-232 at the connector")
        self.inverted.setToolTip(
            "Between the transceivers, an RS-232 line is the other way up:\n"
            "high when it rests. Tick this for a probe on the connector."
        )
        self.form.addRow("Baud:", self.baud)
        self.form.addRow("Data bits:", self.bits)
        self.form.addRow("Parity:", self.parity)
        self.form.addRow("Stop bits:", self.stop_bits)
        self.form.addRow(self.msb_first)
        self.form.addRow(self.inverted)
        self.add_threshold()
        if setup is not None:
            self.show_setup(setup)
            index = self.baud.findData(setup.baud)
            if index >= 0:
                self.baud.setCurrentIndex(index)
            else:
                self.baud.setEditText(str(setup.baud))
            self.bits.setValue(setup.bits)
            self.parity.setCurrentIndex(self.parity.findData(setup.parity))
            self.stop_bits.setCurrentIndex(self.stop_bits.findData(setup.stop_bits))
            self.msb_first.setChecked(setup.msb_first)
            self.inverted.setChecked(setup.inverted)

    def chosen_baud(self) -> int | None:
        index = self.baud.findText(self.baud.currentText())
        if index >= 0:
            return int(self.baud.itemData(index))
        text = self.baud.currentText().strip().lower().removesuffix("baud").strip()
        try:
            baud = round(float(text.removesuffix("k")) * (1000 if text.endswith("k") else 1))
        except ValueError:
            return None
        return baud if baud > 0 else None

    def check(self) -> str:
        return "" if self.chosen_baud() else "The baud rate is not one: 9600, or 115200, say."

    def setup(self) -> UartSetup:
        return UartSetup(
            self.line("line"),
            self.chosen_baud() or 115200,
            self.bits.value(),
            self.parity.currentData(),
            self.stop_bits.currentData(),
            self.msb_first.isChecked(),
            self.inverted.isChecked(),
            self.chosen_threshold(),
        )


class SpiDialog(BusDialog):
    title = "Decode as SPI"

    def __init__(self, channels, start, setup: SpiSetup | None = None, parent=None) -> None:
        super().__init__(channels, start, parent)
        self.add_line("sclk", "Clock")
        self.add_line("mosi", "MOSI", optional=True)
        self.add_line("miso", "MISO", optional=True)
        self.add_line("cs", "Chip select", optional=True)
        self.mode = QComboBox()
        for mode, said in (
            (0, "0: clock rests low, read rising"),
            (1, "1: clock rests low, read falling"),
            (2, "2: clock rests high, read falling"),
            (3, "3: clock rests high, read rising"),
        ):
            self.mode.addItem(said, mode)
        self.bits = QSpinBox()
        self.bits.setRange(1, 64)
        self.bits.setValue(8)
        self.bits.setSuffix(" bits a word")
        self.msb_first = QCheckBox("Most significant bit first")
        self.msb_first.setChecked(True)
        self.cs_active_low = QCheckBox("Chip select active low")
        self.cs_active_low.setChecked(True)
        self.form.addRow("Mode:", self.mode)
        self.form.addRow("Word:", self.bits)
        self.form.addRow(self.msb_first)
        self.form.addRow(self.cs_active_low)
        self.add_threshold()
        if setup is not None:
            self.show_setup(setup)
            self.mode.setCurrentIndex(self.mode.findData(setup.mode))
            self.bits.setValue(setup.bits)
            self.msb_first.setChecked(setup.msb_first)
            self.cs_active_low.setChecked(setup.cs_active_low)

    def check(self) -> str:
        if not (self.line("mosi") or self.line("miso")):
            return "Choose MOSI, MISO or both: there is nothing to read without them."
        return ""

    def setup(self) -> SpiSetup:
        return SpiSetup(
            self.line("sclk"),
            self.line("mosi"),
            self.line("miso"),
            self.line("cs"),
            self.mode.currentData(),
            self.bits.value(),
            self.msb_first.isChecked(),
            self.cs_active_low.isChecked(),
            self.chosen_threshold(),
        )


class I2cDialog(BusDialog):
    title = "Decode as I²C"

    def __init__(self, channels, start, setup: I2cSetup | None = None, parent=None) -> None:
        super().__init__(channels, start, parent)
        self.add_line("scl", "SCL")
        self.add_line("sda", "SDA")
        self.add_threshold()
        if setup is not None:
            self.show_setup(setup)

    def setup(self) -> I2cSetup:
        return I2cSetup(self.line("scl"), self.line("sda"), self.chosen_threshold())
