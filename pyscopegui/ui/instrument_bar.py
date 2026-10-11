# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The toolbar: which instrument, Open, and Stop, Single, Normal and Auto.

Connecting to an instrument and reading it are two things. Open connects --
which for a scope is the slow part, done once -- and Close lets it go, so
that another program can have it. The four beside it are a scope's own:
whichever is pressed in is what it is doing.

More than one instrument can be open at once. The list chooses which of them
Open, the Instrument pane and the trigger toolbar are about, and says which
are open; the Open button says what pressing it will do to the one chosen,
Open or Close. Stop, Single, Normal and Auto are for every one that is open.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QComboBox, QLabel, QToolBar, QToolButton

from pyscopegui import backends
from pyscopegui.core.acquire import AUTO, MODES, NORMAL, SINGLE, STOP
from pyscopegui.core.context import Context

SETTING = "instrument.name"
OPEN_TIP = "Connect to the instrument chosen, ready to be run."
#: Said after an instrument's name in the list while it is open.
OPEN_MARK = "  (open)"
CLOSE_TIP = "Stop, and let go of the instrument, so that another program can use it."
#: Mode -> what its button says, and what it means.
BUTTONS = {
    STOP: ("Stop", "Stop reading. What has been collected stays on the plot."),
    SINGLE: (
        "Single",
        "Wait for one trigger, show what is either side of it, and stop.\n"
        "With no trigger chosen: read one plot's worth, and stop.",
    ),
    NORMAL: (
        "Normal",
        "Show each trigger as it comes, and hold the last one until the next.\n"
        "With no trigger chosen this is the same as Auto.",
    ),
    AUTO: (
        "Auto",
        "Show each trigger as it comes, and what there is anyway when none does.\n"
        "With no trigger chosen: the newest samples, as they arrive.",
    ),
}


class InstrumentBar(QToolBar):
    #: The back end's name.
    open_requested = Signal(str)
    close_requested = Signal()
    #: One of the modes in pyscopegui.core.acquire.
    mode_requested = Signal(str)

    def __init__(self, ctx: Context) -> None:
        super().__init__("Instrument")
        self.setObjectName("instrument")  # saveState identifies toolbars by objectName
        self.setMovable(False)
        self._ctx = ctx

        self.instrument = QComboBox()
        for name in backends.names():
            self.instrument.addItem(backends.title(name), name)
        self.instrument.setToolTip(
            "Which instrument Open, the Instrument pane and the trigger are about.\n"
            "Several can be open at once: choose another and open that too.\n"
            "A maker's own library is not included: it has to be installed\n"
            "for its instrument to open."
        )
        saved = ctx.settings.get(SETTING, backends.DEFAULT)
        if (index := self.instrument.findData(saved)) >= 0:
            self.instrument.setCurrentIndex(index)
        self.instrument.currentIndexChanged.connect(
            lambda _i: ctx.settings.set(SETTING, self.current())
        )

        self.open = QToolButton()
        self.open.setCheckable(True)
        self.open.clicked.connect(self._on_open_clicked)

        #: Mode -> its button. One of them is always pressed in.
        self.modes: dict[str, QToolButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for mode in MODES:
            text, tip = BUTTONS[mode]
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tip)
            button.setCheckable(True)
            # clicked, not toggled: only a press somebody made.
            button.clicked.connect(lambda _on=False, m=mode: self.mode_requested.emit(m))
            self._group.addButton(button)
            self.modes[mode] = button

        self.addWidget(QLabel(" Instrument: "))
        self.addWidget(self.instrument)
        self.addWidget(self.open)
        self.addSeparator()
        for button in self.modes.values():
            self.addWidget(button)
        self.set_open(False)
        self.set_mode(STOP)

    def current(self) -> str:
        return str(self.instrument.currentData())

    def _on_open_clicked(self, on: bool) -> None:
        if on:
            self.open_requested.emit(self.current())
        else:
            self.close_requested.emit()

    def set_open(self, is_open: bool) -> None:
        """Show what is so, without asking for it again."""
        self.open.setChecked(is_open)
        self.open.setText("Close" if is_open else "Open")
        self.open.setToolTip(CLOSE_TIP if is_open else OPEN_TIP)

    def mark_open(self, names: set[str]) -> None:
        """Say in the list which instruments are open."""
        for index in range(self.instrument.count()):
            name = self.instrument.itemData(index)
            text = backends.title(name) + (OPEN_MARK if name in names else "")
            if self.instrument.itemText(index) != text:
                self.instrument.setItemText(index, text)

    def set_mode(self, mode: str) -> None:
        """Press in the button for what is being done, without asking for it again."""
        self.modes[mode if mode in self.modes else STOP].setChecked(True)

    def mode(self) -> str:
        return next(mode for mode, button in self.modes.items() if button.isChecked())
