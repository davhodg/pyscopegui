# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""What a trigger waits for, beyond a plain edge: a window, a pulse's width, a
runt, a timeout, a pattern of logic levels -- found in the samples as they
arrive, as pyscopegui.core.acquire finds an edge.

A condition is found the same way on any instrument that streams. An
instrument that triggers itself -- that sends sweeps, each around its own
trigger -- is told what it can do of it, and does that.

Each kind works on levels: a channel above or below a threshold, with a little
hysteresis so that noise on a slow edge is not taken for many edges; a logic
channel is its own level. The levels become runs, and the runs are measured
with NumPy: a fast signal has thousands of edges in every block, and none of
them is looked at one at a time.

| Kind | Triggers on |
|------|-------------|
| Edge | a rising edge, a falling one, or either |
| Window | the signal entering the band between the level and the upper level, or leaving it |
| Pulse width | the end of a pulse -- high, or low -- shorter than a time, longer, or between two |
| Runt | a pulse that crosses the level but goes back without reaching the upper level |
| Timeout | the signal staying high, low, or either, for longer than a time: at that moment |
| Logic pattern | logic channels each at the level wanted, together: at once, or once held |
| Protocol | a frame, burst or transfer read off a decoded bus that matches: at its start |

And for all of them, a holdoff: after a trigger, none is taken for this long.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from pyscopegui.core.edges import Steps, combined, crossings
from pyscopegui.core.stretch import Stretch

EDGE, WINDOW, PULSE, RUNT, TIMEOUT, PATTERN = (
    "edge",
    "window",
    "pulse",
    "runt",
    "timeout",
    "pattern",
)
KINDS = {
    EDGE: "Edge",
    WINDOW: "Window",
    PULSE: "Pulse width",
    RUNT: "Runt",
    TIMEOUT: "Timeout",
    PATTERN: "Logic pattern",
    "protocol": "Protocol",
}
PROTOCOL = "protocol"
#: A protocol trigger's type: for CAN, a data or a remote frame; for I2C, a read,
#: a write, or an address nobody acknowledged.
ANY, DATA, REMOTE, READ, WRITE, NACK = "any", "data", "remote", "read", "write", "nack"
#: Which of what is read: all of it, only what was read cleanly, or only what was not.
ALL, GOOD, PROBLEM = "all", "good", "problem"
RISING, FALLING, EITHER = "rising", "falling", "either"
ENTER, LEAVE = "enter", "leave"
HIGH, LOW = "high", "low"
SHORTER, LONGER, BETWEEN = "shorter", "longer", "between"


