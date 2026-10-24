# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The trigger found where the signal gets clear of the band, in samples as
they are held, finds just what it found by comparing every sample in volts.

The old ways are kept here as they were, to be compared with: on noisy
signals, cut into blocks anywhere, held as volts, as counts whose scale
changes part way, with gaps, and as logic inputs packed into a port.
"""

from itertools import pairwise

import numpy as np
import pytest

from pyscopegui.backends.base import ANALOG, DIGITAL, LOST, Channel, Scale
from pyscopegui.core.acquire import find_triggers
from pyscopegui.core.can_decode import levels
from pyscopegui.core.capture import Bit, Record
from pyscopegui.core.edges import changes, falls, rises
from pyscopegui.core.triggers import (
    BETWEEN,
    EDGE,
    EITHER,
    ENTER,
    FALLING,
    HIGH,
    LEAVE,
    LONGER,
    LOW,
    PATTERN,
    PULSE,
    RISING,
    RUNT,
    SHORTER,
    TIMEOUT,
    WINDOW,
    Condition,
    Finder,
)

RATE = 1000.0
SAMPLES = 20_000


# --- the old ways ------------------------------------------------------------------------------
def old_find_triggers(samples, level, low, rising, armed):
    """Every sample compared, as find_triggers did."""
    if not rising:
        samples, level, low = -samples.astype(np.float32), -level, -low
    count = len(samples)
    if count == 0:
        return np.empty(0, dtype=np.int64), armed
    above = samples >= level
    below = samples <= low
    numbers = np.arange(1, count + 1)
    last_above = np.maximum.accumulate(np.where(above, numbers, 0))
    last_below = np.maximum.accumulate(np.where(below, numbers, 0))
    before = np.concatenate(([0], last_above[:-1]))
    ready = (2 * last_below + int(armed)) > 2 * before
    found = np.flatnonzero(above & ready).astype(np.int64)
    if last_below[-1] > last_above[-1]:
        armed = True
    elif last_above[-1] > last_below[-1]:
        armed = False
    return found, armed


class OldFinder:
    """The Finder as it was, comparing every sample in the channel's unit."""

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
    def _levels(self, name: str, samples: np.ndarray, threshold: float) -> np.ndarray:
        """Above the threshold or not, carried on from the last block."""
        before = self._high.get(name, False)
        if samples.dtype.kind in "ub":
            found = samples >= 1
        else:
            half = self.margin / 2
            found = levels(samples, threshold - half, threshold + half, start=before)
        self._high[name] = bool(found[-1]) if len(found) else before
        return found

    def _before(self, name: str, samples: np.ndarray, threshold: float) -> bool:
        """The level before these samples: what the last block ended at, or at
        the very first, the first sample's own -- nothing has happened yet."""
        if name not in self._high and len(samples):
            first = samples[0]
            self._high[name] = bool(first >= 1 if samples.dtype.kind in "ub" else first > threshold)
        return self._high.get(name, False)

    # --- finding ------------------------------------------------------------------------
    def find(self, data: dict[str, np.ndarray], first: int) -> np.ndarray:
        """The sample numbers it is met at in these samples, numbered from
        ``first``: the trigger's channel, or for a pattern, its channels."""
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
        before = self._before("level", samples, self.level)
        level = self._levels("level", samples, self.level)
        edge = self.condition.edge
        if edge == RISING:
            return rises(before, level) + first
        if edge == FALLING:
            return falls(before, level) + first
        return changes(before, level) + first

    def _window(self, samples, first):
        was = self._before("lower", samples, self.level) and not self._before(
            "upper", samples, self.upper
        )
        inside = self._levels("lower", samples, self.level) & ~self._levels(
            "upper", samples, self.upper
        )
        if self.condition.direction == ENTER:
            return rises(was, inside) + first
        return falls(was, inside) + first

    def _polar(self, name: str, samples, threshold: float) -> tuple[bool, np.ndarray]:
        """A pulse's level, high pulses high and low ones high too: and before."""
        before = self._before(name, samples, threshold)
        found = self._levels(name, samples, threshold)
        if self.condition.polarity == LOW:
            return not before, ~found
        return before, found

    def _pulse(self, samples, first):
        before, pulse = self._polar("level", samples, self.level)
        starts, ends = rises(before, pulse), falls(before, pulse)
        began = self._began(starts, ends, first, before)
        width = ends + first - began
        compare = self.condition.compare
        if compare == SHORTER:
            wanted = width < self.shortest
        elif compare == LONGER:
            wanted = width > self.shortest
        else:
            wanted = (width >= self.shortest) & (width <= self.longest)
        self._carry(starts, ends, first, before, len(pulse))
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

    def _carry(self, starts, ends, first, before, count):
        """The pulse still going at the end of the block, if one is."""
        if len(starts) and (not len(ends) or starts[-1] > ends[-1]):
            self._run_start = int(starts[-1]) + first
        elif len(ends):
            self._run_start = None
        elif not before:
            self._run_start = None

    def _runt(self, samples, first):
        polarity = self.condition.polarity
        if polarity == LOW:
            # Down through the upper level, and back without reaching the lower.
            before = not self._before("upper", samples, self.upper)
            self._before("lower", samples, self.level)
            pulse = ~self._levels("upper", samples, self.upper)
            beyond = ~self._levels("lower", samples, self.level)
        else:
            before = self._before("lower", samples, self.level)
            self._before("upper", samples, self.upper)
            pulse = self._levels("lower", samples, self.level)
            beyond = self._levels("upper", samples, self.upper)
        starts, ends = rises(before, pulse), falls(before, pulse)
        reached = np.concatenate(([0], np.cumsum(beyond)))
        index = np.searchsorted(starts, ends, side="right") - 1
        inside = index >= 0
        from_start = reached[ends] - reached[starts[np.maximum(index, 0)]] if len(starts) else 0
        got_there = np.where(inside, from_start > 0, self._reached | (reached[ends] > 0))
        seen = inside | before
        found = (ends + first)[seen & ~got_there]
        # Whether the pulse still going has reached the upper level yet.
        if len(starts) and (not len(ends) or starts[-1] > ends[-1]):
            self._reached = bool(reached[-1] - reached[starts[-1]] > 0)
        elif not len(ends) and before:
            self._reached = self._reached or bool(reached[-1] > 0)
        else:
            self._reached = False
        return found

    def _timeout(self, samples, first):
        before = self._before("level", samples, self.level)
        level = self._levels("level", samples, self.level)
        return self._held(level, before, first, self.condition.polarity, self.shortest)

    def _held(self, level, before, first, polarity, length):
        """Where a run of a level has lasted ``length`` samples: once a run."""
        count = len(level)
        if self._run_level is None:
            self._run_level, self._run_start, self._fired = bool(level[0]), first, False
        bounds = changes(before, level)
        starts = np.concatenate(([self._run_start], bounds + first))
        ends = np.concatenate((bounds + first, [first + count]))
        run_levels = np.concatenate(([self._run_level], level[bounds]))
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
        matched = None
        for key, wanted in self.condition.pattern:
            samples = data.get(key)
            if samples is None:
                return []
            self._before(key, samples, self.level)
            high = self._levels(key, samples, self.level)
            each = high if wanted else ~high
            matched = each if matched is None else matched & each
        if matched is None or not len(matched):
            return []
        # A pattern there from the very first sample did not begin here.
        before = self._high.get("matched", bool(matched[0]))
        self._high["matched"] = bool(matched[-1])
        if not self.held:
            return rises(before, matched) + first
        return self._held(matched, before, first, HIGH, self.held)

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


