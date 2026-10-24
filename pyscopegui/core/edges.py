# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Where a logic level changes, for the decoders: found with NumPy, carried on
from one block to the next by the level the last block ended at."""

from __future__ import annotations

import numpy as np


def rises(before: bool, levels: np.ndarray) -> np.ndarray:
    """The samples at which the level goes from low to high: the first high
    one. ``before`` is the level just before the first sample."""
    previous = np.concatenate(([bool(before)], levels[:-1]))
    return np.flatnonzero(levels & ~previous)


def falls(before: bool, levels: np.ndarray) -> np.ndarray:
    """The samples at which the level goes from high to low: the first low one."""
    previous = np.concatenate(([bool(before)], levels[:-1]))
    return np.flatnonzero(~levels & previous)


def changes(before: bool, levels: np.ndarray) -> np.ndarray:
    """The samples at which the level changes, either way."""
    previous = np.concatenate(([bool(before)], levels[:-1]))
    return np.flatnonzero(levels != previous)


def last(levels: np.ndarray, before: bool) -> bool:
    """The level the block ends at: what comes before the next one."""
    return bool(levels[-1]) if len(levels) else before


def number(bits, msb_first: bool = True) -> int:
    """Bits as a number: the first the most significant, or the least."""
    value = 0
    for bit in bits if msb_first else reversed(bits):
        value = (value << 1) | int(bit)
    return value


# --- a level with hysteresis, found where the signal gets clear of the band ---------------------
def starts(clear: np.ndarray) -> np.ndarray:
    """Where each run of samples that are clear of the band starts. One that
    runs on from the block before starts again at nought: that is harmless,
    as it only says again what the level already is."""
    found = np.flatnonzero(clear[1:] > clear[:-1]) + 1
    if len(clear) and clear[0]:
        found = np.concatenate(([0], found))
    return found


def crossings(
    ups: np.ndarray, downs: np.ndarray, before: int
) -> tuple[np.ndarray, np.ndarray, int]:
    """Where a level with hysteresis changes, from where the signal gets clear
    above the band (``ups``) and below it (``downs``): the samples it changes
    at, whether each is to high (1) or to low (0), and the level it ends at.

    ``before`` is the level before the first sample: 1, 0, or -1 for not
    clear of the band yet, when the first it gets clear is not a change.
    Only these few positions are looked at, never every sample.
    """
    at = np.concatenate((ups, downs)).astype(np.int64)
    into = np.concatenate((np.ones(len(ups), np.int8), np.zeros(len(downs), np.int8)))
    order = np.argsort(at, kind="stable")
    at, into = at[order], into[order]
    if not len(into):
        return at, into, before
    previous = np.concatenate(([before], into[:-1]))
    # Getting clear for the first time is no change: it was neither before.
    changed = previous == 1 - into
    return at[changed], into[changed], int(into[-1])


class Steps:
    """A logic level over a block of samples, as the samples it changes at:
    what the decoders and the triggers need, without a value for every sample."""

    def __init__(self, before: bool, at: np.ndarray, count: int) -> None:
        #: The level just before the first sample, and where it changes after that.
        self.before = bool(before)
        self.at = np.asarray(at, dtype=np.int64)
        self.count = count

    def __len__(self) -> int:
        return self.count

    @property
    def after(self) -> bool:
        """The level at the end: what comes before the next block."""
        return self.before != bool(len(self.at) % 2)

    def rises(self) -> np.ndarray:
        """The samples at which it goes from low to high: the first high one."""
        return self.at[1 if self.before else 0 :: 2]

    def falls(self) -> np.ndarray:
        """The samples at which it goes from high to low: the first low one."""
        return self.at[0 if self.before else 1 :: 2]

    def each(self) -> np.ndarray:
        """The level each change goes to."""
        return (np.arange(len(self.at)) % 2 == 0) != self.before

    def level_at(self, samples: np.ndarray) -> np.ndarray:
        """The level at each of these samples."""
        changes = np.searchsorted(self.at, samples, side="right")
        return (changes % 2 == 1) != self.before

    def inverted(self) -> Steps:
        return Steps(not self.before, self.at, self.count)

    def from_level(self, before: bool) -> Steps:
        """The same levels, with a different level before them: a change at
        the first sample appears, or goes, to make up the difference."""
        if bool(before) == self.before:
            return self
        if len(self.at) and self.at[0] == 0:
            return Steps(before, self.at[1:], self.count)
        if not self.count:
            return Steps(before, self.at, 0)
        return Steps(before, np.concatenate(([0], self.at)), self.count)

    def any_high(self, start: np.ndarray, stop: np.ndarray) -> np.ndarray:
        """Whether it is high anywhere in each stretch from ``start`` up to ``stop``."""
        start, stop = np.asarray(start, dtype=np.int64), np.asarray(stop, dtype=np.int64)
        rises = self.rises()
        later = np.searchsorted(rises, stop, side="left") - np.searchsorted(rises, start, "right")
        return (start < stop) & (self.level_at(start) | (later > 0))


def combined(steps: list[Steps], how) -> Steps:
    """Several levels over the same samples made one: ``how`` takes their
    levels, as arrays, and gives the one level they make."""
    count = steps[0].count
    at = np.unique(np.concatenate([each.at for each in steps]))
    before = bool(how(*[np.array([each.before]) for each in steps])[0])
    levels = how(*[each.level_at(at) for each in steps])
    previous = np.concatenate(([before], levels[:-1]))
    return Steps(before, at[levels != previous], count)
