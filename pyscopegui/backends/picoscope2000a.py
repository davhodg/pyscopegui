# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""PicoScope 2000 series scopes on Pico's ``ps2000a`` library: the 2206B and its relatives.

The newer of the two ranges that share the name. The two-channel 2206, 2207
and 2208, in their A and B forms; the mixed-signal ones, which add sixteen
logic inputs; and the four-channel 2405A to 2408B. The older scopes, on the
``ps2000`` library, are in ``picoscope2000``: this is that back end with the
other driver under it, and what is the same in the two -- scales and probes,
the thread the scope is read on, how a run is started and stopped -- is used
from there.

What differs is the driver. It answers every call with a status, not with
nought for no; it fills buffers it is handed, where the older one hands over
its own; a block can be as long as the scope's memory, which is thousands of
times what the older scopes have; and it says what the scope has -- how many
channels, which ranges -- so nothing is listed here by model.

A mixed-signal scope's logic inputs come in two ports of eight, D0 to D7 and
D8 to D15, each switched on as a whole with a threshold of its own, and each
input is a channel like any other once it is read.
"""

from __future__ import annotations

import copy
import ctypes
import math
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import numpy as np

from pyscopegui.backends import picoscope2000 as pico
from pyscopegui.backends.base import DIGITAL, LOST, Block, Channel, Scale, Setting
from pyscopegui.backends.picoscope2000 import (
    BLOCKS,
    RANGES,
    STREAM,
    ScopeError,
    Trigger,
    crossed,
)
from pyscopegui.core.acquire import HYSTERESIS
from pyscopegui.core.triggers import (
    BETWEEN,
    EDGE,
    EITHER,
    ENTER,
    LOW,
    PATTERN,
    PULSE,
    RUNT,
    SHORTER,
    WINDOW,
    Condition,
)

#: Set to the library's full path to use that one and look nowhere else.
LIBRARY_ENV = "PYSCOPEGUI_PS2000A"
LIBRARY = "ps2000a"

# --- what the driver calls things: Pico's "PicoScope 2000 Series (A API) Programmer's Guide" ---
#: The analog channels, in the driver's order: A is 0.
ANALOG = ("A", "B", "C", "D")
#: The first of the two ports of logic inputs; the second is one more.
DIGITAL_PORT0 = 0x80
#: Logic inputs in a port.
PORT_BITS = 8
PORTS = (0, 1)
COUPLING_AC, COUPLING_DC = 0, 1
TIME_UNITS_NS = 2
RATIO_NONE = 0
#: Full scale, unless the scope says otherwise when it is opened: these are
#: 8-bit scopes, and the driver leaves the bottom byte of its 16 bits empty.
MAX_VALUE = 32512
#: Written in place of a sample the driver lost to a full buffer: what a
#: channel sent as counts holds a gap as, so kept as it is.
LOST_DATA = LOST
#: A logic threshold is given in these: full scale is five volts.
THRESHOLD_VOLTS, THRESHOLD_COUNTS = 5.0, 32767
DEFAULT_THRESHOLD = 1.5
INFO_VARIANT, INFO_SERIAL = 3, 4
#: Asked of ps2000aGetChannelInformation: the ranges the scope has.
INFO_RANGES = 0
#: Trigger directions for an analog channel, PS2000A_THRESHOLD_DIRECTION:
#: above or below the upper threshold, for a pattern; through it, for an edge;
#: into or out of a window; through the lower threshold, for a pulse's width
#: to be timed from, since the driver will not have one threshold do both; and
#: a runt. A channel left out is given NONE, which is RISING.
ABOVE, BELOW = 0, 1
RISING, FALLING, RISING_OR_FALLING = 2, 3, 4
ENTER_WINDOW, EXIT_WINDOW = RISING, FALLING
RISING_LOWER, FALLING_LOWER = 7, 8
POSITIVE_RUNT, NEGATIVE_RUNT = 9, 10
NO_DIRECTION = RISING
#: And for a logic input, PS2000A_DIGITAL_DIRECTION.
DIGITAL_LOW, DIGITAL_HIGH = 1, 2
DIGITAL_RISING, DIGITAL_FALLING, DIGITAL_EITHER = 3, 4, 5
#: In a trigger condition: this has to be so.
CONDITION_TRUE = 1
#: A channel's trigger has one threshold, or two that make a window.
LEVEL_MODE, WINDOW_MODE = 0, 1
#: PS2000A_PULSE_WIDTH_TYPE: none, shorter, longer, or between.
PW_NONE, PW_LESS_THAN, PW_GREATER_THAN, PW_IN_RANGE = 0, 1, 2, 3
#: A steady voltage: at nought volts, the nearest the driver has to off.
WAVES = {"off": 8, "sine": 0, "square": 1, "triangle": 2}
#: When the generator puts its wave out: at once, or when the scope triggers.
NOW, ON_TRIGGER = "now", "trigger"
#: PS2000A_SIGGEN_TRIG_TYPE and _SOURCE: on a rising edge of the scope's trigger.
SIGGEN_RISING, SIGGEN_NONE, SIGGEN_SCOPE_TRIG = 0, 0, 1
#: As shots: start at the trigger and run on, rather than a number of cycles.
SIGGEN_CONTINUOUS_RUN = 0xFFFFFFFF
#: The most cycles it is asked for after a trigger: the driver's limit.
MOST_SHOTS = (1 << 30) - 1
GENERATOR_VOLTS = 2.0
GENERATOR_HZ = 1_000_000.0

OK = 0
NOT_FOUND = 3
BUFFER_STALL = 0x1C
#: What the driver answers when the scope is no longer there.
GONE = (NOT_FOUND, 0x07, 0x0C)
#: The driver's statuses that are worth words of their own. Any other is
#: given by its number, which Pico's PicoStatus.h has the meaning of.
STATUS = {
    0x01: "too many scopes are open",
    0x02: "the computer is out of memory",
    0x03: "no scope was found",
    0x04: "the scope's firmware could not be loaded",
    0x07: "the scope is not responding",
    0x08: "the scope's configuration is corrupt or missing",
    0x09: "the driver installed for it is too old",
    0x0A: "the scope's own memory is corrupt",
    0x0B: "this operating system is not supported by the driver",
    0x0C: "the scope is no longer open",
    0x0D: "the driver did not accept one of the values",
    0x0E: "it has no such timebase",
    0x0F: "it does not have that range",
    0x10: "it has no such channel",
    0x11: "that channel cannot be its trigger",
    0x13: "it has no signal generator",
    0x14: "streaming failed",
    0x15: "the block failed",
    0x1D: "that is more samples than its memory holds",
    0x27: "the scope is busy",
    0x2B: "it cannot sample at that interval",
}

#: Timebases run to the end of 32 bits; none past this is ever wanted.
MAX_TIMEBASE = 2**32 - 1
#: Below this a timebase that is refused is one too fast for the channels
#: that are on, and a slower one is tried; above it, it is the scope's last.
FIRST_STEADY_TIMEBASE = 3
#: The most samples a block is read as, however much memory the scope has:
#: a million points is more than a plot can show, and quick to read.
MOST_SAMPLES = 1_000_000
FEWEST_SAMPLES = pico.FEWEST_SAMPLES
AUTO_TRIGGER_MS = pico.AUTO_TRIGGER_MS
#: The buffer the driver fills between two polls when streaming, for each
#: channel: this many samples at the least, and this long at the rate it is
#: streaming at -- a hundred polls' worth -- so that a computer busy for a
#: moment, with a large save, say, does not leave the driver nowhere to put them.
STREAM_SAMPLES = 1_000_000
STREAM_S = 1.0
#: The fastest rate offered for streaming: a sample every 32 ns, which is the
#: most USB 2 carries from these scopes with one channel on.
FASTEST_RATE = 31_250_000
DEFAULT_RATE = pico.DEFAULT_RATE

_INT16, _INT32, _UINT32 = ctypes.c_int16, ctypes.c_int32, ctypes.c_uint32
_FLOAT, _VOID = ctypes.c_float, ctypes.c_void_p
_STATUS = ctypes.c_uint32
_P = ctypes.POINTER

#: What streaming calls when it has samples: the handle, how many, where in
#: the buffers they start, and five things not used here.
_CALLBACK_FACTORY = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
StreamingReady = _CALLBACK_FACTORY(
    None, _INT16, _INT32, _UINT32, _INT16, _UINT32, _INT16, _INT16, _VOID
)


class Conditions(ctypes.Structure):
    """PS2000A_TRIGGER_CONDITIONS: what has to be so, of each source, for a trigger."""

    _pack_ = 1
    _fields_ = [
        (name, _INT32) for name in ("a", "b", "c", "d", "external", "aux", "pulse_width", "digital")
    ]


class DigitalDirection(ctypes.Structure):
    """PS2000A_DIGITAL_CHANNEL_DIRECTIONS: a logic input, and the edge wanted of it."""

    _pack_ = 1
    _fields_ = [("channel", _INT32), ("direction", _INT32)]


class Properties(ctypes.Structure):
    """PS2000A_TRIGGER_CHANNEL_PROPERTIES: a channel's thresholds, in counts,
    each with the hysteresis it has to be passed by."""

    _pack_ = 1
    _fields_ = [
        ("upper", _INT16),
        ("upper_hysteresis", ctypes.c_uint16),
        ("lower", _INT16),
        ("lower_hysteresis", ctypes.c_uint16),
        ("channel", _INT32),
        ("mode", _INT32),
    ]


class PwqConditions(ctypes.Structure):
    """PS2000A_PWQ_CONDITIONS: which source's pulses the pulse-width qualifier times."""

    _pack_ = 1
    _fields_ = [(name, _INT32) for name in ("a", "b", "c", "d", "external", "aux", "digital")]


