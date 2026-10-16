# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Decoding a channel as a CAN bus: what is on it, how fast, and where its levels divide."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from pyscopegui.core.can_decode import BITRATES
from pyscopegui.core.decoding import (
    CAN_H,
    CAN_L,
    DIFFERENTIAL,
    LOGIC,
    SOURCES,
    THRESHOLDS,
    CanSetup,
)
from pyscopegui.core.sharing import GROUP, is_group

AUTOMATIC = "Found from the signal"
SOURCE_TIP = (
    "What the channel is on. A logic input or a probe on a transceiver's RX\n"
    "pin is a logic level. On the bus itself, CAN_H less CAN_L is the one to\n"
    "use: make it a maths channel of the two, and decode that."
)
BITRATE_TIP = (
    "The bus's bit rate. Found from the signal, it is worked out from the\n"
    "shortest pulses once there are enough of them. Each bit needs a few\n"
    "samples at least: 500 kbit/s wants 5 MS/s or more."
)
SHARE_TIP = (
    "Send each frame on, as it is decoded, by UDP multicast: pycangui hears\n"
    "239.74.163.10 as a channel called pyscopegui, and any other python-can\n"
    "program can join it. It stays on this computer unless Tools > Settings\n"
    "says to share UDP multicast on the local network."
)
THRESHOLD_TIP = (
    "Where dominant and recessive divide, in volts. The signal has to go\n"
    "a tenth of a volt past it either way to change, so that noise on a\n"
    "slow edge is not read as bits."
)


def bitrate_text(bits: float) -> str:
    """500000 -> "500 kbit/s"."""
    if bits >= 1e6:
        return f"{bits / 1e6:g} Mbit/s"
    return f"{bits / 1e3:g} kbit/s"


def source_for(channel: str, name: str, analog: bool) -> str:
    """What a channel is most likely to be, to start the dialog with."""
    if not analog:
        return LOGIC
    said = f"{channel} {name}".upper()
    if channel.startswith("maths:") and "-" in channel:
        return DIFFERENTIAL
    if "CAN_L" in said or "CANL" in said:
        return CAN_L
    return CAN_H if "CAN_H" in said or "CANH" in said else DIFFERENTIAL


class CanDialog(QDialog):
    def __init__(
        self, channel: str, name: str, analog: bool, setup: CanSetup | None = None, parent=None
    ) -> None:
        """``channel`` is the instrument's own key for it, and ``name`` what it is
        called; ``setup`` is how it is decoded already, if it is."""
        super().__init__(parent)
        self.setWindowTitle("Decode as CAN")
        self._channel = channel
        self.source = QComboBox()
        for source, said in SOURCES.items():
            if (source == LOGIC) != analog:
                self.source.addItem(said, source)
        self.source.setToolTip(SOURCE_TIP)
        self.bitrate = QComboBox()
        self.bitrate.setEditable(True)
        self.bitrate.addItem(AUTOMATIC, 0)
        for bits in BITRATES:
            self.bitrate.addItem(bitrate_text(bits), bits)
        self.bitrate.setToolTip(BITRATE_TIP)
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(-50.0, 50.0)
        self.threshold.setDecimals(2)
        self.threshold.setSingleStep(0.1)
        self.threshold.setSuffix(" V")
        self.threshold.setToolTip(THRESHOLD_TIP)
        self.threshold.setEnabled(analog)
        self.source.currentIndexChanged.connect(self._usual_threshold)
        self.share = QCheckBox("Send the frames on to pycangui")
        self.share.setToolTip(SHARE_TIP)
        self.group = QLineEdit(GROUP)
        self.group.setToolTip(
            "The multicast group they are sent to. pycangui offers 239.74.163.10;\n"
            "a second bus would go to another, 239.74.163.11 say."
        )
        self.share.toggled.connect(self.group.setEnabled)
        self.group.setEnabled(False)

        chosen = setup.source if setup is not None else source_for(channel, name, analog)
        self.source.setCurrentIndex(max(self.source.findData(chosen), 0))
        self._usual_threshold()
        if setup is not None:
            index = self.bitrate.findData(setup.bitrate)
            if index >= 0:
                self.bitrate.setCurrentIndex(index)
            else:
                self.bitrate.setEditText(bitrate_text(setup.bitrate))
            if setup.threshold is not None:
                self.threshold.setValue(setup.threshold)
            if setup.share:
                self.share.setChecked(True)
                self.group.setText(setup.share)

        form = QFormLayout()
        form.addRow("Channel:", QLabel(name))
        form.addRow("It is:", self.source)
        form.addRow("Bit rate:", self.bitrate)
        form.addRow("Threshold:", self.threshold)
        form.addRow(self.share)
        form.addRow("Group:", self.group)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.problem = QLabel()
        self.problem.setStyleSheet("color: #d08000;")
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.problem)
        layout.addWidget(buttons)

    def _usual_threshold(self, *_args) -> None:
        source = self.source.currentData()
        if source in THRESHOLDS:
            self.threshold.setValue(THRESHOLDS[source])

    def chosen_bitrate(self) -> int | None:
        """The bit rate chosen, nought for found from the signal, or None for
        something typed that is not one."""
        index = self.bitrate.findText(self.bitrate.currentText())
        if index >= 0:
            return int(self.bitrate.itemData(index))
        text = self.bitrate.currentText().strip().lower().replace(" ", "")
        scale = 1
        for unit, times in (("mbit/s", 1e6), ("kbit/s", 1e3), ("bit/s", 1), ("m", 1e6), ("k", 1e3)):
            if text.endswith(unit):
                text, scale = text[: -len(unit)], times
                break
        try:
            bits = round(float(text) * scale)
        except ValueError:
            return None
        return bits if bits > 0 else None

    def accept(self) -> None:
        if self.chosen_bitrate() is None:
            self.problem.setText("The bit rate is not one: 500k, or 250 kbit/s, say.")
            return
        if self.share.isChecked() and not is_group(self.group.text()):
            self.problem.setText("The group is not a multicast address: 239.74.163.10, say.")
            return
        super().accept()

    def setup(self) -> CanSetup:
        source = self.source.currentData()
        threshold = None
        if source in THRESHOLDS and abs(self.threshold.value() - THRESHOLDS[source]) > 1e-9:
            threshold = round(self.threshold.value(), 3)
        share = self.group.text().strip() if self.share.isChecked() else ""
        return CanSetup(self._channel, source, self.chosen_bitrate() or 0, threshold, share)
