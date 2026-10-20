# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""What every instrument looks like to the rest of pyscopegui.

A scope, a logic analyser and a board of your own all come down to the same
thing: a set of channels, sampled evenly, arriving a block at a time. A back
end turns whatever its hardware speaks into that, and nothing above it knows
which one it is talking to.

Samples are counted rather than timestamped. A block says which sample it
starts at and the rate they were taken at, so the time of any sample is its
number over the rate -- exact, and free of the jitter in when a block
happened to reach the computer, which is milliseconds and would otherwise be
drawn as if the signal had it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from pyscopegui.core.triggers import Condition

ANALOG = "analog"
DIGITAL = "digital"
#: The count that is not a reading, in a channel sent as counts: a sample the
#: instrument lost, or a gap. PicoScope's drivers mark a lost sample with it.
LOST = -32768


@dataclass(frozen=True)
class Channel:
    """One input of an instrument."""

    #: What the instrument calls it, and what its samples arrive under.
    key: str
    name: str
    kind: str = ANALOG
    #: What an analog sample is measured in. A digital one is 0 or 1.
    unit: str = "V"
    #: The most an analog channel can read, either side of zero, as it is set
    #: up now: 5.0 on a range of ±5 V. Zero where there is no such limit.
    full_scale: float = 0.0
    #: How it is set up, in a line, to be read beside its name: "1 V/div, 10x, DC".
    detail: str = ""
    #: The group its settings are listed under, so that choosing the channel
    #: can show them: "Channel A". Empty where it has none.
    group: str = ""
    #: The colour the instrument itself draws it in, as "#rrggbb", so that the
    #: plot and the scope's own screen agree. Empty where it has none.
    colour: str = ""
    #: The middle of what it can read, which full_scale is either side of:
    #: nought, or minus an offset. With a 1 V offset on a ±5 V range what is
    #: read is -6 V to 4 V, and the plot's axis is set to that.
    middle: float = 0.0
    #: Sent as the instrument's own 16-bit counts, with a Scale in each block,
    #: and held as they came: half the memory of volts, and nothing to work
    #: out until a sample is looked at. An analog channel only.
    counts: bool = False
    #: For a logic input sent packed: the key its port's samples arrive under,
    #: a byte a sample with eight inputs in it, and which bit of it this one
    #: is. Held packed, and read out only where it is looked at. Empty for
    #: a channel sent as itself.
    port: str = ""
    bit: int = 0

    def plain(self) -> Channel:
        """The same channel as a file holds it: in its unit, and on its own."""
        return replace(self, counts=False, port="", bit=0)


@dataclass(frozen=True)
class Scale:
    """How a channel's counts become its unit: count times ``per_count``, less
    ``offset``. LOST is not a reading, and becomes NaN."""

    per_count: float
    offset: float = 0.0

    def apply(self, counts: np.ndarray, out: np.ndarray | None = None) -> np.ndarray:
        """These counts in the channel's unit, as 32-bit floats."""
        values = np.multiply(counts, np.float32(self.per_count), out=out, dtype=np.float32)
        if self.offset:
            values -= np.float32(self.offset)
        values[counts == LOST] = np.nan
        return values


