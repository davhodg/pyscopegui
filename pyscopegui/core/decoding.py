# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Channels decoded as buses -- CAN, UART, SPI, I2C, parallel -- and what has been found on them.

An instrument's channels are read as they arrive, as maths channels are worked
out: so a stream is decoded live, a scope's sweep is decoded when it comes, and
what is already held is decoded as soon as it is asked for. A bus with more
than one line -- SPI's clock and data, I2C's SCL and SDA -- has them all from
one instrument, whose channels are sampled together. What is found is kept
for as long as the samples it was read from are: when its start has gone from
the history, it goes too.

Each protocol has a setup -- which channels, and how the bus is set -- and a
decoding, which keeps a decoder fed and what it has found. How the bits are
read is in the decoders: pyscopegui.core.can_decode, uart_decode, spi_decode,
i2c_decode and parallel_decode.

An analog channel is made logic levels at a threshold, with a little
hysteresis, so that noise on a slow edge is not read as bits; a logic channel
is used as it is.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import ClassVar

import numpy as np

from pyscopegui.backends.base import ANALOG, Block, Channel
from pyscopegui.core.can_decode import CanDecoder, guess_bitrate, levels
from pyscopegui.core.i2c_decode import I2cDecoder
from pyscopegui.core.parallel_decode import (
    EDGES,
    NO_MUX,
    RISING,
    SELECT,
    ParallelDecoder,
    WordReader,
)
from pyscopegui.core.sharing import is_group
from pyscopegui.core.spi_decode import SpiDecoder
from pyscopegui.core.uart_decode import EVEN, NONE, ODD, UartDecoder

CAN, UART, SPI, I2C, PARALLEL = "can", "uart", "spi", "i2c", "parallel"
#: What each is called.
PROTOCOLS = {CAN: "CAN", UART: "UART", SPI: "SPI", I2C: "I²C", PARALLEL: "Parallel"}
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


#: How a parallel bus's words are numbers: as they are, offset binary -- the
#: middle code nought, as many ADCs send -- or two's complement.
UNSIGNED, OFFSET, TWOS = "unsigned", "offset", "twos"
CODINGS = {UNSIGNED: "Unsigned", OFFSET: "Offset binary", TWOS: "Two's complement"}


def signed(words: np.ndarray, width: int, coding: str) -> np.ndarray:
    """Words as the numbers they stand for, as the coding says."""
    words = np.asarray(words, dtype=np.int64)
    if coding == OFFSET:
        return words - (1 << (width - 1))
    if coding == TWOS:
        return np.where(words >= 1 << (width - 1), words - (1 << width), words)
    return words


@dataclass(frozen=True)
class ParallelSetup:
    """How a parallel bus is decoded: its data lines, bit 0 first, and a clock,
    a multiplex line and an enable if it has them -- all of one instrument."""

    protocol: ClassVar[str] = PARALLEL
    data: tuple[str, ...]
    #: The clock, or "" to read a word wherever the lines change and settle.
    clock: str = ""
    edge: str = RISING
    #: Without a clock: how long the lines hold still for a word, in seconds;
    #: nought for two samples.
    settle_s: float = 0.0
    #: What says more about each word, or "": for now a channel select, its
    #: level saying which of two channels a word is from. ``mux_swapped`` has
    #: a high level channel A.
    mux: str = ""
    mux_kind: str = SELECT
    mux_swapped: bool = False
    #: Active while a transfer is sent, or "" for none.
    enable: str = ""
    enable_active_low: bool = True
    coding: str = UNSIGNED
    threshold: float | None = None
    #: Its words drawn as channels of the instrument, one for each channel a
    #: select says, held at each word until the next: an ADC's samples.
    plot: bool = False
    #: In volts, the span from the lowest word to the highest -- an ADC's
    #: input span, 2 V peak to peak, say; nought to draw the numbers as they are.
    full_scale: float = 0.0

    @property
    def key(self) -> str:
        return f"parallel:{self.data[0]}"

    @property
    def main(self) -> str:
        return self.data[0]

    @property
    def width(self) -> int:
        return len(self.data)

    def channels(self) -> tuple[str, ...]:
        # A line may be two things at once: the AD9238's clock is its channel select.
        return tuple(dict.fromkeys(c for c in (*self.data, self.clock, self.mux, self.enable) if c))

    def stream_name(self, stream: int) -> str:
        """What a channel select's level is called: A or B."""
        return "AB"[stream ^ int(self.mux_swapped)]

    def streams(self) -> list[tuple[int | None, str]]:
        """The channels its words are drawn as: (the select's level, A or B),
        or one, (None, ""), without a select. None where it is not drawn."""
        if not self.plot:
            return []
        if self.mux:
            return sorted(
                ((level, self.stream_name(level)) for level in (0, 1)), key=lambda s: s[1]
            )
        return [(None, "")]

    def channel_key(self, name: str) -> str:
        """What a drawn channel's samples are held under: unlike any instrument's."""
        return f"bus:{self.key}" + (f":{name}" if name else "")

    def drawn_channel(self, name: str, main_name: str) -> Channel:
        """A drawn channel, called after the bus's first line: "Parallel D0 A"."""
        half = 1 << (self.width - 1)
        if self.full_scale:
            unit, scale = "V", self.full_scale / 2
        else:
            unit, scale = "", float(half)
        middle = scale if self.coding == UNSIGNED else 0.0
        said = f"Parallel {main_name}" + (f" {name}" if name else "")
        return Channel(
            self.channel_key(name),
            said,
            ANALOG,
            unit=unit,
            full_scale=scale,
            middle=middle,
            detail=f"{self.width}-bit {CODINGS[self.coding].lower()}",
        )

    def in_units(self, words: np.ndarray) -> np.ndarray:
        """Words as what is drawn: volts across the full scale, or the numbers."""
        values = signed(words, self.width, self.coding).astype(np.float64)
        if self.full_scale:
            values *= self.full_scale / (1 << self.width)
        return values

    def as_saved(self) -> dict:
        return {
            "protocol": PARALLEL,
            "data": list(self.data),
            "clock": self.clock,
            "edge": self.edge,
            "settle_s": self.settle_s,
            "mux": self.mux,
            "mux_kind": self.mux_kind,
            "mux_swapped": self.mux_swapped,
            "enable": self.enable,
            "enable_active_low": self.enable_active_low,
            "coding": self.coding,
            "threshold": self.threshold,
            "plot": self.plot,
            "full_scale": self.full_scale,
        }

    @classmethod
    def from_saved(cls, saved: dict) -> ParallelSetup | None:
        data = saved.get("data")
        if not isinstance(data, list) or not 1 <= len(data) <= 32:
            return None
        lines = tuple(_key(line) for line in data)
        if not all(lines) or len(set(lines)) != len(lines):
            return None
        clock, mux, enable = (_key(saved.get(line, "")) for line in ("clock", "mux", "enable"))
        if {clock, enable} & set(lines) - {""} or (mux and mux in lines):
            return None
        edge, kind = saved.get("edge", RISING), saved.get("mux_kind", SELECT)
        coding = saved.get("coding", UNSIGNED)
        settle = _number(saved.get("settle_s", 0.0), None)
        full_scale = _number(saved.get("full_scale", 0.0), None)
        if full_scale is None or full_scale < 0:
            return None
        if edge not in EDGES or kind not in (SELECT,) or coding not in CODINGS:
            return None
        if settle is None or settle < 0:
            return None
        return cls(
            lines,
            clock,
            edge,
            settle,
            mux,
            kind,
            saved.get("mux_swapped") is True,
            enable,
            saved.get("enable_active_low", True) is not False,
            coding,
            _number(saved.get("threshold"), None),
            saved.get("plot") is True,
            full_scale,
        )