#: Name -> (return type, argument types), for the functions used here.
PROTOTYPES = {
    "ps2000aOpenUnit": (_STATUS, [_P(_INT16), ctypes.c_char_p]),
    "ps2000aCloseUnit": (_STATUS, [_INT16]),
    "ps2000aPingUnit": (_STATUS, [_INT16]),
    "ps2000aGetUnitInfo": (_STATUS, [_INT16, ctypes.c_char_p, _INT16, _P(_INT16), _UINT32]),
    "ps2000aMaximumValue": (_STATUS, [_INT16, _P(_INT16)]),
    "ps2000aGetAnalogueOffset": (_STATUS, [_INT16, _INT32, _INT32, _P(_FLOAT), _P(_FLOAT)]),
    "ps2000aGetChannelInformation": (
        _STATUS,
        [_INT16, _INT32, _INT32, _P(_INT32), _P(_INT32), _INT32],
    ),
    "ps2000aSetChannel": (_STATUS, [_INT16, _INT32, _INT16, _INT32, _INT32, _FLOAT]),
    "ps2000aSetDigitalPort": (_STATUS, [_INT16, _INT32, _INT16, _INT16]),
    "ps2000aSetSimpleTrigger": (
        _STATUS,
        [_INT16, _INT16, _INT32, _INT16, _INT32, _UINT32, _INT16],
    ),
    "ps2000aSetTriggerChannelConditions": (_STATUS, [_INT16, _P(Conditions), _INT16]),
    "ps2000aSetTriggerChannelDirections": (_STATUS, [_INT16, *[_INT32] * 6]),
    "ps2000aSetTriggerChannelProperties": (
        _STATUS,
        [_INT16, _P(Properties), _INT16, _INT16, _INT32],
    ),
    "ps2000aSetPulseWidthQualifier": (
        _STATUS,
        [_INT16, _P(PwqConditions), _INT16, _INT32, _UINT32, _UINT32, _INT32],
    ),
    "ps2000aSetTriggerDigitalPortProperties": (_STATUS, [_INT16, _P(DigitalDirection), _INT16]),
    "ps2000aGetTimebase2": (
        _STATUS,
        [_INT16, _UINT32, _INT32, _P(_FLOAT), _INT16, _P(_INT32), _UINT32],
    ),
    "ps2000aRunBlock": (
        _STATUS,
        [_INT16, _INT32, _INT32, _UINT32, _INT16, _P(_INT32), _UINT32, _VOID, _VOID],
    ),
    "ps2000aIsReady": (_STATUS, [_INT16, _P(_INT16)]),
    "ps2000aSetDataBuffer": (_STATUS, [_INT16, _INT32, _P(_INT16), _INT32, _UINT32, _INT32]),
    "ps2000aGetValues": (
        _STATUS,
        [_INT16, _UINT32, _P(_UINT32), _UINT32, _INT32, _UINT32, _P(_INT16)],
    ),
    "ps2000aRunStreaming": (
        _STATUS,
        [_INT16, _P(_UINT32), _INT32, _UINT32, _UINT32, _INT16, _UINT32, _INT32, _UINT32],
    ),
    "ps2000aGetStreamingLatestValues": (_STATUS, [_INT16, StreamingReady, _VOID]),
    "ps2000aSetSigGenBuiltIn": (
        _STATUS,
        [
            _INT16,
            _INT32,
            _UINT32,
            _INT16,
            *[_FLOAT] * 4,
            _INT32,
            _INT32,
            _UINT32,
            _UINT32,
            _INT32,
            _INT32,
            _INT16,
        ],
    ),
    "ps2000aStop": (_STATUS, [_INT16]),
}


def triggers_itself(
    condition: Condition, source: str | None, analog: list[str], digital: list[str]
) -> bool:
    """Whether the scope can wait for this itself, reading blocks, given the
    channels and logic inputs that are on.

    An edge either way, on a channel or a logic input; a window, a pulse's
    width or a runt, on a channel; or a pattern of the two together, at once.
    Not a timeout -- the driver has nothing that fires while a level lasts --
    and no holdoff, nor a pattern that has to be held: those are found in
    what is streamed. A pulse on a logic input wants the MSO's own structures,
    which nobody here has a scope to check against yet.
    """
    if condition.holdoff:
        return False
    if condition.kind == PATTERN:
        keys = [key for key, _level in condition.pattern]
        return bool(keys) and not condition.held and all(k in analog or k in digital for k in keys)
    if condition.kind == EDGE:
        return source in analog or source in digital
    if condition.kind in (WINDOW, PULSE, RUNT):
        return source in analog
    return False