@dataclass(frozen=True)
class Setting:
    """One thing about an instrument that can be chosen: a range, a rate.

    Described rather than drawn, so that a back end needs no widgets of its
    own and every instrument's settings look alike. A setting with choices is
    a list to pick from, one whose default is True or False is a tick box,
    one whose default is text is a box to type in, and anything else is a
    number.
    """

    #: What it is saved under, and what the instrument is handed it as.
    key: str
    label: str
    default: object
    #: (value, what the list calls it), for a setting picked from a list.
    choices: tuple[tuple[object, str], ...] = ()
    #: For a number: its limits, how many decimal places, and what it is in.
    minimum: float = 0.0
    maximum: float = 0.0
    decimals: int = 0
    unit: str = ""
    #: How far its arrows move it. Zero is through 1, 2, 5, 10, 20, 50: for a
    #: number that runs over many powers of ten, where no one step suits.
    step: float = 0.0
    #: The heading it is listed under. Headings that start "Channel " are
    #: the same settings over again for each channel, and are shown one
    #: channel at a time.
    group: str = ""
    #: Taken up as the instrument runs, with what is on the plot kept.
    #: Anything else starts the run again, from an empty plot.
    live: bool = False
    #: For a setting that is text: asked for what there is to choose from
    #: when its list is opened -- the instruments plugged in at that moment --
    #: as (value, what the list calls it). It can still be typed.
    found: Callable[[], list[tuple[str, str]]] | None = None
    #: For a setting that is text: what leaving it empty means, shown in it
    #: while it is empty, and offered first in its list.
    empty: str = ""
    #: (key, value) of another setting this one depends on: it has a say only
    #: while that one is at that value, and is greyed out otherwise.
    needs: tuple[str, object] | None = None
    #: Says how the instrument is reached -- an address, a port -- so it is
    #: used when the instrument is opened, and greyed out while it is open.
    closed: bool = False
    tip: str = ""


@dataclass(frozen=True)
class Block:
    """A run of evenly spaced samples of every channel, all the same length."""

    #: The number of its first sample, counted from when the instrument started.
    first: int
    #: Samples per second.
    rate: float
    #: Channel key -> samples: float32 in the channel's unit for an analog
    #: channel, or int16 counts for one in ``scales``; uint8 holding 0 or 1
    #: for a digital one.
    data: dict[str, np.ndarray]
    #: The samples before this one were not taken, on purpose: the instrument
    #: stopped reading for a moment to do something else. Drawn as a gap like
    #: any other, and not reported as samples lost.
    after_pause: bool = False
    #: A capture complete in itself, taken by the instrument around its own
    #: trigger, rather than the next stretch of a stream. It takes the place
    #: of whatever was held; ``first`` is nought.
    sweep: bool = False
    #: In a sweep, the sample the instrument's trigger is at, or None if it
    #: was set to take the sweep without one.
    trigger: int | None = None
    #: In a sweep, whether the signal crossed the level there, as opposed to
    #: the instrument giving up waiting and taking the sweep anyway.
    triggered: bool = False
    #: Channel key -> how its counts become its unit, for a channel sent as
    #: counts: see Channel.counts.
    scales: dict[str, Scale] = field(default_factory=dict)
    #: Logic input's key -> (its port's key in ``data``, its bit), for inputs
    #: sent packed: see Channel.port.
    bits: dict[str, tuple[str, int]] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(next(iter(self.data.values()), ()))

    def values(self, key: str) -> np.ndarray:
        """A channel's samples in its unit: counts scaled, a logic input read
        out of its port, or as they came."""
        if (packed := self.bits.get(key)) is not None:
            port, bit = packed
            return unpacked(self.data[port], bit)
        scale = self.scales.get(key)
        samples = self.data[key]
        return samples if scale is None else scale.apply(samples)

    def in_units(self, keys: Iterable[str] | None = None) -> Block:
        """The same block with these channels -- every one, by default -- in
        their units and on their own: no counts, and no ports."""
        if not self.scales and not self.bits:
            return self
        ports = {port for port, _bit in self.bits.values()}
        wanted = [k for k in self.data if k not in ports] + [*self.bits] if keys is None else keys
        data = {key: self.values(key) for key in wanted if key in self.data or key in self.bits}
        return replace(self, data=data, scales={}, bits={})


def unpacked(port: np.ndarray, bit: int) -> np.ndarray:
    """One logic input, 0 or 1, out of its port's samples."""
    return ((port >> bit) & 1).astype(np.uint8)


