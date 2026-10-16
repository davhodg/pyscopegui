# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Words read off an SPI bus: a clock, the data each way -- MOSI from the
controller, MISO from the device, either or both -- and a chip select.

Each bit is read at the clock edge the mode samples on, and the bits make up
words of eight, or however many are said, the most significant first unless it
is said otherwise:

| Mode | Clock rests | Read on |
|------|-------------|---------|
| 0 | low | rising |
| 1 | low | falling |
| 2 | high | falling |
| 3 | high | rising |

A transfer is what is sent while the chip select is active, low unless it is
said otherwise. Without one, a transfer ends when the clock has rested for a
while: longer than ``gap`` samples, or eight of its own bit times.

The bits are found with NumPy, not a bit at a time: an SPI clock runs at
megahertz, and there may be millions of them in a block.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from pyscopegui.core.edges import changes, falls, last, rises

#: Without a chip select, a transfer ends when the clock rests for this many
#: of its bit times.
REST = 8


@dataclass
class Transfer:
    """What was sent while the chip select was active."""

    #: The sample numbers of its beginning and end.
    start: int
    end: int = 0
    #: The words each way, as numbers; empty for a line not given.
    mosi: list[int] = field(default_factory=list)
    miso: list[int] = field(default_factory=list)
    #: What was wrong, or "" for a good one: a word cut short.
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def encode(
    words: list[int], bits: int = 8, mode: int = 0, msb_first: bool = True, per_bit: int = 4
) -> dict[str, np.ndarray]:
    """One transfer as samples: the clock, MOSI with these words, and the chip
    select, active from before the first bit to after the last. For tests."""
    cpol, cpha = mode >> 1, mode & 1
    stream = []
    for word in words:
        order = range(bits - 1, -1, -1) if msb_first else range(bits)
        stream += [(word >> i) & 1 for i in order]
    half = per_bit // 2
    clock, data = [], []
    for bit in stream:
        # The data is set up on the edge before the one it is read on.
        if cpha == 0:
            clock += [cpol] * half + [1 - cpol] * (per_bit - half)
        else:
            clock += [1 - cpol] * half + [cpol] * (per_bit - half)
        data += [bit] * per_bit
    pad = 2 * per_bit
    return {
        "sclk": np.array([cpol] * pad + clock + [cpol] * pad, dtype=bool),
        "mosi": np.array([0] * pad + data + [0] * pad, dtype=bool),
        "cs": np.array([1] * (pad - 1) + [0] * (len(clock) + 2) + [1] * (pad - 1), dtype=bool),
    }


