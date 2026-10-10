# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""An instrument that needs no hardware: two analog and four digital channels.

Something to look at on a first run, and what the tests read. Every sample is
a function of its number alone, so the same stretch of time always holds the
same data whichever blocks it happened to arrive in.
"""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QObject, QTimer

from pyscopegui.backends.base import DIGITAL, Block, Channel, Instrument

RATE = 100_000.0
#: How often a block is sent. Twenty a second is smooth to watch and far
#: fewer calls than Python would notice.
TICK_MS = 50
#: The most one block holds. A computer that was asleep, or a window dragged
#: for a second, would otherwise be answered with everything it missed at once.
MOST_S = 0.5

SINE_HZ = 50.0
RAMP_HZ = 7.0
#: Samples per half period of the fastest digital channel: 1 kHz at RATE.
#: Each channel after it is half the rate of the one before, as a counter's bits are.
CLOCK_HALF = 50

CHANNELS = [
    Channel("A", "A: sine"),
    Channel("B", "B: ramp"),
    *(Channel(f"D{bit}", f"D{bit}", DIGITAL, "") for bit in range(4)),
]


def samples(first: int, count: int) -> dict[str, np.ndarray]:
    """What every channel reads for ``count`` samples starting at ``first``."""
    n = np.arange(first, first + count, dtype=np.int64)
    t = n / RATE
    data = {
        "A": (2.0 * np.sin(2 * np.pi * SINE_HZ * t)).astype(np.float32),
        "B": ((t * RAMP_HZ) % 1.0 - 0.5).astype(np.float32),
    }
    counter = n // CLOCK_HALF
    for bit in range(4):
        data[f"D{bit}"] = ((counter >> bit) & 1).astype(np.uint8)
    return data


class DemoInstrument(Instrument):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self, interval=TICK_MS, timeout=self._tick)
        self._started = 0.0
        self._sent = 0

    def channels(self) -> list[Channel]:
        return list(CHANNELS)

    @property
    def rate(self) -> float:
        return RATE

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def start(self) -> None:
        if self.running:
            return
        self._started = time.perf_counter()
        self._sent = 0
        self._timer.start()
        self.state_changed.emit(True)

    def stop(self) -> None:
        if not self.running:
            return
        self._timer.stop()
        self.state_changed.emit(False)

    def _tick(self) -> None:
        """Send the samples that have fallen due since the last block."""
        due = int((time.perf_counter() - self._started) * RATE) - self._sent
        if due > MOST_S * RATE:
            # Skipped rather than made up late: the sample count is the clock,
            # so the gap is said as a gap and the capture keeps its time.
            self._sent += due - int(MOST_S * RATE)
            due = int(MOST_S * RATE)
        if due <= 0:
            return
        self.block.emit(Block(self._sent, RATE, samples(self._sent, due)))
        self._sent += due
