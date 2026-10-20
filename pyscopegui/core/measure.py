# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Measurements of a stretch of samples: levels, and how often it repeats.

The levels -- lowest, highest, peak to peak, mean, RMS -- are of every sample
in the stretch. How often it repeats is found by where the signal rises
through the middle of its own range: with a band either side of the middle
that it has to get clear of, so that noise on a slow edge is not counted as
a dozen edges. The frequency is how many whole cycles there are between the
first rising edge and the last, over the time between them; the duty cycle
is how much of that time it was high.

Fewer than two rising edges is no frequency, and a flat signal has none:
said as nothing rather than as a nought that would look like a measurement.

A long stretch is measured a piece at a time, so that it never needs more
memory than a piece; and an edge is found only where the signal gets clear
of the band, a few times a cycle, rather than by working something out for
every sample. While the instrument runs a stretch can be measured from a
share of it instead -- see ``measure_held`` -- which is close, and quick
however long the stretch: exact is for what has stopped.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

import numpy as np

#: Either side of the middle, as a share of peak to peak, that the signal has
#: to get clear of to count as having crossed it.
BAND = 0.1
#: Smaller than this, peak to peak, is flat: there is nothing to cross.
FLAT = 1e-9
#: Measured exactly, this many samples at a time.
PIECE = 1 << 22
#: Measured while running, at most this many samples of a stretch are looked at:
#: the newest of them 6.5 ms at 10 MS/s, enough for a signal above 300 Hz to
#: rise twice in, and a slower one is measured from the spread.
LOOKED_AT = 1 << 16

#: Samples ``start`` to ``stop``, every ``step``'th, in the channel's unit.
Values = Callable[[int, int, int], np.ndarray]


@dataclass(frozen=True)
class Measured:
    """What a stretch of samples measured. None for what it does not have."""

    samples: int
    minimum: float
    maximum: float
    mean: float
    rms: float
    frequency: float | None = None
    duty: float | None = None
    #: Every sample looked at, or -- while running, over a long stretch -- a
    #: share of them: close, rather than exact.
    exact: bool = True

    @property
    def peak_to_peak(self) -> float:
        return self.maximum - self.minimum

    @property
    def period(self) -> float | None:
        return 1.0 / self.frequency if self.frequency else None


@dataclass(frozen=True)
class _Levels:
    count: int
    low: float
    high: float
    mean: float
    rms: float


def measure(samples: np.ndarray, rate: float) -> Measured | None:
    """Measure a stretch of samples taken at this rate, exactly. None with fewer than two."""
    samples = np.asarray(samples)
    return measure_held(lambda a, b, step: samples[a:b:step], 0, len(samples), rate)