def plain_edge(condition: Condition) -> bool:
    """A rising or a falling edge, which the simple trigger does."""
    return condition.kind == EDGE and condition.edge != EITHER and not condition.holdoff


def why(status: int) -> str:
    """A status of the driver's, in words where there are some."""
    return STATUS.get(status, f"driver status 0x{status:02X}")


def channels_of(model: str | None) -> int:
    """How many analog channels: four on a 24xx, as the second digit says."""
    return 4 if model and len(model) > 1 and model[1] == "4" else 2


def has_digital(model: str | None) -> bool:
    """Whether it has logic inputs: a mixed-signal scope says MSO after its number."""
    return bool(model) and "MSO" in model.upper()


def digital_key(port: int, bit: int) -> str:
    return f"D{port * PORT_BITS + bit}"


def port_key(port: int) -> str:
    """What a port's eight inputs, packed, arrive under in a block."""
    return f"port{port}"


def port_label(port: int) -> str:
    return f"D{port * PORT_BITS} to D{port * PORT_BITS + PORT_BITS - 1}"


#: The most offset asked for, either way, at the probe's tip: the scope keeps
#: it to what each range allows, which is far less.
MOST_OFFSET = 1000.0
OFFSET_TIP = (
    "Added to the signal before it is measured, in volts at the probe's tip:\n"
    "-3.5 V puts a signal at 3.5 V in the middle of the range, so a smaller\n"
    "scale can be used and it is read more finely. Each range takes only so\n"
    "much -- the scope says how much -- and the Event Log says when that is\n"
    "less than was asked for."
)


def offset_setting(key: str) -> Setting:
    return Setting(
        f"offset_{key.lower()}",
        "Offset",
        0.0,
        minimum=-MOST_OFFSET,
        maximum=MOST_OFFSET,
        decimals=3,
        unit="V",
        step=0.1,
        group=f"Channel {key}",
        live=True,
        tip=OFFSET_TIP,
    )


def make_settings(
    channels: int = 2, digital: bool = False, ranges: tuple[str, ...] = (), offset: bool = False
) -> tuple[Setting, ...]:
    """The settings to offer for a scope with this many channels, logic inputs or none,
    these ranges, and an offset or none."""
    scales = pico.scales_for(ranges or tuple(RANGES))
    choices = tuple((scale, pico.scale_label(scale)) for scale in scales)
    made = [
        Setting(
            "mode",
            "Reading",
            STREAM,
            choices=((STREAM, "Streaming, to 30 MS/s"), (BLOCKS, "Blocks, to the scope's fastest")),
            group="Sampling",
            tip=(
                "Streaming reads continuously, for as long as it runs, and pyscopegui\n"
                "finds the trigger. Blocks are stretches taken at up to the scope's\n"
                "full rate, each around the scope's own trigger: for what is too\n"
                "fast to stream."
            ),
        ),
        Setting(
            "rate",
            "Sample rate",
            500_000,
            choices=(
                (FASTEST_RATE, "31.25 MS/s"),
                (20_000_000, "20 MS/s"),
                (10_000_000, "10 MS/s"),
                (5_000_000, "5 MS/s"),
                (2_000_000, "2 MS/s"),
                (1_000_000, "1 MS/s"),
                (500_000, "500 kS/s"),
                (200_000, "200 kS/s"),
                (100_000, "100 kS/s"),
                (50_000, "50 kS/s"),
                (20_000, "20 kS/s"),
                (10_000, "10 kS/s"),
            ),
            group="Sampling",
            needs=("mode", STREAM),
            tip=(
                "When streaming: samples a second on each channel. Above 1 MS/s it is\n"
                "for the scope, USB and the computer to keep up, which is harder with\n"
                "more channels on: the Event Log says when they do not. What is kept\n"
                "to go back over is all in memory, and fills it that much faster."
            ),
        ),
        Setting(
            "block_ms",
            "Block length",
            1.0,
            minimum=0.001,
            maximum=1000.0,
            decimals=3,
            unit="ms",
            group="Sampling",
            needs=("mode", BLOCKS),
            tip=(
                "When reading blocks: how long a stretch each one is. The scope samples\n"
                "as fast as it can for that length, up to a million samples a block:\n"
                "a shorter block is sampled faster. The Event Log says what rate a\n"
                "length came to."
            ),
        ),
    ]
    for key in ANALOG[:channels]:
        # The first two are on to begin with, as on a two-channel scope.
        channel = pico.channel_settings(key, choices, enabled=key in "AB")
        if offset:
            # Beside the scale, which it is chosen with.
            channel.insert(2, offset_setting(key))
        made += channel
    if digital:
        for port in PORTS:
            label = port_label(port)
            made += [
                Setting(
                    f"digital_{port}",
                    label,
                    False,
                    group="Logic inputs",
                    tip=f"Whether the logic inputs {label} are read: all eight, or none.",
                ),
                Setting(
                    f"threshold_{port}",
                    f"Threshold, {label}",
                    DEFAULT_THRESHOLD,
                    minimum=-THRESHOLD_VOLTS,
                    maximum=THRESHOLD_VOLTS,
                    decimals=2,
                    step=0.1,
                    unit="V",
                    group="Logic inputs",
                    live=True,
                    tip=(
                        "The voltage above which these inputs read 1. 1.5 V suits 5 V and\n"
                        "3.3 V logic; half the supply suits anything else."
                    ),
                ),
            ]
    made += pico.generator_settings(GENERATOR_HZ)
    made += [
        Setting(
            "gen_start",
            "Start",
            NOW,
            choices=((NOW, "At once"), (ON_TRIGGER, "On the scope's trigger")),
            tip=(
                "At once: the wave runs all the time. On the scope's trigger: the\n"
                "generator waits, and puts out its cycles when the scope triggers --\n"
                "a stimulus at the moment of the capture. The scope triggers itself\n"
                "when reading blocks; streaming, the trigger is found by pyscopegui\n"
                "afterwards, and the generator is not told."
            ),
            group="Signal generator",
            live=True,
        ),
        Setting(
            "gen_cycles",
            "Cycles",
            1,
            minimum=0,
            maximum=MOST_SHOTS,
            decimals=0,
            tip="How many cycles it puts out at each trigger: 0 starts it and leaves it running.",
            group="Signal generator",
            live=True,
        ),
    ]
    return tuple(made)


#: What is offered before a scope is open and has said what it has: two
#: channels and a generator, which every one of them has.
SETTINGS = make_settings()


def find_library(platform: str | None = None, environ=None) -> Path | None:
    return pico.find_library(platform, environ, LIBRARY, LIBRARY_ENV)


def load_library():
    """Pico's ps2000a library, with each function's arguments declared."""
    return pico.load(find_library(), LIBRARY, LIBRARY_ENV, PROTOTYPES)


