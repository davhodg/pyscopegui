# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""A stretch of held samples, compared with a level as they are held.

A PicoScope's channel is held as the driver's counts and a mixed-signal
scope's logic inputs eight to a byte. Asking whether a sample is above a
level need not turn every one of them into volts, or into a 0 or a 1: the
level is turned into a count instead, once, and the counts compared with it
as they are; a logic input is its bit of the byte. The answer is the same as
comparing what the samples are in the channel's unit.
"""

from __future__ import annotations

import operator
from functools import lru_cache

import numpy as np

from pyscopegui.backends.base import LOST, Scale
from pyscopegui.core.edges import starts

#: The comparisons asked for, by what they are written as.
COMPARE = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}
#: Every count but LOST, lowest first.
_COUNTS = np.arange(LOST + 1, 1 << 15, dtype=np.int16)


@lru_cache(maxsize=8)
def _volts(scale: Scale) -> np.ndarray:
    """What every count but LOST is in the channel's unit, worked out just as
    a sample's own would be."""
    return scale.apply(_COUNTS)


@lru_cache(maxsize=64)
def _bounds(scale: Scale, compare: str, level: float) -> tuple[int, int] | None:
    """The lowest and highest count whose value compares as asked with the
    level: None for none. A scale only ever goes up or only down, so those
    that do are all the counts between."""
    found = np.flatnonzero(COMPARE[compare](_volts(scale), level))
    if not len(found):
        return None
    if found[-1] - found[0] + 1 != len(found):
        raise ValueError(f"{scale} does not go one way")
    return int(_COUNTS[found[0]]), int(_COUNTS[found[-1]])


class Stretch:
    """Samples of one channel, as they are held: an array in its unit, a
    logic input's 0s and 1s, counts with the scale each part of them came
    with, or one bit of a port's bytes."""

    def __init__(
        self,
        held: np.ndarray,
        scales: list[tuple[int, int, Scale]] | None = None,
        bit: int | None = None,
    ) -> None:
        self.held = held
        #: For counts: (from, to, scale) for each part, counted from the first sample.
        self.scales = scales
        #: For a port: which of its inputs.
        self.bit = bit

    @classmethod
    def of(cls, samples: np.ndarray | Stretch) -> Stretch:
        """Samples already in their unit, as a stretch: or a stretch as it is."""
        return samples if isinstance(samples, Stretch) else cls(np.asarray(samples))

    def __len__(self) -> int:
        return len(self.held)

    @property
    def digital(self) -> bool:
        """Whether it is a logic input, 0 or 1, rather than a reading."""
        return self.bit is not None or self.held.dtype.kind in "ub"

    def first(self):
        """The first sample, in the channel's unit."""
        if self.bit is not None:
            return (int(self.held[0]) >> self.bit) & 1
        if self.scales is not None:
            return self.scales[0][2].apply(self.held[:1])[0]
        return self.held[0]

    def starts(self, compare: str, level: float) -> np.ndarray:
        """Where each run of samples that compare with the level as asked --
        ">", ">=", "<" or "<=" -- starts. A gap compares as nothing."""
        held = self.held
        if not len(held):
            return np.empty(0, dtype=np.int64)
        if self.bit is not None:
            low, high = (bool(COMPARE[compare](value, level)) for value in (0, 1))
            if low and high:
                return np.zeros(1, dtype=np.int64)
            if not (low or high):
                return np.empty(0, dtype=np.int64)
            ones = (held & np.uint8(1 << self.bit)) != 0
            return starts(ones if high else ~ones)
        if self.scales is None:
            with np.errstate(invalid="ignore"):
                return starts(COMPARE[compare](held, level))
        found = [
            self._counted(held[begin:end], scale, compare, level) + begin
            for begin, end, scale in self.scales
        ]
        return np.concatenate(found) if found else np.empty(0, dtype=np.int64)

    @staticmethod
    def _counted(counts: np.ndarray, scale: Scale, compare: str, level: float) -> np.ndarray:
        bounds = _bounds(scale, compare, level)
        if bounds is None or not len(counts):
            return np.empty(0, dtype=np.int64)
        low, high = bounds
        if low > LOST + 1:
            # LOST is the least count, so it is below every bound but the lowest.
            clear = counts >= low if high == _COUNTS[-1] else (counts >= low) & (counts <= high)
            return starts(clear)
        found = starts(counts <= high)
        # A run that starts with LOST starts at its first reading, if it has one.
        lost = np.flatnonzero(counts[found] == LOST)
        if not len(lost):
            return found
        keep = np.ones(len(found), dtype=bool)
        for index in lost.tolist():
            at = int(found[index])
            readings = np.flatnonzero(counts[at:] != LOST)
            first = at + int(readings[0]) if len(readings) else len(counts)
            if first < len(counts) and counts[first] <= high:
                found[index] = first
            else:
                keep[index] = False
        return found[keep]
