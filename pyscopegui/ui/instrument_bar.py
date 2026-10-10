# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The toolbar: which instrument, and Run.

One button that says what pressing it will do: Run while stopped, Stop while
running. The instrument cannot be changed while it is running, since what is
on the plot would no longer be what the list says.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QLabel, QToolBar, QToolButton

from pyscopegui import backends
from pyscopegui.core.context import Context

SETTING = "instrument.name"
RUN_TIP = "Start reading the instrument chosen, from an empty plot."
STOP_TIP = "Stop reading. What has been collected stays on the plot."


class InstrumentBar(QToolBar):
    #: The back end's name.
    run_requested = Signal(str)
    stop_requested = Signal()

    def __init__(self, ctx: Context) -> None:
        super().__init__("Instrument")
        self.setObjectName("instrument")  # saveState identifies toolbars by objectName
        self.setMovable(False)
        self._ctx = ctx

        self.instrument = QComboBox()
        for name in backends.names():
            self.instrument.addItem(backends.title(name), name)
        self.instrument.setToolTip(
            "Which instrument to read. A maker's own library is not included:\n"
            "install it, and its instrument is found here."
        )
        saved = ctx.settings.get(SETTING, backends.DEFAULT)
        if (index := self.instrument.findData(saved)) >= 0:
            self.instrument.setCurrentIndex(index)
        self.instrument.currentIndexChanged.connect(
            lambda _i: ctx.settings.set(SETTING, self.current())
        )

        self.run = QToolButton()
        self.run.setCheckable(True)
        self.run.toggled.connect(self._on_toggled)
        self.set_running(False)

        self.addWidget(QLabel(" Instrument: "))
        self.addWidget(self.instrument)
        self.addWidget(self.run)

    def current(self) -> str:
        return str(self.instrument.currentData())

    def _on_toggled(self, on: bool) -> None:
        if on:
            self.run_requested.emit(self.current())
        else:
            self.stop_requested.emit()

    def set_running(self, running: bool) -> None:
        """Show what is so, without asking for it again."""
        self.run.blockSignals(True)
        self.run.setChecked(running)
        self.run.blockSignals(False)
        self.run.setText("Stop" if running else "Run")
        self.run.setToolTip(STOP_TIP if running else RUN_TIP)
        self.instrument.setEnabled(not running)
