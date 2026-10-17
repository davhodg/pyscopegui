# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Channels decoded as buses -- CAN, UART, SPI, I2C -- and what has been found on them.

An instrument's channels are read as they arrive, as maths channels are worked
out: so a stream is decoded live, a scope's sweep is decoded when it comes, and
what is already held is decoded as soon as it is asked for. A bus with more
than one line -- SPI's clock and data, I2C's SCL and SDA -- has them all from
one instrument, whose channels are sampled together. What is found is kept
for as long as the samples it was read from are: when its start has gone from
the history, it goes too.

Each protocol has a setup -- which channels, and how the bus is set -- and a
decoding, which keeps a decoder fed and what it has found. How the bits are
read is in the decoders: pyscopegui.core.can_decode, uart_decode, spi_decode
and i2c_decode.

An analog channel is made logic levels at a threshold, with a little
hysteresis, so that noise on a slow edge is not read as bits; a logic channel
is used as it is.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import ClassVar

import numpy as np

from pyscopegui.backends.base import Block
from pyscopegui.core.can_decode import CanDecoder, guess_bitrate, levels
from pyscopegui.core.i2c_decode import I2cDecoder
from pyscopegui.core.sharing import is_group
from pyscopegui.core.spi_decode import SpiDecoder
from pyscopegui.core.uart_decode import EVEN, NONE, ODD, UartDecoder

CAN, UART, SPI, I2C = "can", "uart", "spi", "i2c"
#: What each is called.
PROTOCOLS = {CAN: "CAN", UART: "UART", SPI: "SPI", I2C: "I²C"}
#: Under this name in the workspace, and an instrument's: its channels decoded.
SAVED_KEY = "decode"
#: And under this, the keys of those of its buses that are paused.
PAUSED_KEY = "decode_paused"
#: The most found kept for one decoding. Past it the oldest go.
MOST_ITEMS = 100_000
#: Either side of a threshold that a signal has to go to change level, in volts.
HYSTERESIS = 0.1
#: Where an analog channel carrying logic divides low from high, unless it is
#: said: between the 0.8 V and 2 V of TTL, which 3.3 V and 5 V logic both meet.
LOGIC_THRESHOLD = 1.4

#: What a CAN channel is: how dominant and recessive look on it.
LOGIC, CAN_H, CAN_L, DIFFERENTIAL = "logic", "can_h", "can_l", "differential"
SOURCES = {
    LOGIC: "Logic level: a transceiver's RX or TX",
    CAN_H: "CAN_H",
    CAN_L: "CAN_L",
    DIFFERENTIAL: "CAN_H \u2212 CAN_L",
}
#: Where dominant and recessive are told apart on CAN, in volts, unless it is
#: said: between 2.5 V recessive and 3.5 V on CAN_H, 1.5 V on CAN_L, and
#: between nought and 2 V across the two -- where ISO 11898 puts a receiver's.
THRESHOLDS = {CAN_H: 3.0, CAN_L: 2.0, DIFFERENTIAL: 0.7}


