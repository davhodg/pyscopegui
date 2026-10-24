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

from pyscopegui.backends.base import ANALOG, DIGITAL, LOST, Block, Channel, Scale, unpacked
from pyscopegui.core.decoding import Decoding, Setup, decoding_for
from pyscopegui.core.maths import Maths, Worker
from pyscopegui.core.stretch import Stretch

#: How much of each channel is kept, in seconds, before the oldest is dropped,
#: unless Tools > Settings > History says otherwise.
HISTORY_S = 10.0
#: What History offers, in seconds.
HISTORIES = (1.0, 10.0, 30.0, 60.0, 300.0, 600.0)
#: Samples summed up together as they arrive -- their lowest and highest --
#: for drawing a long stretch from: see Record.drawn.
SUMMED = 256
#: How many of those a column has to span to be drawn from them. Fewer, and
#: going through every sample is as quick: a few million of them is.
SUMMARY_FROM = 32
#: The least history a run is started with when memory is short, in seconds:
#: less than this, and it is not started at all.
LEAST_S = 0.1


def _dtype(channel: Channel) -> type:
    """What a channel's samples are held as: a number, the instrument's own
    counts of one, or a logic level."""
    if channel.kind != ANALOG:
        return np.uint8
    return np.int16 if channel.counts else np.float32