@dataclass(frozen=True)
class Condition:
    """What is waited for, beyond which channel and at what level."""

    kind: str = EDGE
    #: Edge: which way.
    edge: str = RISING
    #: Window and runt: the upper of the two levels; the trigger's own level is the lower.
    upper: float = 1.0
    #: Window: entering the band, or leaving it.
    direction: str = ENTER
    #: Pulse width and runt: a high pulse or a low one. Timeout: staying high,
    #: low, or either.
    polarity: str = HIGH
    #: Pulse width: shorter than ``shortest``, longer than it, or between it and ``longest``.
    compare: str = LONGER
    shortest: float = 1e-3
    longest: float = 2e-3
    #: Logic pattern: each channel's key and the level wanted, 0 or 1.
    pattern: tuple[tuple[str, int], ...] = ()
    #: Logic pattern: held for at least this long, in seconds; nought for at once.
    held: float = 0.0
    #: After a trigger, none for this long, in seconds.
    holdoff: float = 0.0
    #: Protocol: the decoded bus, by its key -- "can:D0" -- and what has to
    #: match: an identifier or address in hex, X for a digit that may be anything;
    #: bytes it contains, in hex, XX for any, or "text" in quotes; its type; and
    #: whether it was read cleanly.
    bus: str = ""
    match_id: str = ""
    match_data: str = ""
    match_type: str = ANY
    which: str = ALL

    def as_saved(self) -> dict:
        saved = {name: getattr(self, name) for name in self.__dataclass_fields__}
        saved["pattern"] = [list(pair) for pair in self.pattern]
        return saved

    @classmethod
    def from_saved(cls, saved: object) -> Condition:
        """From what was saved; anything odd is as it would be to start with."""
        if not isinstance(saved, dict):
            return cls()
        start = cls()
        known = {
            "kind": KINDS,
            "edge": (RISING, FALLING, EITHER),
            "direction": (ENTER, LEAVE),
            "polarity": (HIGH, LOW, EITHER),
            "compare": (SHORTER, LONGER, BETWEEN),
            "match_type": (ANY, DATA, REMOTE, READ, WRITE, NACK),
            "which": (ALL, GOOD, PROBLEM),
        }
        values = {}
        for name, allowed in known.items():
            value = saved.get(name)
            values[name] = value if value in allowed else getattr(start, name)
        for name in ("upper", "shortest", "longest", "held", "holdoff"):
            value = saved.get(name)
            number = isinstance(value, int | float) and not isinstance(value, bool)
            # A level may be below nought; a time may not.
            if number and (name == "upper" or value >= 0):
                values[name] = float(value)
            else:
                values[name] = getattr(start, name)
        pattern = []
        for pair in saved.get("pattern") or ():
            if isinstance(pair, list | tuple) and len(pair) == 2 and isinstance(pair[0], str):
                if pair[1] in (0, 1) and not isinstance(pair[1], bool):
                    pattern.append((pair[0], int(pair[1])))
        values["pattern"] = tuple(pattern)
        for name in ("bus", "match_id", "match_data"):
            value = saved.get(name, "")
            values[name] = value if isinstance(value, str) else ""
        return cls(**values)

    def summary(self, unit: str = "V") -> str:
        """In a few words, for the toolbar: "pulse > 1 ms", "pattern 1X0"."""
        if self.kind == EDGE:
            return "either edge" if self.edge == EITHER else ""
        if self.kind == WINDOW:
            way = "entering" if self.direction == ENTER else "leaving"
            return f"{way} window, to {self.upper:g} {unit}"
        if self.kind == PULSE:
            sign = {SHORTER: "<", LONGER: ">"}.get(self.compare)
            span = (
                f"{_time(self.shortest)} to {_time(self.longest)}"
                if self.compare == BETWEEN
                else f"{sign} {_time(self.shortest)}"
            )
            return f"{self.polarity} pulse {span}"
        if self.kind == RUNT:
            return f"{self.polarity} runt, below {self.upper:g} {unit}"
        if self.kind == TIMEOUT:
            return f"{self.polarity} for {_time(self.shortest)}"
        if self.kind == PATTERN:
            said = " ".join(f"{key}={level}" for key, level in self.pattern) or "no channels"
            return f"pattern {said}" + (f" for {_time(self.held)}" if self.held else "")
        if self.kind == PROTOCOL:
            if not self.bus:
                return "no bus chosen"
            parts = [self.bus.split(":")[0].upper()]
            if self.match_type != ANY:
                parts.append(self.match_type)
            if self.match_id:
                parts.append(f"ID {self.match_id}")
            if self.match_data:
                parts.append(f"data {self.match_data}")
            if self.which != ALL:
                parts.append("with a problem" if self.which == PROBLEM else "good")
            return " ".join(parts)
        return ""


def _time(seconds: float) -> str:
    for scale, unit in ((1.0, "s"), (1e-3, "ms"), (1e-6, "µs"), (1e-9, "ns")):
        if seconds >= scale:
            return f"{seconds / scale:g} {unit}"
    return f"{seconds:g} s"


