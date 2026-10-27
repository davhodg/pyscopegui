# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The instruments in use at once, and what each has sent.

Each instrument keeps time for itself: its samples are counted from when it
started, at its own rate, and nothing says when that was by another's clock.
So each has a capture of its own and a trigger of its own, and what puts two
of them on one time axis is that trigger. Nought on the axis is each
instrument's own trigger, and they line up as well as their triggers do:
exactly, when both are triggered by the same edge on the same wire.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from pyscopegui.backends.base import Channel, Instrument
from pyscopegui.core.acquire import Acquisition
from pyscopegui.core.capture import HISTORY_S, Capture, Record
from pyscopegui.core.clock import SampleClock


class Unit:
    """One instrument: what it is, what it has sent, and what it waits for."""

    def __init__(self, name: str, short: str, history_s: float, parent: QObject | None) -> None:
        #: The instrument's name, which is what it is saved under: its back
        #: end's, with a number for a second of the same kind. Empty for a
        #: capture that stands by itself, with no instrument behind it.
        self.name = name
        #: A word for it, to tell its channels from another's: "Rigol".
        self.short = short
        self.capture = Capture(history_s=history_s, parent=parent)
        self.acquisition = Acquisition(self.capture, parent=parent)
        #: When its samples were taken, on the computer's clock: for showing
        #: it at the same moment as another instrument's trigger.
        self.clock = SampleClock()
        self.instrument: Instrument | None = None
        #: Open, or being opened: an instrument can take seconds to say it is.
        self.wanted_open = False
        #: True while a run is stopped only to be started again.
        self.restarting = False
        #: What the instrument says it is busy with at this moment, if it says.
        self.doing = ""

    def id(self, key: str) -> str:
        """A channel of this instrument, told apart from the same key on another."""
        return f"{self.name}:{key}" if self.name else key

    @property
    def running(self) -> bool:
        return self.instrument is not None and self.instrument.running

    @property
    def is_open(self) -> bool:
        return self.instrument is not None and self.instrument.is_open


class Session(QObject):
    """Every instrument that has been chosen, in the order it was."""

    #: The channels there are to show changed, of any instrument.
    channels_changed = Signal()
    #: A trigger's settings, or what an instrument is doing, changed.
    trigger_changed = Signal()

    def __init__(self, history_s: float = HISTORY_S, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.history_s = history_s
        self.units: dict[str, Unit] = {}
        #: The instrument whose trigger holds every plot, the others shown at
        #: the same moment by their clocks; None for each held by its own.
        self.lead: str | None = None
        #: A channel's id -> the name it was given: "5V rail" for a Rigol's CH1.
        self.labels: dict[str, str] = {}

    @classmethod
    def of(cls, capture: Capture, acquisition: Acquisition | None = None) -> Session:
        """A session of one capture that is already there, with no instrument behind it."""
        session = cls(capture.history_s, capture.parent())
        unit = Unit.__new__(Unit)
        unit.name, unit.short = "", ""
        unit.capture = capture
        unit.acquisition = acquisition or Acquisition(capture, parent=capture.parent())
        unit.instrument, unit.wanted_open, unit.restarting = None, False, False
        unit.doing = ""
        session._take(unit)
        return session

    def unit(self, name: str, short: str = "") -> Unit:
        """The unit for the instrument called this, made if there is not one yet."""
        if name not in self.units:
            self._take(Unit(name, short, self.history_s, self))
        return self.units[name]

    def forget(self, name: str) -> None:
        """Have nothing more to do with the instrument called this: it was removed."""
        unit = self.units.pop(name, None)
        if unit is None:
            return
        unit.capture.channels_changed.disconnect(self.channels_changed)
        unit.acquisition.changed.disconnect(self.trigger_changed)
        self.channels_changed.emit()
        self.trigger_changed.emit()

    def _take(self, unit: Unit) -> None:
        self.units[unit.name] = unit
        unit.capture.channels_changed.connect(self.channels_changed)
        unit.acquisition.changed.connect(self.trigger_changed)

    def set_history(self, seconds: float) -> None:
        self.history_s = seconds
        for unit in self.units.values():
            unit.capture.history_s = seconds

    def shown(self) -> list[Unit]:
        """The units with channels to show."""
        return [unit for unit in self.units.values() if unit.capture.records]

    def entries(self) -> list[tuple[str, Unit, Record]]:
        """Every channel of every unit: its id, whose it is, and what is held of it."""
        return [
            (unit.id(key), unit, record)
            for unit in self.shown()
            for key, record in unit.capture.records.items()
        ]

    def name_of(self, unit: Unit, channel: Channel, whose: bool = True) -> str:
        """What to call a channel: with whose it is, when there is more than one to tell
        apart -- unless ``whose`` is False, for a place that is one instrument's alone --
        and the name it was given first, with which it is in brackets: "5V rail (CH1)"."""
        own = channel.name
        if whose and unit.short and len(self.shown()) > 1:
            own = f"{unit.short} {own}"
        given = self.labels.get(unit.id(channel.key))
        return f"{given} ({own})" if given else own

    def set_label(self, key: str, label: str) -> None:
        """Give a channel, by its id, a name of its own; an empty one takes it away."""
        label = " ".join(label.split())
        if label == self.labels.get(key, ""):
            return
        if label:
            self.labels[key] = label
        else:
            self.labels.pop(key, None)
        self.channels_changed.emit()

    def clear(self) -> None:
        for unit in self.units.values():
            unit.capture.clear()
