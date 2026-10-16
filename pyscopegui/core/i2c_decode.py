# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Transfers read off an I2C bus: SCL and SDA, two logic channels.

A transfer begins with a START -- SDA falling while SCL is high -- and ends
with a STOP, SDA rising while SCL is high, or with another START, a repeated
one. In between, SDA is read on each rising edge of SCL, nine bits at a time:
a byte, the most significant bit first, and the acknowledgement after it, low
for ACK. The first byte is the address, seven bits, and whether the controller
reads (1) or writes (0). A first byte of 11110 followed by two bits is the
start of a ten-bit address, whose low eight bits are the next byte.

SCL rises once more before a STOP, and before a repeated START: that rise
carries no bit, and is not read as one.

The bits are found with NumPy, not a bit at a time, and a transfer that falls
across two blocks is read whole.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from pyscopegui.core.edges import falls, last, number, rises


@dataclass
class Transfer:
    """From a START to the STOP or repeated START after it."""

    #: The sample numbers of its START, and of its STOP or the next START.
    start: int
    end: int = 0
    #: The device's address, seven bits or ten; None until it has been read.
    address: int | None = None
    ten_bit: bool = False
    #: Whether the controller reads from the device, or writes to it.
    read: bool = False
    #: The bytes after the address.
    data: list[int] = field(default_factory=list)
    #: Whether each byte, the address's first, was acknowledged.
    acks: list[bool] = field(default_factory=list)
    #: How it ended: "stop", or "restart" for a repeated START.
    ended: str = ""
    #: What was wrong, or "" for a good one.
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def nacked(self) -> bool:
        """Whether the address was not acknowledged: nobody there."""
        return bool(self.acks) and not self.acks[0]


def encode(
    address: int,
    data: list[int],
    read: bool = False,
    acks: list[bool] | None = None,
    per_bit: int = 8,
    end: str = "stop",
) -> dict[str, np.ndarray]:
    """One transfer as samples of SCL and SDA, from rest through START, the
    address, the data and STOP to rest -- or, ending with ``"restart"``, to SDA
    and SCL high, ready for the START of the next. For tests."""
    if acks is None:
        acks = [True] * (1 + len(data))
    stream = []
    for byte, ack in zip([(address << 1) | int(read), *data], acks, strict=True):
        stream += [(byte >> i) & 1 for i in range(7, -1, -1)] + [0 if ack else 1]
    quarter = per_bit // 4
    scl = [1] * per_bit
    sda = [1] * per_bit
    # START: SDA falls with SCL high, then SCL falls.
    scl += [1] * quarter + [0] * quarter
    sda += [0] * (2 * quarter)
    for bit in stream:
        # SDA changes while SCL is low, and is read while it is high.
        scl += [0] * quarter + [1] * (2 * quarter) + [0] * quarter
        sda += [bit] * (4 * quarter)
    if end == "restart":
        # SDA rises while SCL is low, then SCL rises: the next START follows.
        scl += [0] * quarter + [1] * (3 * quarter)
        sda += [1] * (4 * quarter)
    else:
        # STOP: SDA low, SCL rises, then SDA rises with SCL high.
        scl += [0] * quarter + [1] * (3 * quarter) + [1] * per_bit
        sda += [0] * (2 * quarter) + [1] * (2 * quarter) + [1] * per_bit
    return {"scl": np.array(scl, dtype=bool), "sda": np.array(sda, dtype=bool)}


class I2cDecoder:
    """Transfers from an I2C bus's levels, fed a block at a time."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Forget what was being read: after a gap, or to start again."""
        self._scl: bool | None = None
        self._sda: bool | None = None
        self._open: Transfer | None = None
        self._bits: list[np.ndarray] = []
        #: The sample numbers of the last SCL rise read as a bit, and of the
        #: last SCL fall: a rise not fallen from by a START or STOP is no bit.
        self._last_rise = -1
        self._last_fall = -1
        self._next: int | None = None

    def feed(self, first: int, scl: np.ndarray, sda: np.ndarray) -> list[Transfer]:
        """The transfers that end in these levels, numbered from ``first``."""
        found: list[Transfer] = []
        if self._next is not None and first != self._next:
            found += self._close(first, "", "samples were lost")
            self.reset()
        self._next = first + len(scl)
        if not len(scl):
            return found
        scl, sda = scl.astype(bool), sda.astype(bool)
        if self._scl is None:
            self._scl, self._sda = bool(scl[0]), bool(sda[0])
        clocks = rises(self._scl, scl)
        clock_falls = falls(self._scl, scl)
        # START and STOP: SDA changing while SCL is high -- and was high before.
        before_scl = np.concatenate(([self._scl], scl[:-1]))
        high = scl & before_scl
        starts = falls(self._sda, sda)
        starts = starts[high[starts]]
        stops = rises(self._sda, sda)
        stops = stops[high[stops]]
        self._scl, self._sda = last(scl, self._scl), last(sda, self._sda)
        # Every START and STOP in order, with the clock edges between them read.
        marks = sorted([(int(s), "start") for s in starts] + [(int(s), "stop") for s in stops])
        begin = 0
        for at, what in [*marks, (len(scl), "")]:
            if self._open is not None:
                inside = clocks[np.searchsorted(clocks, begin) : np.searchsorted(clocks, at)]
                self._bits.append(sda[inside].astype(np.uint8))
                if len(inside):
                    self._last_rise = first + int(inside[-1])
            fallen = np.searchsorted(clock_falls, at)
            if fallen:
                self._last_fall = max(self._last_fall, first + int(clock_falls[fallen - 1]))
            if not what:
                break
            if self._open is not None and self._last_rise > self._last_fall:
                self._drop_last_bit()  # the rise before the START or STOP
            if what == "start":
                found += self._close(first + at, "restart")
                self._open = Transfer(first + at)
            else:
                found += self._close(first + at, "stop")
            begin = at
        return found

    def _drop_last_bit(self) -> None:
        for number_ in range(len(self._bits) - 1, -1, -1):
            if len(self._bits[number_]):
                self._bits[number_] = self._bits[number_][:-1]
                return

    def _close(self, at: int, ended: str, error: str = "") -> list[Transfer]:
        transfer = self._open
        if transfer is None:
            return []
        bits = np.concatenate(self._bits) if self._bits else np.zeros(0, dtype=np.uint8)
        self._open, self._bits = None, []
        transfer.end, transfer.ended = at, ended
        whole = len(bits) // 9
        for row in bits[: whole * 9].reshape(whole, 9):
            byte, ack = number(row[:8]), not row[8]
            transfer.acks.append(ack)
            if transfer.address is None:
                transfer.read = bool(byte & 1)
                if byte >> 3 == 0b11110:
                    transfer.ten_bit = True
                    transfer.address = (byte >> 1) & 0b11  # the high two bits, so far
                else:
                    transfer.address = byte >> 1
            elif transfer.ten_bit and len(transfer.acks) == 2:
                transfer.address = (transfer.address << 8) | byte
            else:
                transfer.data.append(byte)
        if error:
            transfer.error = error
        elif len(bits) % 9:
            transfer.error = f"it ended part way through a byte: {len(bits) % 9} bits of 9"
        elif not len(bits):
            transfer.error = "nothing between the START and its end"
        return [transfer]

    def flush(self) -> list[Transfer]:
        """At the end of a capture: the transfer still open, as far as it got."""
        found = self._close(self._next or 0, "", "the capture ends part way through it")
        self.reset()
        return found
