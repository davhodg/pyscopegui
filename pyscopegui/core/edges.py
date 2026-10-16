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