class Finder:
    """A condition found in one instrument's samples, block after block."""

    def __init__(self, condition: Condition, level: float, margin: float, rate: float) -> None:
        """``level`` is the trigger's level, ``margin`` the hysteresis about it
        in the channel's unit, and ``rate`` the samples a second."""
        self.condition = condition
        self.level = level
        self.upper = condition.upper
        if condition.kind in (WINDOW, RUNT) and self.upper < self.level:
            self.level, self.upper = self.upper, self.level
        self.margin = margin
        self.shortest = max(1, round(condition.shortest * rate))
        self.longest = max(self.shortest, round(condition.longest * rate))
        self.held = round(condition.held * rate)
        self.holdoff = round(condition.holdoff * rate)
        #: Carried from one block to the next: each threshold's level, a run's
        #: start, whether a runt's pulse reached the upper level, and the last trigger.
        self._high: dict[str, bool] = {}
        self._run_start: int | None = None
        self._run_level: bool | None = None
        self._fired = False
        self._reached = False
        self._last = -(10**18)

    # --- levels ------------------------------------------------------------------------
    def _levels(self, name: str, samples: Stretch, threshold: float) -> Steps:
        """Above the threshold or not, carried on from the last block: found
        only where the samples get clear of the hysteresis either side of it."""
        before = self._high.get(name, False)
        if samples.digital:
            ups, downs = samples.starts(">=", 1), samples.starts("<", 1)
        else:
            half = self.margin / 2
            ups = samples.starts(">", threshold + half)
            downs = samples.starts("<", threshold - half)
        at, _into, _after = crossings(ups, downs, int(before))
        found = Steps(before, at, len(samples))
        self._high[name] = found.after
        return found

    def _before(self, name: str, samples: Stretch, threshold: float) -> bool:
        """The level before these samples: what the last block ended at, or at
        the very first, the first sample's own -- nothing has happened yet."""
        if name not in self._high and len(samples):
            first = samples.first()
            self._high[name] = bool(first >= 1 if samples.digital else first > threshold)
        return self._high.get(name, False)

    # --- finding ------------------------------------------------------------------------
    def find(self, data: dict[str, np.ndarray | Stretch], first: int) -> np.ndarray:
        """The sample numbers it is met at in these samples, numbered from
        ``first``: the trigger's channel, or for a pattern, its channels. Each
        is samples in the channel's unit, or a stretch of them as held."""
        data = {key: Stretch.of(samples) for key, samples in data.items()}
        kind = self.condition.kind
        if kind == PATTERN:
            found = self._pattern(data, first)
        else:
            samples = next(iter(data.values()))
            if not len(samples):
                return np.empty(0, dtype=np.int64)
            found = {
                EDGE: self._edge,
                WINDOW: self._window,
                PULSE: self._pulse,
                RUNT: self._runt,
                TIMEOUT: self._timeout,
            }[kind](samples, first)
        return self._hold_off(np.asarray(found, dtype=np.int64))

    def _edge(self, samples, first):
        self._before("level", samples, self.level)
        level = self._levels("level", samples, self.level)
        edge = self.condition.edge
        if edge == RISING:
            return level.rises() + first
        if edge == FALLING:
            return level.falls() + first
        return level.at + first

    def _window(self, samples, first):
        self._before("lower", samples, self.level)
        self._before("upper", samples, self.upper)
        lower = self._levels("lower", samples, self.level)
        upper = self._levels("upper", samples, self.upper)
        inside = combined([lower, upper], lambda low, high: low & ~high)
        if self.condition.direction == ENTER:
            return inside.rises() + first
        return inside.falls() + first

    def _polar(self, name: str, samples, threshold: float) -> Steps:
        """A pulse's level, high pulses high and low ones high too."""
        self._before(name, samples, threshold)
        found = self._levels(name, samples, threshold)
        return found.inverted() if self.condition.polarity == LOW else found

    def _pulse(self, samples, first):
        pulse = self._polar("level", samples, self.level)
        before = pulse.before
        starts, ends = pulse.rises(), pulse.falls()
        began = self._began(starts, ends, first, before)
        width = ends + first - began
        compare = self.condition.compare
        if compare == SHORTER:
            wanted = width < self.shortest
        elif compare == LONGER:
            wanted = width > self.shortest
        else:
            wanted = (width >= self.shortest) & (width <= self.longest)
        self._carry(starts, ends, first, before)
        return (ends + first)[(began >= 0) & wanted]

    def _began(self, starts, ends, first, before) -> np.ndarray:
        """Where each pulse that ends in this block began, as a sample number:
        -1 for one whose start was never seen."""
        index = np.searchsorted(starts, ends, side="right") - 1
        if len(starts):
            began = np.where(index >= 0, starts[np.maximum(index, 0)] + first, -1)
        else:
            began = np.full(len(ends), -1, dtype=np.int64)
        if before and self._run_start is not None:
            began = np.where(index < 0, self._run_start, began)
        return began.astype(np.int64)

    def _carry(self, starts, ends, first, before):
        """The pulse still going at the end of the block, if one is."""
        if len(starts) and (not len(ends) or starts[-1] > ends[-1]):
            self._run_start = int(starts[-1]) + first
        elif len(ends):
            self._run_start = None
        elif not before:
            self._run_start = None

    def _runt(self, samples, first):
        self._before("lower", samples, self.level)
        self._before("upper", samples, self.upper)
        lower = self._levels("lower", samples, self.level)
        upper = self._levels("upper", samples, self.upper)
        if self.condition.polarity == LOW:
            # Down through the upper level, and back without reaching the lower.
            pulse, beyond = upper.inverted(), lower.inverted()
        else:
            pulse, beyond = lower, upper
        before, count = pulse.before, len(samples)
        starts, ends = pulse.rises(), pulse.falls()
        index = np.searchsorted(starts, ends, side="right") - 1
        inside = index >= 0
        began = starts[np.maximum(index, 0)] if len(starts) else np.zeros(len(ends), np.int64)
        # Whether each pulse reached the upper level: one that began before
        # this block may have done so already.
        got_there = np.where(
            inside,
            beyond.any_high(began, ends),
            self._reached | beyond.any_high(np.zeros(len(ends), np.int64), ends),
        )
        seen = inside | before
        found = (ends + first)[seen & ~got_there]
        # Whether the pulse still going has reached the upper level yet.
        if len(starts) and (not len(ends) or starts[-1] > ends[-1]):
            self._reached = bool(beyond.any_high([starts[-1]], [count])[0])
        elif not len(ends) and before:
            self._reached = self._reached or bool(beyond.any_high([0], [count])[0])
        else:
            self._reached = False
        return found

    def _timeout(self, samples, first):
        self._before("level", samples, self.level)
        level = self._levels("level", samples, self.level)
        return self._held(level, first, self.condition.polarity, self.shortest)

    def _held(self, level: Steps, first, polarity, length):
        """Where a run of a level has lasted ``length`` samples: once a run."""
        count = len(level)
        if self._run_level is None:
            self._run_level = bool(level.level_at(np.zeros(1, np.int64))[0])
            self._run_start, self._fired = first, False
        bounds = level.at
        starts = np.concatenate(([self._run_start], bounds + first))
        ends = np.concatenate((bounds + first, [first + count]))
        run_levels = np.concatenate(([self._run_level], level.each()))
        fired = np.zeros(len(starts), dtype=bool)
        fired[0] = self._fired
        wanted = (
            np.ones(len(starts), dtype=bool)
            if polarity == EITHER
            else run_levels == (polarity == HIGH)
        )
        hit = wanted & ~fired & (ends - starts > length)
        self._run_start, self._run_level = int(starts[-1]), bool(run_levels[-1])
        self._fired = bool(fired[-1] or hit[-1])
        return starts[hit] + length

    def _pattern(self, data, first):
        each = []
        for key, wanted in self.condition.pattern:
            samples = data.get(key)
            if samples is None:
                return []
            self._before(key, samples, self.level)
            high = self._levels(key, samples, self.level)
            each.append(high if wanted else high.inverted())
        if not each or not len(each[0]):
            return []
        matched = combined(each, lambda *levels: np.logical_and.reduce(levels))
        # A pattern there from the very first sample did not begin here.
        at_first = bool(matched.level_at(np.zeros(1, np.int64))[0])
        matched = matched.from_level(self._high.get("matched", at_first))
        self._high["matched"] = matched.after
        if not self.held:
            return matched.rises() + first
        return self._held(matched, first, HIGH, self.held)

    def _hold_off(self, found: np.ndarray) -> np.ndarray:
        """None within the holdoff of the one before."""
        if not len(found):
            return found
        if not self.holdoff:
            self._last = int(found[-1])
            return found
        kept = []
        for at in found.tolist():
            if at - self._last >= self.holdoff:
                kept.append(at)
                self._last = at
        return np.array(kept, dtype=np.int64)


