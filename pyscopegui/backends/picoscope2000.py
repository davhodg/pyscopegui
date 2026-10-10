# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""PicoScope 2204A and its relatives, through Pico's own ``ps2000`` library.

The older two-channel 2000 Series scopes -- 2202, 2203, 2204, 2204A, 2205 and
2205A -- use the ``ps2000`` driver, not ``ps2000a``. The library comes with
Pico's software and is not bundled: this looks for it where Pico installs it.

Read in what Pico calls fast streaming: the scope samples continuously and
the driver hands over whatever has arrived each time it is asked. That is the
mode for anything slower than a few hundred microseconds a division, where
the scope's own 8 kS buffer holds too little for block mode to be any use.

Everything that talks to the scope runs on a thread of its own, because
opening it takes seconds -- the driver loads the scope's firmware every time
-- and a window that stops answering for that long looks broken.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from pyscopegui.backends.base import Block, Channel, Instrument

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
ERRORS = {
    1: "too many scopes are open",
    2: "the computer is out of memory",
    3: "no scope was found",
    4: "the scope's firmware could not be loaded",
    5: "the scope is not responding",
    6: "the scope's configuration is corrupt or missing",
    7: "this operating system is not supported by the driver",
}

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
}


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
            # PicoScope 7 keeps a copy beside its own program, in a folder
            # named for the edition.
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
            "Pico's ps2000 library was not found. It comes with the PicoSDK, and with "
            "PicoScope 7, from picotech.com/downloads; or set "
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
        self.ranges = {
            "A": self._range(options.get("range_a")),
            "B": self._range(options.get("range_b")),
        }
        self.dc = {"A": bool(options.get("dc_a", True)), "B": bool(options.get("dc_b", True))}
        self.enabled = {"A": True, "B": bool(options.get("enabled_b", True))}

    @staticmethod
    def _range(name) -> str:
        return name if name in RANGES else DEFAULT_RANGE

    def keys(self) -> list[str]:
        """The channels switched on, in order."""
        return [key for key in ("A", "B") if self.enabled[key]]


class Stream:
    """One run of fast streaming: open, poll until told to stop, close.

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
        #: What the callback copied out during the poll in progress.
        self._arrived: dict[str, np.ndarray] = {}
        # Kept for as long as the driver may call it: ctypes does not, and a
        # callback that has been collected is a crash inside the driver.
        self._callback = OverviewCallback(self._on_values)
        #: Lines for the Event Log, as (text, is it a warning).
        self.notes: list[tuple[str, bool]] = []

    # --- opening ---------------------------------------------------------------------------
    def open(self) -> None:
        """Open the scope, set it up and start it streaming. ScopeError if it will not."""
        library, settings = self._library, self.settings
        try:
            handle = library.ps2000_open_unit()
        except OSError as exc:
            # The driver's own failure, let out as a Windows exception: seen
            # when the scope leaves the bus while it is being opened.
            raise ScopeError(
                "Pico's driver failed while opening the scope, which is what happens when "
                f"the scope drops off USB part way through ({exc}). Unplug it, plug it in "
                "again and press Run."
            ) from exc
        if handle <= 0:
            raise ScopeError(self._why_not_opened(handle))
        self._handle = handle
        self.notes.append(
            (f"PicoScope {self._info(INFO_VARIANT)}, {self._info(INFO_SERIAL)}.", False)
        )
        for key, channel in (("A", CHANNEL_A), ("B", CHANNEL_B)):
            code, _volts = RANGES[settings.ranges[key]]
            done = library.ps2000_set_channel(
                handle, channel, settings.enabled[key], settings.dc[key], code
            )
            if not done:
                raise ScopeError(
                    f"The scope would not set channel {key} to ±{settings.ranges[key]}: "
                    "not every model has every range."
                )
        # No trigger: streaming is everything, from the moment it starts.
        library.ps2000_set_trigger(handle, NO_TRIGGER, 0, 0, 0, 0)
        started = library.ps2000_run_streaming_ns(
            handle, settings.interval_ns, TIME_UNITS_NS, DRIVER_SAMPLES, 0, 1, OVERVIEW_SAMPLES
        )
        if not started:
            raise ScopeError(
                f"The scope would not stream at one sample every {settings.interval_ns} ns. "
                "Try a lower rate."
            )
        self._sent = 0
        self._started = self._clock()

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
        self._arrived = {}
        self._library.ps2000_get_streaming_last_values(self._handle, self._callback)
        if not self._arrived:
            return None
        count = min(len(samples) for samples in self._arrived.values())
        data = {}
        for key, raw in self._arrived.items():
            _code, volts = RANGES[self.settings.ranges[key]]
            scaled = raw[:count].astype(np.float32) * np.float32(volts / MAX_VALUE)
            scaled[raw[:count] == LOST_DATA] = np.nan
            data[key] = scaled
        block = Block(self._sent, self.settings.rate, data)
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
        self._handle = 0


class _Reader(QThread):
    """The thread a stream runs on, from opening the scope to closing it."""

    block = Signal(object)
    note = Signal(str)
    warning = Signal(str)
    failed = Signal(str)
    opened = Signal()

    def __init__(self, stream: Stream, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._stream = stream
        self._wanted = True

    def ask_to_stop(self) -> None:
        self._wanted = False

    def _say(self) -> None:
        notes, self._stream.notes = self._stream.notes, []
        for text, is_warning in notes:
            (self.warning if is_warning else self.note).emit(text)

    def run(self) -> None:
        try:
            self._stream.open()
            self._say()
            self.opened.emit()
            while self._wanted:
                if (block := self._stream.poll()) is not None:
                    self.block.emit(block)
                self._say()
                time.sleep(POLL_S)
        except ScopeError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # report, never die: nothing else would say why
            self.failed.emit(f"PicoScope: {type(exc).__name__}: {exc}")
        finally:
            self._stream.close()


class PicoScope2000(Instrument):
    def __init__(self, parent: QObject | None = None, options: dict | None = None) -> None:
        super().__init__(parent)
        self.settings = Settings(options)
        #: Loaded now rather than at Run, so that a missing library is said
        #: when the instrument is chosen and in the same words as any other.
        self._library = load_library()
        self._reader: _Reader | None = None

    def channels(self) -> list[Channel]:
        return [
            Channel(key, f"{key}: ±{self.settings.ranges[key]}") for key in self.settings.keys()
        ]

    @property
    def rate(self) -> float:
        return self.settings.rate

    @property
    def running(self) -> bool:
        return self._reader is not None and self._reader.isRunning()

    def start(self) -> None:
        if self.running:
            return
        reader = _Reader(Stream(self._library, self.settings), self)
        reader.block.connect(self.block)
        reader.note.connect(self.note)
        reader.warning.connect(self.warning)
        reader.failed.connect(self.error)
        reader.opened.connect(lambda: self.state_changed.emit(True))
        reader.finished.connect(self._on_finished)
        self._reader = reader
        self.note.emit("Opening the PicoScope, which takes a few seconds...")
        reader.start()

    def _on_finished(self) -> None:
        self.state_changed.emit(False)

    def stop(self) -> None:
        if self._reader is None:
            return
        self._reader.ask_to_stop()
        # Opening cannot be interrupted, so this can be most of its few seconds.
        self._reader.wait(10_000)