class SpiDecoder:
    """Transfers from an SPI bus's levels, fed a block at a time."""

    def __init__(
        self,
        mode: int = 0,
        bits: int = 8,
        msb_first: bool = True,
        cs_active_low: bool = True,
        gap: int | None = None,
    ) -> None:
        if mode not in (0, 1, 2, 3) or not 1 <= bits <= 64:
            raise ValueError(f"no such SPI: mode {mode}, {bits} bits a word")
        self.mode, self.bits, self.msb_first = mode, bits, msb_first
        cpol, cpha = mode >> 1, mode & 1
        #: Whether bits are read on the clock's rising edge.
        self._on_rising = cpol == cpha
        self.cs_active_low = cs_active_low
        self.gap = gap
        self.reset()

    def reset(self) -> None:
        """Forget what was being read: after a gap, or to start again."""
        self._clock: bool | None = None
        self._cs: bool | None = None
        self._open: Transfer | None = None
        self._mosi_bits: list[np.ndarray] = []
        self._miso_bits: list[np.ndarray] = []
        #: The last bit's sample, and a bit time, for ending a transfer without a chip select.
        self._last_bit = -1
        self._bit_time = 0.0
        self._next: int | None = None

    def feed(
        self,
        first: int,
        sclk: np.ndarray,
        mosi: np.ndarray | None = None,
        miso: np.ndarray | None = None,
        cs: np.ndarray | None = None,
    ) -> list[Transfer]:
        """The transfers that end in these levels, numbered from ``first``. Any
        of MOSI, MISO and the chip select may be left out."""
        found: list[Transfer] = []
        if self._next is not None and first != self._next:
            found += self._close(first, "samples were lost")
            self.reset()
        self._next = first + len(sclk)
        if not len(sclk):
            return found
        if self._clock is None:
            self._clock = bool(sclk[0])
        edges = (rises if self._on_rising else falls)(self._clock, sclk)
        self._clock = last(sclk, self._clock)
        if cs is None:
            found += self._without_cs(first, edges, mosi, miso)
        else:
            found += self._with_cs(first, edges, mosi, miso, cs)
        return found

    # --- bits into words ----------------------------------------------------------------
    def _bits(self, at: np.ndarray, mosi, miso) -> None:
        """Read the data lines at these samples, into the transfer open."""
        if mosi is not None:
            self._mosi_bits.append(mosi[at].astype(np.uint8))
        if miso is not None:
            self._miso_bits.append(miso[at].astype(np.uint8))

    def _words(self, parts: list[np.ndarray]) -> tuple[list[int], int]:
        bits = np.concatenate(parts) if parts else np.zeros(0, dtype=np.uint8)
        whole = len(bits) // self.bits
        rows = bits[: whole * self.bits].reshape(whole, self.bits).astype(np.uint64)
        if not self.msb_first:
            rows = rows[:, ::-1]
        weights = np.uint64(1) << np.arange(self.bits - 1, -1, -1, dtype=np.uint64)
        return [int(v) for v in (rows * weights).sum(axis=1)], len(bits) - whole * self.bits

    def _close(self, at: int, error: str = "") -> list[Transfer]:
        transfer = self._open
        if transfer is None:
            return []
        transfer.end = at
        transfer.mosi, left = self._words(self._mosi_bits)
        transfer.miso, left_miso = self._words(self._miso_bits)
        if not error and (left or left_miso):
            error = f"a word cut short: {max(left, left_miso)} bits of {self.bits}"
        transfer.error = error
        self._open, self._mosi_bits, self._miso_bits = None, [], []
        return [transfer] if (transfer.mosi or transfer.miso or error) else []

    # --- with a chip select -------------------------------------------------------------
    def _with_cs(self, first, edges, mosi, miso, cs) -> list[Transfer]:
        active = ~cs if self.cs_active_low else cs.astype(bool)
        if self._cs is None:
            self._cs = bool(active[0])
            if self._cs:
                self._open = Transfer(first)
        found: list[Transfer] = []
        bounds = changes(self._cs, active)
        begin = 0
        for bound in [*bounds.tolist(), len(active)]:
            # The clock edges while it was active, from the last change to this one.
            if self._open is not None:
                inside = edges[np.searchsorted(edges, begin) : np.searchsorted(edges, bound)]
                self._bits(inside, mosi, miso)
            if bound == len(active):
                break
            if active[bound]:
                self._open = Transfer(first + bound)
            else:
                found += self._close(first + bound)
            begin = bound
        self._cs = last(active, self._cs)
        return found

    # --- without one --------------------------------------------------------------------
    def _without_cs(self, first, edges, mosi, miso) -> list[Transfer]:
        found: list[Transfer] = []
        if not len(edges):
            return found
        absolute = edges + first
        # Where the clock rested long enough to end a transfer.
        steps = np.diff(np.concatenate(([self._last_bit], absolute))).astype(float)
        if self._last_bit < 0:
            steps[0] = np.inf  # the first bit there has been: a transfer begins
        if self._bit_time == 0.0 and len(absolute) > 1:
            self._bit_time = float(np.median(np.diff(absolute)))
        rest = self.gap if self.gap is not None else REST * max(self._bit_time, 1.0)
        breaks = np.flatnonzero(steps > rest)
        begin = 0
        for brk in [*breaks.tolist(), len(edges)]:
            if brk > begin and self._open is not None:
                self._bits(edges[begin:brk], mosi, miso)
            if brk == len(edges):
                break
            # A transfer ends at its last bit, and the next begins at this one.
            ended = int(absolute[brk - 1]) if brk > 0 else self._last_bit
            found += self._close(ended)
            self._open = Transfer(int(absolute[brk]))
            begin = brk
        self._last_bit = int(absolute[-1])
        return found

    def flush(self) -> list[Transfer]:
        """At the end of a capture: the transfer still open, as far as it got."""
        found = self._close(self._last_bit if self._last_bit >= 0 else (self._next or 0))
        self.reset()
        return found