class Settings(pico.Settings):
    """How the scope is set up, from the ``instrument.picoscope2000a`` settings.

    Read for the most a scope on this driver can have -- four channels and
    both ports of logic inputs -- and then kept to what the one that is open
    has, once that is known.
    """

    def __init__(self, options: dict | None = None, channels: int = 4, digital: bool = True):
        options = options if isinstance(options, dict) else {}
        #: The analog channels the scope has, and whether it has logic inputs.
        self.analog = ANALOG[:channels]
        self.has_digital = digital
        rate = self._number(options.get("rate"), DEFAULT_RATE)
        self.interval_ns = max(1, round(1e9 / rate)) if rate > 0 else round(1e9 / DEFAULT_RATE)
        self.rate = 1e9 / self.interval_ns
        self.probe, self.ranges, self.dc, self.enabled = {}, {}, {}, {}
        #: Volts at the probe's tip added before it is measured, by channel.
        self.offset: dict[str, float] = {}
        for key in ANALOG:
            low = key.lower()
            self.probe[key] = self._probe(options, low)
            self.ranges[key] = self._range(options.get(f"scale_{low}"), self.probe[key].gain, None)
            self.dc[key] = options.get(f"coupling_{low}", "DC") != "AC"
            self.enabled[key] = bool(options.get(f"enabled_{low}", key in "AB"))
            self.offset[key] = min(
                max(self._number(options.get(f"offset_{low}"), 0.0), -MOST_OFFSET), MOST_OFFSET
            )
        #: Port -> whether its eight logic inputs are read, and the volts
        #: above which one of them is a 1.
        self.ports = {port: bool(options.get(f"digital_{port}", False)) for port in PORTS}
        self.threshold = {
            port: min(
                max(
                    self._number(options.get(f"threshold_{port}"), DEFAULT_THRESHOLD),
                    -THRESHOLD_VOLTS,
                ),
                THRESHOLD_VOLTS,
            )
            for port in PORTS
        }
        self.blocks = options.get("mode") == BLOCKS
        self.block_s = min(max(self._number(options.get("block_ms"), 1.0), 0.001), 1000.0) / 1000
        wave = options.get("gen_wave", "off")
        self.generator = (
            wave if wave in WAVES else "off",
            min(max(self._number(options.get("gen_frequency"), 1000.0), 1.0), GENERATOR_HZ),
            min(max(self._number(options.get("gen_amplitude"), 2.0), 0.0), 2 * GENERATOR_VOLTS),
            min(
                max(self._number(options.get("gen_offset"), 0.0), -GENERATOR_VOLTS),
                GENERATOR_VOLTS,
            ),
            ON_TRIGGER if options.get("gen_start") == ON_TRIGGER else NOW,
            int(min(max(self._number(options.get("gen_cycles"), 1.0), 0), MOST_SHOTS)),
        )

    def for_scope(self, channels: int, digital: bool) -> Settings:
        """These, kept to what a scope with this many channels, and logic inputs or none, has."""
        if (self.analog, self.has_digital) == (ANALOG[:channels], digital):
            return self
        kept = copy.copy(self)
        kept.analog, kept.has_digital = ANALOG[:channels], digital
        return kept

    def setup(self) -> tuple:
        return (self.ranges, self.dc, self.threshold, self.offset)

    def keys(self) -> list[str]:
        """The analog channels switched on, in order."""
        return [key for key in self.analog if self.enabled[key]]

    def ports_on(self) -> list[int]:
        """The ports of logic inputs switched on."""
        return [port for port in PORTS if self.has_digital and self.ports[port]]

    def digital_keys(self) -> list[str]:
        """The logic inputs that are read, in order."""
        return [digital_key(port, bit) for port in self.ports_on() for bit in range(PORT_BITS)]


