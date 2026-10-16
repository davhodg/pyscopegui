# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""CAN frames, read off a channel: a logic input on a transceiver's RX pin, or a
probe on CAN_H, CAN_L, or the two -- a maths channel of CAN_H less CAN_L.

Classic CAN, as ISO 11898-1 has it: 11- and 29-bit identifiers, data and
remote frames, bit stuffing, the 15-bit CRC, the acknowledgement. A CAN FD
frame is recognised, and said to be one, but not read.

Two steps. First the samples become levels -- recessive or dominant -- at a
threshold with some hysteresis, so that noise on a slow edge is not taken for
bits. Then the levels become bits, by how long each run of one level lasts:
a run of three bit times is three bits. Timing taken afresh at every edge is
how a CAN controller keeps in step with a bus whose nodes' clocks differ, and
stuffing makes sure there is an edge at least every six bits.

Both steps carry on from one block of samples to the next, so a stream is read
as it arrives and a frame that falls across two blocks is read whole. A gap --
samples that were lost -- abandons whatever frame was being read.

Nothing here loops over samples: a block is turned into runs with NumPy, and
only the bits of a frame are gone through one at a time, a hundred or so each.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: The usual bit rates, which a measured one is taken to be when it is near.
BITRATES = (10_000, 20_000, 50_000, 83_333, 100_000, 125_000, 250_000, 500_000, 800_000, 1_000_000)
#: How near, as a share of the bit rate.
NEAR = 0.05
#: The CRC's polynomial: x^15 + x^14 + x^10 + x^8 + x^7 + x^4 + x^3 + 1.
CRC_POLYNOMIAL = 0x4599
#: Recessive bits that make the bus idle: the end of frame and intermission,
#: or a node joining a bus that is already running.
IDLE_BITS = 11
#: Recessive bits after a frame before the next may start: the intermission.
INTERMISSION = 3
#: The fewest samples a bit is read from: fewer, and its edges cannot be told
#: from one bit to the next.
FEWEST_SAMPLES = 3


@dataclass
class Frame:
    """One frame read off the bus, good or not."""

    #: The sample numbers of its start of frame, and of the last bit read of it.
    start: int
    end: int = 0
    identifier: int = 0
    extended: bool = False
    remote: bool = False
    dlc: int = 0
    data: bytes = b""
    #: Whether some node acknowledged it: drove the ACK slot dominant.
    acked: bool = False
    #: What was wrong, in a few words, or "" for a good frame.
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def crc15(bits) -> int:
    """CAN's CRC of these bits: start of frame to the end of the data, unstuffed."""
    crc = 0
    for bit in bits:
        top = ((crc >> 14) & 1) ^ bit
        crc = (crc << 1) & 0x7FFF
        if top:
            crc ^= CRC_POLYNOMIAL
    return crc


def _bits_of(value: int, count: int) -> list[int]:
    return [(value >> (count - 1 - i)) & 1 for i in range(count)]


def _number(bits) -> int:
    value = 0
    for bit in bits:
        value = (value << 1) | bit
    return value


def _bytes(bits) -> bytes:
    return bytes(_number(bits[i : i + 8]) for i in range(0, len(bits), 8))


def encode(
    identifier: int,
    data: bytes = b"",
    extended: bool = False,
    remote: bool = False,
    dlc: int | None = None,
    acked: bool = True,
) -> list[int]:
    """A frame as the bits on the bus, stuffed: 0 dominant, 1 recessive.

    From the start of frame to the end of the end of frame, with the ACK slot
    driven if ``acked``. For tests, and for anything that makes a bus up.
    """
    dlc = len(data) if dlc is None else dlc
    if extended:
        head = [0, *_bits_of(identifier >> 18, 11), 1, 1, *_bits_of(identifier & 0x3FFFF, 18)]
        head += [int(remote), 0, 0]
    else:
        head = [0, *_bits_of(identifier, 11), int(remote), 0, 0]
    head += _bits_of(dlc, 4)
    if not remote:
        for byte in data:
            head += _bits_of(byte, 8)
    unstuffed = head + _bits_of(crc15(head), 15)
    stuffed, run, last = [], 0, -1
    for bit in unstuffed:
        stuffed.append(bit)
        run = run + 1 if bit == last else 1
        last = bit
        if run == 5:
            stuffed.append(1 - bit)
            run, last = 1, 1 - bit
    # CRC delimiter, the ACK slot and its delimiter, and the end of frame.
    return stuffed + [1, 0 if acked else 1, 1] + [1] * 7


