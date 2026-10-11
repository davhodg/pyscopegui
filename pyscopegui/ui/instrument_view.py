# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The Instrument pane: what the instrument chosen lets you set.

Built from the back end's own list of settings rather than written for each
instrument, so a new one gets its controls by describing them and every
instrument's look the same. The pane only says what was changed: saving it,
and deciding whether the instrument has to be started again, is the window's
business.

A scope's channels all have the same settings, and four of them one under
another is a pane to scroll through. So they are shown one at a time, under
a row of tabs. How every channel is set is read in the plot's channel list,
all at once; clicking one there brings its settings up here.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QStackedWidget,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from pyscopegui.backends.base import Setting
from pyscopegui.ui.spin import SequenceSpin

NOTHING = "This instrument has nothing to set."
#: Behind what has been typed and not yet taken up: Enter, or leaving the
#: box, takes it up. The amber pycangui uses for the same thing.
PENDING = "QLineEdit { background-color: rgba(230, 150, 0, 70); }"
#: Added to the tip of a setting that is not taken up as the instrument runs.
RESTARTS = "A change starts a run again, from an empty plot."
#: What a group's heading starts with when it is one channel's settings.
CHANNEL = "Channel "


class InstrumentView(QWidget):
    #: Key, the new value, and whether it takes effect without a restart.
    changed = Signal(str, object, bool)

    def __init__(self) -> None:
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(6, 6, 6, 6)
        #: Setting key -> the control showing it.
        self.controls: dict[str, QCheckBox | QComboBox | QDoubleSpinBox | QLineEdit] = {}
        self._settings: tuple[Setting, ...] = ()
        self._forms: dict[str, QFormLayout] = {}
        #: The tabs, one for each channel, and the settings under them.
        self.tabs: QTabBar | None = None
        self._pages: QStackedWidget | None = None
        #: Channel group -> which tab is its.
        self._tab_of: dict[str, int] = {}
        #: The channel last looked at, kept when the settings are shown again.
        self._group = ""
        self.changed.connect(self._show_needed)
        self.show_settings((), {})

    def show_settings(self, settings: tuple[Setting, ...], values: dict) -> None:
        """Show these settings, at the values saved for them or their defaults."""
        while (item := self._layout.takeAt(0)) is not None:
            if (widget := item.widget()) is not None:
                # Out of sight now: it is not deleted until the event loop gets to it.
                widget.setParent(None)
                widget.deleteLater()
        self.controls = {}
        self._settings, self._forms = settings, {}
        self.tabs, self._pages, self._tab_of = None, None, {}
        if not settings:
            self._layout.addWidget(QLabel(NOTHING))
            self._layout.addStretch()
            return
        forms = self._forms
        for setting in settings:
            if setting.group not in forms:
                forms[setting.group] = self._form(setting.group)
            control = self._control(setting, values.get(setting.key, setting.default))
            tip = setting.tip
            if not setting.live and not isinstance(control, QLineEdit):
                tip = f"{tip}\n{RESTARTS}" if tip else RESTARTS
            control.setToolTip(tip)
            self.controls[setting.key] = control
            if isinstance(control, QCheckBox):
                forms[setting.group].addRow(control)  # it carries its own label
            else:
                forms[setting.group].addRow(setting.label + ":", control)
        self._layout.addStretch()
        self.select_group(self._group)
        self._show_needed()

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
            self.tabs.currentChanged.connect(self._on_tab)
            column.addWidget(self.tabs)
            column.addWidget(self._pages)
            self._layout.addWidget(box)
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 6, 0, 0)
        self._pages.addWidget(page)
        self._tab_of[group] = self.tabs.addTab(group[len(CHANNEL) :])
        return form

    def _on_tab(self, index: int) -> None:
        self._pages.setCurrentIndex(index)
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

    def commit(self) -> None:
        """Take up anything typed and still waiting: before the instrument is opened or run."""
        for control in self.controls.values():
            if isinstance(control, QLineEdit):
                control.editingFinished.emit()
            elif isinstance(control, QDoubleSpinBox):
                control.interpretText()

    def value(self, key: str) -> object:
        """What the control for this setting is at."""
        control = self.controls[key]
        if isinstance(control, QCheckBox):
            return control.isChecked()
        if isinstance(control, QComboBox):
            return control.currentData()
        if isinstance(control, QLineEdit):
            return control.text()
        return control.value()

    def _show_needed(self, *_changed) -> None:
        """Grey out what has no say while another setting is as it is."""
        for setting in self._settings:
            if setting.needs is None or setting.needs[0] not in self.controls:
                continue
            key, value = setting.needs
            control = self.controls[setting.key]
            on = self.value(key) == value
            control.setEnabled(on)
            if (label := self._forms[setting.group].labelForField(control)) is not None:
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
            box.setCurrentIndex(index if index >= 0 else max(box.findData(setting.default), 0))
            # activated, not currentIndexChanged: only a choice somebody made.
            box.activated.connect(
                lambda _i, s=setting, b=box: self.changed.emit(s.key, b.currentData(), s.live)
            )
            return box
        if isinstance(setting.default, str):
            line = QLineEdit(value if isinstance(value, str) else setting.default)
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