# --- signals -----------------------------------------------------------------------------------
def wave(rng, period=97.0, noise=0.08):
    """A square wave with slow edges, noise and runts: in volts, about ±1."""
    t = np.arange(SAMPLES)
    shape = np.clip(3 * np.sin(2 * np.pi * t / period), -1, 1)
    # Now and then a pulse that turns back half way.
    shape[(t // 400) % 7 == 3] *= 0.45
    return (shape + rng.normal(0, noise, SAMPLES)).astype(np.float32)


def with_gaps(rng, samples, gap):
    held = samples.copy()
    for at in rng.choice(SAMPLES - 50, 12, replace=False):
        held[at : at + rng.integers(1, 40)] = gap
    return held


SCALES = (Scale(1 / 8192), Scale(1 / 16384, 0.05), Scale(1 / 4096))


def volts_record(rng):
    record = Record(Channel("A", "A", full_scale=2.0), RATE, SAMPLES)
    record.append(with_gaps(rng, wave(rng), np.nan))
    return record


def counts_record(rng):
    """Counts, with the range changed twice part way, and gaps."""
    record = Record(Channel("A", "A", full_scale=2.0, counts=True), RATE, SAMPLES)
    volts = wave(rng)
    cuts = (0, SAMPLES // 3, 2 * SAMPLES // 3, SAMPLES)
    counts = np.empty(SAMPLES, dtype=np.int16)
    for scale, start, stop in zip(SCALES, cuts, cuts[1:], strict=False):
        part = np.round((volts[start:stop] + scale.offset) / scale.per_count)
        counts[start:stop] = np.clip(part, LOST + 1, 32767)
    counts = with_gaps(rng, counts, LOST)
    for scale, start, stop in zip(SCALES, cuts, cuts[1:], strict=False):
        record.append(counts[start:stop], scale)
    return record


def port_bits(rng):
    """A port of eight logic inputs, each its own square wave with glitches."""
    port = Record(Channel("port0", "port0", DIGITAL), RATE, SAMPLES)
    t = np.arange(SAMPLES)
    packed = np.zeros(SAMPLES, dtype=np.uint8)
    for bit in range(8):
        level = (t // (17 + 9 * bit)) % 2
        level[rng.random(SAMPLES) < 0.01] ^= 1
        packed |= (level << bit).astype(np.uint8)
    port.append(packed)
    return port, [
        Bit(Channel(f"D{bit}", f"D{bit}", DIGITAL, port="port0", bit=bit), port) for bit in range(8)
    ]


def blocks(rng, count=SAMPLES):
    """Cut anywhere: a block of one sample, and of thousands."""
    cuts = np.unique(np.concatenate((rng.integers(1, count, 60), [1, 2, count - 1])))
    edges = [0, *cuts.tolist(), count]
    return list(pairwise(edges))


def records(seed):
    rng = np.random.default_rng(seed)
    _port, bits = port_bits(rng)
    return {"volts": volts_record(rng), "counts": counts_record(rng), "bit": bits[3]}


# --- an edge -----------------------------------------------------------------------------------
@pytest.mark.parametrize("seed", range(4))
@pytest.mark.parametrize("held", ["volts", "counts", "bit"])
@pytest.mark.parametrize("rising", [True, False])
def test_an_edge_is_found_where_it_was(seed, held, rising):
    rng = np.random.default_rng(100 + seed)
    record = records(seed)[held]
    if record.channel.kind == ANALOG:
        # Exactly on a count, sometimes: where a sample is the level itself.
        level = float(SCALES[0].apply(np.array([rng.integers(-2000, 2000)], np.int16))[0])
        margin = 0.04 * rng.random()
        low = level - margin if rising else level + margin
    else:
        level = low = 0.5
    armed_old = armed_new = bool(rng.integers(2))
    old, new = [], []
    for start, stop in blocks(rng):
        found, armed_old = old_find_triggers(
            record.values(start, stop), level, low, rising, armed_old
        )
        old += (found + start).tolist()
        found, armed_new = find_triggers(record.stretch(start, stop), level, low, rising, armed_new)
        new += (found + start).tolist()
        assert armed_new == armed_old
    assert new == old and len(old) > 20


# --- the other kinds ---------------------------------------------------------------------------
CONDITIONS = [
    Condition(EDGE, edge=RISING),
    Condition(EDGE, edge=FALLING),
    Condition(EDGE, edge=EITHER, holdoff=0.03),
    Condition(WINDOW, upper=0.7, direction=ENTER),
    Condition(WINDOW, upper=0.7, direction=LEAVE),
    Condition(PULSE, polarity=HIGH, compare=SHORTER, shortest=0.04),
    Condition(PULSE, polarity=LOW, compare=LONGER, shortest=0.04),
    Condition(PULSE, polarity=HIGH, compare=BETWEEN, shortest=0.01, longest=0.045),
    Condition(RUNT, upper=0.7, polarity=HIGH),
    Condition(RUNT, upper=0.7, polarity=LOW),
    Condition(TIMEOUT, polarity=HIGH, shortest=0.03),
    Condition(TIMEOUT, polarity=LOW, shortest=0.03),
    Condition(TIMEOUT, polarity=EITHER, shortest=0.02, holdoff=0.05),
]


def both(condition, level, margin, data_for, rng):
    old, new = OldFinder(condition, level, margin, RATE), Finder(condition, level, margin, RATE)
    found_old, found_new = [], []
    for start, stop in blocks(rng):
        values, held = data_for(start, stop)
        found_old += old.find(values, start).tolist()
        found_new += new.find(held, start).tolist()
    return found_old, found_new


@pytest.mark.parametrize("seed", range(3))
@pytest.mark.parametrize("held", ["volts", "counts", "bit"])
@pytest.mark.parametrize("condition", CONDITIONS, ids=lambda c: c.summary() or c.edge)
def test_every_kind_is_found_where_it_was(seed, held, condition):
    rng = np.random.default_rng(200 + seed)
    record = records(seed)[held]
    analog = record.channel.kind == ANALOG
    level, margin = (-0.1, 0.05) if analog else (0.5, 0.0)
    if not analog and condition.kind in (WINDOW, RUNT):
        pytest.skip("a window or a runt is of an analog channel")

    def data_for(start, stop):
        return {"X": record.values(start, stop)}, {"X": record.stretch(start, stop)}

    old, new = both(condition, level, margin, data_for, rng)
    assert new == old


@pytest.mark.parametrize("seed", range(4))
@pytest.mark.parametrize("held", [0.0, 0.004])
def test_a_pattern_is_found_where_it_was(seed, held):
    rng = np.random.default_rng(300 + seed)
    _port, bits = port_bits(rng)
    condition = Condition(PATTERN, pattern=(("D0", 1), ("D2", 0), ("D5", 1)), held=held)

    def data_for(start, stop):
        keys = ("D0", "D2", "D5")
        chosen = (bits[0], bits[2], bits[5])
        return (
            {key: bit.values(start, stop) for key, bit in zip(keys, chosen, strict=True)},
            {key: bit.stretch(start, stop) for key, bit in zip(keys, chosen, strict=True)},
        )

    old, new = both(condition, 0.5, 0.0, data_for, rng)
    assert new == old and len(old) > 5
