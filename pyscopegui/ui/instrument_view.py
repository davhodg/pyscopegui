# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The Instrument pane: what the instrument chosen lets you set.

Built from the back end's own list of settings rather than written for each
instrument, so a new one gets its controls by describing them and every
instrument's look the same. The pane only says what was changed: saving it,
and deciding whether the instrument has to be started again, is the window's
business.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pyscopegui.backends.base import Setting

NOTHING = "This instrument has nothing to set."
RESTARTS = (
    "A change here starts the instrument again, from an empty plot, unless it is "
    "to the signal generator, which changes at once."
)


class InstrumentView(QWidget):
    #: Key, the new value, and whether it takes effect without a restart.
    changed = Signal(str, object, bool)

    def __init__(self) -> None:
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(6, 6, 6, 6)
        #: Setting key -> the control showing it.
        self.controls: dict[str, QComboBox | QDoubleSpinBox] = {}
        self.show_settings((), {})

    def show_settings(self, settings: tuple[Setting, ...], values: dict) -> None:
        """Show these settings, at the values saved for them or their defaults."""
        while (item := self._layout.takeAt(0)) is not None:
            if (widget := item.widget()) is not None:
                widget.deleteLater()
        self.controls = {}
        if not settings:
            self._layout.addWidget(QLabel(NOTHING))
            self._layout.addStretch()
            return
        forms: dict[str, QFormLayout] = {}
        for setting in settings:
            if setting.group not in forms:
                box = QGroupBox(setting.group)
                forms[setting.group] = QFormLayout(box)
                self._layout.addWidget(box)
            control = self._control(setting, values.get(setting.key, setting.default))
            control.setToolTip(setting.tip)
            self.controls[setting.key] = control
            forms[setting.group].addRow(setting.label + ":", control)
        note = QLabel(RESTARTS)
        note.setWordWrap(True)
        # As wide as the controls above it and no wider: a wrapped label asks
        # for the width of its whole text, and the pane grew a scroll bar for it.
        note.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._layout.addWidget(note)
        self._layout.addStretch()

    def _control(self, setting: Setting, value) -> QComboBox | QDoubleSpinBox:
        if setting.choices:
            box = QComboBox()
            for choice, label in setting.choices:
                box.addItem(label, choice)
            # A value that is not on the list -- from a hand-edited
            # settings.json -- is shown as the default, which is also what
            # the back end falls back to.
            index = box.findData(value)
            box.setCurrentIndex(index if index >= 0 else max(box.findData(setting.default), 0))
            # activated, not currentIndexChanged: only a choice somebody made.
            box.activated.connect(
                lambda _i, s=setting, b=box: self.changed.emit(s.key, b.currentData(), s.live)
            )
            return box
        spin = QDoubleSpinBox()
        spin.setDecimals(setting.decimals)
        spin.setRange(setting.minimum, setting.maximum)
        if setting.unit:
            spin.setSuffix(" " + setting.unit)
        try:
            spin.setValue(float(value))
        except (TypeError, ValueError):
            spin.setValue(float(setting.default))
        # Once the number is finished, not at every digit typed on the way.
        spin.setKeyboardTracking(False)
        spin.valueChanged.connect(lambda v, s=setting: self.changed.emit(s.key, v, s.live))
        return spin
