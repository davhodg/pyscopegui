# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The trigger toolbar: which channel, which way, at what level, and where it sits.

One trigger for the whole window rather than one for each plot: Stop, Single,
Normal and Auto are one set of buttons, and what they wait for is one thing.
"""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QLabel, QSpinBox, QToolBar

from pyscopegui.backends.base import ANALOG, Channel
from pyscopegui.core.acquire import Acquisition
from pyscopegui.core.context import Context

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
POSITION_TIP = (
    "Where the trigger sits in the plot, from its left edge: 50% is the middle,\n"
    "with as much before the trigger as after it."
)


class TriggerBar(QToolBar):
    def __init__(self, acquisition: Acquisition, ctx: Context) -> None:
        super().__init__("Trigger")
        self.setObjectName("trigger")  # saveState identifies toolbars by objectName
        self.setMovable(False)
        self.acquisition = acquisition
        self._ctx = ctx
        self._channels: dict[str, Channel] = {}

        self.source = QComboBox()
        self.source.setToolTip(SOURCE_TIP)
        self.source.addItem(NONE, None)
        self.edge = QComboBox()
        self.edge.addItems((RISING, FALLING))
        self.edge.setToolTip(EDGE_TIP)
        self.level = QDoubleSpinBox()
        self.level.setDecimals(3)
        self.level.setRange(-100.0, 100.0)
        self.level.setSingleStep(0.1)
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
        self._wanted_source = ctx.settings.get("trigger.source")
        self.edge.setCurrentText(FALLING if ctx.settings.get("trigger.rising") is False else RISING)
        self.level.setValue(self._number("trigger.level", 0.0))
        self.position.setValue(round(self._number("trigger.position", 50.0)))
        acquisition.set_trigger(
            level=self.level.value(),
            rising=self.edge.currentText() == RISING,
            position=self.position.value() / 100,
        )

        self.source.activated.connect(self._on_source)
        self.edge.activated.connect(self._on_edge)
        self.level.valueChanged.connect(self._on_level)
        self.position.valueChanged.connect(self._on_position)

        for label, widget in (
            (" Trigger: ", self.source),
            (" Edge: ", self.edge),
            (" Level: ", self.level),
            (" Position: ", self.position),
        ):
            self.addWidget(QLabel(label))
            self.addWidget(widget)
        self._show_usable()

    def _number(self, key: str, default: float) -> float:
        try:
            return float(self._ctx.settings.get(key, default))
        except (TypeError, ValueError):
            return default

    # --- which channels there are ----------------------------------------------------------
    def set_channels(self, channels: list[Channel]) -> None:
        """List these channels to trigger on, keeping the one chosen if it is still there."""
        self._channels = {c.key: c for c in channels}
        self.source.blockSignals(True)
        self.source.clear()
        self.source.addItem(NONE, None)
        for channel in channels:
            self.source.addItem(channel.name, channel.key)
        index = self.source.findData(self._wanted_source)
        self.source.setCurrentIndex(max(index, 0))
        self.source.blockSignals(False)
        chosen = self.source.currentData()
        if chosen != self.acquisition.source:
            self.acquisition.set_trigger(source=chosen, clear_source=chosen is None)
        self._show_usable()

    def _show_usable(self) -> None:
        """A level means something only for an analog channel, and none of it with no trigger."""
        channel = self._channels.get(self.source.currentData())
        self.edge.setEnabled(channel is not None)
        self.position.setEnabled(channel is not None)
        self.level.setEnabled(channel is not None and channel.kind == ANALOG)

    # --- what somebody changed -------------------------------------------------------------
    def _on_source(self, _index: int) -> None:
        chosen = self.source.currentData()
        self._wanted_source = chosen
        self._ctx.settings.set("trigger.source", chosen)
        self.acquisition.set_trigger(source=chosen, clear_source=chosen is None)
        self._show_usable()

    def _on_edge(self, _index: int) -> None:
        rising = self.edge.currentText() == RISING
        self._ctx.settings.set("trigger.rising", rising)
        self.acquisition.set_trigger(rising=rising)

    def _on_level(self, value: float) -> None:
        self._ctx.settings.set("trigger.level", value)
        self.acquisition.set_trigger(level=value)

    def _on_position(self, value: int) -> None:
        self._ctx.settings.set("trigger.position", value)
        self.acquisition.set_trigger(position=value / 100)