def levels(samples: np.ndarray, low: float, high: float, start: bool = True) -> np.ndarray:
    """Recessive (True) or dominant (False) for each sample, with hysteresis.

    A sample above ``high`` is recessive and below ``low`` dominant -- for a
    signal where dominant is the higher, swap them and invert the result. In
    between, it is what it was. ``start`` is the level before the first
    sample; a gap -- not a number -- keeps the level it had.
    """
    decided = np.full(len(samples), -1, dtype=np.int8)
    with np.errstate(invalid="ignore"):
        decided[samples > high] = 1
        decided[samples < low] = 0
    # Each undecided sample takes the last decided one before it.
    where = np.where(decided >= 0, np.arange(len(samples)), -1)
    np.maximum.accumulate(where, out=where)
    held = np.where(where >= 0, decided[np.maximum(where, 0)], int(start))
    return held.astype(bool)


def guess_bitrate(recessive: np.ndarray, rate: float) -> float | None:
    """The bit rate these levels were sent at, from the shortest runs of one
    level, which are single bits; a usual rate where it is near one. None
    where there are too few edges to tell."""
    edges = np.flatnonzero(recessive[1:] != recessive[:-1])
    runs = np.diff(edges)
    if len(runs) < 8:
        return None
    shortest = np.percentile(runs, 5)
    single = runs[(runs >= 0.6 * shortest) & (runs <= 1.4 * shortest)]
    if not len(single):
        return None
    measured = rate / float(np.mean(single))
    usual = min(BITRATES, key=lambda b: abs(b - measured))
    return float(usual) if abs(usual - measured) <= NEAR * usual else measured


@dataclass
class _Reading:
    """A frame part way through: its bits so far, unstuffed, and the stuffing count."""

    frame: Frame
    bits: list[int] = field(default_factory=list)
    #: Bits the same in a row, and what they are, for finding the stuff bits.
    run: int = 0
    last: int = -1
    #: How many bits the stuffed part has -- to the last of the CRC -- once known.
    stuffed_until: int | None = None
    #: The bits after the CRC: delimiter, ACK slot, ACK delimiter, end of frame.
    tail: list[int] = field(default_factory=list)


