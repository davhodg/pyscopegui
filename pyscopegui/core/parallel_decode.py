# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Words read off a parallel bus: several data lines read together, bit 0
first, with a clock, an enable and a multiplex line if there are any.

With a clock, a word is read at each edge the bus is clocked on -- rising,
falling, or both -- as it was just before the edge: what a latch clocked by
that edge would take. Without one, a word is read wherever the lines change
and then hold steady for ``settle`` samples, so that lines changing a sample
or two apart are not read as words of their own.

A multiplex line says more about each word. For now that is a *channel
select*: its level as the word is read says which of two channels the word
is from -- an ADC such as the AD9238, sending both its channels on one bus,
a word each half clock. Other kinds can be added beside it.

Words go together into transfers: what is read while the enable is active,
or, without one, a run of words that a pause ends -- ``REST`` of the bus's
own word times with nothing read. A bus that never pauses, an ADC's, is cut
into transfers of ``MOST_WORDS``, so that there is something to show as it
runs.

Found with NumPy, not a word at a time: a bus can be clocked at tens of
megahertz, with millions of words in a block.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from pyscopegui.core.edges import changes, falls, last, rises

RISING, FALLING, BOTH = "rising", "falling", "both"
EDGES = (RISING, FALLING, BOTH)
#: What a multiplex line does: none, or say which of two channels a word is from.
NO_MUX, SELECT = "", "select"
#: Without an enable, a transfer ends when nothing is read for this many word times.
REST = 8
#: The most words a transfer holds: a bus that never pauses is cut up into these.
MOST_WORDS = 32


@dataclass
class Transfer:
    """Words read together: while the enable was active, or between pauses."""

    #: The sample numbers of its beginning and end.
    start: int
    end: int = 0
    #: The words, as read: bit 0 the first line's.
    words: list[int] = field(default_factory=list)
    #: For a channel select: which channel each word is from, 0 or 1. Empty
    #: without a multiplex line.
    streams: list[int] = field(default_factory=list)
    #: What was wrong, or "" for a good one.
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    def of(self, stream: int) -> list[int]:
        """The words of one channel, in the order they were read."""
        return [w for w, s in zip(self.words, self.streams, strict=True) if s == stream]


def word_values(lines: list[np.ndarray], at: np.ndarray | None = None) -> np.ndarray:
    """The word on these lines -- bit 0 the first -- at each of these samples,
    or at every sample."""
    total = np.zeros(len(lines[0]) if at is None else len(at), dtype=np.int64)
    for bit, line in enumerate(lines):
        values = line if at is None else line[at]
        total |= values.astype(np.int64) << bit
    return total


def encode(
    words: list[int], width: int, per_word: int = 4, streams: list[int] | None = None
) -> dict[str, np.ndarray]:
    """Words as samples, for tests: lines "D0" up, a clock that rises halfway
    through each word and falls at its end, and, with ``streams``, a select
    line "SEL" at each word's channel. Two words' time of nothing either side."""
    pad = 2 * per_word
    half = per_word // 2
    out: dict[str, list[int]] = {f"D{b}": [0] * pad for b in range(width)}
    out["CLK"] = [0] * pad
    out["SEL"] = [0] * pad
    for n, word in enumerate(words):
        for b in range(width):
            out[f"D{b}"] += [(word >> b) & 1] * per_word
        out["CLK"] += [0] * half + [1] * (per_word - half)
        out["SEL"] += [streams[n] if streams else 0] * per_word
    for key in out:
        out[key] += [out[key][-1] if key.startswith("D") else 0] * pad
    return {key: np.array(levels, dtype=bool) for key, levels in out.items()}


