# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""pycangui's signals, as they come over UDP multicast, made into samples.

pycangui sends the signals ticked *UDP out* in its Signals and Plot pane as
JSON, on a group of their own (pycangui/core/signal_share.py). Two kinds of
message:

- **a description**, every second and whenever a tick changes: for each
  signal a short number, its group and name, and its unit, limits and value
  names where it has them; split into parts where it is long;
- **values**: per frame time, the numbers and values decoded at it, on the
  computer's monotonic clock -- the clock pyscopegui lines its instruments up
  on, so the two agree exactly on one computer.

Every message carries pycangui's run id and the description's count. Values
are read only against the description with the same two, so a pycangui
restarted, or a signal ticked or unticked, never puts one signal's values on
another's channel: values that come before their description is complete are
not used.

A signal arrives when its frame does, and not at any rate of its own. Here it
is held at its last value and read out at a steady rate, a step at each new
value, so that everything that works on an instrument's samples -- triggers,
cursors, measurements, export -- works on it unchanged. Nothing is known of a
signal before its first value: it reads NaN, a gap, until then.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

import numpy as np

#: Where pycangui sends them: a group and a port of their own, clear of the
#: CAN frames' (python-can's udp_multicast, port 43113).
GROUP = "239.74.163.20"
PORT = 43114
#: The format read. A message of another is passed over.
VERSION = 1


@dataclass(frozen=True)
class Described:
    """One signal, as pycangui describes it."""

    number: int
    group: str
    name: str
    unit: str = ""
    #: The database's limits, where it gives them.
    low: float | None = None
    high: float | None = None
    #: Value -> its name, for a signal whose values are states: 0 "Off", 1 "Run".
    names: dict[int, str] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """What it is known by here: the same however pycangui numbers it."""
        return f"{self.group}/{self.name}"


@dataclass
class _Parts:
    """A description arriving in parts: how many, and those there are."""

    count: int
    signals: dict[int, list] = field(default_factory=dict)


class Receiver:
    """What has been read of pycangui's messages: the signals described, and their
    values waiting to be sampled. ``feed`` each datagram as it arrives."""

    def __init__(self) -> None:
        #: The run and description count the signals are from, or None before any.
        self.described_as: tuple[str, int] | None = None
        #: Every signal described, in pycangui's order.
        self.signals: list[Described] = []
        self._by_number: dict[int, str] = {}
        self._parts: dict[tuple[str, int], _Parts] = {}
        #: Key -> values not yet sampled, as (time, value), oldest first.
        self.pending: dict[str, list[tuple[float, float]]] = {}
        #: Messages of pycangui's read, values read, and messages set aside: for
        #: knowing it is there, and for Help > Diagnostics.
        self.messages_read = 0
        self.values_read = 0
        self.passed_over = 0

    def feed(self, datagram: bytes) -> bool:
        """Read one message. True when it changed what the signals are."""
        try:
            message = json.loads(datagram.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self.passed_over += 1
            return False
        if not isinstance(message, dict) or message.get("v") != VERSION:
            self.passed_over += 1
            return False
        run, gen = message.get("run"), message.get("gen")
        if not isinstance(run, str) or not isinstance(gen, int):
            self.passed_over += 1
            return False
        if message.get("k") == "description":
            self.messages_read += 1
            return self._describe(message, (run, gen))
        if message.get("k") == "values":
            self.messages_read += 1
            self._values(message, (run, gen))
        else:
            self.passed_over += 1
        return False

    def _describe(self, message: dict, said_as: tuple[str, int]) -> bool:
        part, parts = message.get("part", 1), message.get("parts", 1)
        signals = message.get("signals")
        if not isinstance(part, int) or not isinstance(parts, int) or not isinstance(signals, list):
            self.passed_over += 1
            return False
        if said_as == self.described_as:
            return False  # said again, as it is every second
        gathering = self._parts.setdefault(said_as, _Parts(parts))
        gathering.signals[part] = signals
        if len(gathering.signals) < gathering.count:
            return False
        # Complete: those of other counts will not be, now.
        self._parts.clear()
        described = []
        for entry in (s for index in sorted(gathering.signals) for s in gathering.signals[index]):
            if (signal := _signal(entry)) is not None:
                described.append(signal)
        before = [(s.key, s.unit, s.low, s.high) for s in self.signals]
        self.described_as = said_as
        self.signals = described
        self._by_number = {s.number: s.key for s in described}
        keys = {s.key for s in described}
        self.pending = {k: v for k, v in self.pending.items() if k in keys}
        return [(s.key, s.unit, s.low, s.high) for s in described] != before

    def _values(self, message: dict, said_as: tuple[str, int]) -> None:
        frames = message.get("frames")
        if said_as != self.described_as or not isinstance(frames, list):
            self.passed_over += 1
            return
        for frame in frames:
            if not (isinstance(frame, list) and len(frame) == 2 and isinstance(frame[1], list)):
                continue
            at = frame[0]
            if not isinstance(at, int | float):
                continue
            for pair in frame[1]:
                if not (isinstance(pair, list) and len(pair) == 2):
                    continue
                number, value = pair
                key = self._by_number.get(number)
                if key is None or not isinstance(value, int | float):
                    continue
                self.pending.setdefault(key, []).append((float(at), float(value)))
                self.values_read += 1


def _signal(entry: object) -> Described | None:
    """One signal of a description, or None where it is not one."""
    if not isinstance(entry, dict):
        return None
    number, group, name = entry.get("n"), entry.get("group"), entry.get("name")
    if not isinstance(number, int) or not isinstance(name, str) or not name:
        return None
    unit = entry.get("unit") if isinstance(entry.get("unit"), str) else ""
    low, high = entry.get("min"), entry.get("max")
    if not (isinstance(low, int | float) and isinstance(high, int | float) and low < high):
        low = high = None
    names = {}
    if isinstance(entry.get("names"), dict):
        for value, said in entry["names"].items():
            try:
                names[int(value)] = str(said)
            except ValueError:
                continue
    return Described(number, group if isinstance(group, str) else "", name, unit, low, high, names)


class Held:
    """One signal read out at a steady rate: each sample its last value at or
    before the sample's time."""

    def __init__(self) -> None:
        self.value = math.nan

    def sample(self, times: np.ndarray, changes: list[tuple[float, float]]) -> np.ndarray:
        """The signal at these times, oldest first, given the values that have come
        since last time, oldest first. Those later than the last time wait."""
        if not len(times):
            return np.empty(0, dtype=np.float32)
        changes.sort(key=lambda change: change[0])  # as they were decoded, not as they came
        used = [change for change in changes if change[0] <= times[-1]]
        out = np.full(len(times), self.value, dtype=np.float32)
        if used:
            at = np.array([t for t, _v in used])
            values = np.array([v for _t, v in used], dtype=np.float32)
            index = np.searchsorted(at, times, side="right") - 1
            later = index >= 0
            out[later] = values[index[later]]
            self.value = float(values[-1])
        del changes[: len(used)]
        return out
