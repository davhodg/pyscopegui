# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""PicoScope 2000 series scopes on Pico's own ``ps2000`` library: the 2204A and its relatives.

The older two-channel 2000 Series scopes -- 2202, 2203, 2204, 2204A, 2205 and
2205A -- use the ``ps2000`` driver, not ``ps2000a``. The library comes with
Pico's software and is not bundled: this looks for it where Pico installs it.

Read in one of two ways. In what Pico calls fast streaming the scope samples
continuously and the driver hands over whatever has arrived each time it is
asked: up to a million samples a second, for as long as it is left running,
with the trigger found by pyscopegui in the samples. In block mode the scope
triggers itself and fills its own memory at up to a hundred million samples a
second, which is a few thousand samples and so a short stretch of time: the
mode for what is too fast to stream.

Everything that talks to the scope runs on a thread of its own, because
opening it takes seconds -- the driver loads the scope's firmware every time
-- and a window that stops answering for that long looks broken. The scope
is opened once and kept open: starting, stopping and changing a setting are
then quick, since none of them loads the firmware again.
"""

from __future__ import annotations

import copy
import ctypes
import ctypes.util
import math
import os
import queue
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from pyscopegui.backends.base import Block, Channel, Instrument, Setting

#: Set to the library's full path to use that one and look nowhere else.
LIBRARY_ENV = "PYSCOPEGUI_PS2000"

# --- what the driver calls things: Pico's "PicoScope 2000 Series Programmer's Guide" ----
CHANNEL_A, CHANNEL_B, NO_TRIGGER = 0, 1, 5
TIME_UNITS_NS = 2
#: Full scale, whichever range is set: the driver scales every reading to 16 bits.
MAX_VALUE = 32767
#: Written in place of a sample the driver lost to a full buffer.
LOST_DATA = -32768
INFO_VARIANT, INFO_SERIAL, INFO_ERROR = 3, 4, 6
#: Range name -> the driver's code and full scale in volts. A scope supports
#: only some of them, and refuses the rest when it is set up.
RANGES: dict[str, tuple[int, float]] = {
    "20mV": (1, 0.02),
    "50mV": (2, 0.05),
    "100mV": (3, 0.1),
    "200mV": (4, 0.2),
    "500mV": (5, 0.5),
    "1V": (6, 1.0),
    "2V": (7, 2.0),
    "5V": (8, 5.0),
    "10V": (9, 10.0),
    "20V": (10, 20.0),
}
#: Range name -> volts a division, of eight up a screen, with a 1x probe. The
#: scope has ranges and no divisions; a range is set by its scale, as on a
#: bench scope, so that every instrument is set the same way. Each range is
#: at least the eight divisions its scale would fill.
SCALES: dict[str, float] = {
    "20mV": 0.005,
    "50mV": 0.01,
    "100mV": 0.02,
    "200mV": 0.05,
    "500mV": 0.1,
    "1V": 0.2,
    "2V": 0.5,
    "5V": 1.0,
    "10V": 2.0,
    "20V": 5.0,
}
PROBES = (1, 10, 100)
ERRORS = {
    1: "too many scopes are open",
    2: "the computer is out of memory",
    3: "no scope was found",
    4: "the scope's firmware could not be loaded",
    5: "the scope is not responding",
    6: "the scope's configuration is corrupt or missing",
    7: "this operating system is not supported by the driver",
}

#: Waveform name -> the driver's code. Off is a steady zero volts, which is
#: the nearest thing the driver has to switching the output off.
WAVES = {"off": 5, "sine": 0, "square": 1, "triangle": 2}
#: What the generator is allowed here: within two volts of zero.
GENERATOR_VOLTS = 2.0
GENERATOR_HZ = 100_000.0

#: Trigger directions, as the driver numbers them.
RISING, FALLING = 0, 1
#: The slowest timebase any of these scopes has. Each is twice the interval
#: of the one before, from the scope's fastest at nought.
MAX_TIMEBASE = 23
#: How long the scope waits for a trigger in Auto before taking the block
#: anyway, in milliseconds, at the least.
AUTO_TRIGGER_MS = 100
#: The fewest samples a block is asked to hold, however short it is.
FEWEST_SAMPLES = 16
#: Either side of where the trigger should be, how many samples are looked
#: at to see whether the signal really crossed the level there.
NEAR_TRIGGER = 3
STREAM, BLOCKS = "stream", "block"

# --- how it is read ----------------------------------------------------------------------
#: Samples a second on each channel, unless the settings say otherwise. Half
#: the 1 MS/s the 2204A can stream, since whether that is shared between two
#: channels is not something Pico's guide says.
DEFAULT_RATE = 500_000.0
DEFAULT_RANGE = "5V"
#: The driver's own store, per channel, which it wraps round in.
DRIVER_SAMPLES = 1_000_000
#: The driver's holding buffer between two polls: the most it allows.
OVERVIEW_SAMPLES = 1_000_000
#: How long the thread sleeps between polls. A hundred a second, at most.
POLL_S = 0.01
#: And how often it looks to see whether it has been asked for anything
#: while the scope is open and not streaming.
IDLE_S = 0.1
#: How long before the rate that is arriving is compared with the one asked for.
CHECK_AFTER_S = 5.0
#: How far out it may be before it is said.
RATE_TOLERANCE = 0.05

#: The callback fast streaming hands its buffers to: four of them -- A's
#: highest and lowest, then B's -- and how many values each holds.
_CALLBACK_FACTORY = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
OverviewCallback = _CALLBACK_FACTORY(
    None,
    ctypes.POINTER(ctypes.POINTER(ctypes.c_int16)),
    ctypes.c_int16,
    ctypes.c_uint32,
    ctypes.c_int16,
    ctypes.c_int16,
    ctypes.c_uint32,
)

_INT16, _INT32, _UINT32 = ctypes.c_int16, ctypes.c_int32, ctypes.c_uint32
#: Name -> (return type, argument types), for the functions used here.
PROTOTYPES = {
    "ps2000_open_unit": (_INT16, []),
    "ps2000_close_unit": (_INT16, [_INT16]),
    "ps2000_get_unit_info": (_INT16, [_INT16, ctypes.c_char_p, _INT16, _INT16]),
    "ps2000_set_channel": (_INT16, [_INT16] * 5),
    "ps2000_set_trigger": (_INT16, [_INT16] * 6),
    "ps2000_run_streaming_ns": (
        _INT16,
        [_INT16, _UINT32, _INT32, _UINT32, _INT16, _UINT32, _UINT32],
    ),
    "ps2000_get_streaming_last_values": (_INT16, [_INT16, OverviewCallback]),
    "ps2000_overview_buffer_status": (_INT16, [_INT16, ctypes.POINTER(_INT16)]),
    "ps2000_stop": (_INT16, [_INT16]),
    "ps2000_get_timebase": (
        _INT16,
        [
            _INT16,
            _INT16,
            _INT32,
            ctypes.POINTER(_INT32),
            ctypes.POINTER(_INT16),
            _INT16,
            ctypes.POINTER(_INT32),
        ],
    ),
    "ps2000_run_block": (_INT16, [_INT16, _INT32, _INT16, _INT16, ctypes.POINTER(_INT32)]),
    "ps2000_ready": (_INT16, [_INT16]),
    "ps2000_get_values": (
        _INT32,
        [_INT16, *[ctypes.POINTER(_INT16)] * 4, ctypes.POINTER(_INT16), _INT32],
    ),
    "ps2000_set_sig_gen_built_in": (
        _INT16,
        [_INT16, _INT32, _UINT32, _INT32, *[ctypes.c_float] * 4, _INT32, _UINT32],
    ),
}

_COUPLING = (("DC", "DC"), ("AC", "AC"))
_GENERATOR = {"group": "Signal generator", "live": True}


@dataclass(frozen=True)
class Model:
    """What one model of scope has, where that is known."""

    #: The ranges it has. Empty where there is no list of them: every range
    #: is then offered, and the scope refuses the ones it lacks.
    ranges: tuple[str, ...] = ()
    generator: bool = True


#: From 50 mV up, which is what the 2204A and 2205A have.
_FROM_50MV = tuple(name for name in RANGES if name != "20mV")
#: By the name the scope gives itself. The ranges of the 2204A and 2205A are
#: from Pico's specifications; that the 2202 has no signal generator is from
#: Pico's programmer's guide. A scope not here is offered everything.
MODELS: dict[str, Model] = {
    "2204A": Model(_FROM_50MV),
    "2205A": Model(_FROM_50MV),
    "2202": Model(generator=False),
}


def _range_label(name: str) -> str:
    return f"±{name[:-2]} mV" if name.endswith("mV") else f"±{name[:-1]} V"


def scale_label(volts: float) -> str:
    """0.05 -> "50 mV/div"."""
    return f"{volts * 1000:g} mV/div" if volts < 1 else f"{volts:g} V/div"


def scales_for(ranges: tuple[str, ...]) -> tuple[float, ...]:
    """Every scale these ranges give with one probe or another, smallest first."""
    return tuple(sorted({round(SCALES[name] * probe, 6) for name in ranges for probe in PROBES}))


def range_for(scale: float, probe: int) -> str:
    """The range that this scale is, through this probe: the nearest there is."""
    return min(SCALES, key=lambda name: abs(math.log(SCALES[name] * probe / scale)))


_SCALE_TIP = (
    "Volts a division, of eight up a scope's screen, with the probe counted.\n"
    "The scope is set to the range that holds that: 1 V/div is its ±5 V range.\n"
    "A scale the scope cannot reach through this probe is the nearest it can."
)
_PROBE_TIP = (
    "What the probe divides by, as its switch says. The scope cannot tell:\n"
    "voltages are multiplied by this to be what is at the probe's tip."
)


def make_settings(ranges: tuple[str, ...], generator: bool) -> tuple[Setting, ...]:
    """The settings to offer for a scope with these ranges, and a generator or none."""
    choices = tuple((scale, scale_label(scale)) for scale in scales_for(ranges))
    probes = tuple((probe, f"{probe}x") for probe in PROBES)
    made = [
        Setting(
            "mode",
            "Reading",
            STREAM,
            choices=((STREAM, "Streaming, to 1 MS/s"), (BLOCKS, "Blocks, to 100 MS/s")),
            group="Sampling",
            tip=(
                "Streaming reads continuously, for as long as it runs, and pyscopegui\n"
                "finds the trigger. Blocks are short stretches taken at up to the\n"
                "scope's full rate, each around the scope's own trigger: for what\n"
                "is too fast to stream."
            ),
        ),
        Setting(
            "rate",
            "Sample rate",
            500_000,
            choices=(
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
            tip="When streaming: samples a second on each channel.",
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
                "When reading blocks: how long a stretch each one is. The scope's\n"
                "memory holds a few thousand samples, so a shorter block is sampled\n"
                "faster. The Event Log says what rate a length came to."
            ),
        ),
        Setting(
            "enabled_a", "Enabled", True, group="Channel A", tip="Whether channel A is read at all."
        ),
        Setting(
            "scale_a",
            "Scale",
            1.0,
            choices=choices,
            group="Channel A",
            live=True,
            tip=_SCALE_TIP,
        ),
        Setting("coupling_a", "Coupling", "DC", choices=_COUPLING, group="Channel A", live=True),
        Setting(
            "probe_a",
            "Probe",
            1,
            choices=probes,
            group="Channel A",
            live=True,
            tip=_PROBE_TIP,
        ),
        Setting(
            "enabled_b", "Enabled", True, group="Channel B", tip="Whether channel B is read at all."
        ),
        Setting(
            "scale_b",
            "Scale",
            1.0,
            choices=choices,
            group="Channel B",
            live=True,
            tip=_SCALE_TIP,
        ),
        Setting("coupling_b", "Coupling", "DC", choices=_COUPLING, group="Channel B", live=True),
        Setting(
            "probe_b",
            "Probe",
            1,
            choices=probes,
            group="Channel B",
            live=True,
            tip=_PROBE_TIP,
        ),
    ]
    if generator:
        made += [
            Setting(
                "gen_wave",
                "Output",
                "off",
                choices=(
                    ("off", "Off"),
                    ("sine", "Sine"),
                    ("square", "Square"),
                    ("triangle", "Triangle"),
                ),
                tip="What the scope's signal generator output puts out. Off is zero volts.",
                **_GENERATOR,
            ),
            Setting(
                "gen_frequency",
                "Frequency",
                1000.0,
                minimum=1.0,
                maximum=GENERATOR_HZ,
                unit="Hz",
                **_GENERATOR,
            ),
            Setting(
                "gen_amplitude",
                "Peak to peak",
                2.0,
                maximum=2 * GENERATOR_VOLTS,
                decimals=2,
                step=0.1,
                unit="V",
                tip="From the bottom of the wave to the top: 2 V is a wave between -1 V and +1 V.",
                **_GENERATOR,
            ),
            Setting(
                "gen_offset",
                "Offset",
                0.0,
                minimum=-GENERATOR_VOLTS,
                maximum=GENERATOR_VOLTS,
                decimals=2,
                step=0.1,
                unit="V",
                **_GENERATOR,
            ),
        ]
    return tuple(made)


#: What is offered before a scope is open and has said which model it is:
#: what the 2204A has.
SETTINGS = make_settings(_FROM_50MV, generator=True)


def settings_for(model: str | None) -> tuple[Setting, ...]:
    """What to offer for the model a scope says it is, or for none yet."""
    if model is None:
        return SETTINGS
    known = MODELS.get(model, Model())
    return make_settings(known.ranges or tuple(RANGES), known.generator)


@dataclass(frozen=True)
class Trigger:
    """What the scope itself is to trigger on, when it is reading blocks."""

    #: "A", "B" or None for no trigger.
    source: str | None = None
    level: float = 0.0
    rising: bool = True
    #: Where the trigger sits in the block, from 0 at its start to 1 at its end.
    position: float = 0.5
    #: Take the block anyway when no trigger comes.
    auto: bool = True


class ScopeError(Exception):
    """Something the scope or its driver would not do, in words for the Event Log."""


def library_candidates(platform: str | None = None, environ=None) -> list[Path]:
    """Where Pico's installers put the library, most likely first."""
    platform = sys.platform if platform is None else platform
    environ = os.environ if environ is None else environ
    if platform == "win32":
        found = []
        for variable in ("ProgramFiles", "ProgramFiles(x86)"):
            if not (base := environ.get(variable)):
                continue
            pico = Path(base) / "Pico Technology"
            found.append(pico / "SDK" / "lib" / "ps2000.dll")
            # Looked for beside Pico's own programs too, each in a folder of
            # its own: a copy there serves as well. Not promised anywhere,
            # since which of them carry one is Pico's business.
            found.extend(sorted(pico.glob("*/ps2000.dll")))
        return found
    return [Path("/opt/picoscope/lib/libps2000.so.2"), Path("/opt/picoscope/lib/libps2000.so")]


