# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The Instrument pane: the instruments in use, and what the one chosen lets you set.

Built from the back end's own list of settings rather than written for each
instrument, so a new one gets its controls by describing them and every
instrument's look the same. The pane only says what was changed: saving it,
and deciding whether the instrument has to be started again, is the window's
business.

A scope's channels all have the same settings, and four of them one under
another is a pane to scroll through. So they are shown one at a time, under
a row of tabs. How every channel is set is read in the plot's channel list,
all at once; clicking one there brings its settings up here.

There is a tab for each instrument across the top: the one chosen is the one
the settings, Open and the trigger toolbar are about, and the cross on a tab
removes its instrument. Open is at the end of that row; while the instrument
is open the same button closes it, and what says how it is reached is greyed
out until it does.

A pane is narrow, so it shows no more than has a say: a setting that has
none while another is as it is -- a block's length while streaming, a
generator's frequency while it is off -- is not shown until it does. Two
that go together share a line: a port of logic inputs and its threshold.
Each channel's Enabled is on the line with the channels' tabs.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from pyscopegui.backends.base import Setting
from pyscopegui.ui.spin import SequenceSpin

NOTHING = "This instrument has nothing to set."
NONE_ADDED = "No instrument. Add instrument, on the toolbar, puts one here."
#: Behind what has been typed and not yet taken up: Enter, or leaving the
#: box, takes it up. The amber pycangui uses for the same thing.
PENDING = "QLineEdit { background-color: rgba(230, 150, 0, 70); }"
#: Added to the tip of a setting that is not taken up as the instrument runs.
RESTARTS = "A change starts a run again, from an empty plot."
#: What a group's heading starts with when it is one channel's settings.
CHANNEL = "Channel "
#: A channel's tick for whether it is read, shown on the line with its tab.
ENABLED = "Enabled"
#: The group that says how an instrument is reached, where Open is.
CONNECTION = "Connection"
OPEN_TIP = "Connect to this instrument, ready to be run."
CLOSE_TIP = (
    "Stop, and let go of this instrument, so that another program can use it.\n"
    "What says how it is reached can be changed once it is closed."
)
#: On an instrument's tab while it is open: a dot, since a pane is narrow
#: and a word on every tab would have three of them scrolling.
OPEN_MARK = " \u25cf"
OPEN_SAID, CLOSED_SAID = "Open.", "Not open."
REMOVE_TIP = "The cross closes this instrument and takes it out of the pane."


def _nearest_index(choices: tuple, value: object) -> int:
    """Where the nearest number on the list is, for a number not on it: a
    scale saved through one probe, with another on the channel now. -1 for
    anything else."""
    numbers = [
        (i, choice)
        for i, (choice, _label) in enumerate(choices)
        if isinstance(choice, int | float) and not isinstance(choice, bool)
    ]
    if isinstance(value, bool) or not isinstance(value, int | float) or not numbers:
        return -1
    return min(numbers, key=lambda pair: abs(pair[1] - value))[0]


class Picker(QComboBox):
    """A box to type in, with a list of what was found when the list is opened.

    For naming one of several instruments that are plugged in: the list is
    made each time it is opened, so that one plugged in a moment ago is in it.
    """

    def __init__(self, setting: Setting, text: str) -> None:
        super().__init__()
        self._setting = setting
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.lineEdit().setPlaceholderText(setting.empty)
        self.setEditText(text)

    def fill(self) -> None:
        """List what there is now, with what leaving it empty means first."""
        text = self.currentText()
        self.blockSignals(True)
        self.clear()
        self.addItem(self._setting.empty or "(none)", "")
        try:
            found = self._setting.found() if self._setting.found is not None else []
        except Exception:  # a list that cannot be made is an empty one
            found = []
        for value, label in found:
            self.addItem(label, value)
        self.setCurrentIndex(-1)
        self.setEditText(text)
        self.blockSignals(False)

    def showPopup(self) -> None:
        self.fill()
        super().showPopup()