class Stream(pico.Stream):
    """The scope, from opening it to closing it, with any number of runs between.

    The older driver's, with every call to the driver made this one's way.
    """

    def __init__(
        self,
        library,
        settings: Settings,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        super().__init__(library, settings, clock)
        #: What the scope turned out to have, once open.
        self.channels = 2
        self.digital = False
        self.ranges: tuple[str, ...] = tuple(RANGES)
        #: Whether the scope can add an offset at all: not every model can.
        self.has_offset = False
        #: (range code, DC) -> the least and most offset it allows, as the scope said.
        self._offset_limits: dict[tuple[int, bool], tuple[float, float]] = {}
        #: Channel -> the offset the scope was given, in volts at its input:
        #: what is taken off again, so what is read is the signal itself.
        self._applied: dict[str, float] = {}
        self._max = MAX_VALUE
        #: What the driver fills, by what it calls the channel or port. Kept
        #: for as long as it may: a buffer that has been collected is written
        #: to all the same.
        self._buffers: dict[int, ctypes.Array] = {}
        #: What the callback copied out during the poll in progress.
        self._arrived: dict[int, list[np.ndarray]] = {}
        self._callback = StreamingReady(self._on_values)
        #: The rate it is really streaming at, which the driver may round.
        self._rate = settings.rate
        #: Samples before the trigger in a block.
        self._before_trigger = 0
        #: Whether the trigger last set was on a logic input, to be cleared.
        self._digital_trigger = False
        #: Whether it was more than an edge, and timed pulses: to be cleared.
        self._advanced = False
        self._pulse_width = False

    # --- opening ---------------------------------------------------------------------------
    def open(self) -> None:
        """Open the scope, and ask it what it has. ScopeError if it will not."""
        handle = ctypes.c_int16(0)
        try:
            status = self._library.ps2000aOpenUnit(ctypes.byref(handle), None)
        except OSError as exc:
            raise ScopeError(
                "Pico's driver failed while opening the scope, which is what happens when "
                f"the scope drops off USB part way through ({exc}). Unplug it, plug it in "
                "again and press Open."
            ) from exc
        if status == NOT_FOUND or (status == OK and handle.value <= 0):
            raise ScopeError(
                "No PicoScope was found. Check that it is plugged in, and that PicoScope 7 "
                "is closed: only one program can have the scope open."
            )
        if status != OK:
            raise ScopeError(f"The PicoScope would not open: {why(status)}.")
        self._handle = handle.value
        self.heard_from()
        self.model = self._info(INFO_VARIANT)
        self.channels, self.digital = channels_of(self.model), has_digital(self.model)
        self.settings = self.settings.for_scope(self.channels, self.digital)
        most = ctypes.c_int16(0)
        if self._library.ps2000aMaximumValue(self._handle, ctypes.byref(most)) == OK:
            self._max = most.value or MAX_VALUE
        self.ranges = self._ranges()
        self.has_offset = self._limits(RANGES["5V"][0], True) != (0.0, 0.0)
        self.notes.append((f"PicoScope {self.model}, {self._info(INFO_SERIAL)}.", False))

    def _answers(self) -> bool:
        # Busy, say, is still there: only what says it has gone is gone.
        return self._library.ps2000aPingUnit(self._handle) not in GONE

    def _info(self, line: int) -> str:
        text, needed = ctypes.create_string_buffer(64), ctypes.c_int16(0)
        self._library.ps2000aGetUnitInfo(self._handle, text, len(text), ctypes.byref(needed), line)
        return text.value.decode("ascii", "replace") or "?"

    def _limits(self, code: int, dc: bool) -> tuple[float, float]:
        """The least and most offset this range allows, at the scope's input.
        Nought and nought for a scope without one, or one that will not say."""
        if (code, dc) not in self._offset_limits:
            most, least = ctypes.c_float(0), ctypes.c_float(0)
            status = self._library.ps2000aGetAnalogueOffset(
                self._handle,
                code,
                COUPLING_DC if dc else COUPLING_AC,
                ctypes.byref(most),
                ctypes.byref(least),
            )
            found = (least.value, most.value) if status == OK else (0.0, 0.0)
            self._offset_limits[(code, dc)] = found
        return self._offset_limits[(code, dc)]

    def _offset_for(self, key: str, code: int) -> float:
        """The offset to give the scope for this channel, at its input: what
        was asked for at the probe's tip, kept to what the range allows."""
        settings = self.settings
        probe = settings.probe[key]
        wanted = settings.offset[key] / probe.gain
        if not wanted or not settings.enabled[key]:
            return 0.0
        least, most = self._limits(code, settings.dc[key])
        given = min(max(wanted, least), most)
        if given != wanted:
            at_tip, unit = given * probe.gain, probe.unit
            if not self.has_offset:
                said = f"This scope has no offset, so channel {key} is read with none."
            else:
                said = (
                    f"Channel {key}'s range of ±{settings.ranges[key]} takes an offset of "
                    f"{least * probe.gain:g} {unit} to {most * probe.gain:g} {unit}, so it is "
                    f"{at_tip:g} {unit} where {settings.offset[key]:g} {unit} was asked for. "
                    "A larger scale allows more."
                )
            self.notes.append((said, True))
        return given

    def offset_at_tip(self, key: str) -> float:
        """The offset a channel is read with, at the probe's tip: in volts, or
        amps through a current probe."""
        return self._applied.get(key, 0.0) * self.settings.probe[key].gain

    def _ranges(self) -> tuple[str, ...]:
        """The ranges the scope says it has; every one, if it will not say."""
        codes, length = (ctypes.c_int32 * 32)(), ctypes.c_int32(32)
        status = self._library.ps2000aGetChannelInformation(
            self._handle, INFO_RANGES, 0, codes, ctypes.byref(length), 0
        )
        has = set(codes[: max(0, min(length.value, 32))]) if status == OK else set()
        return tuple(name for name, (code, _v) in RANGES.items() if code in has) or tuple(RANGES)

    # --- running ---------------------------------------------------------------------------
    def start(self, settings: Settings | None = None, trigger: Trigger | None = None) -> None:
        """Set the scope up and start it reading, counting samples from zero."""
        self.stop()
        if settings is not None:
            self.settings = settings.for_scope(self.channels, self.digital)
        if trigger is not None:
            self.trigger = trigger
        if not self._sources():
            raise ScopeError("Every channel is switched off, so there is nothing to read.")
        self._set_channels()
        self.set_generator(self.settings.generator)
        if self.settings.blocks:
            self._choose_timebase()
            self._block_pending = False
            self.streaming = True
            return
        # No trigger: streaming is everything, from the moment it starts.
        self._no_trigger()
        self._start_streaming()
        self._sent = 0
        self._started = self._clock()
        self._rate_checked = False
        self._paused = False

    def _sources(self) -> list[tuple[int, object]]:
        """What is read, as (what the driver calls it, the channel's key or the port)."""
        settings = self.settings
        return [(ANALOG.index(key), key) for key in settings.keys()] + [
            (DIGITAL_PORT0 + port, port) for port in settings.ports_on()
        ]

    def _set_channels(self) -> None:
        settings = self.settings
        for index, key in enumerate(ANALOG[: self.channels]):
            code, _volts = RANGES[settings.ranges[key]]
            offset = self._offset_for(key, code)
            status = self._library.ps2000aSetChannel(
                self._handle,
                index,
                int(settings.enabled[key]),
                COUPLING_DC if settings.dc[key] else COUPLING_AC,
                code,
                offset,
            )
            if status != OK:
                raise ScopeError(
                    f"The scope would not set channel {key} to ±{settings.ranges[key]}: "
                    f"{why(status)}."
                )
            self._applied[key] = offset
        if not self.digital:
            return
        for port in PORTS:
            counts = round(settings.threshold[port] / THRESHOLD_VOLTS * THRESHOLD_COUNTS)
            status = self._library.ps2000aSetDigitalPort(
                self._handle, DIGITAL_PORT0 + port, int(settings.ports[port]), counts
            )
            if status != OK:
                raise ScopeError(
                    f"The scope would not set its logic inputs {port_label(port)}: {why(status)}."
                )

    def _hand_buffers(self, samples: int) -> None:
        """Give the driver somewhere to put this many samples of everything read."""
        self._buffers = {}
        for code, _what in self._sources():
            buffer = (ctypes.c_int16 * samples)()
            status = self._library.ps2000aSetDataBuffer(
                self._handle, code, buffer, samples, 0, RATIO_NONE
            )
            if status != OK:
                raise ScopeError(f"The driver would not take a buffer to read into: {why(status)}.")
            self._buffers[code] = buffer

    def _start_streaming(self) -> None:
        settings = self.settings
        room = max(STREAM_SAMPLES, round(settings.rate * STREAM_S))
        self._hand_buffers(room)
        interval = ctypes.c_uint32(settings.interval_ns)
        status = self._library.ps2000aRunStreaming(
            self._handle,
            ctypes.byref(interval),
            TIME_UNITS_NS,
            0,
            room,
            0,
            1,
            RATIO_NONE,
            room,
        )
        if status != OK:
            raise ScopeError(
                f"The scope would not stream at one sample every {settings.interval_ns} ns: "
                f"{why(status)}. Try a lower rate."
            )
        # The driver says what the interval came to, which is what time is counted in.
        self._rate = 1e9 / interval.value if interval.value else settings.rate
        if interval.value and interval.value != settings.interval_ns:
            self.notes.append(
                (
                    f"The scope is streaming at {self._rate:,.0f} samples a second, the "
                    f"nearest it has to the {settings.rate:,.0f} asked for.",
                    False,
                )
            )
        self.streaming = True

    def _streaming_rate(self) -> float:
        # What the driver said it came to, which may not be what was asked for.
        return self._rate

    def stop(self) -> None:
        """Stop reading and leave the scope open. Safe when it is not reading."""
        if self.streaming:
            self._library.ps2000aStop(self._handle)
        self.streaming = False
        self._block_pending = False

    # --- triggers --------------------------------------------------------------------------
    def _no_digital_trigger(self) -> None:
        if self._digital_trigger:
            self._library.ps2000aSetTriggerDigitalPortProperties(self._handle, None, 0)
            self._digital_trigger = False

    def _no_pulse_width(self) -> None:
        if self._pulse_width:
            self._library.ps2000aSetPulseWidthQualifier(
                self._handle, None, 0, NO_DIRECTION, 0, 0, PW_NONE
            )
            self._pulse_width = False

    def _no_trigger(self) -> None:
        self._no_digital_trigger()
        self._no_pulse_width()
        self._advanced = False
        self._library.ps2000aSetSimpleTrigger(self._handle, 0, 0, 0, RISING, 0, 0)

    def _counts(self, key: str, value: float) -> int:
        """A level on a channel, in the counts it is read in: as the scope
        measures it, which is with the offset in it."""
        volts = self.settings.volts(key)
        level = value + self.offset_at_tip(key)
        return round(min(max(level / volts, -1.0), 1.0) * self._max)

    def _set_trigger(self) -> None:
        """Tell the scope what a block is to be taken around."""
        trigger, settings = self.trigger, self.settings
        # How long to wait for a trigger before taking the block anyway:
        # nought is for ever, which is what Normal and Single mean.
        wait_ms = max(AUTO_TRIGGER_MS, round(2e3 * settings.block_s)) if trigger.auto else 0
        wait_ms = min(wait_ms, 32767)
        condition = trigger.condition
        if not plain_edge(condition) and triggers_itself(
            condition, trigger.source, settings.keys(), settings.digital_keys()
        ):
            status = self._set_advanced(wait_ms)
            if status != OK:
                raise ScopeError(
                    f"The scope would not trigger on {condition.summary() or 'that'}: "
                    f"{why(status)}."
                )
            return
        self._no_pulse_width()
        self._advanced = False
        if trigger.source in settings.keys():
            self._no_digital_trigger()
            status = self._library.ps2000aSetSimpleTrigger(
                self._handle,
                1,
                ANALOG.index(trigger.source),
                self._counts(trigger.source, trigger.level),
                RISING if trigger.rising else FALLING,
                0,
                wait_ms,
            )
        elif trigger.source in settings.digital_keys():
            status = self._set_digital_trigger(int(trigger.source[1:]), trigger.rising, wait_ms)
        else:
            self._no_trigger()
            return
        if status != OK:
            raise ScopeError(f"The scope would not trigger on {trigger.source}: {why(status)}.")

    def _set_digital_trigger(self, bit: int, rising: bool, wait_ms: int) -> int:
        """Trigger on an edge of one logic input, which takes three calls where an
        analog channel takes one."""
        library = self._library
        wanted = Conditions(digital=CONDITION_TRUE)
        edge = DigitalDirection(bit, DIGITAL_RISING if rising else DIGITAL_FALLING)
        self._digital_trigger = True
        return (
            library.ps2000aSetTriggerChannelConditions(self._handle, ctypes.byref(wanted), 1)
            or library.ps2000aSetTriggerDigitalPortProperties(self._handle, ctypes.byref(edge), 1)
            or library.ps2000aSetTriggerChannelProperties(self._handle, None, 0, 0, wait_ms)
        )

    def _set_advanced(self, wait_ms: int) -> int:
        """Trigger on more than an edge: each source's thresholds, which have
        to be so together, the way through each, the pulse-width qualifier,
        and the logic inputs -- in the order Pico's own examples set them."""
        trigger = self.trigger
        condition, source = trigger.condition, trigger.source
        hysteresis = round(HYSTERESIS * self._max)
        properties: list[Properties] = []
        wanted = Conditions()
        directions = [NO_DIRECTION] * 6
        digital: list[DigitalDirection] = []
        pulse = None

        def threshold(key: str, upper: float, lower: float, mode: int) -> int:
            index = ANALOG.index(key)
            properties.append(
                Properties(
                    self._counts(key, upper),
                    hysteresis,
                    self._counts(key, lower),
                    hysteresis,
                    index,
                    mode,
                )
            )
            setattr(wanted, "abcd"[index], CONDITION_TRUE)
            return index

        if condition.kind == PATTERN:
            for key, level in condition.pattern:
                if key in ANALOG:
                    index = threshold(key, trigger.level, trigger.level, LEVEL_MODE)
                    directions[index] = ABOVE if level else BELOW
                else:
                    digital.append(
                        DigitalDirection(int(key[1:]), DIGITAL_HIGH if level else DIGITAL_LOW)
                    )
        elif source not in ANALOG:
            # A logic input: an edge, either way being all there is beyond the simple trigger.
            digital.append(DigitalDirection(int(source[1:]), DIGITAL_EITHER))
        elif condition.kind == EDGE:
            index = threshold(source, trigger.level, trigger.level, LEVEL_MODE)
            directions[index] = RISING_OR_FALLING
        elif condition.kind in (WINDOW, RUNT):
            low, high = sorted((trigger.level, condition.upper))
            index = threshold(source, high, low, WINDOW_MODE)
            if condition.kind == WINDOW:
                directions[index] = ENTER_WINDOW if condition.direction == ENTER else EXIT_WINDOW
            else:
                directions[index] = NEGATIVE_RUNT if condition.polarity == LOW else POSITIVE_RUNT
        else:
            # A pulse's width is timed from its start, through the lower
            # threshold, and the trigger is at its end, through the upper:
            # both at the level.
            index = threshold(source, trigger.level, trigger.level, LEVEL_MODE)
            high = condition.polarity != LOW
            directions[index] = FALLING if high else RISING
            wanted.pulse_width = CONDITION_TRUE
            timed = PwqConditions(**{"abcd"[index]: CONDITION_TRUE})
            shortest = max(1, round(condition.shortest * self._block_rate))
            longest = max(shortest + 1, round(condition.longest * self._block_rate))
            kind = {SHORTER: PW_LESS_THAN, BETWEEN: PW_IN_RANGE}.get(
                condition.compare, PW_GREATER_THAN
            )
            pulse = (timed, RISING_LOWER if high else FALLING_LOWER, shortest, longest, kind)
        if digital:
            wanted.digital = CONDITION_TRUE
        library, handle = self._library, self._handle
        listed = (Properties * len(properties))(*properties) if properties else None
        status = (
            library.ps2000aSetTriggerChannelProperties(handle, listed, len(properties), 0, wait_ms)
            or library.ps2000aSetTriggerChannelConditions(handle, ctypes.byref(wanted), 1)
            or library.ps2000aSetTriggerChannelDirections(handle, *directions)
        )
        if status == OK and pulse is not None:
            timed, way, shortest, longest, kind = pulse
            status = library.ps2000aSetPulseWidthQualifier(
                handle, ctypes.byref(timed), 1, way, shortest, longest, kind
            )
            self._pulse_width = True
        elif status == OK:
            self._no_pulse_width()
        if status == OK and (digital or self._digital_trigger):
            edges = (DigitalDirection * len(digital))(*digital) if digital else None
            status = library.ps2000aSetTriggerDigitalPortProperties(handle, edges, len(digital))
            self._digital_trigger = bool(digital)
        self._advanced = True
        return status

    # --- blocks ----------------------------------------------------------------------------
    def _ask_timebase(self, timebase: int) -> tuple[float, int] | None:
        """The interval in nanoseconds and the most samples at this timebase, if it has it."""
        interval, most = ctypes.c_float(0), ctypes.c_int32(0)
        status = self._library.ps2000aGetTimebase2(
            self._handle, timebase, 1, ctypes.byref(interval), 1, ctypes.byref(most), 0
        )
        if status != OK or interval.value <= 0 or most.value <= 0:
            return None
        return interval.value, min(most.value, MOST_SAMPLES)

    def _choose_timebase(self) -> None:
        """The fastest timebase at which a block this long is no more samples than
        are read.

        There are four thousand million timebases, each a little slower than
        the one before, so the scope is asked about a few and the one wanted
        is closed in on: doubling until one is slow enough, or slower than the
        scope goes, then halving the gap. Which the scope has depends on the
        model and on what is on.
        """
        wanted_ns = self.settings.block_s * 1e9
        answers: dict[int, tuple[float, int] | None] = {}

        def far_enough(timebase: int) -> bool:
            """Slow enough for the block -- or slower than the scope goes."""
            answers[timebase] = answer = self._ask_timebase(timebase)
            if answer is None:
                # Among the first few, one refused is too fast for what is on.
                return timebase > FIRST_STEADY_TIMEBASE
            return answer[0] * answer[1] >= wanted_ns

        slow, fast, timebase = None, -1, 0
        while slow is None and timebase <= MAX_TIMEBASE:
            if far_enough(timebase):
                slow = timebase
            else:
                fast, timebase = timebase, max(1, timebase * 2)
        while slow is not None and slow - fast > 1:
            middle = (slow + fast) // 2
            if far_enough(middle):
                slow = middle
            else:
                fast = middle
        if slow is not None and answers[slow] is None:
            slow = None  # past its slowest: the one before is its longest block
        had = [timebase for timebase, answer in answers.items() if answer is not None]
        if not had:
            raise ScopeError("The scope offered no timebase to read a block at.")
        # The one found, or the slowest it has: its longest block.
        self._timebase = slow if slow is not None else max(had)
        interval_ns, most_samples = answers[self._timebase]
        samples = max(FEWEST_SAMPLES, math.ceil(wanted_ns / interval_ns))
        self._block_samples = min(samples, most_samples)
        self._block_rate = 1e9 / interval_ns
        length = self._block_samples * interval_ns / 1e9
        self.notes.append(
            (
                f"Blocks of {self._block_samples} samples at {self._block_rate:,.0f} a second: "
                f"{length * 1e3:g} ms each.",
                False,
            )
        )
        if samples > most_samples:
            self.notes.append(
                (
                    f"That is the longest block the scope can take: {length * 1e3:g} ms of "
                    f"the {wanted_ns / 1e6:g} ms asked for. Streaming reads for longer.",
                    True,
                )
            )

    def _arm(self) -> None:
        """Tell the scope what to trigger on, and start it filling a block."""
        self._set_trigger()
        samples = self._block_samples
        self._before_trigger = min(round(self.trigger.position * samples), samples)
        busy = ctypes.c_int32(0)
        status = self._library.ps2000aRunBlock(
            self._handle,
            self._before_trigger,
            samples - self._before_trigger,
            self._timebase,
            1,
            ctypes.byref(busy),
            0,
            None,
            None,
        )
        if status != OK:
            raise ScopeError(
                f"The scope would not take a block of {samples} samples: {why(status)}. "
                "Try a different block length."
            )
        self._block_pending = True

    def _poll_block(self) -> Block | None:
        """The block that was asked for, if it is in; and ask for the next."""
        wanted, self.wanted = self.wanted, None
        trigger, self.wanted_trigger = self.wanted_trigger, None
        if wanted is not None or trigger is not None:
            # A block being waited for was asked for with the old settings,
            # and in Normal may be waited for for ever: give it up.
            if self._block_pending:
                self._library.ps2000aStop(self._handle)
                self._block_pending = False
            if trigger is not None:
                self.trigger = trigger
            if wanted is not None:
                self._take_up_between_blocks(wanted)
        if not self._block_pending:
            self._arm()
            return None
        ready = ctypes.c_int16(0)
        if self._library.ps2000aIsReady(self._handle, ctypes.byref(ready)) != OK:
            raise ScopeError("The scope stopped answering: it may have been unplugged.")
        if not ready.value:
            return None
        self._block_pending = False
        return self._read_block()

    def _take_up_between_blocks(self, wanted: Settings) -> None:
        super()._take_up_between_blocks(wanted.for_scope(self.channels, self.digital))

    def _take_up(self, wanted: Settings) -> None:
        super()._take_up(wanted.for_scope(self.channels, self.digital))

    def _read_block(self) -> Block | None:
        samples = self._block_samples
        self._hand_buffers(samples)
        count, overflow = ctypes.c_uint32(samples), ctypes.c_int16(0)
        status = self._library.ps2000aGetValues(
            self._handle, 0, ctypes.byref(count), 1, RATIO_NONE, 0, ctypes.byref(overflow)
        )
        buffers, self._buffers = self._buffers, {}
        if status != OK or count.value == 0:
            return None
        data, scales, bits = self._as_sent(
            {code: np.ctypeslib.as_array(buffer)[: count.value] for code, buffer in buffers.items()}
        )
        block = Block(0, self._block_rate, data, sweep=True, scales=scales, bits=bits)
        trigger = self.trigger
        pattern = self._advanced and trigger.condition.kind == PATTERN
        keys = [key for key, _level in trigger.condition.pattern] if pattern else [trigger.source]
        if any(key not in data and key not in bits for key in keys):
            return block
        at = min(self._before_trigger, count.value - 1)
        # Looked at in volts, which only the channels triggered on are worked out in.
        looked_at = {key: block.values(key) for key in keys}
        if self._advanced:
            # Waited for in Normal; in Auto, there if it is found where it should be.
            triggered = not trigger.auto or self._met_near(keys, looked_at, at)
        else:
            # A logic input is 0 or 1, and an edge goes through the half between.
            level = trigger.level if trigger.source in self.settings.keys() else 0.5
            triggered = crossed(looked_at[trigger.source], at, level, trigger.rising)
        return replace(block, trigger=at, triggered=triggered)

    def _met_near(self, keys: list[str], data: dict[str, np.ndarray], at: int) -> bool:
        """Whether what was waited for is in the block where the trigger is:
        the driver does not say whether it triggered or gave up waiting."""
        trigger = self.trigger
        first = keys[0]
        margin = HYSTERESIS * self.settings.volts(first) if first in ANALOG else 0.0
        level = trigger.level if first in ANALOG or trigger.condition.kind == PATTERN else 0.5
        return pico.met_near(trigger.condition, data, keys, at, level, margin, self._block_rate)

    def _as_sent(
        self, raw: dict[int, np.ndarray]
    ) -> tuple[dict[str, np.ndarray], dict[str, Scale], dict[str, tuple[str, int]]]:
        """What the driver filled, as it is sent on: a channel as its counts,
        with how they become volts, and a port as its eight logic inputs
        packed in a byte, with which bit each input is."""
        data, scales, bits = {}, {}, {}
        for code, what in self._sources():
            if code not in raw:
                continue
            counts = raw[code]
            if isinstance(what, str):
                data[what] = counts
                # The offset was added before it was measured: taken off again.
                volts = self.settings.volts(what)
                scales[what] = Scale(volts / self._max, self.offset_at_tip(what))
                continue
            # As the driver gave it: the inputs are its low byte, which is what
            # is held of it, the driver leaving the high one empty.
            data[port_key(what)] = counts
            for bit in range(PORT_BITS):
                bits[digital_key(what, bit)] = (port_key(what), bit)
        return data, scales, bits

    def set_generator(self, generator: tuple) -> None:
        """Set the signal generator output: a fixed frequency, no sweep, and at
        once or a number of cycles each time the scope triggers."""
        wave, frequency, amplitude, offset, start, cycles = generator
        off = wave == "off"
        triggered = start == ON_TRIGGER and not off
        shots = (cycles or SIGGEN_CONTINUOUS_RUN) if triggered else 0
        status = self._library.ps2000aSetSigGenBuiltIn(
            self._handle,
            0 if off else round(offset * 1e6),
            0 if off else round(amplitude * 1e6),
            WAVES[wave],
            frequency,
            frequency,
            0.0,
            0.0,
            0,
            0,
            shots,
            0,
            SIGGEN_RISING,
            SIGGEN_SCOPE_TRIG if triggered else SIGGEN_NONE,
            0,
        )
        if status != OK and not off:
            self.notes.append(
                (
                    f"The scope would not set its signal generator to that output: {why(status)}.",
                    True,
                )
            )
        elif not off:
            when = ""
            if triggered:
                when = (
                    f", {cycles} cycle{'s' if cycles != 1 else ''} at each trigger"
                    if cycles
                    else ", from the scope's trigger on"
                )
            self.notes.append(
                (
                    f"Signal generator: {wave}, {frequency:g} Hz, {amplitude:g} V peak to peak, "
                    f"{offset:g} V offset{when}.",
                    False,
                )
            )
            if triggered and not self.settings.blocks:
                self.notes.append(
                    (
                        "The signal generator waits for the scope's own trigger, which it "
                        "has only when reading blocks: streaming, it waits for ever.",
                        True,
                    )
                )
        elif self._generating:
            self.notes.append(("Signal generator: off.", False))
        self._generating = status == OK and not off

    # --- reading ---------------------------------------------------------------------------
    def _on_values(
        self, _handle, count, start, _overflow, _triggered_at, _triggered, _auto_stop, _parameter
    ) -> None:
        """Called by the driver from inside ``poll``. Copies, and nothing else:
        the buffers are filled again as soon as this returns."""
        if count <= 0:
            return
        for code, buffer in self._buffers.items():
            values = np.ctypeslib.as_array(buffer)[start : start + count].copy()
            self._arrived.setdefault(code, []).append(values)

    def poll(self) -> Block | None:
        """Whatever has arrived since the last poll, or None if nothing has."""
        if self.settings.blocks:
            return self._poll_block()
        # Taken and cleared in one step: it is set from the GUI thread.
        wanted, self.wanted = self.wanted, None
        if wanted is not None:
            self._take_up(wanted)
        self._arrived = {}
        status = self._library.ps2000aGetStreamingLatestValues(self._handle, self._callback, None)
        if status in GONE:
            raise ScopeError("The scope stopped answering: it may have been unplugged.")
        if status == BUFFER_STALL:
            raise ScopeError(
                "The driver's buffer filled before it was read, and it has stopped: the "
                "computer did not keep up. Try a lower rate."
            )
        if not self._arrived:
            return None
        # Mostly one batch a poll, which is taken as it is.
        raw = {
            code: parts[0] if len(parts) == 1 else np.concatenate(parts)
            for code, parts in self._arrived.items()
        }
        count = min(len(values) for values in raw.values())
        data, scales, bits = self._as_sent({code: values[:count] for code, values in raw.items()})
        block = Block(
            self._sent, self._rate, data, after_pause=self._paused, scales=scales, bits=bits
        )
        self._paused = False
        self._sent += count
        # Marked as lost by the driver in an analog channel: a logic port has
        # no such mark, and a gap in one is as wide as in the channels.
        lost = max(
            (
                int(np.count_nonzero(values[:count] == LOST_DATA))
                for code, values in raw.items()
                if code < DIGITAL_PORT0
            ),
            default=0,
        )
        self._check_lost(lost)
        self._check_rate()
        return block

    def close(self) -> None:
        """Stop and let go of the scope. Safe when it never opened."""
        if self._handle > 0:
            self._library.ps2000aStop(self._handle)
            self._library.ps2000aCloseUnit(self._handle)
        self.streaming = False
        self._handle = 0
        self._buffers = {}


class PicoScope2000A(pico.PicoScope2000):
    SETTINGS = SETTINGS
    #: The ranges the scope said it has, once it has been opened.
    _ranges: tuple[str, ...] = ()
    #: Whether the scope said it can add an offset, once it has been opened.
    _has_offset = False

    def _load_library(self):
        return load_library()

    def _has(self) -> tuple[int, bool]:
        """Channels, and whether there are logic inputs. Before a scope is
        open, the most there can be: so that whatever was switched on the
        last time is listed, whichever scope it was."""
        if self._model is None:
            return 4, True
        return channels_of(self._model), has_digital(self._model)

    def _make_settings(self, options):
        return Settings(options, *self._has())

    def _make_stream(self):
        return Stream(self._library, self.settings)

    def triggers_itself(self, condition: Condition, source: str | None) -> bool:
        settings = self.settings
        if condition.kind == PATTERN and not condition.pattern:
            # Its channels are still to be chosen, and it can do some.
            return not condition.held and not condition.holdoff
        return triggers_itself(condition, source, settings.keys(), settings.digital_keys())

    def settings_offered(self) -> tuple[Setting, ...]:
        if self._model is None:
            return SETTINGS
        return make_settings(*self._has(), self._ranges, self._has_offset)

    def _on_opened(self, model: str) -> None:
        self._model = model or None
        if self._stream is not None:
            self._ranges = self._stream.ranges
            self._has_offset = self._stream.has_offset
        # Read again, now that what the scope has is known.
        self.settings = self._make_settings(self._options)
        super()._on_opened(model)

    def channels(self) -> list[Channel]:
        settings = self.settings
        analog = [
            # Said with the rest of how it is set, where it is not nought.
            replace(
                channel,
                detail=f"{channel.detail}, offset {settings.offset[channel.key]:g} {channel.unit}",
                # What is read is the signal with the offset taken off again,
                # over a range that the offset has moved.
                middle=-settings.offset[channel.key],
            )
            if settings.offset[channel.key] and self._has_offset
            else channel
            for channel in super().channels()
        ]
        return analog + [
            Channel(
                digital_key(port, bit),
                digital_key(port, bit),
                DIGITAL,
                "",
                detail=f"above {settings.threshold[port]:g} V",
                port=port_key(port),
                bit=bit,
            )
            for port in settings.ports_on()
            for bit in range(PORT_BITS)
        ]
