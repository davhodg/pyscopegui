# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The details of a trigger beyond its channel, edge and level: a window's
upper level, a pulse's width, a pattern's channels, a holdoff.

What is asked depends on the kind chosen on the toolbar; the holdoff is asked
of every kind. A time is typed as it is said -- 1 ms, 500 us, 2e-6 -- since a
trigger's times run from nanoseconds to seconds.
"""

from __future__ import annotations

import re
from dataclasses import replace

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from pyscopegui.core.triggers import (
    ALL,
    ANY,
    BETWEEN,
    DATA,
    EITHER,
    ENTER,
    GOOD,
    HIGH,
    KINDS,
    LEAVE,
    LONGER,
    LOW,
    NACK,
    PATTERN,
    PROBLEM,
    PROTOCOL,
    PULSE,
    READ,
    REMOTE,
    RUNT,
    SHORTER,
    TIMEOUT,
    WINDOW,
    WRITE,
    Condition,
    parse_data,
    parse_id,
)

#: A time as it is said, to seconds.
UNITS = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "µs": 1e-6, "ns": 1e-9}
#: A pattern channel's choices: either level, low, or high.
EITHER_LEVEL, WANTS_LOW, WANTS_HIGH = "X", "0", "1"
#: A protocol trigger's types, for each protocol that has them.
TYPES = {
    "can": ((ANY, "Any frame"), (DATA, "Data frames"), (REMOTE, "Remote frames")),
    "i2c": ((ANY, "Any transfer"), (READ, "Reads"), (WRITE, "Writes"), (NACK, "Nobody there")),
}
NO_BUS = (
    "No bus is decoded on this instrument. Right-click a channel in the plot's\n"
    "list and choose Decode as, then choose Protocol here."
)


def parse_time(text: str) -> float | None:
    """Seconds from "1 ms", "500us", "2e-6", "0.5 s"; None for anything else."""
    found = re.fullmatch(r"\s*([0-9.]+(?:e-?[0-9]+)?)\s*([a-zµ]*)\s*", text.strip().lower())
    if found is None:
        return None
    number, unit = found.groups()
    try:
        value = float(number)
    except ValueError:
        return None
    if unit and unit not in UNITS:
        return None
    return value * UNITS.get(unit or "s", 1.0)


def time_text(seconds: float) -> str:
    for scale, unit in ((1.0, "s"), (1e-3, "ms"), (1e-6, "µs"), (1e-9, "ns")):
        if seconds >= scale:
            return f"{seconds / scale:g} {unit}"
    return f"{seconds:g} s"


class TriggerDialog(QDialog):
    def __init__(
        self,
        condition: Condition,
        channels: list[tuple[str, str]],
        unit: str = "V",
        parent=None,
        buses: list[tuple[str, str, str]] = (),
    ) -> None:
        """``channels`` are the instrument's, as (key, what it is called), for a
        pattern; ``unit`` is the trigger channel's, for its levels; ``buses``
        its decoded buses, as (key, what to call it, protocol), for a protocol."""
        super().__init__(parent)
        self.setWindowTitle(f"Trigger: {KINDS[condition.kind]}")
        self._condition = condition
        self.form = QFormLayout()
        kind = condition.kind
        self.upper = self.direction = self.polarity = self.compare = None
        self.shortest = self.longest = self.held = None
        self.pattern: dict[str, QComboBox] = {}
        self.bus = self.match_type = self.match_id = self.match_data = self.which = None
        self._protocols = {key: protocol for key, _said, protocol in buses}
        if kind in (WINDOW, RUNT):
            self.upper = QDoubleSpinBox()
            self.upper.setRange(-1000.0, 1000.0)
            self.upper.setDecimals(3)
            self.upper.setSingleStep(0.05)
            self.upper.setSuffix(f" {unit}")
            self.upper.setValue(condition.upper)
            self.upper.setToolTip("The upper level. The toolbar's level is the lower.")
            self.form.addRow("Upper level:", self.upper)
        if kind == WINDOW:
            self.direction = self._choice(
                ((ENTER, "Entering the window"), (LEAVE, "Leaving it")), condition.direction
            )
            self.form.addRow("When:", self.direction)
        if kind in (PULSE, RUNT, TIMEOUT):
            choices = [(HIGH, "High"), (LOW, "Low")]
            if kind == TIMEOUT:
                choices.append((EITHER, "Either"))
            self.polarity = self._choice(choices, condition.polarity)
            self.form.addRow("Pulse:" if kind != TIMEOUT else "Staying:", self.polarity)
        if kind == PULSE:
            self.compare = self._choice(
                ((SHORTER, "Shorter than"), (LONGER, "Longer than"), (BETWEEN, "Between")),
                condition.compare,
            )
            self.form.addRow("Width:", self.compare)
        if kind in (PULSE, TIMEOUT):
            self.shortest = QLineEdit(time_text(condition.shortest))
            self.form.addRow("Time:" if kind == TIMEOUT else "", self.shortest)
        if kind == PULSE:
            self.longest = QLineEdit(time_text(condition.longest))
            self.form.addRow("and:", self.longest)
            self.compare.currentIndexChanged.connect(self._show_longest)
            self._show_longest()
        if kind == PATTERN:
            box = QGroupBox("Each channel at")
            grid = QGridLayout(box)
            wanted = dict(condition.pattern)
            for row, (key, name) in enumerate(channels):
                level = QComboBox()
                for value, said in ((EITHER_LEVEL, "either"), (WANTS_LOW, "0"), (WANTS_HIGH, "1")):
                    level.addItem(said, value)
                level.setCurrentIndex(
                    level.findData(EITHER_LEVEL if key not in wanted else str(wanted[key]))
                )
                grid.addWidget(QLabel(name), row, 0)
                grid.addWidget(level, row, 1)
                self.pattern[key] = level
            self.form.addRow(box)
            self.held = QLineEdit(time_text(condition.held) if condition.held else "0")
            self.held.setToolTip("Held at least this long before it counts: 0 for at once.")
            self.form.addRow("Held for:", self.held)
        if kind == PROTOCOL:
            self._protocol_rows(condition, buses)
        self.holdoff = QLineEdit(time_text(condition.holdoff) if condition.holdoff else "0")
        self.holdoff.setToolTip("After a trigger, none for this long: 0 for none.")
        self.form.addRow("Holdoff:", self.holdoff)
        self.problem = QLabel()
        self.problem.setStyleSheet("color: #d08000;")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(self.problem)
        layout.addWidget(buttons)

    def _protocol_rows(self, condition: Condition, buses) -> None:
        if not buses:
            self.form.addRow(QLabel(NO_BUS))
            return
        self.bus = QComboBox()
        for key, said, _protocol in buses:
            self.bus.addItem(said, key)
        self.bus.setCurrentIndex(max(self.bus.findData(condition.bus), 0))
        self.form.addRow("Bus:", self.bus)
        self.match_type = QComboBox()
        self.form.addRow("Type:", self.match_type)
        self.match_id = QLineEdit(condition.match_id)
        self.match_id.setPlaceholderText("any")
        self.match_id.setToolTip(
            "A CAN identifier, or an I\u00b2C address, in hex: X for a digit that\n"
            "may be anything -- 18FEXX00. Empty for any."
        )
        self.form.addRow("ID / address:", self.match_id)
        self.match_data = QLineEdit(condition.match_data)
        self.match_data.setPlaceholderText("anything")
        self.match_data.setToolTip(
            "Bytes it contains, anywhere, in hex: XX for one that may be anything --\n"
            '12 XX 34. Or text in quotes, for a serial line: "OK". Empty for anything.'
        )
        self.form.addRow("Data contains:", self.match_data)
        self.which = self._choice(
            ((ALL, "All of it"), (GOOD, "Only what was read cleanly"), (PROBLEM, "Only problems")),
            condition.which,
        )
        self.form.addRow("Which:", self.which)
        self.bus.currentIndexChanged.connect(lambda _i: self._show_types(ANY))
        self._show_types(condition.match_type)

    def _show_types(self, current: str) -> None:
        """The types the bus's protocol has, and the ID only where it has one."""
        protocol = self._protocols.get(self.bus.currentData(), "")
        self.match_type.clear()
        for value, said in TYPES.get(protocol, ((ANY, "Anything"),)):
            self.match_type.addItem(said, value)
        self.match_type.setCurrentIndex(max(self.match_type.findData(current), 0))
        self.match_type.setEnabled(protocol in TYPES)
        self.match_id.setEnabled(protocol in ("can", "i2c"))

    def _choice(self, choices, current: str) -> QComboBox:
        box = QComboBox()
        for value, said in choices:
            box.addItem(said, value)
        box.setCurrentIndex(max(box.findData(current), 0))
        return box

    def _show_longest(self, *_args) -> None:
        between = self.compare.currentData() == BETWEEN
        self.longest.setEnabled(between)

    def _times(self) -> dict[str, float] | str:
        """Each time typed, in seconds; or what is wrong with one."""
        found = {}
        for name, field in (
            ("shortest", self.shortest),
            ("longest", self.longest),
            ("held", self.held),
            ("holdoff", self.holdoff),
        ):
            if field is None or (name == "longest" and not field.isEnabled()):
                continue
            seconds = parse_time(field.text())
            if seconds is None:
                return f"{field.text()!r} is not a time: 1 ms, 500 us or 2e-6, say."
            found[name] = seconds
        if found.get("shortest") == 0.0:
            return "The time has to be more than nought."
        if "longest" in found and found["longest"] <= found["shortest"]:
            return "The second time has to be longer than the first."
        return found

    def accept(self) -> None:
        times = self._times()
        if isinstance(times, str):
            self.problem.setText(times)
            return
        if self.pattern and all(box.currentData() == EITHER_LEVEL for box in self.pattern.values()):
            self.problem.setText("Choose the level of one channel at least.")
            return
        if self._condition.kind == PROTOCOL:
            if self.bus is None:
                self.problem.setText("There is no bus to wait on.")
                return
            if parse_id(self.match_id.text()) is None:
                self.problem.setText("The ID is not hex: 123, or 18FEXX00, say.")
                return
            if parse_data(self.match_data.text()) is None:
                self.problem.setText('The data is not bytes: 12 XX 34, or "text", say.')
                return
        super().accept()

    def condition(self) -> Condition:
        times = self._times()
        changes = dict(times) if isinstance(times, dict) else {}
        for name, box in (
            ("direction", self.direction),
            ("polarity", self.polarity),
            ("compare", self.compare),
        ):
            if box is not None:
                changes[name] = box.currentData()
        if self.upper is not None:
            changes["upper"] = self.upper.value()
        if self.pattern:
            changes["pattern"] = tuple(
                (key, int(box.currentData()))
                for key, box in self.pattern.items()
                if box.currentData() != EITHER_LEVEL
            )
        if self.bus is not None:
            changes["bus"] = self.bus.currentData()
            changes["match_type"] = self.match_type.currentData()
            changes["match_id"] = self.match_id.text().strip()
            changes["match_data"] = self.match_data.text().strip()
            changes["which"] = self.which.currentData()
        return replace(self._condition, **changes)