Setup = CanSetup | UartSetup | SpiSetup | I2cSetup | ParallelSetup
_SETUPS = {
    setup.protocol: setup for setup in (CanSetup, UartSetup, SpiSetup, I2cSetup, ParallelSetup)
}


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


class WordChannels:
    """A parallel bus's words as channels: each sample the last word read, of
    its channel, in volts or as the number -- NaN before the first. Worked out
    block by block, as maths channels are, with what it needs carried on."""

    def __init__(self, setup: ParallelSetup, rate: float) -> None:
        self.setup = setup
        settle = round(setup.settle_s * rate) if setup.settle_s else ParallelDecoding.SETTLE
        self._reader = WordReader(setup.width, setup.edge, bool(setup.clock), max(settle, 1))
        self.reset()

    def reset(self) -> None:
        """Start afresh: a new run, a sweep, or after a gap."""
        self._reader.reset()
        self._held = {name: np.nan for _level, name in self.setup.streams()}
        self._high: dict[str, bool] = {}

    def take(self, first: int, data: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        """Each drawn channel's samples for this block, by its key."""
        setup = self.setup
        threshold = LOGIC_THRESHOLD if setup.threshold is None else setup.threshold
        levels = {}
        for key, samples in data.items():
            levels[key], self._high[key] = high(samples, threshold, self._high.get(key, True))
        count = len(data[setup.data[0]])
        at, words, streams = self._reader.read(
            first,
            [levels[key] for key in setup.data],
            clock=levels.get(setup.clock),
            select=levels.get(setup.mux),
        )
        values = setup.in_units(words)
        out = {}
        for level, name in setup.streams():
            mine = streams == level if level is not None else np.ones(len(at), dtype=bool)
            where = np.clip(at[mine], 0, None)
            got = values[mine]
            if not len(got):
                # No word of its own here: what it was holds on.
                out[setup.channel_key(name)] = np.full(count, self._held[name], np.float32)
                continue
            # The word read latest at or before each sample, or the one held from before.
            latest = np.searchsorted(where, np.arange(count), side="right") - 1
            samples = np.where(latest >= 0, got[np.clip(latest, 0, None)], self._held[name])
            self._held[name] = float(got[-1])
            out[setup.channel_key(name)] = samples.astype(np.float32)
        return out


class ParallelDecoding(Decoding):
    """A parallel bus decoded: its words, a transfer at a time."""

    #: Without a clock and a settle time said, the lines hold this many samples for a word.
    SETTLE = 2

    def _restart(self) -> None:
        setup = self.setup
        settle = round(setup.settle_s * self.rate) if setup.settle_s else self.SETTLE
        self._decoder = ParallelDecoder(
            setup.width,
            setup.edge,
            clocked=bool(setup.clock),
            settle=max(settle, 1),
            mux=setup.mux_kind if setup.mux else NO_MUX,
            enable_active_low=setup.enable_active_low,
        )

    def _take(self, first: int, data: dict[str, np.ndarray], sweep: bool) -> list:
        setup = self.setup
        # Each line made levels once, however many things it is.
        levels = {key: self._levels(key, samples) for key, samples in data.items()}
        found = self._decoder.feed(
            first,
            [levels[key] for key in setup.data],
            clock=levels.get(setup.clock),
            select=levels.get(setup.mux),
            enable=levels.get(setup.enable),
        )
        if sweep:
            found += self._decoder.flush()
        return found


_DECODINGS = {
    CAN: CanDecoding,
    UART: UartDecoding,
    SPI: SpiDecoding,
    I2C: I2cDecoding,
    PARALLEL: ParallelDecoding,
}


def decoding_for(setup: Setup) -> Decoding:
    """A decoding of the bus this setup says."""
    return _DECODINGS[setup.protocol](setup)