class Instrument(QObject):
    """A source of samples. Subclass it, and add the class to ``BACKENDS``.

    Made with a parent and its own settings: whatever settings.json holds
    under ``instrument.<name>``, which may be nothing, or not a dictionary.
    """

    #: A ``Block``. Emitted on the GUI thread, or queued to it from another.
    block = Signal(object)
    #: Open, or not: connected to, and ready to be started.
    opened_changed = Signal(bool)
    #: Running, or not.
    state_changed = Signal(bool)
    #: Something went wrong that stopped it, in words for the Event Log.
    error = Signal(str)
    #: Something worth recording that is not a problem: which scope was found.
    note = Signal(str)
    #: It is still running, but what it is sending is not what was asked for.
    warning = Signal(str)
    #: What it is busy with at this moment, in a few words, for an instrument
    #: slow enough that a silence looks like a fault: "reading CH2 (2 of 4)".
    #: Empty when it is busy with nothing in particular.
    activity = Signal(str)

    #: What can be set, in the order it should be listed, before anything
    #: is known about the instrument that is plugged in.
    SETTINGS: tuple[Setting, ...] = ()

    def settings_offered(self) -> tuple[Setting, ...]:
        """What can be set on this one. Asked again once it is open, when a
        back end may know more: which ranges this model has."""
        return self.SETTINGS

    #: Whether its scales are as they are at its inputs, and the probe on each
    #: channel is counted here rather than by the instrument. See fitted.
    PROBES_COUNTED_HERE = False

    @classmethod
    def fitted(cls, offered: tuple[Setting, ...], options: dict) -> tuple[Setting, ...]:
        """What can be set, as it is with these chosen: a channel with a
        current probe has its scale and offset in amps."""
        from pyscopegui.backends import probes

        return probes.fitted(offered, options, cls.PROBES_COUNTED_HERE)

    @property
    def sweeps(self) -> bool:
        """Whether it sends sweeps, each complete in itself, rather than a stream."""
        return False

    @property
    def reference(self) -> bool:
        """Whether what it holds is to be drawn as a reference: faded, behind the
        others, to compare them with. A capture opened from a file can be."""
        return False

    @property
    def reads_as_is(self) -> bool:
        """Whether it is read as it is, with nothing on it changed. Its own
        trigger is then in charge and the toolbar's has no say: there is
        nothing to wait for, only what it shows to be read, once or over
        and over."""
        return False

    def set_trigger(
        self,
        source: str | None,
        level: float,
        rising: bool,
        position: float,
        auto: bool,
        condition: Condition | None = None,
    ) -> None:
        """What to trigger on, for an instrument that sends sweeps and so
        triggers itself. ``auto`` is to take a sweep anyway when no trigger
        comes; ``condition`` is what is waited for beyond an edge, which it
        does if ``triggers_itself`` says it can, and a rising or falling
        edge otherwise. An instrument that streams is triggered by
        pyscopegui, and need do nothing here."""

    def triggers_itself(self, condition: Condition, source: str | None) -> bool:
        """Whether, sending sweeps, it can wait for this itself, on this
        channel: a rising or a falling edge, unless it says it can do more."""
        return condition.kind == "edge" and condition.edge != "either" and not condition.holdoff

    def set(self, key: str, value: object) -> None:
        """Take up a setting. A ``live`` one may arrive while running; any
        other arrives while stopped, and is used at the next start."""

    @property
    def is_open(self) -> bool:
        raise NotImplementedError

    def open(self) -> None:
        """Connect to the instrument, which may take seconds and happen on a
        thread: ``opened_changed`` says when it has, or that it could not."""
        raise NotImplementedError

    def close(self) -> None:
        """Stop, and let go of the instrument, so that another program can have it."""
        raise NotImplementedError

    def channels(self) -> list[Channel]:
        """The inputs it has, in the order they should be listed."""
        raise NotImplementedError

    @property
    def rate(self) -> float:
        """Samples per second, the same for every channel."""
        raise NotImplementedError

    @property
    def running(self) -> bool:
        raise NotImplementedError

    def start(self) -> None:
        """Begin sending blocks, counting samples from zero again. Opens the
        instrument first if it is not open."""
        raise NotImplementedError

    def stop(self) -> None:
        """Stop sending blocks. Stopping one that is not running is not an error."""
        raise NotImplementedError