def _number(value: object, default: float | None, whole: bool = False):
    """A number from what was saved, or the default for anything else."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    return int(value) if whole else float(value)


def _key(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def high(samples: np.ndarray, threshold: float, before: bool) -> tuple[np.ndarray, bool]:
    """High or not for each sample, and the level it ended at: a logic channel
    as it is, an analog one at the threshold with hysteresis. ``before`` is the
    level before the first sample."""
    if samples.dtype.kind in "ub":
        found = samples >= 1
    else:
        found = levels(samples, threshold - HYSTERESIS, threshold + HYSTERESIS, start=before)
    return found, bool(found[-1]) if len(found) else before


# --- how each is set up -------------------------------------------------------------------------
@dataclass(frozen=True)
class CanSetup:
    """How one channel is decoded as CAN."""

    protocol: ClassVar[str] = CAN
    #: The instrument's own key for the channel: "CH1", "D3", "maths:CH1-CH2".
    channel: str
    source: str = DIFFERENTIAL
    #: Bits a second, or nought to find it from the signal.
    bitrate: int = 0
    #: Volts, or None for the source's usual. Not used for a logic level.
    threshold: float | None = None
    #: The multicast group its frames are sent on to, or "" for not sent:
    #: see pyscopegui.core.sharing.
    share: str = ""

    @property
    def key(self) -> str:
        return f"can:{self.channel}"

    @property
    def main(self) -> str:
        """The channel it is decoded from, and changed from."""
        return self.channel

    def channels(self) -> tuple[str, ...]:
        return (self.channel,)

    @property
    def level(self) -> float:
        """The threshold in use."""
        return self.threshold if self.threshold is not None else THRESHOLDS.get(self.source, 0.5)

    def as_saved(self) -> dict:
        return {
            "protocol": CAN,
            "channel": self.channel,
            "source": self.source,
            "bitrate": self.bitrate,
            "threshold": self.threshold,
            "share": self.share,
        }

    @classmethod
    def from_saved(cls, saved: dict) -> CanSetup | None:
        channel, source = _key(saved.get("channel")), saved.get("source")
        bitrate = _number(saved.get("bitrate", 0), None, whole=True)
        threshold = saved.get("threshold")
        if not channel or source not in SOURCES or bitrate is None:
            return None
        if threshold is not None and _number(threshold, None) is None:
            return None
        share = _key(saved.get("share", ""))
        if share and not is_group(share):
            share = ""
        return cls(channel, source, max(bitrate, 0), threshold, share)


@dataclass(frozen=True)
class UartSetup:
    """How one channel is decoded as a serial line."""

    protocol: ClassVar[str] = UART
    line: str
    baud: int = 115200
    bits: int = 8
    parity: str = NONE
    stop_bits: float = 1
    msb_first: bool = False
    #: RS-232 at the connector: the line the other way up.
    inverted: bool = False
    threshold: float | None = None

    @property
    def key(self) -> str:
        return f"uart:{self.line}"

    @property
    def main(self) -> str:
        return self.line

    def channels(self) -> tuple[str, ...]:
        return (self.line,)

    def as_saved(self) -> dict:
        return {
            "protocol": UART,
            "line": self.line,
            "baud": self.baud,
            "bits": self.bits,
            "parity": self.parity,
            "stop_bits": self.stop_bits,
            "msb_first": self.msb_first,
            "inverted": self.inverted,
            "threshold": self.threshold,
        }

    @classmethod
    def from_saved(cls, saved: dict) -> UartSetup | None:
        line = _key(saved.get("line"))
        baud = _number(saved.get("baud"), None, whole=True)
        bits = _number(saved.get("bits", 8), None, whole=True)
        stop = _number(saved.get("stop_bits", 1), None)
        parity = saved.get("parity", NONE)
        if not line or not baud or baud <= 0 or bits not in range(5, 10):
            return None
        if parity not in (NONE, EVEN, ODD) or stop not in (1, 1.5, 2):
            return None
        return cls(
            line,
            baud,
            bits,
            parity,
            stop,
            saved.get("msb_first") is True,
            saved.get("inverted") is True,
            _number(saved.get("threshold"), None),
        )


@dataclass(frozen=True)
class SpiSetup:
    """How an SPI bus is decoded: its clock, data and chip select, of one instrument."""

    protocol: ClassVar[str] = SPI
    sclk: str
    #: Either data line may be left out, and the chip select: "" for none.
    mosi: str = ""
    miso: str = ""
    cs: str = ""
    mode: int = 0
    bits: int = 8
    msb_first: bool = True
    cs_active_low: bool = True
    threshold: float | None = None

    @property
    def key(self) -> str:
        return f"spi:{self.sclk}"

    @property
    def main(self) -> str:
        return self.sclk

    def channels(self) -> tuple[str, ...]:
        return tuple(c for c in (self.sclk, self.mosi, self.miso, self.cs) if c)

    def as_saved(self) -> dict:
        return {
            "protocol": SPI,
            "sclk": self.sclk,
            "mosi": self.mosi,
            "miso": self.miso,
            "cs": self.cs,
            "mode": self.mode,
            "bits": self.bits,
            "msb_first": self.msb_first,
            "cs_active_low": self.cs_active_low,
            "threshold": self.threshold,
        }

    @classmethod
    def from_saved(cls, saved: dict) -> SpiSetup | None:
        sclk = _key(saved.get("sclk"))
        mosi, miso, cs = (_key(saved.get(line, "")) for line in ("mosi", "miso", "cs"))
        mode = _number(saved.get("mode", 0), None, whole=True)
        bits = _number(saved.get("bits", 8), None, whole=True)
        if not sclk or not (mosi or miso) or mode not in (0, 1, 2, 3):
            return None
        if bits is None or not 1 <= bits <= 64:
            return None
        return cls(
            sclk,
            mosi,
            miso,
            cs,
            mode,
            bits,
            saved.get("msb_first", True) is not False,
            saved.get("cs_active_low", True) is not False,
            _number(saved.get("threshold"), None),
        )


@dataclass(frozen=True)
class I2cSetup:
    """How an I2C bus is decoded: its SCL and SDA, of one instrument."""

    protocol: ClassVar[str] = I2C
    scl: str
    sda: str
    threshold: float | None = None

    @property
    def key(self) -> str:
        return f"i2c:{self.scl}"

    @property
    def main(self) -> str:
        return self.scl

    def channels(self) -> tuple[str, ...]:
        return (self.scl, self.sda)

    def as_saved(self) -> dict:
        return {"protocol": I2C, "scl": self.scl, "sda": self.sda, "threshold": self.threshold}

    @classmethod
    def from_saved(cls, saved: dict) -> I2cSetup | None:
        scl, sda = _key(saved.get("scl")), _key(saved.get("sda"))
        if not scl or not sda or scl == sda:
            return None
        return cls(scl, sda, _number(saved.get("threshold"), None))


Setup = CanSetup | UartSetup | SpiSetup | I2cSetup
_SETUPS = {setup.protocol: setup for setup in (CanSetup, UartSetup, SpiSetup, I2cSetup)}


def from_saved(saved: object) -> Setup | None:
    """A setup from what was saved, of whichever protocol it says; None for
    anything that is not one."""
    if not isinstance(saved, dict):
        return None
    kind = _SETUPS.get(saved.get("protocol", CAN))
    return kind.from_saved(saved) if kind is not None else None


# --- what each has found ----------------------------------------------------------------------
@dataclass
class Message:
    """Characters that came together on a serial line: a burst, with no more
    than a couple of characters' time between any two."""

    start: int
    end: int
    values: list[int]
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


