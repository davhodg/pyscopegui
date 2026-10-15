# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The samples held for each channel, and how they are cut down to be drawn.

Everything stays in NumPy arrays and nothing here loops over samples: a
million a second is nothing to an array operation and a great deal to a
Python loop.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
from PySide6.QtCore import QObject, Signal

from pyscopegui.backends.base import ANALOG, Block, Channel
from pyscopegui.core.maths import Maths

#: How much of each channel is kept, in seconds, before the oldest is dropped,
#: unless Tools > Settings > History says otherwise.
HISTORY_S = 10.0
#: What History offers, in seconds.
HISTORIES = (1.0, 10.0, 30.0, 60.0, 300.0, 600.0)
#: How much longer than its capacity a record's array is. The newest samples
#: are copied back to the start each time this much has been written past
#: them, so less of it means more copying and more of it means more memory.
SLACK = 0.5


class Record:
    """The newest samples of one channel, as one contiguous array.

    Half as much again as the capacity is allocated and samples are written
    on at the end; when the end is reached the newest are copied back to the
    start. So what is held is always one slice, never two to be joined, and
    the copy is paid once per half a capacity of samples rather than once per
    block.
    """

    def __init__(self, channel: Channel, rate: float, capacity: int) -> None:
        self.channel = channel
        self.rate = rate
        self.capacity = max(1, int(capacity))
        dtype = np.float32 if channel.kind == ANALOG else np.uint8
        self._buffer = np.zeros(self.capacity + max(1, int(self.capacity * SLACK)), dtype=dtype)
        self._end = 0
        #: Samples ever written, which is the number of the next one.
        self.total = 0
        self.count = 0

    @property
    def memory_bytes(self) -> int:
        return self._buffer.nbytes

    @property
    def first(self) -> int:
        """The number of the oldest sample still held."""
        return self.total - self.count

    def append(self, samples: np.ndarray) -> None:
        new = len(samples)
        self.total += new
        if new >= self.capacity:
            self._buffer[: self.capacity] = samples[-self.capacity :]
            self._end = self.count = self.capacity
            return
        if self._end + new > len(self._buffer):
            keep = min(self.count, self.capacity - new)
            self._buffer[:keep] = self._buffer[self._end - keep : self._end]
            self._end = keep
        self._buffer[self._end : self._end + new] = samples
        self._end += new
        self.count = min(self.count + new, self.capacity)

    def empty(self) -> None:
        """Hold nothing, and count from nought again."""
        self._end = self.total = self.count = 0

    def skip(self, missing: int) -> None:
        """Samples that never arrived: held as a gap, so later ones keep their time."""
        blank = np.nan if self._buffer.dtype.kind == "f" else 0
        self.append(np.full(min(missing, self.capacity), blank, dtype=self._buffer.dtype))
        self.total += missing - min(missing, self.capacity)

    def view(self) -> np.ndarray:
        """Everything held, oldest first. A view: copy it to keep it."""
        return self._buffer[self._end - self.count : self._end]

    def between(self, t_from: float, t_to: float) -> tuple[int, np.ndarray]:
        """The samples in this stretch of time, and the number of the first of them."""
        start = max(self.first, int(np.floor(t_from * self.rate)))
        stop = min(self.total, int(np.ceil(t_to * self.rate)) + 1)
        if stop <= start:
            return start, self._buffer[:0]
        held = self.view()
        return start, held[start - self.first : stop - self.first]


