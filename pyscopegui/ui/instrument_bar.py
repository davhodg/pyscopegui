# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The toolbar: Add instrument, and the buttons Stop, Single, Normal and Auto.

Add instrument lists the kinds of instrument there are, and puts one more in
the Instrument pane, which is where each is then opened, set up and removed.
The same kind can be added twice: two scopes of one model are two instruments.

The four run buttons are a scope's own: whichever is pressed in is what the
instruments are doing, and they are for every one that is open. Read is
there for an instrument that is read as it is, with nothing on it changed:
it has no trigger here to wait for, so one reading of what it shows is asked
for by a button of its own.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QMenu, QToolBar, QToolButton

from pyscopegui import backends
from pyscopegui.core.acquire import AUTO, MODES, NORMAL, SINGLE, STOP
from pyscopegui.core.context import Context

ADD_TIP = (
    "Add an instrument to the Instrument pane, where it is opened and set up.\n"
    "Several can be in use at once, and two of the same kind.\n"
    "A maker's own library is not included: it has to be installed\n"
    "for its instrument to open."
)
READ_TIP = (
    "Read what the instrument shows, once, with nothing on it changed.\n"
    "Auto reads it over and over."
)
#: Said under Single and Normal when there is no trigger for them to wait for.
NO_TRIGGER_TIP = (
    "\n\nNot for an instrument read as it is, which has no trigger here to wait for:\n"
    "Read takes what it shows once, and Auto keeps reading it."
)
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
    #: The kind of instrument to add one more of: a back end's name.
    add_requested = Signal(str)
    #: One of the modes in pyscopegui.core.acquire.
    mode_requested = Signal(str)
    #: Read what the instrument chosen shows, once.
    read_requested = Signal()

    def __init__(self, ctx: Context) -> None:
        super().__init__("Instrument")
        self.setObjectName("instrument")  # saveState identifies toolbars by objectName
        self.setMovable(False)
        self._ctx = ctx

        self.add = QToolButton()
        self.add.setText("Add instrument")
        self.add.setToolTip(ADD_TIP)
        # The button is its list: a press of either part of it opens that.
        self.add.setPopupMode(QToolButton.MenuButtonPopup)
        self.add.clicked.connect(self.add.showMenu)
        self.kinds = QMenu(self.add)
        for name in backends.names():
            action = self.kinds.addAction(backends.title(name))
            action.setData(name)
            action.triggered.connect(lambda _on=False, n=name: self.add_requested.emit(n))
        self.add.setMenu(self.kinds)

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

        self.read = QToolButton()
        self.read.setText("Read")
        self.read.setToolTip(READ_TIP)
        self.read.clicked.connect(self.read_requested)

        self.addWidget(self.add)
        # Shown through its action, which is how a toolbar shows and hides
        # what is on it. Only for an instrument that is read as it is.
        self._read_action = self.addWidget(self.read)
        self._read_action.setVisible(False)
        # The four run buttons are made and answered for here, and shown in
        # the trigger toolbar's frame: they are how a trigger is waited for.
        self.set_mode(STOP)

    def add_kind(self, name: str) -> None:
        """Ask for one more instrument of this kind, as choosing it in the list does."""
        for action in self.kinds.actions():
            if action.data() == name:
                action.trigger()

    def set_reads(self, shown: bool, busy: bool = False) -> None:
        """Offer Read, for an instrument that is read as it is; not while it is reading."""
        self._read_action.setVisible(shown)
        self.read.setEnabled(not busy)

    def reads(self) -> bool:
        """Whether Read is offered."""
        return self._read_action.isVisible()

    def set_triggered(self, triggered: bool) -> None:
        """Whether there is a trigger for Single and Normal to wait for: there is
        none when every instrument they would run is read as it is."""
        for mode in (SINGLE, NORMAL):
            button = self.modes[mode]
            button.setEnabled(triggered)
            button.setToolTip(BUTTONS[mode][1] + ("" if triggered else NO_TRIGGER_TIP))

    def set_mode(self, mode: str) -> None:
        """Press in the button for what is being done, without asking for it again."""
        self.modes[mode if mode in self.modes else STOP].setChecked(True)

    def mode(self) -> str:
        return next(mode for mode, button in self.modes.items() if button.isChecked())