class CanDecoder:
    """CAN frames from a run of levels, fed a block at a time."""

    def __init__(self, rate: float, bitrate: float) -> None:
        #: Samples a bit, which may be a fraction.
        self.per_bit = rate / bitrate
        if self.per_bit < FEWEST_SAMPLES:
            raise ValueError(
                f"{rate:g} samples a second is too few for {bitrate:g} bits a second: "
                f"each bit needs {FEWEST_SAMPLES} samples at least"
            )
        self.reset()

    def reset(self) -> None:
        """Forget what was being read: after a gap, or to start again."""
        #: The level of the run that is still going, and the sample it began at.
        self._level: bool | None = None
        self._run_start = 0
        #: Recessive bits in a row, while waiting for the bus to be idle.
        self._idle = 0
        self._idle_needed = IDLE_BITS
        self._reading: _Reading | None = None
        #: The sample the next block is expected to start at.
        self._next: int | None = None

    def feed(self, recessive: np.ndarray, first: int) -> list[Frame]:
        """The frames that end in these levels; ``first`` is the number of the
        first sample. A block that does not follow the last is a gap."""
        found: list[Frame] = []
        if self._next is not None and first != self._next:
            found += self._abandon("samples were lost")
            self.reset()
        self._next = first + len(recessive)
        if not len(recessive):
            return found
        if self._level is None:
            self._level, self._run_start = bool(recessive[0]), first
        before = np.concatenate(([self._level], recessive[:-1]))
        for edge in np.flatnonzero(recessive != before):
            at = first + int(edge)
            bits = round((at - self._run_start) / self.per_bit)
            found += self._run(self._level, self._run_start, bits)[1]
            self._level, self._run_start = bool(recessive[edge]), at
        # The run still going at the end of the block: as much of it as there
        # is, while a frame is being read, so that one ending in it is not
        # kept waiting for the next edge -- which on an idle bus may never come.
        if self._reading is not None and self._level:
            whole = int((self._next - self._run_start) // self.per_bit)
            if whole:
                used, frames = self._run(True, self._run_start, whole, partial=True)
                found += frames
                self._run_start += round(used * self.per_bit)
        return found

    def flush(self) -> list[Frame]:
        """At the end of a capture: the frame being read, as far as it got."""
        found: list[Frame] = []
        if self._reading is not None and self._next is not None and self._level is not None:
            bits = round((self._next - self._run_start) / self.per_bit)
            found += self._run(self._level, self._run_start, bits)[1]
        found += self._abandon("the capture ends part way through it")
        self.reset()
        return found

    # --- runs into bits -----------------------------------------------------------------
    def _run(
        self, recessive: bool, start: int, bits: int, partial: bool = False
    ) -> tuple[int, list[Frame]]:
        """Read a run of ``bits`` bits of one level, from sample ``start``. With
        ``partial``, only while a frame is being read. How many bits were used,
        and the frames that ended in them."""
        found: list[Frame] = []
        level = int(recessive)
        number = 0
        while number < bits:
            if self._reading is None:
                if partial:
                    break
                if level:
                    # Idle: counted, not gone through a bit at a time.
                    self._idle = min(self._idle + bits - number, self._idle_needed)
                    number = bits
                    break
                if self._idle < self._idle_needed:
                    self._idle = 0  # dominant on a bus not yet idle: not a start of frame
                    number = bits
                    break
                at = start + round(number * self.per_bit)
                self._reading = _Reading(Frame(start=at, end=at), bits=[0], run=1, last=0)
                self._idle = 0
                number += 1
                continue
            if (done := self._bit(level, start + round(number * self.per_bit))) is not None:
                found.append(done)
            number += 1
        return number, found

    # --- bits into a frame --------------------------------------------------------------
    def _bit(self, bit: int, at: int) -> Frame | None:
        reading = self._reading
        reading.frame.end = at
        until = reading.stuffed_until
        stuffed = until is None or len(reading.bits) < until
        # After five the same comes a stuff bit -- after the last of the CRC too.
        if reading.run == 5 and (stuffed or (len(reading.bits) == until and not reading.tail)):
            if bit == reading.last:
                return self._finish("a stuff error: six bits the same")
            reading.run, reading.last = (1 if stuffed else 0), bit
            return None
        if stuffed:
            reading.run = reading.run + 1 if bit == reading.last else 1
            reading.last = bit
            reading.bits.append(bit)
            return self._fields()
        reading.run = 0
        reading.tail.append(bit)
        return self._tail()

    def _fields(self) -> Frame | None:
        """Read what the bits so far say; work out where the CRC ends once the
        length is known, and check it once it is there."""
        reading = self._reading
        bits, frame = reading.bits, reading.frame
        count = len(bits)
        if count == 12:
            frame.identifier = _number(bits[1:12])
        elif count == 14:
            frame.extended = bool(bits[13])
            if not frame.extended:
                frame.remote = bool(bits[12])
        if not frame.extended:
            if count == 15 and bits[14]:
                return self._finish("CAN FD, which is not read")
            if count == 19:
                self._length(_number(bits[15:19]), 19)
        elif count == 32:
            frame.identifier = (frame.identifier << 18) | _number(bits[14:32])
        elif count == 33:
            frame.remote = bool(bits[32])
        elif count == 34 and bits[33]:
            return self._finish("CAN FD, which is not read")
        elif count == 39:
            self._length(_number(bits[35:39]), 39)
        if count == reading.stuffed_until:
            data_end = count - 15
            if not frame.remote:
                frame.data = _bytes(bits[data_end - 8 * min(frame.dlc, 8) : data_end])
            if crc15(bits[:data_end]) != _number(bits[data_end:]):
                frame.error = "the CRC is wrong"
        return None

    def _length(self, dlc: int, header: int) -> None:
        reading = self._reading
        reading.frame.dlc = dlc
        data = 0 if reading.frame.remote else 8 * min(dlc, 8)
        reading.stuffed_until = header + data + 15

    def _tail(self) -> Frame | None:
        """The CRC delimiter, the ACK slot and its delimiter, and the end of frame."""
        reading = self._reading
        tail, frame = reading.tail, reading.frame
        last = len(tail) - 1
        if last == 0 and not tail[0]:
            return self._finish("the CRC delimiter is dominant")
        if last == 1:
            frame.acked = not tail[1]
        if last == 2 and not tail[2]:
            return self._finish("the ACK delimiter is dominant")
        if last >= 3 and not tail[last]:
            # Dominant in the end of frame: another node saw something wrong.
            return self._finish("an error frame in the end of frame")
        if last == 9:
            return self._finish("", INTERMISSION)
        return None

    def _finish(self, error: str, idle_needed: int = IDLE_BITS) -> Frame:
        frame = self._reading.frame
        if error and not frame.error:
            frame.error = error
        self._reading = None
        self._idle, self._idle_needed = 0, idle_needed
        return frame

    def _abandon(self, why: str) -> list[Frame]:
        return [self._finish(why)] if self._reading is not None else []
