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

from dataclasses import replace

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
    QToolButton,
)

from pyscopegui.backends.base import ANALOG, Channel
from pyscopegui.core.acquire import Acquisition
from pyscopegui.core.context import Context
from pyscopegui.core.decoding import PROTOCOLS
from pyscopegui.core.session import Session, Unit
from pyscopegui.core.triggers import (
    EDGE,
    EITHER,
    FALLING,
    KINDS,
    PATTERN,
    PROTOCOL,
    RISING,
    Condition,
)
from pyscopegui.ui.trigger_dialog import TriggerDialog

NONE = "None"
#: What the edge list says, for each way.
EDGES = {RISING: "Rising", FALLING: "Falling", EITHER: "Either"}
KIND_TIP = (
    "What to wait for: an edge, a window, a pulse of a width, a runt, a\n"
    "level held too long, or a pattern of logic levels. The details are\n"
    "under the button beside it."
)
SELF_TRIGGERED_TIP = (
    "This instrument sends sweeps and triggers itself: what it cannot wait\n"
    "for itself is greyed out, and is found in what is streamed instead."
)
DETAILS_TIP = "The details of what is waited for: levels, times, a pattern, a holdoff."
#: The lead list's first choice: no lead.
EACH = "Each its own"
LEAD_TIP = (
    "Which instrument's trigger holds the plot. Each its own: every instrument\n"
    "is held by its own trigger. One of them: its trigger holds the plot, and\n"
    "the others are shown at the same moment, by the computer's clock -- to a\n"
    "millisecond or a few. Their own triggers are not waited for, and Single\n"
    "stops them all."
)
#: Where the lead chosen is kept: one for the plot, as Position is.
LEAD_KEY = "trigger.lead"
SOURCE_TIP = (
    "The channel to trigger on. None is no trigger: the plot follows the\n"
    "newest samples, as a chart recorder does."
)
EDGE_TIP = "Trigger as the signal goes up through the level, down through it, or either."
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
        self.kind = QComboBox()
        for kind, said in KINDS.items():
            self.kind.addItem(said, kind)
        self.kind.setToolTip(KIND_TIP)
        self.edge = QComboBox()
        for edge, said in EDGES.items():
            self.edge.addItem(said, edge)
        self.edge.setToolTip(EDGE_TIP)
        self.details = QToolButton()
        self.details.setText("\u22ef")
        self.details.setToolTip(DETAILS_TIP)
        self.details.setAutoRaise(True)
        #: What the details come to, in a few words.
        self.said = QLabel()
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
        self.lead = QComboBox()
        self.lead.addItem(EACH, None)
        self.lead.setToolTip(LEAD_TIP)
        self.lead.activated.connect(self._on_lead)
        self.lead_label = QLabel(" Lead: ")

        self.source.activated.connect(self._on_source)
        self.kind.activated.connect(self._on_kind)
        self.edge.activated.connect(self._on_edge)
        self.details.clicked.connect(self.ask_details)
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
        row.addWidget(self.lead_label)
        row.addWidget(self.lead)
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
        row.addWidget(self.kind)
        for label, widget in ((" Edge: ", self.edge), (" Level: ", self.level)):
            row.addWidget(QLabel(label))
            row.addWidget(widget)
        row.addWidget(self.details)
        row.addWidget(self.said)
        self.addWidget(self.frame)
        self.show_leads()
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
        rising = self._saved(unit.name, "rising") is not False
        condition = Condition.from_saved(self._saved(unit.name, "condition"))
        if condition.kind == EDGE and condition.edge != EITHER:
            # The edge was saved on its own before there were kinds.
            condition = replace(condition, edge=RISING if rising else FALLING)
        unit.acquisition.set_trigger(
            level=level,
            rising=rising,
            position=self.position.value() / 100,
            condition=condition,
        )

    def bind(self, unit: Unit | None) -> None:
        """Be about this instrument from now on, and show its trigger: or about
        none, with nothing to choose, when the Instrument pane has none."""
        self.unit = unit
        if unit is None:
            self._channels = {}
            self.source.blockSignals(True)
            self.source.clear()
            self.source.addItem(NONE, None)
            self.source.blockSignals(False)
            self.label.setText(" Trigger: ")
            self.show_usable()
            return
        acquisition = unit.acquisition
        self._show_condition(acquisition.condition)
        self.level.blockSignals(True)
        self.level.setValue(acquisition.level)
        self.level.blockSignals(False)
        self.set_channels(unit)

    def _show_condition(self, condition: Condition) -> None:
        for widget in (self.kind, self.edge):
            widget.blockSignals(True)
        self.kind.setCurrentIndex(max(self.kind.findData(condition.kind), 0))
        self.edge.setCurrentIndex(max(self.edge.findData(condition.edge), 0))
        for widget in (self.kind, self.edge):
            widget.blockSignals(False)
        channel = self._channels.get(self.source.currentData())
        self.said.setText(f" {condition.summary(channel.unit if channel else 'V')}")

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
        sweeps = instrument is not None and instrument.sweeps
        if self._following():
            self._show_following()
            return
        channel = self._channels.get(self.source.currentData())
        condition = self.unit.acquisition.condition if self.unit is not None else Condition()
        # A pattern's channels, and a protocol's bus, are chosen in their details.
        pattern = condition.kind in (PATTERN, PROTOCOL)
        self.source.setEnabled(not as_is and not pattern)
        self.source.setToolTip(AS_IS_TIP if as_is else SOURCE_TIP)
        # An instrument that triggers itself does what it says it can.
        source = self.source.currentData()
        for row in range(self.kind.count()):
            kind = self.kind.itemData(row)
            item = self.kind.model().item(row)
            item.setEnabled(
                not sweeps or self._doable(replace(condition, kind=kind, holdoff=0.0), source)
            )
        self.kind.setEnabled((channel is not None or pattern) and not as_is)
        self.kind.setToolTip(SELF_TRIGGERED_TIP if sweeps else KIND_TIP)
        either = self.edge.model().item(self.edge.findData(EITHER))
        if either is not None:
            either.setEnabled(
                not sweeps or self._doable(replace(condition, edge=EITHER, holdoff=0.0), source)
            )
        self.edge.setEnabled(channel is not None and not as_is and condition.kind == EDGE)
        on = channel is not None or pattern
        # A plain edge's only detail is a holdoff, which not every instrument does itself.
        details = (
            condition.kind != EDGE
            or not sweeps
            or self._doable(replace(condition, holdoff=1e-3), source)
        )
        self.details.setEnabled(on and not as_is and details)
        self.said.setVisible(on and not as_is)
        self.position.setEnabled(on)
        analog = channel is not None and channel.kind == ANALOG
        pattern_analog = condition.kind == PATTERN and any(
            (c := self._channels.get(key)) is not None and c.kind == ANALOG
            for key, _level in condition.pattern
        )
        self.level.setEnabled((analog or pattern_analog) and not as_is)

    def _doable(self, condition: Condition, source: str | None) -> bool:
        """Whether the instrument chosen can wait for this itself, as it sends sweeps."""
        instrument = self.unit.instrument if self.unit is not None else None
        if instrument is None or not instrument.sweeps:
            return True
        return instrument.triggers_itself(condition, source)

    # --- one instrument leading the others --------------------------------------------------
    def show_leads(self) -> None:
        """Offer each instrument shown as the lead, with two or more; and the
        one chosen last time, once it is there."""
        units = self.session.shown()
        wanted = self.session.lead or self._ctx.settings.get(LEAD_KEY)
        self.lead.blockSignals(True)
        self.lead.clear()
        self.lead.addItem(EACH, None)
        for unit in units:
            self.lead.addItem(unit.short or unit.name, unit.name)
        self.lead.setCurrentIndex(max(self.lead.findData(wanted), 0))
        self.lead.blockSignals(False)
        self.session.lead = self.lead.currentData() if wanted in self.session.units else wanted
        several = len(units) > 1
        self.lead.setVisible(several)
        self.lead_label.setVisible(several)

    def _on_lead(self, _index: int) -> None:
        self.session.lead = self.lead.currentData()
        self._ctx.settings.set(LEAD_KEY, self.session.lead)
        self.show_usable()

    def _following(self) -> bool:
        """Whether the instrument chosen follows another's trigger."""
        lead = self.session.lead
        shown = [u.name for u in self.session.shown()]
        return self.unit is not None and len(shown) > 1 and lead in shown and self.unit.name != lead

    def _show_following(self) -> None:
        lead = self.session.units[self.session.lead]
        said = (
            f"Shown at the moment {lead.short or lead.name} triggers: its trigger holds the plot."
        )
        for widget in (self.source, self.kind, self.edge, self.level, self.details):
            widget.setEnabled(False)
            widget.setToolTip(said)
        self.said.setText(f" follows {lead.short or lead.name}")
        self.said.setVisible(True)
        self.position.setEnabled(True)

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
        edge = self.edge.currentData()
        if edge != EITHER:
            self._save("rising", edge == RISING)
        self._set_condition(replace(self.unit.acquisition.condition, edge=edge))

    def _on_kind(self, _index: int) -> None:
        if self.unit is None:
            return
        condition = replace(self.unit.acquisition.condition, kind=self.kind.currentData())
        self._set_condition(condition)
        settled = (condition.kind == PATTERN and condition.pattern) or (
            condition.kind == PROTOCOL and condition.bus
        )
        if condition.kind != EDGE and not settled:
            # A kind of its own wants its details: a pattern, its channels.
            self.ask_details()

    def ask_details(self) -> None:
        """The details of what is waited for, asked for in a dialog."""
        if self.unit is None:
            return
        condition = self.unit.acquisition.condition
        channels = [(c.key, c.name) for c in self._channels.values()]
        channel = self._channels.get(self.source.currentData())
        buses = []
        for decoding in self.unit.capture.decodings:
            setup = decoding.setup
            names = []
            for key in setup.channels():
                found = self._channels.get(key)
                names.append(found.name if found is not None else key)
            buses.append(
                (decoding.key, f"{PROTOCOLS[setup.protocol]} on {', '.join(names)}", setup.protocol)
            )
        instrument = self.unit.instrument
        sweeps = instrument is not None and instrument.sweeps
        source = self.source.currentData()
        dialog = TriggerDialog(
            condition,
            channels,
            channel.unit if channel else "V",
            self,
            buses=buses,
            doable=(lambda wanted: self._doable(wanted, source)) if sweeps else None,
        )
        if dialog.exec() == TriggerDialog.Accepted:
            self._set_condition(dialog.condition())

    def _set_condition(self, condition: Condition) -> None:
        self._save("condition", condition.as_saved())
        self.unit.acquisition.set_trigger(condition=condition)
        self._show_condition(condition)
        self.show_usable()

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
