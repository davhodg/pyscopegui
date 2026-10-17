# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The samples held for each channel, and how they are cut down to be drawn.

Everything stays in NumPy arrays and nothing here loops over samples: a
million a second is nothing to an array operation and a great deal to a
Python loop.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import numpy as np
from PySide6.QtCore import QObject, Signal

from pyscopegui.backends.base import ANALOG, Block, Channel
from pyscopegui.core.decoding import Decoding, Setup, decoding_for
from pyscopegui.core.maths import Maths, Worker

#: How much of each channel is kept, in seconds, before the oldest is dropped,
#: unless Tools > Settings > History says otherwise.
HISTORY_S = 10.0
#: What History offers, in seconds.
HISTORIES = (1.0, 10.0, 30.0, 60.0, 300.0, 600.0)
#: How much longer than its capacity a record's array is. The newest samples
#: are copied back to the start each time this much has been written past
#: them, so less of it means more copying and more of it means more memory.
SLACK = 0.5
#: The least history a run is started with when memory is short, in seconds:
#: less than this, and it is not started at all.
LEAST_S = 0.1


def _dtype(channel: Channel) -> type:
    """What a channel's samples are held as: a number, or a logic level."""
    return np.float32 if channel.kind == ANALOG else np.uint8


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
        self._buffer = np.zeros(
            self.capacity + max(1, int(self.capacity * SLACK)), dtype=_dtype(channel)
        )
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
    #: Frames decoded from a block as it arrived: the decoding, the frames,
    #: and how many samples of the channel had arrived by then -- so how long
    #: ago each frame was. Not those found when a channel is first decoded.
    decoded = Signal(object, object, int)

    def __init__(self, history_s: float = HISTORY_S, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.history_s = history_s
        self.records: dict[str, Record] = {}
        #: Maths channels of this instrument's: worked out as blocks arrive,
        #: and held as channels of their own. See pyscopegui.core.maths.
        self.maths: list[Maths] = []
        #: What works each out, block after block, by its key: carrying what
        #: a rate of change, an integral or an average needs from the last.
        self._workers: dict[str, Worker] = {}
        #: Channels decoded as CAN buses, kept up to date as blocks arrive.
        #: See pyscopegui.core.decoding.
        self.decodings: list[Decoding] = []

    def set_channels(
        self,
        channels: list[Channel],
        rate: float,
        capacity: int | None = None,
        room: Callable[[], int | None] | None = None,
    ) -> None:
        """Start again, empty, for these channels at this rate, and with
        nothing decoded yet.

        Room for the history's worth of samples, unless a capacity is given:
        an instrument that sends sweeps holds one sweep, whatever its length.
        ``room``, asked once what was held before has been let go, is how many
        bytes the history may take, or None for no limit: a history that
        would take more is cut down to what fits, and held_s says how long it
        is. MemoryError if that is less than LEAST_S, or if the memory is not
        there; what was held before is gone either way.
        """
        self.records = {}
        for decoding in self.decodings:
            decoding.reset()
        if capacity is None:
            capacity = int(rate * self.history_s)
            most = room() if room is not None else None
            if most is not None and capacity > (fits := int(most // self._each(channels))):
                if fits < rate * LEAST_S:
                    self.channels_changed.emit()
                    raise MemoryError(f"room for {fits} samples a channel")
                capacity = fits
        try:
            self.records = {c.key: Record(c, rate, capacity) for c in channels}
            self._workers = {}  # a new run: nothing came before
            for maths, channel in self._maths_channels():
                self.records[maths.key] = Record(channel, rate, capacity)
        finally:
            self.channels_changed.emit()

    def _each(self, channels: list[Channel]) -> float:
        """Bytes a sample of every one of these channels takes, held: with its
        maths channels, and the slack a record has on top."""
        analog = {c.key for c in channels if c.kind == ANALOG}
        maths = sum(1 for m in self.maths if all(key in analog for key in m.sources))
        each = sum(np.dtype(_dtype(c)).itemsize for c in channels)
        each += maths * np.dtype(np.float32).itemsize
        return max(each, 1) * (1 + SLACK)

    def held_s(self) -> float:
        """How long a stretch of each channel is held, in seconds: the history,
        or less, where there was not the memory for all of it."""
        return min((r.capacity / r.rate for r in self.records.values()), default=0.0)

    def _maths_channels(self) -> list[tuple[Maths, Channel]]:
        """Each maths channel there are the channels for, and what it is."""
        found = []
        for maths in self.maths:
            records = [self.records.get(key) for key in maths.sources]
            if all(r is not None and r.channel.kind == ANALOG for r in records):
                found.append((maths, maths.channel(*(r.channel for r in records))))
        return found

    def set_maths(self, maths: list[Maths]) -> None:
        """These maths channels and no others, worked out at once from what is held."""
        self.maths = list(dict.fromkeys(maths))
        wanted = {m.key for m in self.maths}
        for key in [key for key in self.records if key.startswith("maths:")]:
            if key not in wanted:
                del self.records[key]
        for key in [key for key in self._workers if key not in wanted]:
            del self._workers[key]
        for maths, channel in self._maths_channels():
            if maths.key in self.records:
                continue
            sources = [self.records[key] for key in maths.sources]
            a = sources[0]
            record = Record(channel, a.rate, a.capacity)
            first = max(r.first for r in sources)
            last = min(r.total for r in sources)
            record.total = first  # numbered as the samples it is worked out from
            worker = self._workers[maths.key] = Worker(maths, a.rate)
            if last > first:
                record.append(
                    worker.take(*(r.view()[first - r.first : last - r.first] for r in sources))
                )
            self.records[maths.key] = record
        self.channels_changed.emit()

    def _with_maths(self, block: Block) -> Block:
        """The block, with each maths channel worked out from it."""
        if not self.maths:
            return block
        data = dict(block.data)
        for maths in self.maths:
            record = self.records.get(maths.key)
            if record is None or not all(key in data for key in maths.sources):
                continue
            worker = self._workers.get(maths.key)
            if worker is None:
                worker = self._workers[maths.key] = Worker(maths, block.rate)
            if block.sweep or block.first != record.total:
                # Complete in itself, or after a gap: nothing to carry on from.
                worker.reset()
            data[maths.key] = worker.take(*(data[key] for key in maths.sources), rate=block.rate)
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
        for worker in self._workers.values():
            worker.reset()
        for decoding in self.decodings:
            decoding.reset()

    # --- decoded --------------------------------------------------------------------------
    def set_decodings(self, setups: list[Setup]) -> None:
        """These buses decoded and no others. One that is new is decoded at once
        from what is held; one that was there already is left as it is."""
        had = {decoding.setup: decoding for decoding in self.decodings}
        self.decodings = []
        for setup in dict.fromkeys(setups):
            if (decoding := had.get(setup)) is None:
                decoding = decoding_for(setup)
                if (held := self._held(setup.channels())) is not None:
                    decoding.take_block(held)
            self.decodings.append(decoding)

    def _held(self, keys: tuple[str, ...]) -> Block | None:
        """What is held of these channels, as one block: the stretch they all
        have. None where any of them is missing, or has nothing."""
        records = [self.records.get(key) for key in keys]
        if any(record is None or not record.count for record in records):
            return None
        first = max(record.first for record in records)
        last = min(record.total for record in records)
        if last <= first:
            return None
        data = {
            key: record.view()[first - record.first : last - record.first]
            for key, record in zip(keys, records, strict=True)
        }
        return Block(first, records[0].rate, data, sweep=True)

    def _decode(self, block: Block) -> None:
        """Each decoded bus's share of a block: its channels, read on from the last."""
        for decoding in self.decodings:
            if decoding.paused:
                continue
            found = decoding.take_block(block)
            held = [self.records[k].first for k in decoding.setup.channels() if k in self.records]
            if held:
                decoding.forget_before(max(held))
            if found:
                self.decoded.emit(decoding, found, block.first + len(block))

    def add(self, block: Block) -> None:
        block = self._with_maths(block)
        if block.sweep:
            self._take_sweep(block)
            self._decode(block)
            return
        missing = 0
        for key, samples in block.data.items():
            if (record := self.records.get(key)) is None:
                continue
            if block.first > record.total:
                missing = block.first - record.total
                record.skip(missing)
            record.append(samples)
        self._decode(block)
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