class WordReader:
    """Where a parallel bus's words are read, and what each is: the samples, the
    words, and for a channel select, which channel each is from. Fed a block at
    a time, carrying what a clock edge or a settling word needs from the last.
    Used by the decoder, and on its own to draw a bus's words as channels."""

    def __init__(
        self, width: int, edge: str = RISING, clocked: bool = True, settle: int = 2
    ) -> None:
        if not 1 <= width <= 32 or edge not in EDGES:
            raise ValueError(f"no such parallel bus: {width} lines, read on {edge}")
        self.width, self.edge, self.clocked = width, edge, clocked
        self.settle = max(int(settle), 1)
        self.reset()

    def reset(self) -> None:
        """Forget what was being read: after a gap, or to start again."""
        self._clock: bool | None = None
        #: The word and select level at the last sample of the block before:
        #: what a clock edge at the first sample of this one reads.
        self._word_before: int | None = None
        self._select_before = 0
        #: Without a clock: a change not yet known to have held steady, as
        #: (its sample, its word, its select level).
        self._pending: tuple[int, int, int] | None = None

    def read(
        self,
        first: int,
        data: list[np.ndarray],
        clock: np.ndarray | None = None,
        select: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """The words read in these levels: where -- within the block, and
        before its first for a settled word that changed in the block before
        -- what, and from which channel, nought without a select."""
        if self.clocked and clock is not None:
            return self._clocked(data, clock, select)
        return self._unclocked(first, data, select)

    def take_pending(self) -> tuple[int, int, int] | None:
        """At the end of a capture: the last word, which has held as long as it could."""
        pending, self._pending = self._pending, None
        return pending

    def _clocked(self, data, clock, select):
        """The words read at the clock's edges: each as it was the sample before."""
        if self._clock is None:
            self._clock = bool(clock[0])
        edges = {RISING: rises, FALLING: falls, BOTH: changes}[self.edge](self._clock, clock)
        self._clock = last(clock, self._clock)
        before = edges - 1
        inside = before >= 0
        words = np.empty(len(edges), dtype=np.int64)
        words[inside] = word_values(data, before[inside])
        streams = np.zeros(len(edges), dtype=np.int64)
        if select is not None:
            streams[inside] = select[before[inside]].astype(np.int64)
        if not inside.all():
            # An edge at the very first sample reads what the last block ended with.
            if self._word_before is None:
                edges, words, streams = edges[inside], words[inside], streams[inside]
            else:
                words[~inside] = self._word_before
                streams[~inside] = self._select_before
        self._word_before = int(word_values(data, np.array([len(data[0]) - 1]))[0])
        if select is not None:
            self._select_before = int(select[-1])
        return edges, words, streams

    def _unclocked(self, first, data, select):
        """The words read where the lines change and then hold for ``settle`` samples."""
        count = len(data[0])
        every = word_values(data)
        sel = select.astype(np.int64) if select is not None else np.zeros(count, dtype=np.int64)
        # A select change is a change too: the same word from the other channel.
        state = every | (sel << self.width)
        previous = np.concatenate(([state[0]], state[:-1]))
        moved = np.flatnonzero(state != previous)
        if self._word_before is not None:
            was = self._word_before | (self._select_before << self.width)
            if state[0] != was:
                moved = np.concatenate(([0], moved))
        self._word_before = int(every[-1])
        self._select_before = int(sel[-1])
        # Where each change is followed by the next: how long it held.
        until = np.concatenate((moved[1:], [-1]))
        at, words, streams = [], [], []
        if self._pending is not None:
            pending_at, pending_word, pending_select = self._pending
            held_to = first + (int(moved[0]) if len(moved) else count)
            if held_to - pending_at >= self.settle:
                # Read where it changed: in the block before, so before this one's first.
                at.append(pending_at - first)
                words.append(pending_word)
                streams.append(pending_select)
                self._pending = None
            elif len(moved):
                self._pending = None  # changed again too soon: not a word
        held = until - moved
        steady = (until >= 0) & (held >= self.settle)
        at += moved[steady].tolist()
        words += every[moved[steady]].tolist()
        streams += sel[moved[steady]].tolist()
        if len(moved):
            end = int(moved[-1])
            if count - end >= self.settle:
                at.append(end)
                words.append(int(every[end]))
                streams.append(int(sel[end]))
            else:
                self._pending = (first + end, int(every[end]), int(sel[end]))
        order = np.argsort(np.array(at, dtype=np.int64), kind="stable")
        return (
            np.array(at, dtype=np.int64)[order],
            np.array(words, dtype=np.int64)[order],
            np.array(streams, dtype=np.int64)[order],
        )


class ParallelDecoder:
    """Transfers from a parallel bus's levels, fed a block at a time."""

    def __init__(
        self,
        width: int,
        edge: str = RISING,
        clocked: bool = True,
        settle: int = 2,
        mux: str = NO_MUX,
        enable_active_low: bool = True,
        gap: int | None = None,
    ) -> None:
        if mux not in (NO_MUX, SELECT):
            raise ValueError(f"no such multiplex line: {mux}")
        self._reader = WordReader(width, edge, clocked, settle)
        self.width = width
        self.mux = mux
        self.enable_active_low = enable_active_low
        self.gap = gap
        self.reset()

    def reset(self) -> None:
        """Forget what was being read: after a gap, or to start again."""
        self._reader.reset()
        self._next: int | None = None
        self._enable: bool | None = None
        self._open: Transfer | None = None
        self._last_read = -1
        self._word_time = 0.0

    # --- feeding --------------------------------------------------------------------------
    def feed(
        self,
        first: int,
        data: list[np.ndarray],
        clock: np.ndarray | None = None,
        select: np.ndarray | None = None,
        enable: np.ndarray | None = None,
    ) -> list[Transfer]:
        """The transfers that end in these levels, numbered from ``first``."""
        found: list[Transfer] = []
        if self._next is not None and first != self._next:
            found += self._close(first, "samples were lost")
            self.reset()
        count = len(data[0])
        self._next = first + count
        if not count:
            return found
        at, words, streams = self._reader.read(first, data, clock, select)
        if enable is None:
            found += self._without_enable(first, count, at, words, streams)
        else:
            found += self._with_enable(first, at, words, streams, enable)
        return found

    # --- words into transfers -------------------------------------------------------------
    def _add(self, first: int, at: np.ndarray, words: np.ndarray, streams: np.ndarray) -> list:
        """Put words into the transfer open, closing it whenever it is full."""
        found: list[Transfer] = []
        for n in range(len(at)):
            if self._open is None:
                self._open = Transfer(first + int(at[n]))
            self._open.words.append(int(words[n]))
            if self.mux == SELECT:
                self._open.streams.append(int(streams[n]))
            self._last_read = first + int(at[n])
            if len(self._open.words) >= MOST_WORDS:
                found += self._close(self._last_read + 1)
        return found

    def _close(self, at: int, error: str = "") -> list[Transfer]:
        transfer = self._open
        self._open = None
        if transfer is None:
            return []
        transfer.end = max(at, transfer.start)
        transfer.error = error
        return [transfer] if (transfer.words or error) else []

    def _with_enable(self, first, at, words, streams, enable) -> list[Transfer]:
        active = ~enable.astype(bool) if self.enable_active_low else enable.astype(bool)
        if self._enable is None:
            self._enable = bool(active[0])
            if self._enable:
                self._open = Transfer(first)
        found: list[Transfer] = []
        # A word without a clock can be read where it changed in the block before.
        begin = min(0, int(at[0])) if len(at) else 0
        reading = self._enable
        for bound in [*changes(self._enable, active).tolist(), len(active)]:
            # The words read while it was active, from the last change to this one.
            if reading:
                lo, hi = np.searchsorted(at, begin), np.searchsorted(at, bound)
                found += self._add(first, at[lo:hi], words[lo:hi], streams[lo:hi])
            if bound == len(active):
                break
            reading = bool(active[bound])
            found += self._close(first + bound)
            if reading:
                self._open = Transfer(first + bound)
            begin = bound
        self._enable = last(active, self._enable)
        return found

    def _without_enable(self, first, count, at, words, streams) -> list[Transfer]:
        found: list[Transfer] = []
        rest = self.gap if self.gap is not None else REST * max(self._word_time, 1.0)
        if not len(at):
            # Quiet for long enough: the transfer open is finished.
            if self._open is not None and first + count - self._last_read > rest:
                found += self._close(self._last_read + 1)
            return found
        absolute = at + first
        steps = np.diff(np.concatenate(([self._last_read], absolute))).astype(float)
        if self._last_read < 0:
            steps[0] = np.inf
        if self._word_time == 0.0 and len(absolute) > 1:
            self._word_time = float(np.median(np.diff(absolute)))
        rest = self.gap if self.gap is not None else REST * max(self._word_time, 1.0)
        breaks = np.flatnonzero(steps > rest)
        begin = 0
        for brk in [*breaks.tolist(), len(at)]:
            if brk > begin:
                found += self._add(first, at[begin:brk], words[begin:brk], streams[begin:brk])
            if brk == len(at):
                break
            found += self._close(self._last_read + 1)
            begin = brk
        if self._open is not None and first + count - self._last_read > rest:
            found += self._close(self._last_read + 1)
        return found

    def flush(self) -> list[Transfer]:
        """At the end of a capture: the transfer still open, as far as it got."""
        if (pending := self._reader.take_pending()) is not None:
            pending_at, word, select = pending
            if self._open is None:
                self._open = Transfer(pending_at)
            self._open.words.append(word)
            if self.mux == SELECT:
                self._open.streams.append(select)
            self._last_read = pending_at
        found = self._close(self._last_read + 1 if self._last_read >= 0 else (self._next or 0))
        self.reset()
        return found