def find_library(platform: str | None = None, environ=None) -> Path | None:
    environ = os.environ if environ is None else environ
    if chosen := environ.get(LIBRARY_ENV):
        return Path(chosen)
    for candidate in library_candidates(platform, environ):
        if candidate.is_file():
            return candidate
    named = ctypes.util.find_library("ps2000")
    return Path(named) if named else None


def load_library():
    """Pico's library, with each function's arguments declared.

    ImportError when it is not there, saying what to install: the same
    failure as a Python package that is missing, and reported the same way.
    """
    path = find_library()
    if path is None:
        raise ImportError(
            "Pico's ps2000 library was not found. It comes with the PicoSDK, from "
            "picotech.com/downloads; or set "
            f"{LIBRARY_ENV} to the full path of ps2000.dll (libps2000.so on Linux)."
        )
    try:
        if sys.platform == "win32":
            # The library loads others of Pico's from beside it.
            if path.parent.is_dir():
                os.add_dll_directory(str(path.parent))
            library = ctypes.WinDLL(str(path))
        else:
            library = ctypes.CDLL(str(path))
    except OSError as exc:
        raise ImportError(f"Pico's ps2000 library at {path} would not load: {exc}") from exc
    for name, (returns, arguments) in PROTOTYPES.items():
        function = getattr(library, name)
        function.restype, function.argtypes = returns, arguments
    return library