class Decoding:
    """One bus, decoded: kept up to date as blocks arrive at its instrument."""

    def __init__(self, setup: Setup) -> None:
        self.setup = setup
        #: What has been found, oldest first: frames, messages or transfers.
        self.items: deque = deque(maxlen=MOST_ITEMS)
        #: The rate the items' sample numbers are at.
        self.rate = 1.0
        #: What is wrong, where nothing can be decoded: too few samples a bit.
        self.problem = ""
        #: Paused: kept, with what it found, but nothing more decoded until
        #: it is set going again.
        self.paused = False
        self.reset()

    @property
    def key(self) -> str:
        return self.setup.key

    def pause(self, paused: bool) -> None:
        """Pause, or go on: from the next block, as though from a gap, rather
        than joining what came after the pause to what came before it."""
        if self.paused and not paused:
            self._high = {}
            self._restart()
        self.paused = paused

    def reset(self) -> None:
        """Start again, with nothing found: a new run, or the history cleared."""
        self.items.clear()
        self.problem = ""
        self._high: dict[str, bool] = {}
        self._restart()

    def _restart(self) -> None:
        """Make the decoder again: from the next block, for a new run or rate."""

    def take_block(self, block: Block) -> list:
        """Decode an instrument's block: its share of the channels decoded. A
        sweep is complete in itself, and replaces what was found before."""
        data = {key: block.data.get(key) for key in self.setup.channels()}
        if any(samples is None for samples in data.values()):
            return []
        if block.sweep:
            self.items.clear()
            self._restart()
        if block.rate != self.rate:
            self.rate = block.rate
            self._restart()
        found = self._take(block.first, data, block.sweep)
        self.items.extend(found)
        return found

    def _take(self, first: int, data: dict[str, np.ndarray], sweep: bool) -> list:
        raise NotImplementedError

    def _levels(self, key: str, samples: np.ndarray) -> np.ndarray:
        threshold = getattr(self.setup, "threshold", None)
        found, self._high[key] = high(
            samples,
            LOGIC_THRESHOLD if threshold is None else threshold,
            self._high.get(key, True),
        )
        return found

    def forget_before(self, first: int) -> None:
        """Let go of what starts before this sample: no longer held."""
        while self.items and self.items[0].start < first:
            self.items.popleft()

    def errors(self) -> int:
        return sum(1 for item in self.items if item.error)