class Record:
    """The newest samples of one channel, round in a ring.

    Each sample is written where its number, over the length of the array,
    leaves it: the newest over the oldest, and nothing ever copied about.
    The array is as long as the capacity, to the next whole SUMMED, so that
    where it goes round is where two of those meet. A stretch read across
    that point is two pieces: drawing takes each as it is, and whatever else
    reads it has them joined, which is a copy of no more than was asked for.

    A channel sent as counts is held as counts, with the scale each stretch
    of them came with -- the range can change while it runs -- and is turned
    into its unit only where it is looked at: see ``values`` and ``drawn``.
    """

    def __init__(self, channel: Channel, rate: float, capacity: int) -> None:
        self.channel = channel
        self.rate = rate
        self.capacity = max(1, int(capacity))
        self._buffer = np.zeros(-(-self.capacity // SUMMED) * SUMMED, dtype=_dtype(channel))
        #: Samples ever written, which is the number of the next one.
        self.total = 0
        self.count = 0
        #: Held as counts, and if so (the number of the first sample it is
        #: for, its scale), oldest first; the first is taken for the oldest held.
        self.counts = self._buffer.dtype == np.int16
        self._scales: list[tuple[int, Scale]] = []
        #: For a port: the last stretch cut down to be drawn, kept for the next
        #: of its inputs to ask for the same.
        self._packed_drawn: tuple | None = None
        #: What was last drawn of it: (from, to, its lowest, its highest), for a
        #: measurement over the same stretch while it runs. See ``drawn``.
        self.last_drawn: tuple[int, int, float, float] | None = None
        #: Goes up each time what is held is thrown away for something else, as
        #: a new sweep is. Otherwise a sample, once held, never changes, so what
        #: was worked out from a stretch of them stands while the stretch does.
        self.resets = 0
        #: The lowest and highest of each SUMMED samples, kept as they arrive,
        #: round in a ring as the samples are; and the first sample they are
        #: right from. For logic levels, the bits that are 1 throughout and
        #: those that are 1 anywhere, which for an input of its own, 0 or 1,
        #: are its lowest and highest too.
        slots = len(self._buffer) // SUMMED
        self._lows = np.empty(slots, dtype=self._buffer.dtype)
        self._highs = np.empty(slots, dtype=self._buffer.dtype)
        self._summed_from = 0

    @property
    def memory_bytes(self) -> int:
        return self._buffer.nbytes + self._lows.nbytes + self._highs.nbytes

    @property
    def first(self) -> int:
        """The number of the oldest sample still held."""
        return self.total - self.count

    def append(self, samples: np.ndarray, scale: Scale | None = None) -> None:
        """Samples on the end: in the channel's unit, or counts with their scale."""
        if self.counts:
            if scale is None:
                raise ValueError(f"{self.channel.key} is held as counts: it needs their scale")
            if not self._scales or self._scales[-1][1] != scale:
                self._scales.append((self.total, scale))
        self._write(samples)
        while len(self._scales) > 1 and self._scales[1][0] <= self.first:
            del self._scales[0]

    def _write(self, samples: np.ndarray) -> None:
        new = len(samples)
        began = self.total
        self.total += new
        self.count = min(self.count + new, self.capacity)
        # More than it holds leaves only the newest: they go where their numbers say.
        kept = samples[-self.capacity :]
        self._put(self.total - len(kept), kept)
        self._sum(max(began, self.first))

    def _put(self, number: int, samples: np.ndarray) -> None:
        """Samples from this number on, each where its number puts it."""
        length = len(self._buffer)
        at = number % length
        first = min(len(samples), length - at)
        self._buffer[at : at + first] = samples[:first]
        self._buffer[: len(samples) - first] = samples[first:]

    def _pieces(self, start: int, stop: int) -> list[np.ndarray]:
        """Samples start to stop, by number, as they are held: one view of
        the array, or two where they go round its end. None for none."""
        if stop <= start:
            return []
        length = len(self._buffer)
        at = start % length
        if at + (stop - start) <= length:
            return [self._buffer[at : at + stop - start]]
        return [self._buffer[at:], self._buffer[: at + stop - start - length]]

    def _held(self, start: int, stop: int) -> np.ndarray:
        """Samples start to stop, by number, as they are held: a view, or
        where they go round the end of the array, the two pieces joined."""
        pieces = self._pieces(start, stop)
        if len(pieces) == 1:
            return pieces[0]
        if not pieces:
            return self._buffer[:0]
        return np.concatenate(pieces)

    def _sum(self, began: int) -> None:
        """Sum up again every SUMMED samples that what arrived from ``began`` is in.

        The last of them is only part there, and is summed again when more
        arrives. One whose first samples are no longer held is not summed:
        it is never drawn from. Where the array goes round is where two of
        them meet, so each piece of what is held is summed on its own.
        """
        first = -(-max(began // SUMMED * SUMMED, self.first) // SUMMED) * SUMMED
        if first >= self.total:
            return
        lows, highs = [], []
        for piece in self._pieces(first, self.total):
            whole = len(piece) // SUMMED
            parts = [piece[: whole * SUMMED].reshape(whole, SUMMED)] if whole else []
            low, high = _summed(parts, piece[whole * SUMMED :], self.counts)
            lows.append(low)
            highs.append(high)
        lows, highs = np.concatenate(lows), np.concatenate(highs)
        slots = len(self._lows)
        at = (first // SUMMED) % slots
        ahead = min(len(lows), slots - at)
        self._lows[at : at + ahead], self._highs[at : at + ahead] = lows[:ahead], highs[:ahead]
        self._lows[: len(lows) - ahead], self._highs[: len(lows) - ahead] = (
            lows[ahead:],
            highs[ahead:],
        )

    def empty(self) -> None:
        """Hold nothing, and count from nought again."""
        self.total = self.count = 0
        self._scales = []
        self.resets += 1
        self._summed_from = 0

    def skip(self, missing: int) -> None:
        """Samples that never arrived: held as a gap, so later ones keep their time."""
        blank = np.nan if self._buffer.dtype.kind == "f" else LOST if self.counts else 0
        if missing < self.capacity:
            self._write(np.full(missing, blank, dtype=self._buffer.dtype))
            return
        # Nothing but the gap is held then, wherever it is in the array: and
        # nothing summed up of it, so it is drawn sample by sample.
        self._buffer[:] = blank
        self.total += missing
        self.count = self.capacity
        self._summed_from = self.total

    def values(
        self, start: int | None = None, stop: int | None = None, step: int = 1
    ) -> np.ndarray:
        """Samples start to stop, by number -- everything held, by default --
        every ``step``'th, in the channel's unit. A view where it can be: copy
        it to keep it. Counts are worked out only for those asked for."""
        start = self.first if start is None else max(start, self.first)
        stop = max(start, self.total if stop is None else min(stop, self.total))
        pieces = self._pieces(start, stop)
        if len(pieces) == 2:
            # Every step'th of both, counted on across where they meet.
            second = pieces[1][(step - len(pieces[0]) % step) % step :: step]
            held = np.concatenate((pieces[0][::step], second))
        else:
            held = pieces[0][::step] if pieces else self._buffer[:0]
        if not self.counts:
            return held
        out = np.empty(len(held), dtype=np.float32)
        for begin, end, scale in self._stretches(start, stop):
            # The first and the last of those asked for in this stretch.
            part = slice(-(-(begin - start) // step), -(-(end - start) // step))
            scale.apply(held[part], out=out[part])
        return out

    def view(self) -> np.ndarray:
        """Everything held, oldest first, in the channel's unit: see ``values``."""
        return self.values()

    def copied(self, start: int, stop: int) -> Record:
        """Samples start to stop, by number, as a record of their own and still
        numbered as they are here: for a thread to write out while this one
        goes on filling. Copied as they are held, which is quick."""
        start = max(start, self.first)
        stop = max(start, min(stop, self.total))
        copy = Record(self.channel, self.rate, max(1, stop - start))
        copy._put(start, self._held(start, stop))
        copy.count, copy.total = stop - start, stop
        copy._scales = [(begin, scale) for begin, _end, scale in self._stretches(start, stop)]
        # Not summed up: a copy is written out, and not drawn.
        copy._summed_from = stop
        return copy

    def stretch(self, start: int, stop: int) -> Stretch:
        """Samples start to stop, by number, as they are held, to be compared
        with a level: see pyscopegui.core.stretch."""
        start = max(start, self.first)
        stop = max(start, min(stop, self.total))
        held = self._held(start, stop)
        if not self.counts:
            return Stretch(held)
        parts = [(b - start, e - start, scale) for b, e, scale in self._stretches(start, stop)]
        return Stretch(held, parts)

    def _stretches(self, start: int, stop: int):
        """(from, to, scale) for each part of samples start to stop with a scale of its own."""
        scales = self._scales
        for index, (begin, scale) in enumerate(scales):
            end = scales[index + 1][0] if index + 1 < len(scales) else stop
            begin, end = max(start if index == 0 else begin, start), min(end, stop)
            if begin < end:
                yield begin, end, scale

    @property
    def identity(self) -> tuple:
        """Which samples these are: the same, for as long as it says the same."""
        return id(self), self.resets

    def numbers(self, t_from: float, t_to: float) -> tuple[int, int]:
        """The numbers of the samples held in this stretch of time: from, and to."""
        start = max(self.first, int(np.floor(t_from * self.rate)))
        stop = min(self.total, int(np.ceil(t_to * self.rate)) + 1)
        return start, max(start, stop)

    def between(self, t_from: float, t_to: float) -> tuple[int, np.ndarray]:
        """The samples in this stretch of time, in the channel's unit, and the
        number of the first of them."""
        start, stop = self.numbers(t_from, t_to)
        return start, self.values(start, stop)

    def drawn(self, t_from: float, t_to: float, columns: int) -> tuple[int, np.ndarray, np.ndarray]:
        """This stretch of time cut down to be drawn this many columns wide:
        see ``min_max``. The number of its first sample, positions from it,
        and the values there in the channel's unit -- worked out from counts
        only for the few that are drawn."""
        start, stop = self.numbers(t_from, t_to)
        positions, picked = self._cut_down(start, stop, columns, packed=False)
        if self.counts:
            values = np.empty(len(picked), dtype=np.float32)
            numbers = start + positions
            for begin, end, scale in self._stretches(start, stop):
                inside = (numbers >= begin) & (numbers < end)
                values[inside] = scale.apply(picked[inside])
            picked = values
        self.last_drawn = _extremes(start, stop, picked)
        return start, positions, picked

    def _cut_down(
        self, start: int, stop: int, columns: int, packed: bool
    ) -> tuple[np.ndarray, np.ndarray]:
        """Samples start to stop as ``min_max`` cuts them down -- or for a port,
        ``min_max_packed`` -- and the same, but quicker for a long stretch:
        where a column spans SUMMARY_FROM SUMMED or more, the whole ones in it are
        taken from what was summed up as they arrived, and only the samples
        at its two ends are looked at."""
        count = stop - start
        if columns < 1 or count <= 2 * columns:
            return np.arange(count), self._held(start, stop)
        per = -(-count // columns)
        # Each column is samples begin to end; the whole SUMMED in it are
        # those from inside to outside.
        begins = start + np.arange(0, count, per)
        ends = np.minimum(begins + per, stop)
        inside = -(-begins // SUMMED)
        outside = ends // SUMMED
        if (
            start < self._summed_from
            or per < SUMMARY_FROM * SUMMED
            or (outside <= inside).any()  # a short last column with no whole one in it
        ):
            low, high = self._by_columns(start, stop, per, packed)
            return _as_drawn(low, high, per, count)
        dtype = self._buffer.dtype
        summed_lows, summed_highs = self._summed_between(int(inside[0]), int(outside[-1]))
        # Each column's whole ones, inside to outside, and between two columns
        # the ones they share an end of, which are left out: taken every
        # other one, and the last to the end.
        at = np.empty(2 * len(inside) - 1, dtype=np.int64)
        at[0::2], at[1::2] = inside - inside[0], outside[:-1] - inside[0]
        bits = packed or dtype == np.uint8
        if bits:
            low = np.bitwise_and.reduceat(summed_lows, at)[0::2]
            high = np.bitwise_or.reduceat(summed_highs, at)[0::2]
        elif dtype.kind == "f":
            low = np.fmin.reduceat(summed_lows, at)[0::2]
            high = np.fmax.reduceat(summed_highs, at)[0::2]
        else:
            low = np.minimum.reduceat(summed_lows, at)[0::2]
            high = np.maximum.reduceat(summed_highs, at)[0::2]
        # And the samples at either end of each column, fewer than SUMMED.
        end_low, end_high = self._ends(start, stop, begins, inside, outside, bits)
        if bits:
            low &= end_low
            high |= end_high
        elif dtype.kind == "f":
            low, high = np.fmin(low, end_low), np.fmax(high, end_high)
        else:
            low, high = np.minimum(low, end_low), np.maximum(high, end_high)
            if self.counts:
                # Above the highest is a column with no readings at all: a gap.
                low[low > high] = LOST
        return _as_drawn(low, high, per, count)

    def _by_columns(
        self, start: int, stop: int, per: int, packed: bool
    ) -> tuple[np.ndarray, np.ndarray]:
        """The lowest and highest -- for a port, the AND and the OR -- of every
        ``per`` samples from start to stop, the last of them maybe fewer: from
        every sample. Where the array goes round, each piece is cut down as
        it is, and only the column that spans the two is joined to be."""
        pieces = self._pieces(start, stop)
        if len(pieces) == 1:
            return _columns(pieces[0], per, packed)
        before, after = pieces
        whole = len(before) // per
        parts = [_columns(before[: whole * per], per, packed)] if whole else []
        rest = after
        if len(before) % per:
            joins = (whole + 1) * per - len(before)
            parts.append(
                _columns(np.concatenate((before[whole * per :], after[:joins])), per, packed)
            )
            rest = after[joins:]
        if len(rest):
            parts.append(_columns(rest, per, packed))
        return np.concatenate([low for low, _ in parts]), np.concatenate(
            [high for _, high in parts]
        )

    def _ends(
        self,
        start: int,
        stop: int,
        begins: np.ndarray,
        inside: np.ndarray,
        outside: np.ndarray,
        bits: bool,
    ) -> tuple[np.ndarray, np.ndarray]:
        """For each column -- samples start to stop, cut at ``begins`` -- the
        lowest and highest, or the AND and the OR, of those before its first
        whole SUMMED and after its last: fewer than SUMMED at each end, and
        what passes over where there are none. ``inside`` and ``outside`` are
        where the whole SUMMED in each column begin and end, over SUMMED.

        Where two columns meet, the end of one and the start of the next are
        the SUMMED the boundary is in: each is a row of the array, which goes
        round where two of them meet, and is split where the boundary falls.
        """
        dtype, counts = self._buffer.dtype, self.counts
        if bits:
            neutral = (np.uint8(0xFF), np.uint8(0))
            lower, higher = np.bitwise_and, np.bitwise_or
        elif dtype.kind == "f":
            neutral = (np.float32(np.nan), np.float32(np.nan))
            lower, higher = np.fmin, np.fmax
        else:
            # LOST is the least count, so never the highest of anything but
            # gaps; for the lowest, it is put above every reading, to be passed over.
            neutral = (np.int16(HIGHEST), np.int16(LOST))
            lower, higher = np.minimum, np.maximum

        def lowest(samples, **where):
            if counts:
                samples = np.where(samples == LOST, np.int16(HIGHEST), samples)
            return lower.reduce(samples, initial=neutral[0], **where)

        def highest(samples, **where):
            return higher.reduce(samples, initial=neutral[1], **where)

        columns = len(begins)
        low = np.full(columns, neutral[0], dtype)
        high = np.full(columns, neutral[1], dtype)
        # The start of the first column, and the end of the last.
        head = self._held(start, int(inside[0]) * SUMMED)
        tail = self._held(int(outside[-1]) * SUMMED, stop)
        low[0], high[0] = lowest(head), highest(head)
        low[-1], high[-1] = lower(low[-1], lowest(tail)), higher(high[-1], highest(tail))
        if columns > 1:
            boundaries = begins[1:]
            rows = self._buffer.reshape(-1, SUMMED)
            shared = rows[(boundaries // SUMMED) % len(rows)]
            split = (boundaries % SUMMED)[:, np.newaxis]
            place = np.arange(SUMMED)
            # The end of the column before each boundary, and the start of the one after.
            before, after = place < split, place >= split
            low[:-1] = lower(low[:-1], lowest(shared, axis=1, where=before))
            high[:-1] = higher(high[:-1], highest(shared, axis=1, where=before))
            low[1:] = lower(low[1:], lowest(shared, axis=1, where=after))
            high[1:] = higher(high[1:], highest(shared, axis=1, where=after))
        return low, high

    def _summed_between(self, first: int, last: int) -> tuple[np.ndarray, np.ndarray]:
        """What was summed up of SUMMED ``first`` to ``last``, by number over
        SUMMED: a view of the ring, or two pieces of it joined."""
        slots = len(self._lows)
        begin, end = first % slots, first % slots + (last - first)
        if end <= slots:
            return self._lows[begin:end], self._highs[begin:end]
        end -= slots
        return (
            np.concatenate((self._lows[begin:], self._lows[:end])),
            np.concatenate((self._highs[begin:], self._highs[:end])),
        )

    def drawn_packed(
        self, t_from: float, t_to: float, columns: int
    ) -> tuple[int, np.ndarray, np.ndarray]:
        """For a port of packed logic inputs: as ``drawn``, but cut down bit by
        bit, so that each input read out of it is its own lowest and highest.
        Worked out once for all eight, as the plot asks for each in turn."""
        start, stop = self.numbers(t_from, t_to)
        asked = (start, stop, columns)
        if self._packed_drawn is None or self._packed_drawn[0] != asked:
            positions, values = self._cut_down(start, stop, columns, packed=True)
            self._packed_drawn = (asked, positions, values)
        _asked, positions, values = self._packed_drawn
        return start, positions, values


class Bit:
    """One logic input of a port held packed: everything a Record says, with
    its samples read out of the port's where they are looked at."""

    counts = False
    #: The port's record holds the memory.
    memory_bytes = 0

    def __init__(self, channel: Channel, port: Record) -> None:
        self.channel = channel
        self.port = port
        self.last_drawn: tuple[int, int, float, float] | None = None

    @property
    def bit(self) -> int:
        return self.channel.bit

    # What is held is the port's.
    rate = property(lambda self: self.port.rate)
    capacity = property(lambda self: self.port.capacity)
    total = property(lambda self: self.port.total)
    count = property(lambda self: self.port.count)
    first = property(lambda self: self.port.first)

    @property
    def identity(self) -> tuple:
        return (*self.port.identity, self.bit)

    def values(
        self, start: int | None = None, stop: int | None = None, step: int = 1
    ) -> np.ndarray:
        return unpacked(self.port.values(start, stop, step), self.bit)

    def view(self) -> np.ndarray:
        return self.values()

    def copied(self, start: int, stop: int, ports: dict | None = None) -> Bit:
        """As Record.copied. ``ports`` keeps each port copied once, for all its inputs."""
        ports = {} if ports is None else ports
        key = (id(self.port), start, stop)
        if key not in ports:
            ports[key] = self.port.copied(start, stop)
        return Bit(self.channel, ports[key])

    def stretch(self, start: int, stop: int) -> Stretch:
        """Its samples start to stop, as bits of the port's bytes."""
        return Stretch(self.port.stretch(start, stop).held, bit=self.bit)

    def numbers(self, t_from: float, t_to: float) -> tuple[int, int]:
        return self.port.numbers(t_from, t_to)

    def between(self, t_from: float, t_to: float) -> tuple[int, np.ndarray]:
        start, packed = self.port.between(t_from, t_to)
        return start, unpacked(packed, self.bit)

    def drawn(self, t_from: float, t_to: float, columns: int) -> tuple[int, np.ndarray, np.ndarray]:
        start, positions, packed = self.port.drawn_packed(t_from, t_to, columns)
        values = unpacked(packed, self.bit)
        self.last_drawn = _extremes(
            start, start + (positions[-1] + 1 if len(positions) else 0), values
        )
        return start, positions, values


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
        self.records: dict[str, Record | Bit] = {}
        #: Ports of logic inputs sent packed, by the key they arrive under:
        #: what the records of their inputs read out of. See Channel.port.
        self.ports: dict[str, Record] = {}
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
        self.records, self.ports = {}, {}
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
            for channel in channels:
                if channel.port and channel.port not in self.ports:
                    self.ports[channel.port] = Record(_port(channel.port), rate, capacity)
            self.records = {c.key: self._record(c, rate, capacity) for c in channels}
            self._workers = {}  # a new run: nothing came before
            for maths, channel in self._maths_channels():
                self.records[maths.key] = Record(channel, rate, capacity)
        finally:
            self.channels_changed.emit()

    def _record(self, channel: Channel, rate: float, capacity: int) -> Record | Bit:
        """What holds a channel: a record of its own, or its bit of its port's."""
        if channel.port:
            return Bit(channel, self.ports[channel.port])
        return Record(channel, rate, capacity)

    def _each(self, channels: list[Channel]) -> float:
        """Bytes a sample of every one of these channels takes, held: with its
        maths channels, a byte for each port of packed inputs, and what a
        record sums up of them as they arrive, on top."""
        analog = {c.key for c in channels if c.kind == ANALOG}
        maths = sum(1 for m in self.maths if all(key in analog for key in m.sources))
        each = sum(np.dtype(_dtype(c)).itemsize for c in channels if not c.port)
        each += len({c.port for c in channels if c.port})
        each += maths * np.dtype(np.float32).itemsize
        return max(each, 1) * (1 + 2 / SUMMED)

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
                record.append(worker.take(*(r.values(first, last) for r in sources)))
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
            sources = (block.values(key) for key in maths.sources)
            data[maths.key] = worker.take(*sources, rate=block.rate)
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
        held = [*self.records.values(), *self.ports.values()]
        return sum(record.memory_bytes for record in held)

    def clear(self) -> None:
        """Throw away what is held, and count samples from zero again."""
        for key, port in list(self.ports.items()):
            self.ports[key] = Record(port.channel, port.rate, port.capacity)
        for key, record in list(self.records.items()):
            self.records[key] = self._record(record.channel, record.rate, record.capacity)
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
        data = {key: record.values(first, last) for key, record in zip(keys, records, strict=True)}
        return Block(first, records[0].rate, data, sweep=True)

    def _decode(self, block: Block) -> None:
        """Each decoded bus's share of a block: its channels, read on from the last."""
        if any(not decoding.paused for decoding in self.decodings):
            wanted = {key for d in self.decodings for key in d.setup.channels()}
            block = block.in_units(wanted)
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
            if (record := self.records.get(key) or self.ports.get(key)) is None:
                continue
            if block.first > record.total:
                missing = block.first - record.total
                record.skip(missing)
            record.append(samples, block.scales.get(key))
        self._decode(block)
        # A pause the instrument took on purpose is a gap on the plot and
        # nothing to warn about.
        if missing and not block.after_pause:
            self.gap.emit(missing)

    def _take_sweep(self, block: Block) -> None:
        """Hold this sweep in place of whatever was held, at its own rate and length."""
        for key, samples in block.data.items():
            if key in self.ports:
                port = self.ports[key]
                if port.rate != block.rate or port.capacity != len(samples):
                    port = self.ports[key] = Record(port.channel, block.rate, len(samples))
                    for bit in self.records.values():
                        if isinstance(bit, Bit) and bit.channel.port == key:
                            bit.port = port
                else:
                    port.empty()
                port.append(samples)
                continue
            if (record := self.records.get(key)) is None:
                continue
            if record.rate != block.rate or record.capacity != len(samples):
                record = Record(record.channel, block.rate, len(samples))
                self.records[key] = record
            else:
                record.empty()
            record.append(samples, block.scales.get(key))

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
    low, high = _columns(samples, per, packed=False)
    return _as_drawn(low, high, per, count)


def min_max_packed(samples: np.ndarray, columns: int) -> tuple[np.ndarray, np.ndarray]:
    """``min_max`` for a port of packed logic inputs: each column's bits that
    are all 1 in it, and those that are 1 anywhere in it -- every input's
    lowest and highest at once."""
    count = len(samples)
    if columns < 1 or count <= 2 * columns:
        return np.arange(count), samples
    per = -(-count // columns)
    low, high = _columns(samples, per, packed=True)
    return _as_drawn(low, high, per, count)


def _columns(samples: np.ndarray, per: int, packed: bool) -> tuple[np.ndarray, np.ndarray]:
    """The lowest and highest of every ``per`` samples, the last maybe fewer:
    for a port, the AND and the OR."""
    count = len(samples)
    whole = count // per
    bins = samples[: whole * per].reshape(whole, per)
    rest = samples[whole * per :]
    if packed:
        low, high = np.bitwise_and.reduce(bins, axis=1), np.bitwise_or.reduce(bins, axis=1)
        if len(rest):
            low = np.append(low, np.bitwise_and.reduce(rest))
            high = np.append(high, np.bitwise_or.reduce(rest))
        return low, high
    # fmin and fmax pass over a gap's NaN where there is anything else to take.
    low, high = np.fmin.reduce(bins, axis=1), np.fmax.reduce(bins, axis=1)
    if len(rest):
        low = np.append(low, np.fmin.reduce(rest))
        high = np.append(high, np.fmax.reduce(rest))
    if samples.dtype == np.int16:
        _pass_over_lost(samples, per, low, high)
    return low, high


def _as_drawn(
    low: np.ndarray, high: np.ndarray, per: int, count: int
) -> tuple[np.ndarray, np.ndarray]:
    """Each column's lowest and highest, as the points a plot draws: at its
    first sample and its last, of ``count`` in ``per``s."""
    values = np.empty(2 * len(low), dtype=low.dtype)
    values[0::2], values[1::2] = low, high
    positions = np.repeat(np.arange(len(low)) * per, 2)
    positions[1::2] += per - 1
    positions[-1] = count - 1
    return positions, values


def _extremes(start: int, stop: int, drawn: np.ndarray) -> tuple[int, int, float, float] | None:
    """What a stretch drawn says of it: from, to, its lowest and its highest."""
    if not len(drawn) or (drawn.dtype.kind == "f" and np.isnan(drawn).all()):
        return None
    return start, stop, float(np.nanmin(drawn)), float(np.nanmax(drawn))


def _port(key: str) -> Channel:
    """What a port's own record is said to hold: eight logic inputs, packed."""
    return Channel(key, key, DIGITAL, "")


def _pass_over_lost(samples: np.ndarray, per: int, low: np.ndarray, high: np.ndarray) -> None:
    """Counts have no NaN to pass over, and LOST is the least of them: a column
    whose least is LOST is looked at again for the least reading in it. One
    with nothing but LOST stays LOST, a gap. Rare, so done column by column."""
    for column in np.flatnonzero((low == LOST) & (high != LOST)):
        values = samples[column * per : (column + 1) * per]
        low[column] = values[values != LOST].min()


#: The highest count: the lowest of a stretch with no readings in it, all LOST.
HIGHEST = 32767


def _summed(
    parts: list[np.ndarray], rest: np.ndarray, counts: bool
) -> tuple[np.ndarray, np.ndarray]:
    """The lowest and highest of each row of samples, and of the rest after
    them: as min_max takes them, or for logic levels, the AND and the OR."""
    lows, highs = [], []
    for part in [*parts, *([rest[np.newaxis]] if len(rest) else [])]:
        if part.dtype == np.uint8:
            low, high = np.bitwise_and.reduce(part, axis=1), np.bitwise_or.reduce(part, axis=1)
        elif part.dtype.kind == "f":
            low, high = np.fmin.reduce(part, axis=1), np.fmax.reduce(part, axis=1)
        else:
            low, high = part.min(axis=1), part.max(axis=1)
            if counts:
                # LOST is the least count, and not a reading: the lowest is of
                # the readings, and with none, above every reading, for the
                # lowest of several to pass over it.
                for row in np.flatnonzero(low == LOST):
                    readings = part[row][part[row] != LOST]
                    low[row] = readings.min() if len(readings) else HIGHEST
        lows.append(low)
        highs.append(high)
    return np.concatenate(lows), np.concatenate(highs)