# --- protocol triggers ---------------------------------------------------------------------
def parse_id(text: str) -> tuple[int, int] | None:
    """A hex identifier or address, X for any digit, as (value, mask): "18FEXX00"
    is (0x18FE0000, 0xFFFF00FF). An empty one matches anything: (0, 0). None for
    one that is not hex."""
    text = text.strip().lower().removeprefix("0x").replace(" ", "")
    if not text:
        return 0, 0
    if not re.fullmatch(r"[0-9a-fx]+", text):
        return None
    value = mask = 0
    for digit in text:
        value, mask = value << 4, mask << 4
        if digit != "x":
            value |= int(digit, 16)
            mask |= 0xF
    return value, mask


def parse_data(text: str) -> list[int | None] | None:
    """Bytes to look for, each a number or None for any: "12 XX 34", or "OK" in
    quotes for text. Empty matches anything: []. None for something that is neither."""
    text = text.strip()
    if not text:
        return []
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return list(text[1:-1].encode("latin-1", "replace"))
    found: list[int | None] = []
    for part in text.replace(",", " ").split():
        part = part.lower().removeprefix("0x")
        if part in ("x", "xx"):
            found.append(None)
        elif re.fullmatch(r"[0-9a-f]{1,2}", part):
            found.append(int(part, 16))
        else:
            return None
    return found


def _contains(values: list[int], wanted: list[int | None]) -> bool:
    if not wanted:
        return True
    span = len(wanted)
    for at in range(len(values) - span + 1):
        if all(w is None or values[at + i] == w for i, w in enumerate(wanted)):
            return True
    return False


def item_matches(protocol: str, item, condition: Condition) -> bool:
    """Whether something read off a bus is what a protocol trigger waits for."""
    if (condition.which == GOOD and item.error) or (condition.which == PROBLEM and not item.error):
        return False
    identifier = parse_id(condition.match_id) or (0, 0)
    wanted = parse_data(condition.match_data) or []
    kind = condition.match_type
    if protocol == "can":
        if (kind == DATA and item.remote) or (kind == REMOTE and not item.remote):
            return False
        return (item.identifier & identifier[1]) == identifier[0] and _contains(
            list(item.data), wanted
        )
    if protocol == "i2c":
        if (kind == READ and not item.read) or (kind == WRITE and item.read):
            return False
        if kind == NACK and not item.nacked:
            return False
        address = item.address if item.address is not None else -1
        if identifier[1] and (address < 0 or (address & identifier[1]) != identifier[0]):
            return False
        return _contains(item.data, wanted)
    if protocol == "uart":
        return _contains(item.values, wanted)
    if protocol == "spi":
        return _contains(item.mosi, wanted) or _contains(item.miso, wanted)
    return False