def measure_held(
    values: Values,
    start: int,
    stop: int,
    rate: float,
    exact: bool = True,
    extremes: tuple[float, float] | None = None,
) -> Measured | None:
    """Measure samples ``start`` to ``stop`` of what ``values`` reads -- a
    record's, say -- taken at this rate. None with fewer than two.

    Exact is every sample, a piece at a time. Otherwise, over a stretch longer
    than LOOKED_AT: the levels of samples spread evenly over it, and how often
    it repeats from the newest LOOKED_AT of them -- or, for a signal too slow
    to rise twice in those, from the spread. ``extremes``, the lowest and
    highest the plot found in the stretch, stand in for the spread's own,
    which miss a spike narrower than the spacing.
    """
    count = stop - start
    if count < 2:
        return None
    if exact or count <= LOOKED_AT:

        def pieces() -> Iterable[np.ndarray]:
            return (values(a, min(a + PIECE, stop), 1) for a in range(start, stop, PIECE))

        levels = _levels(pieces())
        if levels is None:
            return None
        rises, falls = _edges(pieces(), levels)
        return _measured(levels, rises, falls, rate, 1, levels.count, True)
    step = -(-count // LOOKED_AT)
    spread = values(start, stop, step)
    levels = _levels([spread])
    if levels is None:
        return None
    if extremes is not None and not np.isnan(extremes).any():
        low, high = min(levels.low, extremes[0]), max(levels.high, extremes[1])
        levels = _Levels(levels.count, low, high, levels.mean, levels.rms)
    rises, falls = _edges([values(stop - LOOKED_AT, stop, 1)], levels)
    if len(rises) >= 2:
        # The newest samples: the start of the stretch is where to count from.
        rises, falls, step = rises + count - LOOKED_AT, falls + count - LOOKED_AT, 1
    else:
        rises, falls = _edges([spread], levels)
    held = round(levels.count * count / len(spread))
    return _measured(levels, rises, falls, rate, step, held, False)


def _levels(pieces: Iterable[np.ndarray]) -> _Levels | None:
    """The lowest, highest, mean and RMS of every sample that is a reading."""
    count, low, high, total, squares = 0, np.inf, -np.inf, 0.0, 0.0
    for piece in pieces:
        if piece.dtype == np.uint8:
            # A logic input: 0 or 1, so its ones say everything.
            ones = int(np.count_nonzero(piece))
            count += len(piece)
            low = min(low, 0.0 if ones < len(piece) else 1.0)
            high = max(high, 1.0 if ones else 0.0)
            total += ones
            squares += ones
            continue
        if piece.dtype.kind == "f":
            piece = piece[~np.isnan(piece)]
        if not len(piece):
            continue
        wide = piece.astype(np.float64)
        count += len(wide)
        low, high = min(low, float(wide.min())), max(high, float(wide.max()))
        total += float(wide.sum())
        squares += float(np.dot(wide, wide))
    if count < 2:
        return None
    return _Levels(count, low, high, total / count, float(np.sqrt(squares / count)))


def _edges(pieces: Iterable[np.ndarray], levels: _Levels) -> tuple[np.ndarray, np.ndarray]:
    """Where the signal rises through the middle of its range, and where it
    falls, counted from the first sample of the first piece.

    Only where it gets clear of the band, above or below, is anything worked
    out: a few times a cycle, rather than for every sample. In the band, or a
    gap, it is what it was last; before it was first clear, neither.
    """
    if levels.high - levels.low <= FLAT:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64)
    middle, band = (levels.low + levels.high) / 2, (levels.high - levels.low) * BAND
    upper, lower = middle + band, middle - band
    rises: list[np.ndarray] = []
    falls: list[np.ndarray] = []
    #: 1 high, 0 low, -1 not clear of the band yet; and where the last piece ended.
    state, was_above, was_below, offset = -1, False, False, 0
    for piece in pieces:
        if not len(piece):
            continue
        if piece.dtype == np.uint8:
            # A logic input: 1 is above the band, and 0 below, as it lies.
            above = piece.view(np.bool_)
            below = ~above
        elif piece.dtype.kind in "iub":
            # The same comparisons, in the samples' own kind of number.
            above, below = piece > int(np.floor(upper)), piece < int(np.ceil(lower))
        else:
            above, below = piece > upper, piece < lower
        ups = _starts(above, was_above)
        downs = _starts(below, was_below)
        at = np.concatenate((ups, downs))
        into = np.concatenate((np.ones(len(ups), np.int8), np.zeros(len(downs), np.int8)))
        order = np.argsort(at, kind="stable")
        at, into = at[order] + offset, into[order]
        if len(into):
            before = np.concatenate(([state], into[:-1]))
            rises.append(at[(into == 1) & (before == 0)])
            falls.append(at[(into == 0) & (before == 1)])
            state = int(into[-1])
        was_above, was_below = bool(above[-1]), bool(below[-1])
        offset += len(piece)
    empty = np.empty(0, dtype=np.int64)
    return (np.concatenate(rises) if rises else empty, np.concatenate(falls) if falls else empty)


def _starts(clear: np.ndarray, was: bool) -> np.ndarray:
    """Where a run of samples clear of the band starts, with whether the one
    before the first was clear too."""
    starts = np.flatnonzero(clear[1:] > clear[:-1]) + 1
    if clear[0] and not was:
        starts = np.concatenate(([0], starts))
    return starts


def _measured(
    levels: _Levels,
    rises: np.ndarray,
    falls: np.ndarray,
    rate: float,
    step: int,
    count: int,
    exact: bool,
) -> Measured:
    """The levels, with the frequency and duty cycle the edges give: they are
    every ``step``'th sample's."""
    said = {
        "samples": count,
        "minimum": levels.low,
        "maximum": levels.high,
        "mean": levels.mean,
        "rms": levels.rms,
        "exact": exact,
    }
    if len(rises) < 2 or rate <= 0:
        return Measured(**said)
    first, last = int(rises[0]), int(rises[-1])
    # A rise and a fall take turns, so each fall between the first rise and
    # the last is the end of the high that the rise before it began.
    inside = falls[(falls > first) & (falls < last)]
    high = int((inside - rises[: len(inside)]).sum())
    return Measured(
        **said,
        frequency=(len(rises) - 1) * rate / (step * (last - first)),
        duty=high / (last - first),
    )
