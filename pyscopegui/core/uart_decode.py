# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Bytes read off a serial line -- UART, RS-232 behind its transceiver, the
debug port of anything -- from one logic channel.

The line rests high. Each character is a start bit, low; five to nine data
bits, the least significant first unless it is said otherwise; a parity bit,
if there is one; and one, one and a half or two stop bits, high. Each bit is
read in its middle, timed from the falling edge of the start bit, as a UART
does: so the baud rate has to be known, to within a few percent.

RS-232 at the connector, between the transceivers, is the other way up: say
the line is inverted.

A character that falls across two blocks is read whole: what is not yet
enough for a character is kept, and read with the next block.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pyscopegui.core.edges import falls, number

NONE, EVEN, ODD = "none", "even", "odd"
#: The usual baud rates, for a list to choose from.
BAUDS = (300, 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600)
#: The fewest samples a bit is read from.
FEWEST_SAMPLES = 3


@dataclass
class Character:
    """One character read off the line."""

    #: The sample numbers of its start bit's falling edge, and the middle of its
    #: (first) stop bit.
    start: int
    end: int
    value: int
    #: What was wrong, or "" for a good one.
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def encode(
    data: bytes, bits: int = 8, parity: str = NONE, stop_bits: float = 1, msb_first: bool = False
) -> list[float]:
    """Characters as a line's bits, a bit time each -- 1 high -- with the stop
    bits as a number of bit times that may be one and a half. For tests."""
    out: list[float] = []
    for value in data:
        data_bits = [(value >> i) & 1 for i in range(bits)]
        if msb_first:
            data_bits.reverse()
        out += [0, *data_bits]
        if parity != NONE:
            ones = sum(data_bits)
            out.append((ones + (parity == ODD)) % 2)
        out += [1] * int(np.ceil(stop_bits))
    return out


class UartDecoder:
    """Characters from a line's levels, fed a block at a time."""

    def __init__(
        self,
        rate: float,
        baud: float,
        bits: int = 8,
        parity: str = NONE,
        stop_bits: float = 1,
        msb_first: bool = False,
        inverted: bool = False,
    ) -> None:
        self.per_bit = rate / baud
        if self.per_bit < FEWEST_SAMPLES:
            raise ValueError(
                f"{rate:g} samples a second is too few for {baud:g} baud: each bit needs "
                f"{FEWEST_SAMPLES} samples at least"
            )
        if not 5 <= bits <= 9 or parity not in (NONE, EVEN, ODD):
            raise ValueError(f"no such character: {bits} bits, parity {parity}")
        self.bits, self.parity, self.stop_bits = bits, parity, stop_bits
        self.msb_first, self.inverted = msb_first, inverted
        #: Bit times from the start bit's edge to the middle of the first stop bit.
        self._to_stop = 1 + bits + (parity != NONE) + 0.5
        self.reset()

    def reset(self) -> None:
        """Forget what was being read: after a gap, or to start again."""
        #: Samples not yet read, and the number of the first of them.
        self._held = np.zeros(0, dtype=bool)
        self._first = 0
        #: The level just before them: the line rests high.
        self._before = True
        self._next: int | None = None

    def feed(self, line: np.ndarray, first: int) -> list[Character]:
        """The characters in these levels -- True high, as the line is wired --
        numbered from ``first``. A block that does not follow the last is a gap."""
        levels = ~line if self.inverted else line.astype(bool)
        if self._next is not None and first != self._next:
            self.reset()
        self._next = first + len(levels)
        if not len(self._held):
            self._first = first
        self._held = np.concatenate((self._held, levels))
        return self._read()

    def _read(self) -> list[Character]:
        found: list[Character] = []
        held, per_bit = self._held, self.per_bit
        frame = int(np.ceil(self._to_stop * per_bit)) + 1
        # Every falling edge is a start bit, unless it falls within a character.
        position = len(held)
        reached = 0
        for edge in falls(self._before, held):
            start = int(edge)
            if start < reached:
                continue  # a data bit's edge
            if start + frame > len(held):
                position = start  # not all of it yet: kept for the next block
                break
            character = self._character(held, start)
            if character is None:
                continue  # a glitch, not a start bit
            found.append(character)
            # On from the middle of the stop bit: the next start can come after it.
            reached = start + int(self._to_stop * per_bit)
        if position:
            self._before = bool(held[position - 1])
            self._held = held[position:]
            self._first += position
        return found

    def _character(self, held: np.ndarray, start: int) -> Character | None:
        def bit(number_: float) -> bool:
            return bool(held[start + int((number_ + 0.5) * self.per_bit)])

        if bit(0):
            return None  # high again by the middle of its start bit
        data = [int(bit(1 + i)) for i in range(self.bits)]
        value = number(data, msb_first=self.msb_first)
        error = ""
        after = 1 + self.bits
        if self.parity != NONE:
            parity = int(bit(after))
            if (sum(data) + parity) % 2 != (self.parity == ODD):
                error = "the parity is wrong"
            after += 1
        if not bit(after):
            if value == 0 and not any(data):
                error = "a break: the line held low"
            else:
                error = "a framing error: the stop bit is low"
        end = self._first + start + int((after + 0.5) * self.per_bit)
        return Character(self._first + start, end, value, error)

    def flush(self) -> list[Character]:
        """At the end of a capture: nothing more is coming."""
        self.reset()
        return []
