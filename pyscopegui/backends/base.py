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

from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QObject, Signal

ANALOG = "analog"
DIGITAL = "digital"


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


@dataclass(frozen=True)
class Setting:
    """One thing about an instrument that can be chosen: a range, a rate.

    Described rather than drawn, so that a back end needs no widgets of its
    own and every instrument's settings look alike. A setting with choices is
    a list to pick from, one whose default is True or False is a tick box,
    and anything else is a number.
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
    #: The heading it is listed under.
    group: str = ""
    #: Taken up as the instrument runs, with what is on the plot kept.
    #: Anything else starts the run again, from an empty plot.
    live: bool = False
    tip: str = ""


@dataclass(frozen=True)
class Block:
    """A run of evenly spaced samples of every channel, all the same length."""

    #: The number of its first sample, counted from when the instrument started.
    first: int
    #: Samples per second.
    rate: float
    #: Channel key -> samples: float32 in the channel's unit for an analog
    #: channel, uint8 holding 0 or 1 for a digital one.
    data: dict[str, np.ndarray]
    #: The samples before this one were not taken, on purpose: the instrument
    #: stopped reading for a moment to do something else. Drawn as a gap like
    #: any other, and not reported as samples lost.
    after_pause: bool = False

    def __len__(self) -> int:
        return len(next(iter(self.data.values()), ()))


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

    #: What can be set, in the order it should be listed.
    SETTINGS: tuple[Setting, ...] = ()

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
