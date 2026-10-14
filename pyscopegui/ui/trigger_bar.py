# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The trigger toolbar: which channel, which way, at what level, and where it sits.

One trigger for each instrument rather than one for each plot: Stop, Single,
Normal and Auto are one set of buttons, and what an instrument waits for is
one thing. With more than one instrument open, the toolbar is about the one
chosen in the instrument list, and each keeps its own channel, edge and
level: an instrument can only be triggered by a channel of its own. Where the
trigger sits in the plot is the same for all of them, since they share the plot.

Everything to do with triggering is in one frame. First what is the same for
every instrument that is open -- the four run buttons, which are a scope's
trigger modes, and where the trigger sits -- and then, past a line, what the
instrument chosen waits for.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QToolBar,
)

from pyscopegui.backends.base import ANALOG, Channel
from pyscopegui.core.acquire import Acquisition
from pyscopegui.core.context import Context
from pyscopegui.core.session import Session, Unit

NONE = "None"
RISING, FALLING = "Rising", "Falling"
SOURCE_TIP = (
    "The channel to trigger on. None is no trigger: the plot follows the\n"
    "newest samples, as a chart recorder does."
)
EDGE_TIP = "Trigger as the signal goes up through the level, or down through it."
LEVEL_TIP = (
    "The level the signal has to cross. Drawn as a dashed line on the plot.\n"
    "A digital channel has only the one level, between its 0 and its 1."
)
AS_IS_TIP = (
    "This instrument is read as it is, with nothing on it changed: what it\n"
    "triggers on is set on the instrument itself. Press Read for what it\n"
    "shows, or Auto to keep reading it."
)
POSITION_TIP = (
    "Where the trigger sits in the plot, from its left edge: 50% is the middle,\n"
    "with as much before the trigger as after it."
)


