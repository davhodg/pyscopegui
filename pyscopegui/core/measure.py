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
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: Either side of the middle, as a share of peak to peak, that the signal has
#: to get clear of to count as having crossed it.
BAND = 0.1
#: Smaller than this, peak to peak, is flat: there is nothing to cross.
FLAT = 1e-9


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

    @property
    def peak_to_peak(self) -> float:
        return self.maximum - self.minimum

    @property
    def period(self) -> float | None:
        return 1.0 / self.frequency if self.frequency else None


def rising_edges(samples: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Where the signal rises through the middle of its range, and where it is
    high: the indices of the rising edges, and for each sample 1 high, 0 low,
    or -1 before it was first clear of the band either way."""
    low, high = float(samples.min()), float(samples.max())
    middle, band = (low + high) / 2, (high - low) * BAND
    state = np.full(len(samples), -1, dtype=np.int8)
    state[samples > middle + band] = 1
    state[samples < middle - band] = 0
    # Inside the band, it is what it was last: carried forward.
    known = np.where(state >= 0, np.arange(len(state)), 0)
    np.maximum.accumulate(known, out=known)
    # Before it was first clear of the band, index nought is what is carried: -1 there.
    held = state[known]
    edges = np.flatnonzero((held[1:] == 1) & (held[:-1] == 0)) + 1
    return edges, held


def measure(samples: np.ndarray, rate: float) -> Measured | None:
    """Measure a stretch of samples taken at this rate. None with fewer than two."""
    values = np.asarray(samples, dtype=np.float64)
    values = values[~np.isnan(values)]
    if len(values) < 2:
        return None
    low, high = float(values.min()), float(values.max())
    measured = {
        "samples": len(values),
        "minimum": low,
        "maximum": high,
        "mean": float(values.mean()),
        "rms": float(np.sqrt(np.mean(values * values))),
    }
    if high - low <= FLAT or rate <= 0:
        return Measured(**measured)
    edges, held = rising_edges(values)
    if len(edges) < 2:
        return Measured(**measured)
    first, last = int(edges[0]), int(edges[-1])
    cycles = len(edges) - 1
    return Measured(
        **measured,
        frequency=cycles * rate / (last - first),
        duty=float(np.count_nonzero(held[first:last] == 1)) / (last - first),
    )