class CanDecoding(Decoding):
    """A channel decoded as CAN."""

    @property
    def frames(self) -> deque:
        return self.items

    def _restart(self) -> None:
        self.bitrate: float | None = float(self.setup.bitrate) or None
        self._decoder: CanDecoder | None = None
        #: Whether the signal was high at the end of the last samples taken.
        self._was_high = self.setup.source in (LOGIC, CAN_L)

    def _take(self, first: int, data: dict[str, np.ndarray], sweep: bool) -> list:
        return self.take(data[self.setup.channel], first, self.rate, sweep)

    def take(self, samples: np.ndarray, first: int, rate: float, sweep: bool = False) -> list:
        """Decode these samples, numbered from ``first``: the frames found."""
        if not len(samples):
            return []
        levels_now, self._was_high = recessive(self.setup, samples, self._was_high)
        if self._decoder is None or rate != self.rate:
            self.rate = rate
            if self.bitrate is None:
                self.bitrate = guess_bitrate(levels_now, rate)
                if self.bitrate is None:
                    return []  # not enough of the bus yet to tell its bit rate
            try:
                self._decoder = CanDecoder(rate, self.bitrate)
                self.problem = ""
            except ValueError as exc:
                self.problem = str(exc)
                return []
        found = self._decoder.feed(levels_now, first)
        if sweep:
            found += self._decoder.flush()
        return found


def recessive(setup: CanSetup, samples: np.ndarray, was_high: bool) -> tuple[np.ndarray, bool]:
    """Recessive or not for each sample on a CAN channel, and whether the
    signal ended high: ``was_high`` is whether it was before the first."""
    if setup.source == LOGIC:
        found = samples >= 0.5
        return found, bool(found[-1]) if len(found) else was_high
    middle = setup.level
    above = levels(samples, middle - HYSTERESIS, middle + HYSTERESIS, start=was_high)
    ended = bool(above[-1]) if len(above) else was_high
    # CAN_H, and CAN_H less CAN_L, are high when dominant; CAN_L is low.
    return (above if setup.source == CAN_L else ~above), ended


class UartDecoding(Decoding):
    """A serial line decoded: its characters, a burst at a time."""

    #: Characters' time with nothing sent that ends a burst.
    BURST_GAP = 2

    def _restart(self) -> None:
        self._decoder: UartDecoder | None = None
        self._open: Message | None = None

    def _take(self, first: int, data: dict[str, np.ndarray], sweep: bool) -> list:
        setup = self.setup
        if self._decoder is None:
            try:
                self._decoder = UartDecoder(
                    self.rate,
                    setup.baud,
                    setup.bits,
                    setup.parity,
                    setup.stop_bits,
                    setup.msb_first,
                    setup.inverted,
                )
                self.problem = ""
            except ValueError as exc:
                self.problem = str(exc)
                return []
        samples = data[setup.line]
        characters = self._decoder.feed(self._levels(setup.line, samples), first)
        each = (1 + setup.bits + (setup.parity != NONE) + setup.stop_bits) * self._decoder.per_bit
        gap = self.BURST_GAP * each
        found: list[Message] = []
        for character in characters:
            if self._open is not None and character.start - self._open.end > gap:
                found.append(self._open)
                self._open = None
            if self._open is None:
                self._open = Message(character.start, character.end, [], "")
            self._open.values.append(character.value)
            self._open.end = character.end
            if character.error and not self._open.error:
                self._open.error = character.error
        # A burst nothing has followed for long enough is finished.
        if self._open is not None and (sweep or first + len(samples) - self._open.end > gap):
            found.append(self._open)
            self._open = None
        return found


class SpiDecoding(Decoding):
    """An SPI bus decoded: its transfers."""

    def _restart(self) -> None:
        setup = self.setup
        self._decoder = SpiDecoder(setup.mode, setup.bits, setup.msb_first, setup.cs_active_low)

    def _take(self, first: int, data: dict[str, np.ndarray], sweep: bool) -> list:
        setup = self.setup

        def line(key: str):
            return self._levels(key, data[key]) if key else None

        found = self._decoder.feed(
            first,
            line(setup.sclk),
            mosi=line(setup.mosi),
            miso=line(setup.miso),
            cs=line(setup.cs),
        )
        if sweep:
            found += self._decoder.flush()
        return found


class I2cDecoding(Decoding):
    """An I2C bus decoded: its transfers."""

    def _restart(self) -> None:
        self._decoder = I2cDecoder()

    def _take(self, first: int, data: dict[str, np.ndarray], sweep: bool) -> list:
        setup = self.setup
        scl = self._levels(setup.scl, data[setup.scl])
        found = self._decoder.feed(first, scl, self._levels(setup.sda, data[setup.sda]))
        if sweep:
            found += self._decoder.flush()
        return found


_DECODINGS = {CAN: CanDecoding, UART: UartDecoding, SPI: SpiDecoding, I2C: I2cDecoding}


def decoding_for(setup: Setup) -> Decoding:
    """A decoding of the bus this setup says."""
    return _DECODINGS[setup.protocol](setup)