class Border(QFrame):
    """A thin line round what is inside, in the theme's own grey.

    Painted here rather than asked of a style sheet, which would leave the
    labels inside in the colours of the theme the window opened with. The
    style's own panel is too faint to be seen as a border at all.
    """

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # A third of the way from the window's colour to its text's: a grey
        # that shows against either theme, where the palette's own mid-grey
        # is the dark window's background over again.
        window = self.palette().color(QPalette.Window)
        text = self.palette().color(QPalette.WindowText)
        grey = QColor(
            *(
                round(w + (x - w) * 0.35)
                for w, x in zip(window.getRgb()[:3], text.getRgb()[:3], strict=True)
            )
        )
        painter.setPen(QPen(grey, 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)


class TriggerBar(QToolBar):
    def __init__(self, session: Session, ctx: Context, modes: tuple = ()) -> None:
        super().__init__("Trigger")
        self.setObjectName("trigger")  # saveState identifies toolbars by objectName
        self.setMovable(False)
        self.session = session
        self._ctx = ctx
        #: The instrument the toolbar is about now.
        self.unit: Unit | None = None
        self._channels: dict[str, Channel] = {}
        #: Instrument name -> the channel wanted as its trigger, which may not
        #: be there yet: the channels arrive when the instrument is made.
        self._wanted: dict[str, object] = {}

        self.label = QLabel(" Trigger: ")
        self.source = QComboBox()
        self.source.setToolTip(SOURCE_TIP)
        self.source.addItem(NONE, None)
        self.edge = QComboBox()
        self.edge.addItems((RISING, FALLING))
        self.edge.setToolTip(EDGE_TIP)
        self.level = QDoubleSpinBox()
        self.level.setDecimals(3)
        self.level.setRange(-100.0, 100.0)
        self.level.setSingleStep(0.05)
        self.level.setSuffix(" V")
        self.level.setToolTip(LEVEL_TIP)
        # Once the number is finished, not at every digit typed on the way.
        self.level.setKeyboardTracking(False)
        self.position = QSpinBox()
        self.position.setRange(0, 100)
        self.position.setSingleStep(10)
        self.position.setSuffix(" %")
        self.position.setToolTip(POSITION_TIP)
        self.position.setKeyboardTracking(False)
        # What was chosen last time, before anything is connected: putting it
        # back is not a change.
        self.position.setValue(round(self._number("trigger.position", 50.0)))

        self.source.activated.connect(self._on_source)
        self.edge.activated.connect(self._on_edge)
        self.level.valueChanged.connect(self._on_level)
        self.position.valueChanged.connect(self._on_position)

        # In a frame of its own: on one line with the run buttons, the four
        # boxes are otherwise not seen to be one thing, the trigger.
        self.frame = Border()
        row = QHBoxLayout(self.frame)
        row.setContentsMargins(4, 2, 6, 2)
        row.setSpacing(2)
        # For every instrument that is open: how it runs, and where the trigger sits.
        for button in modes:
            # Flat, as it would be on the toolbar itself.
            button.setAutoRaise(True)
            row.addWidget(button)
        row.addWidget(QLabel(" Position: "))
        row.addWidget(self.position)
        #: Between what is for all of them and what is for the one chosen.
        self.divider = QFrame()
        self.divider.setFrameShape(QFrame.VLine)
        self.divider.setFrameShadow(QFrame.Sunken)
        row.addSpacing(4)
        row.addWidget(self.divider)
        row.addSpacing(2)
        # For the instrument chosen: what it waits for.
        row.addWidget(self.label)
        row.addWidget(self.source)
        for label, widget in ((" Edge: ", self.edge), (" Level: ", self.level)):
            row.addWidget(QLabel(label))
            row.addWidget(widget)
        self.addWidget(self.frame)
        self.show_usable()

    @property
    def acquisition(self) -> Acquisition | None:
        return self.unit.acquisition if self.unit is not None else None

    # --- what is saved ---------------------------------------------------------------------
    def _saved(self, name: str, what: str, default: object = None) -> object:
        """What is saved for this instrument's trigger, or what was saved
        when there was one trigger for them all."""
        missing = object()
        value = self._ctx.settings.get(f"trigger.{name}.{what}", missing)
        if value is missing:
            value = self._ctx.settings.get(f"trigger.{what}", default)
        return value

    def _number(self, key: str, default: float) -> float:
        try:
            return float(self._ctx.settings.get(key, default))
        except (TypeError, ValueError):
            return default

    def _save(self, what: str, value: object) -> None:
        if self.unit is not None:
            self._ctx.settings.set(f"trigger.{self.unit.name}.{what}", value)

    # --- which instrument --------------------------------------------------------------------
    def prime(self, unit: Unit) -> None:
        """Give a new instrument the trigger that was saved for it."""
        self._wanted[unit.name] = self._saved(unit.name, "source")
        try:
            level = float(self._saved(unit.name, "level", 0.0))
        except (TypeError, ValueError):
            level = 0.0
        unit.acquisition.set_trigger(
            level=level,
            rising=self._saved(unit.name, "rising") is not False,
            position=self.position.value() / 100,
        )

    def bind(self, unit: Unit) -> None:
        """Be about this instrument from now on, and show its trigger."""
        self.unit = unit
        acquisition = unit.acquisition
        for widget in (self.edge, self.level):
            widget.blockSignals(True)
        self.edge.setCurrentText(RISING if acquisition.rising else FALLING)
        self.level.setValue(acquisition.level)
        for widget in (self.edge, self.level):
            widget.blockSignals(False)
        self.set_channels(unit)

    def set_channels(self, unit: Unit) -> None:
        """An instrument's channels changed: have it trigger on the one wanted,
        if that is there, and list them if the toolbar is about it."""
        channels = [record.channel for record in unit.capture.records.values()]
        wanted = self._wanted.get(unit.name)
        chosen = wanted if any(c.key == wanted for c in channels) else None
        if chosen != unit.acquisition.source:
            unit.acquisition.set_trigger(source=chosen, clear_source=chosen is None)
        if unit is not self.unit:
            return
        several = len(self.session.shown()) > 1
        self.label.setText(f" Trigger, {unit.short}: " if several and unit.short else " Trigger: ")
        self._channels = {c.key: c for c in channels}
        self.source.blockSignals(True)
        self.source.clear()
        self.source.addItem(NONE, None)
        for channel in channels:
            self.source.addItem(channel.name, channel.key)
        self.source.setCurrentIndex(max(self.source.findData(chosen), 0))
        self.source.blockSignals(False)
        self.show_usable()

    def show_usable(self) -> None:
        """A level means something only for an analog channel, and none of it
        with no trigger -- or for an instrument read as it is, whose trigger
        is its own business."""
        instrument = self.unit.instrument if self.unit is not None else None
        as_is = instrument is not None and instrument.reads_as_is
        channel = self._channels.get(self.source.currentData())
        self.source.setEnabled(not as_is)
        self.source.setToolTip(AS_IS_TIP if as_is else SOURCE_TIP)
        self.edge.setEnabled(channel is not None and not as_is)
        self.position.setEnabled(channel is not None)
        self.level.setEnabled(channel is not None and channel.kind == ANALOG and not as_is)

    # --- what somebody changed -------------------------------------------------------------
    def _on_source(self, _index: int) -> None:
        if self.unit is None:
            return
        chosen = self.source.currentData()
        self._wanted[self.unit.name] = chosen
        self._save("source", chosen)
        self.unit.acquisition.set_trigger(source=chosen, clear_source=chosen is None)
        self.show_usable()

    def _on_edge(self, _index: int) -> None:
        if self.unit is None:
            return
        rising = self.edge.currentText() == RISING
        self._save("rising", rising)
        self.unit.acquisition.set_trigger(rising=rising)

    def _on_level(self, value: float) -> None:
        if self.unit is None:
            return
        self._save("level", value)
        self.unit.acquisition.set_trigger(level=value)

    def _on_position(self, value: int) -> None:
        # The one plot is shared, so where the trigger sits in it is too.
        self._ctx.settings.set("trigger.position", value)
        for unit in self.session.units.values():
            unit.acquisition.set_trigger(position=value / 100)