class InstrumentView(QWidget):
    #: Key, the new value, and whether it takes effect without a restart.
    changed = Signal(str, object, bool)
    #: Another instrument's tab was pressed: its name.
    instrument_chosen = Signal(str)
    #: The cross on an instrument's tab was pressed: its name.
    instrument_removed = Signal(str)
    #: Open, or Close, was pressed for the instrument chosen.
    open_requested = Signal()
    close_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        #: One tab for each instrument in use.
        self.instruments = QTabBar()
        self.instruments.setExpanding(False)
        self.instruments.setDrawBase(False)
        self.instruments.setToolTip(
            "The instruments in use. The settings below, Open and the trigger\n"
            "toolbar are about the one chosen here. Add instrument, on the\n"
            "toolbar, puts another here."
        )
        self.instruments.currentChanged.connect(self._on_instrument)
        self.instruments.tabCloseRequested.connect(self._on_removed)
        #: Opens the instrument chosen, and closes it while it is open: at the
        #: end of the line of instruments' tabs.
        self.open = QPushButton()
        self.open.clicked.connect(self._on_open_pressed)
        top = QHBoxLayout()
        top.addWidget(self.instruments)
        top.addStretch()
        top.addWidget(self.open)
        outer.addLayout(top)
        inner = QWidget()
        outer.addWidget(inner, 1)
        #: What is shown of the instrument chosen, rebuilt when another is.
        self._layout = QVBoxLayout(inner)
        self._layout.setContentsMargins(0, 0, 0, 0)
        #: Setting key -> the control showing it.
        self.controls: dict[str, QCheckBox | QComboBox | QDoubleSpinBox | QLineEdit] = {}
        self._settings: tuple[Setting, ...] = ()
        self._forms: dict[str, QFormLayout] = {}
        #: Setting key -> (its form, what is in the field of its line), for a
        #: setting with a line of its own: shown, or not, a line at a time.
        self._rows: dict[str, tuple[QFormLayout, QWidget]] = {}
        #: A setting shown beside another -> what says what it is, if anything;
        #: and the lines with one whose name is not shown, not lined up.
        self._beside: dict[str, QLabel | None] = {}
        self._unnamed: list[QWidget] = []
        #: The tabs, one for each channel, the settings under them, and each
        #: channel's Enabled, beside the tabs.
        self.tabs: QTabBar | None = None
        self._pages: QStackedWidget | None = None
        self._ticks: QStackedWidget | None = None
        #: Channel group -> which tab is its.
        self._tab_of: dict[str, int] = {}
        #: The channel last looked at, kept when the settings are shown again.
        self._group = ""
        #: Whether the instrument is open: how it is reached cannot be changed then.
        self._open = False
        self.changed.connect(self._show_needed)
        self.show_settings((), {})

    def set_instruments(self, listed: list[tuple[str, str, str, bool]], chosen: str) -> None:
        """Show these instruments as tabs -- (name, what to call it, what it is
        in full, whether it is open) -- with this one chosen. Any of them can
        be taken out, the last one too."""
        bar = self.instruments
        bar.blockSignals(True)
        while bar.count():
            bar.removeTab(0)
        bar.setTabsClosable(True)
        for name, short, title, is_open in listed:
            index = bar.addTab(short + (OPEN_MARK if is_open else ""))
            bar.setTabData(index, name)
            tip = f"{title}\n{OPEN_SAID if is_open else CLOSED_SAID}"
            bar.setTabToolTip(index, f"{tip}\n{REMOVE_TIP}")
            if name == chosen:
                bar.setCurrentIndex(index)
        bar.blockSignals(False)

    def listed(self) -> list[str]:
        """The instruments there are tabs for, by name, in order."""
        return [self.instruments.tabData(i) for i in range(self.instruments.count())]

    def _on_instrument(self, index: int) -> None:
        if (name := self.instruments.tabData(index)) is not None:
            self.instrument_chosen.emit(name)

    def _on_removed(self, index: int) -> None:
        if (name := self.instruments.tabData(index)) is not None:
            self.instrument_removed.emit(name)

    def _on_open_pressed(self) -> None:
        (self.close_requested if self._open else self.open_requested).emit()

    def _show_open(self) -> None:
        self.open.setText("Close" if self._open else "Open")
        self.open.setToolTip(CLOSE_TIP if self._open else OPEN_TIP)

    def show_settings(self, settings: tuple[Setting, ...], values: dict) -> None:
        """Show these settings, at the values saved for them or their defaults."""
        self._clear(settings)
        self.open.show()
        self._show_open()
        forms = self._forms
        if not settings:
            self._layout.addWidget(QLabel(NOTHING))
            self._layout.addStretch()
            return
        # How it is reached first, if there is anything to say: it is
        # connected to before it is set up.
        if any(setting.group == CONNECTION for setting in settings):
            forms[CONNECTION] = self._form(CONNECTION)
        partners = {setting.beside: setting for setting in settings if setting.beside}
        for setting in settings:
            if setting.beside:
                continue  # made with the one it is beside
            if setting.group not in forms:
                forms[setting.group] = self._form(setting.group)
            control = self._made(setting, values)
            form = forms[setting.group]
            partner = partners.get(setting.key)
            if partner is None and self._on_tab_line(setting, control):
                continue
            field = control
            if partner is not None:
                field = self._side_by_side(control, partner, values)
            if isinstance(control, QCheckBox):
                form.addRow(field)  # it carries its own label
            else:
                form.addRow(setting.label + ":", field)
            self._rows[setting.key] = (form, field)
        self._line_up()
        self._layout.addStretch()
        self.select_group(self._group)
        self._show_needed()

    def _line_up(self) -> None:
        """In each box, the first of each pair of settings sharing a line as
        wide as the widest of them, so that what is beside them lines up. Not
        where what is beside one has no name to line up: its unit says it."""
        firsts: dict[int, list[QWidget]] = {}
        for form, field in self._rows.values():
            if field not in self.controls.values() and field not in self._unnamed:
                firsts.setdefault(id(form), []).append(field.layout().itemAt(0).widget())
        for widgets in firsts.values():
            widest = max(widget.sizeHint().width() for widget in widgets)
            for widget in widgets:
                widget.setMinimumWidth(widest)

    def _made(self, setting: Setting, values: dict):
        """The control for a setting, at the value saved for it, with its tip."""
        control = self._control(setting, values.get(setting.key, setting.default))
        tip = setting.tip
        if not setting.live and not isinstance(control, QLineEdit | Picker):
            tip = f"{tip}\n{RESTARTS}" if tip else RESTARTS
        control.setToolTip(tip)
        self.controls[setting.key] = control
        return control

    def _side_by_side(self, control: QWidget, partner: Setting, values: dict) -> QWidget:
        """A setting and the one shown beside it, on one line."""
        field = QWidget()
        line = QHBoxLayout(field)
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(control)
        other = self._made(partner, values)
        label = None
        if partner.named and not isinstance(other, QCheckBox):
            label = QLabel(partner.label + ":")
            line.addWidget(label)
        elif not partner.named:
            self._unnamed.append(field)
        line.addWidget(other, 1)
        self._beside[partner.key] = label
        return field

    def _on_tab_line(self, setting: Setting, control: QWidget) -> bool:
        """Put a channel's Enabled on the line with the channels' tabs, if this
        is it: whether it was."""
        if not (
            setting.group.startswith(CHANNEL)
            and setting.label == ENABLED
            and isinstance(control, QCheckBox)
            and self._ticks is not None
        ):
            return False
        index = self._tab_of[setting.group]
        placeholder = self._ticks.widget(index)
        self._ticks.insertWidget(index, control)
        self._ticks.removeWidget(placeholder)
        placeholder.deleteLater()
        self._ticks.setCurrentIndex(self.tabs.currentIndex())
        return True

    def show_none(self) -> None:
        """Say there is no instrument, with nothing to set and nothing to open."""
        self._clear(())
        self.open.hide()
        self._layout.addWidget(QLabel(NONE_ADDED))
        self._layout.addStretch()

    def _clear(self, settings: tuple[Setting, ...]) -> None:
        """Throw away what is shown, ready for these settings."""
        while (item := self._layout.takeAt(0)) is not None:
            if (widget := item.widget()) is not None:
                # Out of sight now: it is not deleted until the event loop gets to it.
                widget.setParent(None)
                widget.deleteLater()
        self.controls = {}
        self._settings, self._forms, self._rows, self._beside = settings, {}, {}, {}
        self._unnamed = []
        self.tabs, self._pages, self._ticks, self._tab_of = None, None, None, {}

    def _form(self, group: str) -> QFormLayout:
        """Somewhere to list a group's settings: a box of its own, or for a
        channel, a tab beside the other channels'."""
        if not group.startswith(CHANNEL):
            box = QGroupBox(group)
            self._layout.addWidget(box)
            return QFormLayout(box)
        if self.tabs is None:
            box = QGroupBox(CHANNEL.strip())
            column = QVBoxLayout(box)
            self.tabs = QTabBar()
            self.tabs.setExpanding(False)
            self.tabs.setDrawBase(False)
            self.tabs.setToolTip(
                "Which channel's settings are below. How every channel is set is\n"
                "in the plot's channel list: click one there to bring it up here."
            )
            self._pages = QStackedWidget()
            self._ticks = QStackedWidget()
            self.tabs.currentChanged.connect(self._on_tab)
            line = QHBoxLayout()
            line.addWidget(self.tabs)
            line.addStretch()
            line.addWidget(self._ticks)
            column.addLayout(line)
            column.addWidget(self._pages)
            self._layout.addWidget(box)
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 6, 0, 0)
        self._pages.addWidget(page)
        self._ticks.addWidget(QWidget())  # until its Enabled, if it has one
        self._tab_of[group] = self.tabs.addTab(group[len(CHANNEL) :])
        return form

    def _on_tab(self, index: int) -> None:
        self._pages.setCurrentIndex(index)
        self._ticks.setCurrentIndex(index)
        self._group = next((g for g, i in self._tab_of.items() if i == index), self._group)

    def select_group(self, group: str) -> None:
        """Bring this channel's settings up, if there is such a channel."""
        if self.tabs is not None and group in self._tab_of:
            self.tabs.setCurrentIndex(self._tab_of[group])

    def _show_pending(self, line: QLineEdit) -> None:
        waiting = line.text().strip() != line.property("taken")
        line.setStyleSheet(PENDING if waiting else "")

    def _take_text(self, setting: Setting, line: QLineEdit) -> None:
        text = line.text().strip()
        if text == line.property("taken"):
            return  # Enter and then leaving the box both say it is finished
        line.setProperty("taken", text)
        self._show_pending(line)
        self.changed.emit(setting.key, text, setting.live)

    def _pick(self, setting: Setting, picker: Picker, value: object) -> None:
        picker.setEditText(value if isinstance(value, str) else "")
        self._take_text(setting, picker.lineEdit())

    def commit(self) -> None:
        """Take up anything typed and still waiting: before the instrument is opened or run."""
        for control in self.controls.values():
            if isinstance(control, QLineEdit):
                control.editingFinished.emit()
            elif isinstance(control, Picker):
                control.lineEdit().editingFinished.emit()
            elif isinstance(control, QDoubleSpinBox):
                control.interpretText()

    def value(self, key: str) -> object:
        """What the control for this setting is at."""
        control = self.controls[key]
        if isinstance(control, QCheckBox):
            return control.isChecked()
        if isinstance(control, Picker):
            return control.currentText().strip()
        if isinstance(control, QComboBox):
            return control.currentData()
        if isinstance(control, QLineEdit):
            return control.text()
        return control.value()

    def set_open(self, is_open: bool) -> None:
        """Say whether the instrument is open: what says how it is reached is
        greyed out while it is, since it was used to open it."""
        if is_open != self._open:
            self._open = is_open
            self._show_needed()
        self._show_open()

    def _show_needed(self, *_changed) -> None:
        """Show only what has a say: not what has none while another setting is
        as it is, nor what needs a setting that is not shown. What says how
        the instrument is reached is greyed out while it is open."""
        hidden: set[str] = set()
        for setting in self._settings:
            shown = True
            for rule, wanted in ((setting.needs, True), (setting.unless, False)):
                if rule is not None and rule[0] in self.controls:
                    key, value = rule
                    shown = shown and (self.value(key) == value) == wanted and key not in hidden
            if not shown:
                hidden.add(setting.key)
            control = self.controls[setting.key]
            on = shown and not (setting.closed and self._open)
            control.setEnabled(on)
            if setting.key in self._rows:
                form, field = self._rows[setting.key]
                form.setRowVisible(field, shown)
                if (label := form.labelForField(field)) is not None:
                    label.setEnabled(on)
            elif setting.key in self._beside:
                control.setVisible(shown)
                if (label := self._beside[setting.key]) is not None:
                    label.setVisible(shown)
                    label.setEnabled(on)

    def _control(
        self, setting: Setting, value
    ) -> QCheckBox | QComboBox | QDoubleSpinBox | QLineEdit:
        if isinstance(setting.default, bool) and not setting.choices:
            # On or off is a tick, not a list of two to open and choose from.
            tick = QCheckBox(setting.label)
            # Anything saved that is not a yes or a no is the default.
            tick.setChecked(value if isinstance(value, bool) else setting.default)
            # clicked, not toggled: only a change somebody made.
            tick.clicked.connect(lambda on, s=setting: self.changed.emit(s.key, bool(on), s.live))
            return tick
        if setting.choices:
            box = QComboBox()
            for choice, label in setting.choices:
                box.addItem(label, choice)
            # A value that is not on the list -- from a hand-edited
            # settings.json -- is shown as the default, which is also what
            # the back end falls back to.
            index = box.findData(value)
            if index < 0:
                index = _nearest_index(setting.choices, value)
            box.setCurrentIndex(index if index >= 0 else max(box.findData(setting.default), 0))
            # activated, not currentIndexChanged: only a choice somebody made.
            box.activated.connect(
                lambda _i, s=setting, b=box: self.changed.emit(s.key, b.currentData(), s.live)
            )
            return box
        if isinstance(setting.default, str) and setting.found is not None:
            picker = Picker(setting, value if isinstance(value, str) else setting.default)
            line = picker.lineEdit()
            line.setProperty("taken", line.text())
            line.textChanged.connect(lambda _t, e=line: self._show_pending(e))
            line.editingFinished.connect(lambda s=setting, e=line: self._take_text(s, e))
            # Chosen from the list: its value in the box, and taken up at once.
            picker.activated.connect(
                lambda index, s=setting, p=picker: self._pick(s, p, p.itemData(index))
            )
            return picker
        if isinstance(setting.default, str):
            line = QLineEdit(value if isinstance(value, str) else setting.default)
            line.setPlaceholderText(setting.empty)
            line.setProperty("taken", line.text())
            # Taken up once it is finished with, not at every letter typed on
            # the way, and shown as waiting until then.
            line.textChanged.connect(lambda _t, e=line: self._show_pending(e))
            line.editingFinished.connect(lambda s=setting, e=line: self._take_text(s, e))
            return line
        spin = QDoubleSpinBox() if setting.step else SequenceSpin()
        if setting.step:
            spin.setSingleStep(setting.step)
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
