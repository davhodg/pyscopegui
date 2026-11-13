# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Decoding a serial line, an SPI bus, an I2C bus or a parallel bus: which
channels are its lines, and how it is set.

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

from pyscopegui.core.decoding import (
    CODINGS,
    LOGIC_THRESHOLD,
    I2cSetup,
    ParallelSetup,
    SpiSetup,
    UartSetup,
)
from pyscopegui.core.parallel_decode import BOTH, FALLING, RISING, SELECT
from pyscopegui.core.uart_decode import BAUDS, EVEN, NONE, ODD
from pyscopegui.ui import icons

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
    "clock": ("CLK", "CLOCK", "DCO", "STROBE"),
    "mux": ("MUX", "SEL", "DCS"),
    "enable": ("EN", "OE", "CS", "CE"),
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
        buttons = icons.on_buttons(QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel))
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


class ParallelDialog(BusDialog):
    """A parallel bus: its data lines, a run of the instrument's channels in
    their order -- D0 to D11, say -- and a clock, a multiplex line and an
    enable if it has them."""

    title = "Decode as parallel"

    def __init__(self, channels, start, setup: ParallelSetup | None = None, parent=None) -> None:
        super().__init__(channels, start, parent)
        self._keys = [key for key, _name, _analog in channels]
        self._names = {key: name for key, name, _analog in channels}
        self.first = QComboBox()
        for key, name, _analog in channels:
            self.first.addItem(name, key)
        self.first.setCurrentIndex(max(self.first.findData(start), 0))
        self.first.setToolTip("The first data line. The rest follow it in the instrument's order.")
        self.width = QSpinBox()
        self.width.setRange(1, min(32, max(len(channels), 1)))
        self.width.setValue(min(8, len(channels)))
        self.width.setSuffix(" lines")
        self.bit0_first = QCheckBox("The first line is bit 0, the least significant")
        self.bit0_first.setChecked(True)
        self.span = QLabel()
        self.form.addRow("First line:", self.first)
        self.form.addRow("Width:", self.width)
        self.form.addRow("", self.span)
        self.form.addRow(self.bit0_first)
        # Taken, so that the lines after it are not guessed to be the first.
        self.lines["first"] = self.first
        self.first.currentIndexChanged.connect(self._show)
        self.width.valueChanged.connect(self._show)
        self.bit0_first.toggled.connect(self._show)

        self.add_line("clock", "Clock", optional=True)
        self.edge = QComboBox()
        for edge, said in ((RISING, "Rising"), (FALLING, "Falling"), (BOTH, "Both")):
            self.edge.addItem(said, edge)
        self.edge.setToolTip(
            "The edges a word is read on: each as it was just before the edge, as a\n"
            "latch clocked by it would take it. Both, for a bus sending a word each\n"
            "half clock, such as a multiplexed ADC's."
        )
        self.form.addRow("Read on:", self.edge)
        self.settle = QDoubleSpinBox()
        self.settle.setRange(0.0, 1e6)
        self.settle.setDecimals(1)
        self.settle.setSuffix(" ns")
        self.settle.setSpecialValueText("Two samples")
        self.settle.setToolTip(
            "Without a clock, a word is read wherever the lines change and then hold\n"
            "still this long, so that lines changing a little apart are not read as\n"
            "words of their own."
        )
        self.form.addRow("Settle:", self.settle)

        self.add_line("mux", "Multiplex", optional=True)
        self.mux_kind = QComboBox()
        self.mux_kind.addItem("Channel select: low is A, high is B", SELECT)
        self.mux_kind.setToolTip(
            "What the multiplex line says. A channel select's level, as each word is\n"
            "read, says which of two channels it is from: an ADC sending both its\n"
            "channels on one bus, such as the AD9238. It may be the clock itself."
        )
        self.mux_swapped = QCheckBox("Swap A and B")
        self.form.addRow("It is:", self.mux_kind)
        self.form.addRow(self.mux_swapped)

        self.add_line("enable", "Enable", optional=True)
        self.enable_active_low = QCheckBox("Enable active low")
        self.enable_active_low.setChecked(True)
        self.form.addRow(self.enable_active_low)
        self.coding = QComboBox()
        for coding, said in CODINGS.items():
            self.coding.addItem(said, coding)
        self.coding.setToolTip(
            "How a word stands for a number: as it is, offset binary -- the middle\n"
            "code nought, as many ADCs send -- or two's complement."
        )
        self.form.addRow("Numbers:", self.coding)
        self.plot = QCheckBox("Show its words as channels on the plot")
        self.plot.setToolTip(
            "Each word held until the next, as a channel of the instrument: an ADC's\n"
            "samples, drawn beside the scope's own. With a multiplex line, a channel\n"
            "for A and one for B."
        )
        self.full_scale = QDoubleSpinBox()
        self.full_scale.setRange(0.0, 1000.0)
        self.full_scale.setDecimals(3)
        self.full_scale.setSingleStep(0.5)
        self.full_scale.setSuffix(" V")
        self.full_scale.setSpecialValueText("The numbers as they are")
        self.full_scale.setToolTip(
            "The span from the lowest word to the highest, in volts: an ADC's input\n"
            "span, 2 V peak to peak, say. Nought draws the numbers themselves."
        )
        self.form.addRow(self.plot)
        self.form.addRow("Full scale:", self.full_scale)
        self.plot.toggled.connect(self._show)
        self.add_threshold()
        for role in ("clock", "mux", "enable"):
            self.lines[role].currentIndexChanged.connect(self._show)
        if setup is not None:
            self._show_parallel(setup)
        self._show()

    def _show_parallel(self, setup: ParallelSetup) -> None:
        """Start from how the bus is decoded already."""
        ordered = list(setup.data)
        bit0_first = True
        if len(ordered) > 1 and self._is_run(ordered[::-1]) and not self._is_run(ordered):
            ordered, bit0_first = ordered[::-1], False
        self.first.setCurrentIndex(max(self.first.findData(ordered[0]), 0))
        self.width.setValue(len(ordered))
        self.bit0_first.setChecked(bit0_first)
        for role in ("clock", "mux", "enable"):
            box = self.lines[role]
            box.setCurrentIndex(max(box.findData(getattr(setup, role)), 0))
        self.edge.setCurrentIndex(max(self.edge.findData(setup.edge), 0))
        self.settle.setValue(setup.settle_s * 1e9)
        self.mux_kind.setCurrentIndex(max(self.mux_kind.findData(setup.mux_kind), 0))
        self.mux_swapped.setChecked(setup.mux_swapped)
        self.enable_active_low.setChecked(setup.enable_active_low)
        self.coding.setCurrentIndex(max(self.coding.findData(setup.coding), 0))
        self.plot.setChecked(setup.plot)
        self.full_scale.setValue(setup.full_scale)
        if setup.threshold is not None:
            self.threshold.setValue(setup.threshold)

    def _is_run(self, keys: list[str]) -> bool:
        """Whether these follow one another in the instrument's order."""
        if keys[0] not in self._keys:
            return False
        at = self._keys.index(keys[0])
        return self._keys[at : at + len(keys)] == keys

    def data_lines(self) -> list[str]:
        """The data lines in the instrument's order from the first, as many as
        the width; fewer where the instrument has run out."""
        first = self.first.currentData()
        at = self._keys.index(first) if first in self._keys else 0
        return self._keys[at : at + self.width.value()]

    def _show(self, *_args) -> None:
        names = [self._names[key] for key in self.data_lines()]
        if len(names) > 1:
            low, high = names[0], names[-1]
            if not self.bit0_first.isChecked():
                low, high = high, low
            self.span.setText(f"Bit 0 is {low}, bit {len(names) - 1} is {high}")
        else:
            self.span.setText(f"Bit 0 is {names[0]}" if names else "")
        clocked = bool(self.line("clock"))
        self.edge.setEnabled(clocked)
        self.settle.setEnabled(not clocked)
        muxed = bool(self.line("mux"))
        self.mux_kind.setEnabled(muxed)
        self.mux_swapped.setEnabled(muxed)
        self.enable_active_low.setEnabled(bool(self.line("enable")))
        self.full_scale.setEnabled(self.plot.isChecked())
        self._show_threshold()

    def _show_threshold(self, *_args) -> None:
        if not hasattr(self, "width"):
            return  # still being made
        used = [*self.data_lines(), *(self.line(r) for r in self.lines)]
        self.threshold.setEnabled(any(self._analog.get(key, False) for key in used if key))

    def accept(self) -> None:
        # Not BusDialog's: a multiplex line may be the clock itself.
        if problem := self.check():
            self.problem.setText(problem)
            return
        QDialog.accept(self)

    def check(self) -> str:
        data = self.data_lines()
        if len(data) < self.width.value():
            return (
                f"There are only {len(data)} channels from {self.first.currentText()} on: "
                "choose an earlier first line, or fewer."
            )
        clock, mux, enable = (self.line(role) for role in ("clock", "mux", "enable"))
        for role, key in (("clock", clock), ("multiplex line", mux), ("enable", enable)):
            if key and key in data:
                return f"The {role} is one of the data lines: choose another."
        if enable and enable in (clock, mux):
            return "The enable has to be a line of its own."
        return ""

    def setup(self) -> ParallelSetup:
        data = self.data_lines()
        if not self.bit0_first.isChecked():
            data = data[::-1]
        return ParallelSetup(
            tuple(data),
            self.line("clock"),
            self.edge.currentData(),
            round(self.settle.value() * 1e-9, 12),
            self.line("mux"),
            self.mux_kind.currentData(),
            self.mux_swapped.isChecked(),
            self.line("enable"),
            self.enable_active_low.isChecked(),
            self.coding.currentData(),
            self.chosen_threshold(),
            self.plot.isChecked(),
            round(self.full_scale.value(), 6) if self.plot.isChecked() else 0.0,
        )