class Settings:
    """How the scope is set up, from the ``instrument.picoscope2000`` settings.

    Anything not given, or not understood, is the default: a hand-edited
    settings.json must not be able to stop the scope from starting.
    """

    def __init__(self, options: dict | None = None) -> None:
        options = options if isinstance(options, dict) else {}
        try:
            rate = float(options.get("rate", DEFAULT_RATE))
        except (TypeError, ValueError):
            rate = DEFAULT_RATE
        #: In whole nanoseconds, which is what the driver is told, so the rate
        #: used everywhere else is the one that interval really gives.
        self.interval_ns = max(1, round(1e9 / rate)) if rate > 0 else round(1e9 / DEFAULT_RATE)
        self.rate = 1e9 / self.interval_ns
        #: What each probe divides by.
        self.probe = {
            "A": self._probe(options.get("probe_a")),
            "B": self._probe(options.get("probe_b")),
        }
        #: The scope's own range for each channel, which is what its scale
        #: comes to through its probe.
        self.ranges = {
            "A": self._range(options.get("scale_a"), self.probe["A"], options.get("range_a")),
            "B": self._range(options.get("scale_b"), self.probe["B"], options.get("range_b")),
        }
        self.dc = {
            "A": options.get("coupling_a", "DC") != "AC",
            "B": options.get("coupling_b", "DC") != "AC",
        }
        self.enabled = {
            "A": bool(options.get("enabled_a", True)),
            "B": bool(options.get("enabled_b", True)),
        }
        #: Blocks around the scope's own trigger, and not a stream.
        self.blocks = options.get("mode") == BLOCKS
        #: How long a stretch each block is, in seconds.
        self.block_s = min(max(self._number(options.get("block_ms"), 1.0), 0.001), 1000.0) / 1000
        wave = options.get("gen_wave", "off")
        #: Waveform, frequency in hertz, volts peak to peak, volts of offset.
        self.generator: tuple[str, float, float, float] = (
            wave if wave in WAVES else "off",
            min(max(self._number(options.get("gen_frequency"), 1000.0), 1.0), GENERATOR_HZ),
            min(max(self._number(options.get("gen_amplitude"), 2.0), 0.0), 2 * GENERATOR_VOLTS),
            min(
                max(self._number(options.get("gen_offset"), 0.0), -GENERATOR_VOLTS),
                GENERATOR_VOLTS,
            ),
        )

    @staticmethod
    def _number(value, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _probe(value) -> int:
        return value if value in PROBES and not isinstance(value, bool) else 1

    @staticmethod
    def _range(scale, probe: int, name) -> str:
        """The range for this scale. A range saved by name, from before
        there were scales, is used where no scale is."""
        try:
            scale = float(scale)
        except (TypeError, ValueError):
            return name if name in RANGES else DEFAULT_RANGE
        return range_for(scale, probe) if scale > 0 else DEFAULT_RANGE

    def volts(self, key: str) -> float:
        """Full scale at the probe's tip, in volts: the range, through the probe."""
        return RANGES[self.ranges[key]][1] * self.probe[key]

    def scale(self, key: str) -> float:
        """Volts a division at the probe's tip, as the scope is really set."""
        return SCALES[self.ranges[key]] * self.probe[key]

    def keys(self) -> list[str]:
        """The channels switched on, in order."""
        return [key for key in ("A", "B") if self.enabled[key]]


class Stream:
    """The scope, from opening it to closing it, with any number of runs between.

    Apart from the thread that calls it, so that it can be driven a step at a
    time with a stand-in for the library.
    """

    def __init__(
        self,
        library,
        settings: Settings,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._library = library
        self.settings = settings
        self._clock = clock
        self._handle = 0
        self._sent = 0
        self._started = 0.0
        self._rate_checked = False
        #: Whether the scope is reading now, as a stream or in blocks.
        self.streaming = False
        #: What it is called by itself, once open: "2204A".
        self.model: str | None = None
        #: The trigger for blocks, and one waiting to replace it, set from
        #: the GUI thread as ``wanted`` is.
        self.trigger = Trigger()
        self.wanted_trigger: Trigger | None = None
        #: In blocks: whether one has been asked for and is not yet in, and
        #: the timebase, length and rate they are taken at.
        self._block_pending = False
        self._timebase = 0
        self._block_samples = 0
        self._block_rate = 0.0
        #: True until the next block: reading stopped for a moment, on purpose.
        self._paused = False
        #: Whether the generator has been set to anything but off.
        self._generating = False
        #: Settings waiting to be taken up by the next poll, or None. Set from
        #: the GUI thread, taken by the thread that owns the scope.
        self.wanted: Settings | None = None
        #: What the callback copied out during the poll in progress.
        self._arrived: dict[str, np.ndarray] = {}
        # Kept for as long as the driver may call it: ctypes does not, and a
        # callback that has been collected is a crash inside the driver.
        self._callback = OverviewCallback(self._on_values)
        #: Lines for the Event Log, as (text, is it a warning).
        self.notes: list[tuple[str, bool]] = []

    # --- opening ---------------------------------------------------------------------------
    def open(self) -> None:
        """Open the scope, which loads its firmware. ScopeError if it will not."""
        try:
            handle = self._library.ps2000_open_unit()
        except OSError as exc:
            # The driver's own failure, let out as a Windows exception: seen
            # when the scope leaves the bus while it is being opened.
            raise ScopeError(
                "Pico's driver failed while opening the scope, which is what happens when "
                f"the scope drops off USB part way through ({exc}). Unplug it, plug it in "
                "again and press Open."
            ) from exc
        if handle <= 0:
            raise ScopeError(self._why_not_opened(handle))
        self._handle = handle
        self.model = self._info(INFO_VARIANT)
        self.notes.append((f"PicoScope {self.model}, {self._info(INFO_SERIAL)}.", False))

    def _info(self, line: int) -> str:
        text = ctypes.create_string_buffer(64)
        self._library.ps2000_get_unit_info(self._handle, text, len(text), line)
        return text.value.decode("ascii", "replace") or "?"

    def _why_not_opened(self, handle: int) -> str:
        if handle == 0:
            return (
                "No PicoScope was found. Check that it is plugged in, and that PicoScope 7 "
                "is closed: only one program can have the scope open."
            )
        # With no scope open, the driver answers about the one that failed.
        code = self._info(INFO_ERROR)
        reason = ERRORS.get(int(code), "") if code.isdigit() else ""
        return f"The PicoScope would not open: {reason or 'driver error ' + code}."

    # --- running ---------------------------------------------------------------------------
    def start(self, settings: Settings | None = None, trigger: Trigger | None = None) -> None:
        """Set the scope up and start it reading, counting samples from zero.

        The scope stays open whether or not this works, so a setting it
        refuses can be put right and tried again without opening it again.
        """
        self.stop()
        if settings is not None:
            self.settings = settings
        if trigger is not None:
            self.trigger = trigger
        if not self.settings.keys():
            raise ScopeError("Both channels are switched off, so there is nothing to read.")
        self._set_channels()
        self.set_generator(self.settings.generator)
        # What is waiting to be taken up is left waiting: it was asked for
        # after this start was, and is newer than what this start was given.
        if self.settings.blocks:
            self._choose_timebase()
            self._block_pending = False
            self.streaming = True
            return
        # No trigger: streaming is everything, from the moment it starts.
        self._library.ps2000_set_trigger(self._handle, NO_TRIGGER, 0, 0, 0, 0)
        self._start_streaming()
        self._sent = 0
        self._started = self._clock()
        self._rate_checked = False
        self._paused = False

    def _set_channels(self) -> None:
        settings = self.settings
        for key, channel in (("A", CHANNEL_A), ("B", CHANNEL_B)):
            code, _volts = RANGES[settings.ranges[key]]
            done = self._library.ps2000_set_channel(
                self._handle, channel, settings.enabled[key], settings.dc[key], code
            )
            if not done:
                raise ScopeError(
                    f"The scope would not set channel {key} to ±{settings.ranges[key]}: "
                    "not every model has every range."
                )

    def _start_streaming(self) -> None:
        settings = self.settings
        started = self._library.ps2000_run_streaming_ns(
            self._handle,
            settings.interval_ns,
            TIME_UNITS_NS,
            DRIVER_SAMPLES,
            0,
            1,
            OVERVIEW_SAMPLES,
        )
        if not started:
            raise ScopeError(
                f"The scope would not stream at one sample every {settings.interval_ns} ns. "
                "Try a lower rate."
            )
        self.streaming = True

    def stop(self) -> None:
        """Stop reading and leave the scope open. Safe when it is not reading."""
        if self.streaming:
            self._library.ps2000_stop(self._handle)
        self.streaming = False
        self._block_pending = False

    # --- blocks ----------------------------------------------------------------------------
    def _choose_timebase(self) -> None:
        """The fastest timebase at which the scope's memory holds a block this long.

        The scope is asked about each in turn, as Pico's guide says to: what
        it has depends on the model and on how many channels are on.
        """
        wanted_ns = self.settings.block_s * 1e9
        interval, units, most = ctypes.c_int32(0), ctypes.c_int16(0), ctypes.c_int32(0)
        found: tuple[int, int, int] | None = None
        for timebase in range(MAX_TIMEBASE + 1):
            usable = self._library.ps2000_get_timebase(
                self._handle,
                timebase,
                1,
                ctypes.byref(interval),
                ctypes.byref(units),
                1,
                ctypes.byref(most),
            )
            if not usable or interval.value <= 0 or most.value <= 0:
                continue
            found = (timebase, interval.value, most.value)
            if interval.value * most.value >= wanted_ns:
                break
        if found is None:
            raise ScopeError("The scope offered no timebase to read a block at.")
        self._timebase, interval_ns, most_samples = found
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
        trigger, settings = self.trigger, self.settings
        source = {"A": CHANNEL_A, "B": CHANNEL_B}.get(trigger.source, NO_TRIGGER)
        if trigger.source is None or not settings.enabled.get(trigger.source, False):
            source = NO_TRIGGER
        counts = 0
        if source != NO_TRIGGER:
            volts = settings.volts(trigger.source)
            counts = round(min(max(trigger.level / volts, -1.0), 1.0) * MAX_VALUE)
        # How long to wait for a trigger before taking the block anyway:
        # nought is for ever, which is what Normal and Single mean.
        wait_ms = max(AUTO_TRIGGER_MS, round(2e3 * settings.block_s)) if trigger.auto else 0
        self._library.ps2000_set_trigger(
            self._handle,
            source,
            counts,
            RISING if trigger.rising else FALLING,
            # As a share of the block, back from its start: -50 is the middle.
            -round(trigger.position * 100),
            min(wait_ms, 32767),
        )
        taken = ctypes.c_int32(0)
        started = self._library.ps2000_run_block(
            self._handle, self._block_samples, self._timebase, 1, ctypes.byref(taken)
        )
        if not started:
            raise ScopeError(
                f"The scope would not take a block of {self._block_samples} samples. "
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
                self._library.ps2000_stop(self._handle)
                self._block_pending = False
            if trigger is not None:
                self.trigger = trigger
            if wanted is not None:
                self._take_up_between_blocks(wanted)
        if not self._block_pending:
            self._arm()
            return None
        ready = self._library.ps2000_ready(self._handle)
        if ready < 0:
            raise ScopeError("The scope stopped answering: it may have been unplugged.")
        if ready == 0:
            return None
        self._block_pending = False
        return self._read_block()

    def _take_up_between_blocks(self, wanted: Settings) -> None:
        before, self.settings = self.settings, wanted
        try:
            if (wanted.ranges, wanted.dc) != (before.ranges, before.dc):
                self._set_channels()
        except ScopeError as exc:
            self.settings = replace_setup(wanted, before)
            self._set_channels()
            self.notes.append((f"{exc} It is still set as it was.", True))
        if wanted.generator != before.generator:
            self.set_generator(wanted.generator)

    def _read_block(self) -> Block | None:
        settings, samples = self.settings, self._block_samples
        buffers = {
            key: (ctypes.c_int16 * samples)() if settings.enabled[key] else None
            for key in ("A", "B")
        }
        overflow = ctypes.c_int16(0)
        count = self._library.ps2000_get_values(
            self._handle, buffers["A"], buffers["B"], None, None, ctypes.byref(overflow), samples
        )
        if count <= 0:
            return None
        data = {}
        for key, buffer in buffers.items():
            if buffer is None:
                continue
            volts = settings.volts(key)
            raw = np.ctypeslib.as_array(buffer)[:count]
            data[key] = raw.astype(np.float32) * np.float32(volts / MAX_VALUE)
        trigger = self.trigger
        if trigger.source not in data:
            return Block(0, self._block_rate, data, sweep=True)
        at = min(round(trigger.position * samples), count - 1)
        return Block(
            0,
            self._block_rate,
            data,
            sweep=True,
            trigger=at,
            triggered=crossed(data[trigger.source], at, trigger.level, trigger.rising),
        )

    def _take_up(self, wanted: Settings) -> None:
        """Change a range, the coupling or the generator while streaming.

        The scope takes none of them while it is streaming -- found on a
        2204A, which refused its generator a new output until it was stopped
        -- so the stream is stopped, the change made and the stream started
        again, with the scope left open. The time that took is counted as
        samples not taken, so what comes after is drawn where it belongs and
        the pause is a gap.
        """
        paused_at = self._clock()
        self.stop()
        before, self.settings = self.settings, wanted
        try:
            if (wanted.ranges, wanted.dc) != (before.ranges, before.dc):
                self._set_channels()
        except ScopeError as exc:
            # Back to what it was reading on, which is still what the plot says.
            self.settings = replace_setup(wanted, before)
            self._set_channels()
            self.notes.append((f"{exc} It is still set as it was.", True))
        if wanted.generator != before.generator:
            self.set_generator(wanted.generator)
        self._start_streaming()
        self._sent += round((self._clock() - paused_at) * self.settings.rate)
        self._paused = True

    def set_generator(self, generator: tuple[str, float, float, float]) -> None:
        """Set the signal generator output: a fixed frequency, no sweep."""
        wave, frequency, amplitude, offset = generator
        off = wave == "off"
        done = self._library.ps2000_set_sig_gen_built_in(
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
        )
        # Not every scope on this driver has a generator, and switching off
        # one that is not there is no failure.
        if not done and not off:
            self.notes.append(
                ("The scope would not set its signal generator to that output.", True)
            )
        elif not off:
            self.notes.append(
                (
                    f"Signal generator: {wave}, {frequency:g} Hz, {amplitude:g} V peak to peak, "
                    f"{offset:g} V offset.",
                    False,
                )
            )
        elif self._generating:
            self.notes.append(("Signal generator: off.", False))
        self._generating = bool(done) and not off

    # --- reading ---------------------------------------------------------------------------
    def _on_values(self, buffers, _overflow, _triggered_at, _triggered, _auto_stop, count) -> None:
        """Called by the driver from inside ``poll``. Copies, and nothing else:
        the buffers are the driver's and are reused as soon as this returns."""
        if count == 0:
            return
        # Unaggregated, the highest and the lowest are the same sample, so
        # the first buffer of each pair is the channel.
        for key, index in (("A", 0), ("B", 2)):
            if self.settings.enabled[key] and buffers[index]:
                self._arrived[key] = np.ctypeslib.as_array(buffers[index], shape=(count,)).copy()

    def poll(self) -> Block | None:
        """Whatever has arrived since the last poll, or None if nothing has."""
        if self.settings.blocks:
            return self._poll_block()
        # Taken and cleared in one step: it is set from the GUI thread.
        wanted, self.wanted = self.wanted, None
        if wanted is not None:
            self._take_up(wanted)
        self._arrived = {}
        self._library.ps2000_get_streaming_last_values(self._handle, self._callback)
        if not self._arrived:
            return None
        count = min(len(samples) for samples in self._arrived.values())
        data = {}
        for key, raw in self._arrived.items():
            volts = self.settings.volts(key)
            scaled = raw[:count].astype(np.float32) * np.float32(volts / MAX_VALUE)
            scaled[raw[:count] == LOST_DATA] = np.nan
            data[key] = scaled
        block = Block(self._sent, self.settings.rate, data, after_pause=self._paused)
        self._paused = False
        self._sent += count
        self._check_overrun()
        self._check_rate()
        return block

    def _check_overrun(self) -> None:
        overrun = ctypes.c_int16(0)
        self._library.ps2000_overview_buffer_status(self._handle, ctypes.byref(overrun))
        if overrun.value:
            self.notes.append(
                (
                    "The driver's buffer filled before it was read, so samples were lost "
                    "and what follows is later than the plot shows it.",
                    True,
                )
            )

    def _check_rate(self) -> None:
        """Say so, once, if samples are not arriving at the rate asked for.

        Time on the plot is the sample count over the rate. A scope that
        quietly samples slower than it was asked to would be drawn with every
        time wrong by that ratio, and nothing else would give it away.
        """
        elapsed = self._clock() - self._started
        if self._rate_checked or elapsed < CHECK_AFTER_S:
            return
        self._rate_checked = True
        arriving = self._sent / elapsed
        if abs(arriving - self.settings.rate) > RATE_TOLERANCE * self.settings.rate:
            self.notes.append(
                (
                    f"The scope is delivering {arriving:,.0f} samples a second where "
                    f"{self.settings.rate:,.0f} were asked for, so times on the plot are out "
                    "by that ratio. Set a rate it can keep to.",
                    True,
                )
            )

    def close(self) -> None:
        """Stop and let go of the scope. Safe when it never opened."""
        if self._handle > 0:
            self._library.ps2000_stop(self._handle)
            self._library.ps2000_close_unit(self._handle)
        self.streaming = False
        self._handle = 0


def crossed(samples: np.ndarray, at: int, level: float, rising: bool) -> bool:
    """Whether the signal goes through the level at this sample, the way asked for.

    The driver does not say whether a block was triggered or taken because
    nothing came, so the samples either side of where the trigger should be
    are looked at instead.
    """
    before = samples[max(at - NEAR_TRIGGER, 0) : at + 1]
    after = samples[at : at + NEAR_TRIGGER + 1]
    if not len(before) or not len(after):
        return False
    if rising:
        return bool(before.min() <= level <= after.max()) and bool(before.min() < after.max())
    return bool(after.min() <= level <= before.max()) and bool(after.min() < before.max())


def replace_setup(wanted: Settings, before: Settings) -> Settings:
    """``wanted``, with the ranges and coupling ``before`` had: for a change the scope refused."""
    kept = copy.copy(wanted)
    kept.ranges, kept.dc = dict(before.ranges), dict(before.dc)
    return kept


class _Reader(QThread):
    """The thread that owns the scope, from opening it to closing it.

    Asked to start, stop and close through a queue, and otherwise polling:
    Pico's driver is called from this thread and no other.
    """

    #: The run it belongs to, and the block.
    block = Signal(int, object)
    note = Signal(str)
    warning = Signal(str)
    failed = Signal(str)
    #: The model the scope says it is.
    opened = Signal(str)
    #: The run that has started, or stopped.
    started_run = Signal(int)
    stopped_run = Signal(int)

    def __init__(self, stream: Stream, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._stream = stream
        self._asked: queue.SimpleQueue = queue.SimpleQueue()

    def ask(self, *command) -> None:
        """("start", settings, run, trigger), ("stop",) or ("close",): done in the order asked."""
        self._asked.put(command)

    def _say(self) -> None:
        notes, self._stream.notes = self._stream.notes, []
        for text, is_warning in notes:
            (self.warning if is_warning else self.note).emit(text)

    def run(self) -> None:
        stream = self._stream
        run = 0
        try:
            stream.open()
            self._say()
            self.opened.emit(stream.model or "")
            while True:
                try:
                    # Waiting to be asked is also the pause between two polls.
                    command = self._asked.get(timeout=POLL_S if stream.streaming else IDLE_S)
                except queue.Empty:
                    command = None
                if command is not None:
                    if command[0] == "close":
                        break
                    was_streaming = stream.streaming
                    stream.stop()
                    if was_streaming:
                        self.stopped_run.emit(run)
                    if command[0] == "start":
                        run = command[2]
                        try:
                            stream.start(command[1], command[3])
                            self._say()
                            self.started_run.emit(run)
                        except ScopeError as exc:
                            stream.stop()
                            self._say()
                            self.failed.emit(str(exc))
                            self.stopped_run.emit(run)
                    continue
                if stream.streaming:
                    try:
                        block = stream.poll()
                    except ScopeError as exc:
                        stream.stop()
                        self._say()
                        self.failed.emit(str(exc))
                        self.stopped_run.emit(run)
                        continue
                    if block is not None:
                        self.block.emit(run, block)
                    self._say()
        except ScopeError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # report, never die: nothing else would say why
            self.failed.emit(f"PicoScope: {type(exc).__name__}: {exc}")
        finally:
            stream.close()


class PicoScope2000(Instrument):
    SETTINGS = SETTINGS

    def __init__(self, parent: QObject | None = None, options: dict | None = None) -> None:
        super().__init__(parent)
        self.settings = Settings(options)
        #: Loaded now rather than at Open, so that a missing library is said
        #: when the instrument is chosen and in the same words as any other.
        self._library = load_library()
        self._reader: _Reader | None = None
        self._stream: Stream | None = None
        self._options = dict(options) if isinstance(options, dict) else {}
        self._is_open = False
        self._running = False
        #: Which run the blocks that count belong to. One more at each start,
        #: so that what a run sends after it was replaced is told apart.
        self._run = 0
        #: The model the scope said it is, once it has been opened.
        self._model: str | None = None
        self._trigger = Trigger()
        #: The rate the last block was taken at, which the scope chooses.
        self._block_rate = 0.0

    def settings_offered(self) -> tuple[Setting, ...]:
        return settings_for(self._model)

    @property
    def sweeps(self) -> bool:
        return self.settings.blocks

    def set_trigger(
        self, source: str | None, level: float, rising: bool, position: float, auto: bool
    ) -> None:
        """What the scope is to trigger on, when it is reading blocks."""
        wanted = Trigger(source, level, rising, position, auto)
        if wanted == self._trigger:
            return
        self._trigger = wanted
        if self._running and self._stream is not None and self.settings.blocks:
            self._stream.wanted_trigger = wanted

    def set(self, key: str, value: object) -> None:
        """Take up a setting: now if it is running, and at the next start if not."""
        self._options[key] = value
        self.settings = Settings(self._options)
        if self._running and self._stream is not None:
            # Handed to the thread that owns the scope, which takes it up
            # between two polls: the driver is not called from two threads at
            # once. Reading stops for a moment while it does; see _take_up.
            self._stream.wanted = self.settings

    def channels(self) -> list[Channel]:
        return [
            Channel(
                key,
                key,
                full_scale=self.settings.volts(key),
                detail=(
                    f"{scale_label(self.settings.scale(key))}, {self.settings.probe[key]}x, "
                    f"{'DC' if self.settings.dc[key] else 'AC'}"
                ),
                group=f"Channel {key}",
            )
            for key in self.settings.keys()
        ]

    @property
    def rate(self) -> float:
        if self.settings.blocks:
            # Chosen by the scope for the block length, so known once a block is in.
            return self._block_rate or 1e9 / max(self.settings.block_s * 1e9 / 4000, 10)
        return self.settings.rate

    @property
    def is_open(self) -> bool:
        return self._is_open

    @property
    def running(self) -> bool:
        return self._running

    # --- opening and closing ---------------------------------------------------------------
    def open(self) -> None:
        if self._reader is not None and self._reader.isRunning():
            return
        self._stream = Stream(self._library, self.settings)
        reader = _Reader(self._stream, self)
        reader.block.connect(self._on_block)
        reader.note.connect(self.note)
        reader.warning.connect(self.warning)
        reader.failed.connect(self.error)
        reader.opened.connect(self._on_opened)
        reader.started_run.connect(self._on_started)
        reader.stopped_run.connect(self._on_stopped)
        reader.finished.connect(self._on_finished)
        self._reader = reader
        self.note.emit("Opening the PicoScope, which takes a few seconds...")
        reader.start()

    def close(self) -> None:
        if self._reader is None:
            return
        self._reader.ask("close")
        # Opening cannot be interrupted, so this can be most of its few seconds.
        self._reader.wait(10_000)

    def _on_opened(self, model: str) -> None:
        self._is_open = True
        self._model = model or None
        self.opened_changed.emit(True)

    def _on_finished(self) -> None:
        """The thread has gone: the scope is closed, however that came about."""
        was_running, was_open = self._running, self._is_open
        self._running = self._is_open = False
        if was_running:
            self.state_changed.emit(False)
        if was_open:
            self.note.emit("PicoScope closed.")
        self.opened_changed.emit(False)

    # --- running ---------------------------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self.open()
        self._run += 1
        self._running = True
        self._block_rate = 0.0
        # Nothing asked for before now is still waiting: this start carries it all.
        self._stream.wanted = self._stream.wanted_trigger = None
        self._reader.ask("start", self.settings, self._run, self._trigger)

    def stop(self) -> None:
        if not self._running or self._reader is None:
            return
        # Said now and not when the thread gets to it: whatever it sends in
        # the meantime belongs to a run that is over.
        self._running = False
        self._reader.ask("stop")
        self.state_changed.emit(False)

    def _on_block(self, run: int, block: Block) -> None:
        if run == self._run and self._running:
            if block.sweep:
                self._block_rate = block.rate
            self.block.emit(block)

    def _on_started(self, run: int) -> None:
        if run == self._run:
            self.state_changed.emit(True)

    def _on_stopped(self, run: int) -> None:
        # A run that was replaced by the next says nothing: the next is running.
        if run == self._run and self._running:
            self._running = False
            self.state_changed.emit(False)