class Capture(QObject):
    """Every channel's record, filled from the blocks an instrument sends."""

    #: The set of channels changed: whatever lists them needs rebuilding.
    channels_changed = Signal()
    #: Samples went missing between two blocks: how many.
    gap = Signal(int)

    def __init__(self, history_s: float = HISTORY_S, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.history_s = history_s
        self.records: dict[str, Record] = {}
        #: Maths channels of this instrument's: worked out as blocks arrive,
        #: and held as channels of their own. See pyscopegui.core.maths.
        self.maths: list[Maths] = []

    def set_channels(
        self, channels: list[Channel], rate: float, capacity: int | None = None
    ) -> None:
        """Start again, empty, for these channels at this rate.

        Room for the history's worth of samples, unless a capacity is given:
        an instrument that sends sweeps holds one sweep, whatever its length.
        MemoryError if that is more than there is room for; what was held
        before is gone either way.
        """
        self.records = {}
        if capacity is None:
            capacity = int(rate * self.history_s)
        try:
            self.records = {c.key: Record(c, rate, capacity) for c in channels}
            for maths, channel in self._maths_channels():
                self.records[maths.key] = Record(channel, rate, capacity)
        finally:
            self.channels_changed.emit()

    def _maths_channels(self) -> list[tuple[Maths, Channel]]:
        """Each maths channel there are both channels for, and what it is."""
        found = []
        for maths in self.maths:
            a, b = self.records.get(maths.a), self.records.get(maths.b)
            if a is not None and b is not None and ANALOG == a.channel.kind == b.channel.kind:
                found.append((maths, maths.channel(a.channel, b.channel)))
        return found

    def set_maths(self, maths: list[Maths]) -> None:
        """These maths channels and no others, worked out at once from what is held."""
        self.maths = list(dict.fromkeys(maths))
        wanted = {m.key for m in self.maths}
        for key in [key for key in self.records if key.startswith("maths:")]:
            if key not in wanted:
                del self.records[key]
        for maths, channel in self._maths_channels():
            if maths.key in self.records:
                continue
            a, b = self.records[maths.a], self.records[maths.b]
            record = Record(channel, a.rate, a.capacity)
            first, last = max(a.first, b.first), min(a.total, b.total)
            record.total = first  # numbered as the samples it is worked out from
            if last > first:
                record.append(
                    maths.work_out(
                        a.view()[first - a.first : last - a.first],
                        b.view()[first - b.first : last - b.first],
                    )
                )
            self.records[maths.key] = record
        self.channels_changed.emit()

    def _with_maths(self, block: Block) -> Block:
        """The block, with each maths channel worked out from it."""
        if not self.maths:
            return block
        data = dict(block.data)
        for maths in self.maths:
            if maths.key in self.records and maths.a in data and maths.b in data:
                data[maths.key] = maths.work_out(data[maths.a], data[maths.b])
        return replace(block, data=data)

    def update_channels(self, channels: list[Channel]) -> None:
        """Take up what has changed about channels that are still the same
        channels -- a range, and so a name -- and keep what is held of them."""
        for channel in channels:
            if (record := self.records.get(channel.key)) is not None:
                record.channel = channel
        # Named for the channels they are worked out from, which may have changed.
        for maths, channel in self._maths_channels():
            if (record := self.records.get(maths.key)) is not None:
                record.channel = channel
        self.channels_changed.emit()

    def memory_bytes(self) -> int:
        """What the records take when they are full."""
        return sum(record.memory_bytes for record in self.records.values())

    def clear(self) -> None:
        """Throw away what is held, and count samples from zero again."""
        for key, record in list(self.records.items()):
            self.records[key] = Record(record.channel, record.rate, record.capacity)

    def add(self, block: Block) -> None:
        block = self._with_maths(block)
        if block.sweep:
            self._take_sweep(block)
            return
        missing = 0
        for key, samples in block.data.items():
            if (record := self.records.get(key)) is None:
                continue
            if block.first > record.total:
                missing = block.first - record.total
                record.skip(missing)
            record.append(samples)
        # A pause the instrument took on purpose is a gap on the plot and
        # nothing to warn about.
        if missing and not block.after_pause:
            self.gap.emit(missing)

    def _take_sweep(self, block: Block) -> None:
        """Hold this sweep in place of whatever was held, at its own rate and length."""
        for key, samples in block.data.items():
            if (record := self.records.get(key)) is None:
                continue
            if record.rate != block.rate or record.capacity != len(samples):
                record = Record(record.channel, block.rate, len(samples))
                self.records[key] = record
            else:
                record.empty()
            record.append(samples)

    def newest(self) -> float | None:
        """The time of the latest sample held, in seconds, or None if there are none."""
        ends = [r.total / r.rate for r in self.records.values() if r.count]
        return max(ends) if ends else None

    def oldest(self) -> float | None:
        starts = [r.first / r.rate for r in self.records.values() if r.count]
        return min(starts) if starts else None

    def stored(self) -> int:
        return sum(r.count for r in self.records.values())


def min_max(samples: np.ndarray, columns: int) -> tuple[np.ndarray, np.ndarray]:
    """Cut samples down to a lowest and a highest for each column of the screen.

    A plot a thousand pixels wide cannot show a million samples, and drawing
    every one of them is slow and looks the same as drawing these: each column
    is a vertical line from the least it held to the most. Taking every
    thousandth sample instead would be quicker still and would lose every
    spike narrower than a column, which is the one thing a scope is for.

    Returns positions within ``samples`` and the values at them. Few enough
    samples are returned as they are.
    """
    count = len(samples)
    if columns < 1 or count <= 2 * columns:
        return np.arange(count), samples
    per = -(-count // columns)  # rounded up, so the last column is the short one
    whole = count // per
    bins = samples[: whole * per].reshape(whole, per)
    # fmin and fmax pass over a gap's NaN where there is anything else to take.
    low, high = np.fmin.reduce(bins, axis=1), np.fmax.reduce(bins, axis=1)
    if whole * per < count:
        rest = samples[whole * per :]
        low = np.append(low, np.fmin.reduce(rest))
        high = np.append(high, np.fmax.reduce(rest))
    values = np.empty(2 * len(low), dtype=samples.dtype)
    values[0::2], values[1::2] = low, high
    positions = np.repeat(np.arange(len(low)) * per, 2)
    positions[1::2] += per - 1
    positions[-1] = count - 1
    return positions, values
