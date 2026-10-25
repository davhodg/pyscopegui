# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Rigol DS1000Z scopes, over the network or USB: the DS1054Z, and the others of the series.

The series differs in bandwidth, and in whether a model has logic inputs
(MSO, or Plus with the option) or a signal generator (-S). The four analog
channels are the same on all of them, and are what is read here.

The scope speaks SCPI as lines of text. Over the network that is TCP port
5555, so nothing of Rigol's is needed and nothing is loaded: a socket is the
whole of it. Over USB the same lines go through a VISA library -- Rigol's
own software installs one, as do National Instruments' and Keysight's --
reached with pyvisa. The commands and the connection are kept apart: either
kind of link is written to and asked in the same three ways.

It cannot stream. It triggers itself and fills its own memory, and what it
took is then read back, so it sends sweeps: each a capture complete in
itself, taking the place of the last. One sweep is one Single on the scope
-- armed, waited for, read, armed again -- which is what makes the four
channels of a sweep belong to the same moment, and what lets it be said
whether the scope triggered or was made to.

Two ways of reading a sweep. The screen is the 1200 points the scope draws,
quick enough to be read a couple of times a second. The memory is everything it
took, thousands to millions of points, read a quarter of a million at a
time.
"""

from __future__ import annotations

import queue
import socket
import time
from dataclasses import dataclass, field

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from pyscopegui.backends import probes, visa
from pyscopegui.backends.base import Block, Channel, Instrument, Setting
from pyscopegui.core.traffic import traced
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
    TIMEOUT,
    WINDOW,
    Condition,
)

PORT = 5555
#: Seconds to wait to be connected, and for an answer once connected.
CONNECT_S = 3.0
ANSWER_S = 5.0

CHANNELS = ("CH1", "CH2", "CH3", "CH4")
#: Divisions on the screen: across, and up.
ACROSS = 12
UP = 8
SCREEN_POINTS = 1200
#: The most the scope hands over in one read of its memory, as bytes.
CHUNK = 250_000

SCREEN = "screen"
MEMORY = "memory"
LAN, USB = "lan", "usb"
#: Rigol's number as a maker of USB devices, as a VISA resource names it:
#: in hexadecimal, or by some libraries in decimal.
RIGOL_USB = ("0X1AB1", "::6833::")

#: After arming, the scope goes on saying it is stopped for a moment: what
#: it says is not asked until this long has gone by.
SETTLE_S = 0.15
#: With Auto, how long past one screen's worth to wait before making it trigger.
AUTO_S = 0.2
#: Seconds between two looks at whether it has triggered, and between two
#: looks at whether anything has been asked while it is not running.
POLL_S = 0.02
#: How long a scope that has stopped may go on having nothing to show
#: before it is armed again.
NOT_READY_S = 1.0
#: How long after the last of its memory was read the scope's beeper is left
#: off, for it to have said the last thing it has to say about that.
QUIET_S = 1.5
IDLE_S = 0.1
#: How long the scope is left stopped before it is asked who it is again, to
#: see that it is still there: while it runs, every look at whether it has
#: triggered says so, but stopped, nothing is sent it, and a scope switched
#: off or unplugged would not be noticed until the next Run.
CHECK_S = 5.0


class ScopeError(Exception):
    """The scope could not be reached, or stopped answering. In words for the Event Log."""


#: Rigol's instruments on USB, and what is said about them.
MAKER = visa.Maker(
    "Rigol",
    RIGOL_USB,
    library=(
        "Rigol's own software installs one, as do National Instruments' and Keysight's. "
        "The network needs none."
    ),
    check=(
        "Check the cable, and that the scope's USB Device setting under Utility > IO is Computer."
    ),
    error=ScopeError,
    answer_s=ANSWER_S,
)


class GivenUpError(Exception):
    """A read was abandoned part way, because something else was asked for."""


#: Each channel in the colour the scope's own screen draws it in.
COLOURS = {"CH1": "#f2e600", "CH2": "#00e5ff", "CH3": "#ff40d0", "CH4": "#3d7bff"}


# --- the settings ---------------------------------------------------------------------------
def _steps(low_exponent: int, high_exponent: int) -> list[float]:
    """1, 2, 5 in every power of ten from one to the other."""
    return [m * 10.0**e for e in range(low_exponent, high_exponent + 1) for m in (1, 2, 5)]


def _engineering(value: float, unit: str) -> str:
    for scale, prefix in ((1.0, ""), (1e-3, "m"), (1e-6, "u"), (1e-9, "n")):
        if value >= scale * 0.999:
            return f"{value / scale:g} {prefix}{unit}"
    return f"{value:g} {unit}"


#: Seconds a division, from 5 ns to 50 s.
TIMES = tuple(round(t, 10) for t in _steps(-9, 1) if 5e-9 <= t <= 50)
#: Volts a division as the screen shows them, probe and all, from 1 mV to 100 V.
SCALES = tuple(round(v, 4) for v in _steps(-3, 2) if v <= 100)
PROBES = probes.RATIOS
COUPLINGS = (("DC", "DC"), ("AC", "AC"), ("GND", "Ground"))
#: How the scope makes each point from the samples it takes. Not averaging:
#: that is over several triggers, and each sweep here is one.
ACQUISITIONS = (("NORM", "Normal"), ("HRES", "High resolution"), ("PEAK", "Peak detect"))


def usb_scopes() -> list[tuple[str, str]]:
    """The Rigol scopes on USB now, as (serial number, what to call it in a list)."""
    return visa.plugged_in(MAKER)


def make_settings() -> tuple[Setting, ...]:
    made = [
        Setting(
            "connection",
            "Connection",
            LAN,
            choices=((LAN, "Network"), (USB, "USB")),
            group="Connection",
            closed=True,
            tip=(
                "How the scope is plugged in. The network needs nothing installed.\n"
                "USB needs a VISA library, which Rigol's own software installs.\n"
                "Changed while the scope is closed."
            ),
        ),
        Setting(
            "address",
            "Address",
            "",
            group="Connection",
            closed=True,
            needs=("connection", LAN),
            tip=(
                "The scope's address on the network, as it shows under\n"
                "Utility > IO > LAN Conf: 192.168.1.50. Changed while the scope is closed."
            ),
        ),
        Setting(
            "usb",
            "USB device",
            "",
            group="Connection",
            closed=True,
            needs=("connection", USB),
            found=usb_scopes,
            empty="First Rigol found",
            tip=(
                "Which scope, where more than one is plugged in. The list is of\n"
                "those plugged in now; a serial number can be typed too. Left\n"
                "empty, the first Rigol found is used. Changed while the scope is closed."
            ),
        ),
        Setting(
            "read",
            "Reading",
            SCREEN,
            choices=((SCREEN, "Screen: 1200 points"), (MEMORY, "Memory: all it took")),
            group="Sampling",
            tip=(
                "The screen is the 1200 points the scope draws, read about twice\n"
                "a second. The memory is every sample it took, which is thousands\n"
                "to millions and takes seconds to read: for Single."
            ),
        ),
        Setting(
            "time_div",
            "Time",
            1e-3,
            choices=tuple((t, _engineering(t, "s/div")) for t in TIMES),
            group="Sampling",
            live=True,
            tip="Seconds a division, of the twelve across the scope's screen.",
        ),
        Setting(
            "acquire",
            "Acquisition",
            "NORM",
            choices=ACQUISITIONS,
            group="Sampling",
            live=True,
            tip=(
                "How the scope makes each point from the samples it takes.\n"
                "Normal keeps one sample for each. High resolution averages the\n"
                "samples either side, which is quieter and slower to follow an edge.\n"
                "Peak detect keeps the lowest and highest, so nothing narrow is missed."
            ),
        ),
    ]
    for number in range(1, len(CHANNELS) + 1):
        group = f"Channel {number}"
        made += [
            Setting(
                f"enabled_{number}",
                "Enabled",
                number == 1,
                group=group,
                tip=f"Whether channel {number} is on, and read.",
            ),
            Setting(
                f"scale_{number}",
                "Scale",
                1.0,
                choices=tuple((v, _engineering(v, "V/div")) for v in SCALES),
                group=group,
                live=True,
                tip="Volts a division, of the eight up the scope's screen, with the probe counted.",
            ),
            Setting(
                f"offset_{number}",
                "Offset",
                0.0,
                minimum=-1000.0,
                maximum=1000.0,
                decimals=3,
                unit="V",
                step=0.1,
                group=group,
                live=True,
                beside=f"scale_{number}",
                tip="Added to the signal before it is drawn: it moves nought volts up the screen.",
            ),
            Setting(
                f"coupling_{number}", "Coupling", "DC", choices=COUPLINGS, group=group, live=True
            ),
            Setting(
                f"limit_{number}",
                "20 MHz limit",
                False,
                group=group,
                live=True,
                beside=f"coupling_{number}",
                tip=(
                    "Leave out what is above 20 MHz, which for a slow signal is\n"
                    "noise. Off, the channel has the scope's full bandwidth."
                ),
            ),
            *probes.settings(str(number), group),
        ]
    return tuple(made)


SETTINGS = make_settings()


def _nearest(value: object, allowed: tuple, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return min(allowed, key=lambda a: abs(a - number))


class Settings:
    """What settings.json holds for this scope, made safe: anything odd is the default."""

    def __init__(self, options: object = None) -> None:
        options = options if isinstance(options, dict) else {}
        address = str(options.get("address") or "").strip()
        host, _, port = address.partition(":")
        self.host = host.strip()
        self.port = int(port) if port.strip().isdigit() else PORT
        #: Over USB, and which scope there, if it was said.
        self.usb = options.get("connection") == USB
        self.usb_device = str(options.get("usb") or "").strip()
        self.memory = options.get("read") == MEMORY
        self.time_div = _nearest(options.get("time_div"), TIMES, 1e-3)
        acquire = options.get("acquire")
        self.acquire = acquire if acquire in dict(ACQUISITIONS) else "NORM"
        #: Whether each channel is held to 20 MHz.
        self.limit: dict[str, bool] = {}
        self.enabled: dict[str, bool] = {}
        self.scale: dict[str, float] = {}
        self.offset: dict[str, float] = {}
        self.coupling: dict[str, str] = {}
        self.probe: dict[str, probes.Probe] = {}
        for number, key in enumerate(CHANNELS, start=1):
            enabled = options.get(f"enabled_{number}")
            self.enabled[key] = enabled if isinstance(enabled, bool) else number == 1
            self.scale[key] = _nearest(options.get(f"scale_{number}"), SCALES, 1.0)
            try:
                self.offset[key] = min(max(float(options.get(f"offset_{number}", 0.0)), -1e3), 1e3)
            except (TypeError, ValueError):
                self.offset[key] = 0.0
            coupling = options.get(f"coupling_{number}")
            self.coupling[key] = coupling if coupling in ("DC", "AC", "GND") else "DC"
            self.probe[key] = probes.read(options, str(number))
            self.limit[key] = options.get(f"limit_{number}") is True

    def keys(self) -> list[str]:
        """The channels that are on, in order."""
        return [key for key in CHANNELS if self.enabled[key]]


@dataclass(frozen=True)
class Trigger:
    """What the scope is to trigger on."""

    #: "CH1" to "CH4", or None for no trigger: sweeps one after another.
    source: str | None = None
    level: float = 0.0
    rising: bool = True
    #: Where the trigger sits across the screen, from 0 at its left to 1 at its right.
    position: float = 0.5
    #: Take the sweep anyway when no trigger comes.
    auto: bool = True
    #: What is waited for beyond an edge, where the scope can: see triggers_itself.
    condition: Condition = field(default_factory=Condition)


#: The trigger types the scope is told, by what pyscopegui calls them.
MODES = {
    EDGE: "EDGE",
    PULSE: "PULS",
    RUNT: "RUNT",
    WINDOW: "WIND",
    TIMEOUT: "TIM",
    PATTERN: "PATT",
}
#: How far either side of the middle of its screen the scope takes a trigger level from,
#: in divisions: past the top and bottom of what it shows.
LEVEL_DIVISIONS = 5
#: The shortest and longest a pattern can be held for the scope's Duration
#: trigger, in seconds: one of its advanced triggers.
DURATIONS = (8e-9, 10.0)
#: The least holdoff the scope has, in seconds: what it is with none.
LEAST_HOLDOFF = 16e-9


def triggers_itself(condition: Condition, source: str | None, on: list[str]) -> bool:
    """Whether the scope can wait for this itself, given the channels that are on.

    An edge either way, a pulse's width, a runt, a window, or a pattern of
    channels at once -- each with a holdoff, which it has as well -- and a
    timeout, which has none. Runt, window and timeout are among the advanced
    triggers a DS1000Z has as an option. A pattern that has to be held is
    its Duration trigger, another of them, for as long as that takes: 8 ns
    to 10 s. Not the Nth time, or a delay.
    """
    if condition.counted or (condition.kind == TIMEOUT and condition.holdoff):
        return False
    if condition.kind == PATTERN:
        keys = [key for key, _level in condition.pattern]
        held = not condition.held or DURATIONS[0] <= condition.held <= DURATIONS[1]
        return held and all(key in on for key in keys)
    return condition.kind in MODES and source in on


def waits(settings: Settings, trigger: Trigger) -> bool:
    """Whether there is a trigger to wait for, or sweeps are taken one after another."""
    condition = trigger.condition
    if condition.kind == PATTERN:
        return bool(condition.pattern) and triggers_itself(
            condition, trigger.source, settings.keys()
        )
    return trigger.source in CHANNELS and settings.enabled[trigger.source]


def _trigger_setup(settings: Settings, trigger: Trigger) -> dict[str, str]:
    """The commands for what is waited for, as what is set -> what to."""
    condition = trigger.condition
    if not triggers_itself(condition, trigger.source, settings.keys()):
        condition = Condition()

    def level(key: str, value: float) -> str:
        """As the scope is told it: through the probe, and inside the five
        divisions either side of the middle that it takes a level from."""
        probe = settings.probe[key]
        reach = LEVEL_DIVISIONS * probe.at_scope(settings.scale[key])
        middle = -probe.at_scope(settings.offset[key])
        return f"{min(max(probe.at_scope(value), middle - reach), middle + reach):g}"

    kind = condition.kind
    wanted = {":TRIG:MODE": MODES[kind]}
    if kind == PATTERN:
        levels = dict(condition.pattern)
        pattern = ",".join(
            "X" if key not in levels else "H" if levels[key] else "L" for key in CHANNELS
        )
        if condition.held:
            # Held for at least this long: the scope's Duration trigger.
            wanted[":TRIG:MODE"] = "DUR"
            wanted[":TRIG:DUR:SOUR"] = "CHAN" + next(iter(levels))[2:]
            wanted[":TRIG:DUR:TYP"] = pattern
            wanted[":TRIG:DUR:WHEN"] = "GRE"
            wanted[":TRIG:DUR:TUPP"] = f"{DURATIONS[1]:g}"
            wanted[":TRIG:DUR:TLOW"] = f"{condition.held:g}"
        else:
            wanted[":TRIG:PATT:PATT"] = pattern
        # Each channel's level, as the pattern trigger has them.
        for key in levels:
            wanted[f":TRIG:PATT:LEV CHAN{key[2:]},"] = level(key, trigger.level)
    else:
        key = trigger.source
        source = "CHAN" + key[2:]
        low, high = sorted((trigger.level, condition.upper))
        if kind == EDGE:
            wanted[":TRIG:EDG:SOUR"] = source
            edge = "RFAL" if condition.edge == EITHER else "POS" if trigger.rising else "NEG"
            wanted[":TRIG:EDG:SLOP"] = edge
            wanted[":TRIG:EDG:LEV"] = level(key, trigger.level)
        elif kind == PULSE:
            wanted[":TRIG:PULS:SOUR"] = source
            wanted[":TRIG:PULS:LEV"] = level(key, trigger.level)
            sign = "N" if condition.polarity == LOW else "P"
            if condition.compare == BETWEEN:
                wanted[":TRIG:PULS:WHEN"] = sign + "GL"
                wanted[":TRIG:PULS:UWID"] = f"{condition.longest:g}"
                wanted[":TRIG:PULS:LWID"] = f"{condition.shortest:g}"
            else:
                wanted[":TRIG:PULS:WHEN"] = sign + ("LES" if condition.compare == SHORTER else "GR")
                wanted[":TRIG:PULS:WIDT"] = f"{condition.shortest:g}"
        elif kind == RUNT:
            wanted[":TRIG:RUNT:SOUR"] = source
            wanted[":TRIG:RUNT:POL"] = "NEG" if condition.polarity == LOW else "POS"
            wanted[":TRIG:RUNT:WHEN"] = "NONE"
            wanted[":TRIG:RUNT:ALEV"] = level(key, high)
            wanted[":TRIG:RUNT:BLEV"] = level(key, low)
        elif kind == TIMEOUT:
            wanted[":TRIG:TIM:SOUR"] = source
            wanted[":TRIG:TIM:SLOP"] = {LOW: "NEG", EITHER: "RFAL"}.get(condition.polarity, "POS")
            wanted[":TRIG:TIM:TIM"] = f"{condition.shortest:g}"
            # Its level is the edge trigger's: there is no command of its own
            # for it. Found by trying, on a DS1054Z.
            wanted[":TRIG:EDG:SOUR"] = source
            wanted[":TRIG:EDG:LEV"] = level(key, trigger.level)
            return wanted  # and no holdoff, which it does not have
        else:
            wanted[":TRIG:WIND:SOUR"] = source
            wanted[":TRIG:WIND:SLOP"] = "RFAL"
            wanted[":TRIG:WIND:POS"] = "ENTER" if condition.direction == ENTER else "EXIT"
            wanted[":TRIG:WIND:ALEV"] = level(key, high)
            wanted[":TRIG:WIND:BLEV"] = level(key, low)
    wanted[":TRIG:HOLD"] = f"{max(condition.holdoff, LEAST_HOLDOFF):g}"
    return wanted


def setup(settings: Settings, trigger: Trigger) -> dict[str, str]:
    """Every command that sets the scope up, as what is set -> what to.

    Kept apart like this so that a change sends only what changed.
    """
    wanted: dict[str, str] = {}
    for key in CHANNELS:
        name = ":CHAN" + key[2:]
        wanted[name + ":DISP"] = "ON" if settings.enabled[key] else "OFF"
        if not settings.enabled[key]:
            continue
        # The probe first: the scope scales what it has by it when it changes.
        # A current probe is 1x to the scope, which is told its volts.
        probe = settings.probe[key]
        wanted[name + ":PROB"] = str(probe.told)
        wanted[name + ":COUP"] = settings.coupling[key]
        wanted[name + ":SCAL"] = f"{probe.at_scope(settings.scale[key]):g}"
        wanted[name + ":OFFS"] = f"{probe.at_scope(settings.offset[key]):g}"
        wanted[name + ":BWL"] = "20M" if settings.limit[key] else "OFF"
    wanted[":ACQ:TYPE"] = settings.acquire
    wanted[":TIM:MAIN:SCAL"] = f"{settings.time_div:g}"
    # The scope's offset is where the middle of its screen is, measured from
    # the trigger: nought has the trigger in the middle.
    position = trigger.position if waits(settings, trigger) else 0.5
    wanted[":TIM:MAIN:OFFS"] = f"{(0.5 - position) * ACROSS * settings.time_div:g}"
    if waits(settings, trigger):
        wanted.update(_trigger_setup(settings, trigger))
    return wanted


#: A lower limit and its upper, which the scope will not have the wrong way round.
LIMITS = (
    (":TRIG:PULS:LWID", ":TRIG:PULS:UWID"),
    (":TRIG:RUNT:BLEV", ":TRIG:RUNT:ALEV"),
    (":TRIG:WIND:BLEV", ":TRIG:WIND:ALEV"),
    (":TRIG:DUR:TLOW", ":TRIG:DUR:TUPP"),
)


def _in_order(changed: list[tuple[str, str]], wanted: dict[str, str]) -> list[tuple[str, str]]:
    """What changed, with each pair of limits sent upper, lower, upper.

    The scope refuses a lower limit above the upper it has, or an upper below
    the lower, and which it has may be anything. Upper, lower and upper again
    ends with both as wanted, whatever they were: one of the three may be
    refused on the way, and nothing is asked about it -- a DS1000Z's link can
    lock up when what it refused is asked about.
    """
    ordered = []
    for what, to in changed:
        pair = next((pair for pair in LIMITS if what in pair), None)
        if pair is None:
            ordered.append((what, to))
        elif not any(done in pair for done, _to in ordered):
            lower, upper = pair
            if lower in wanted and upper in wanted:
                ordered += [(upper, wanted[upper]), (lower, wanted[lower]), (upper, wanted[upper])]
            else:
                ordered.append((what, to))
    return ordered


# --- the wire -------------------------------------------------------------------------------
class Link:
    """Lines of SCPI to the scope and back, on a socket."""

    def __init__(self, host: str, port: int) -> None:
        try:
            self._socket = socket.create_connection((host, port), timeout=CONNECT_S)
        except OSError as exc:
            raise ScopeError(
                f"No scope answered at {host}, port {port}: {exc}. Check the address against "
                "Utility > IO > LAN Conf on the scope, and that it is on this network."
            ) from exc
        self._socket.settimeout(ANSWER_S)
        self._socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._file = self._socket.makefile("rb")

    def write(self, command: str) -> None:
        try:
            self._socket.sendall(command.encode("ascii") + b"\n")
        except OSError as exc:
            raise ScopeError(f"The scope stopped answering: {exc}.") from exc

    def ask(self, command: str) -> str:
        self.write(command)
        try:
            line = self._file.readline()
        except OSError as exc:
            raise ScopeError(f"The scope did not answer {command}: {exc}.") from exc
        if not line:
            raise ScopeError("The scope closed the connection.")
        return line.decode("ascii", "replace").strip()

    def ask_bytes(self, command: str) -> bytes:
        """The answer to a query that comes as a block: #, how many digits, how many bytes."""
        self.write(command)
        try:
            head = self._file.read(2)
            if len(head) < 2 or head[:1] != b"#" or not head[1:].isdigit():
                raise ScopeError(f"The scope answered {command} with something else: {head!r}.")
            length = int(self._file.read(int(head[1:])))
            data = self._file.read(length)
            self._file.readline()  # the end of the line after it
        except (OSError, ValueError) as exc:
            raise ScopeError(f"The scope did not answer {command}: {exc}.") from exc
        if len(data) < length:
            raise ScopeError("The scope closed the connection.")
        return data

    def close(self) -> None:
        for closing in (self._file, self._socket):
            try:
                closing.close()
            except OSError:
                pass


def find_usb(listed: tuple[str, ...], wanted: str) -> str | None:
    """Which of the USB instruments a VISA library lists is the scope asked for:
    by its serial number, or the first of Rigol's."""
    return visa.find(listed, wanted, MAKER)


class NotReadyError(Exception):
    """The scope says it has stopped, and has no sweep to hand over yet."""


class Scope:
    """One scope, from connecting to it to letting go. Used from one thread."""

    def __init__(self, settings: Settings, clock=time.monotonic, sleep=time.sleep) -> None:
        self._sleep = sleep
        self.settings = settings
        self.trigger = Trigger()
        self._clock = clock
        self._link: Link | visa.VisaLink | None = None
        #: What the scope said it is.
        self.model = ""
        self.running = False
        #: (text, whether it is a warning), for whoever is listening.
        self.notes: list[tuple[str, bool]] = []
        #: Settings and a trigger asked for while it runs, taken up between
        #: two looks. Set from another thread, which is safe for one reference.
        self.wanted: Settings | None = None
        self.wanted_trigger: Trigger | None = None
        #: Asked during a long read: whether to give it up.
        self.interrupted = lambda: False
        self._sent: dict[str, str] = {}
        self._armed_at = 0.0
        self._forced = False
        self._said_reading = False
        #: Whether the scope's beeper was on before it was silenced here.
        self._beeper_silenced = False
        #: When it was last asked anything, stopped: see check_there.
        self._heard = 0.0

    # --- opening ---------------------------------------------------------------------------
    def open(self) -> None:
        if self.settings.usb:
            self._link = traced(visa.VisaLink(self.settings.usb_device, MAKER), "Rigol USB")
            where = "on USB"
            self.notes.append((f"On USB: {self._link.name}.", False))
        elif not self.settings.host:
            raise ScopeError(
                "No address to connect to. Put the scope's address in the Instrument pane: "
                "it shows it under Utility > IO > LAN Conf. Or choose USB."
            )
        else:
            self._link = traced(
                Link(self.settings.host, self.settings.port), f"Rigol {self.settings.host}"
            )
            where = f"at {self.settings.host}"
        said = self._link.ask("*IDN?")
        self._heard = self._clock()
        parts = [part.strip() for part in said.split(",")]
        if len(parts) < 4:
            raise ScopeError(f"What answered {where} is not a scope: {said!r}.")
        self.model = parts[1]
        self.notes.append(
            (f"{parts[0]} {parts[1]}, serial {parts[2]}, firmware {parts[3]}.", False)
        )
        # DS1054Z, DS1104Z-S, MSO1074Z: not the older DS1052E, which speaks differently.
        if not self.model.startswith(("DS1", "MSO1")) or "Z" not in self.model:
            self.notes.append(
                (
                    f"This was written for the DS1000Z scopes, and a {self.model} "
                    "may not understand all of it.",
                    True,
                )
            )

    # --- running ---------------------------------------------------------------------------
    def start(self, settings: Settings, trigger: Trigger) -> None:
        self.settings, self.trigger = settings, trigger
        self._said_reading = False
        self._set_up()
        self.running = True
        self._arm()

    def _set_up(self) -> None:
        """Send whatever of the setup is not what was last sent."""
        wanted = setup(self.settings, self.trigger)
        changed = [(what, to) for what, to in wanted.items() if self._sent.get(what) != to]
        for what, to in _in_order(changed, wanted):
            # A pattern's level is said of a channel: "...:LEV CHAN1,0.5".
            self._link.write(f"{what}{to}" if what.endswith(",") else f"{what} {to}")
        self._sent.update(wanted)
        if changed:
            # Answered once all of it has been done: nothing is read before then.
            self._link.ask("*OPC?")
        mode = wanted.get(":TRIG:MODE", "EDGE")
        if mode != "EDGE" and any(what == ":TRIG:MODE" for what, _to in changed):
            # One without the advanced triggers option keeps the type it had.
            if self._link.ask(":TRIG:MODE?") != mode:
                self._sent.pop(":TRIG:MODE", None)
                raise ScopeError(
                    "The scope would not take that type of trigger: runt, window and "
                    "timeout are among Rigol's advanced triggers, an option on a DS1000Z."
                )

    def _arm(self) -> None:
        self._link.write(":SING")
        self._armed_at = self._clock()
        self._forced = False

    def stop(self) -> None:
        if self.running and self._link is not None:
            try:
                # Not left waiting for a trigger with nobody to read it.
                self._link.write(":STOP")
            except ScopeError:
                pass
        self._unsilence()
        self.running = False
        self._heard = self._clock()

    def check_there(self) -> None:
        """ScopeError if it has been stopped a while and does not say who it is
        when asked. Running, it is never asked: it is answering already."""
        if self.running or self._link is None or self._clock() - self._heard < CHECK_S:
            return
        try:
            self._link.ask("*IDN?")
        except ScopeError as exc:
            raise ScopeError(
                "The Rigol stopped answering and has been closed: it may have been switched "
                f"off or unplugged. Press Open once it is back. ({exc})"
            ) from exc
        self._heard = self._clock()

    def poll(self) -> Block | None:
        """The next sweep, if the scope has taken one."""
        if self.wanted is not None or self.wanted_trigger is not None:
            settings, self.wanted = self.wanted or self.settings, None
            trigger, self.wanted_trigger = self.wanted_trigger or self.trigger, None
            self.settings, self.trigger = settings, trigger
            self._set_up()
            self._arm()
            return None
        waited = self._clock() - self._armed_at
        if waited < SETTLE_S:
            return None
        if self._link.ask(":TRIG:STAT?") != "STOP":
            trigger = self.trigger
            give_up = AUTO_S + ACROSS * self.settings.time_div
            if (
                (trigger.auto or not waits(self.settings, trigger))
                and not self._forced
                and (waited > give_up)
            ):
                self._link.write(":TFOR")
                self._forced = True
            return None
        try:
            block = self._read()
        except GivenUpError:
            return None
        except NotReadyError:
            if waited > NOT_READY_S:
                # It stopped with nothing taken, and is not going to take it now.
                self._arm()
            return None
        self._arm()
        return block

    def _read(self) -> Block:
        settings, link = self.settings, self._link
        data: dict[str, np.ndarray] = {}
        rate, at = 0.0, None
        for key in settings.keys():
            link.write(f":WAV:SOUR CHAN{key[2:]}")
            link.write(":WAV:MODE RAW" if settings.memory else ":WAV:MODE NORM")
            link.write(":WAV:FORM BYTE")
            # format, type, points, count, x increment, x origin, x reference,
            # y increment, y origin, y reference
            preamble = link.ask(":WAV:PRE?").split(",")
            try:
                points = int(float(preamble[2]))
                x_step, x_origin = float(preamble[4]), float(preamble[5])
                y_step, y_origin, y_reference = (float(p) for p in preamble[7:10])
            except (IndexError, ValueError) as exc:
                raise ScopeError(f"The scope described its waveform oddly: {preamble}.") from exc
            if points <= 0 or x_step <= 0:
                # It says it has stopped a moment before it has anything to show.
                raise NotReadyError
            if settings.memory:
                raw = self._read_memory(points)
            else:
                # Said every time: the scope remembers which piece of its memory
                # was last asked for, and hands over that much of the screen.
                link.write(":WAV:STAR 1")
                link.write(f":WAV:STOP {points}")
                raw = link.ask_bytes(":WAV:DATA?")
            counts = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
            # Volts at the probe's tip; amps, through a current probe.
            y_step *= settings.probe[key].from_scope
            data[key] = (counts - (y_origin + y_reference)) * np.float32(y_step)
            rate = 1.0 / x_step
            # Nought on the scope's time axis is its trigger.
            at = round(-x_origin / x_step)
        shortest = min((len(samples) for samples in data.values()), default=0)
        if not shortest:
            raise ScopeError("The scope sent a sweep with nothing in it.")
        data = {key: samples[:shortest] for key, samples in data.items()}
        if not self._said_reading:
            self._said_reading = True
            self.notes.append(
                (f"Sweeps of {shortest} points at {rate:,.0f} a second, from each channel.", False)
            )
        if not waits(settings, self.trigger) or at is None or not 0 <= at < shortest:
            return Block(0, rate, data, sweep=True)
        return Block(0, rate, data, sweep=True, trigger=at, triggered=not self._forced)

    def _silence(self) -> None:
        """Turn the scope's beeper off while its memory is read.

        After each piece it says "Can Operate Now!" and beeps: two dozen
        times for a deep memory, every sweep. Put back when the run stops.
        """
        if not self._beeper_silenced and self._link.ask(":SYST:BEEP?") in ("1", "ON"):
            self._link.write(":SYST:BEEP OFF")
            self._beeper_silenced = True

    def _unsilence(self) -> None:
        if self._beeper_silenced and self._link is not None:
            self._beeper_silenced = False
            try:
                # Not at once: the scope has one more "Can Operate Now!" to
                # say after the last piece, and would beep with it.
                self._sleep(QUIET_S)
                self._link.write(":SYST:BEEP ON")
            except ScopeError:
                pass

    def _read_memory(self, points: int) -> bytes:
        self._silence()
        parts = []
        for first in range(1, points + 1, CHUNK):
            if self.interrupted():
                raise GivenUpError
            last = min(first + CHUNK - 1, points)
            # In an order that never has the start past the stop: the scope
            # moves the other end to suit, and beeps as it does.
            if first == 1:
                self._link.write(":WAV:STAR 1")
                self._link.write(f":WAV:STOP {last}")
            else:
                self._link.write(f":WAV:STOP {last}")
                self._link.write(f":WAV:STAR {first}")
            parts.append(self._link.ask_bytes(":WAV:DATA?"))
        return b"".join(parts)

    def close(self) -> None:
        self._unsilence()
        if self._link is not None:
            self._link.close()
        self._link = None
        self.running = False


class _Reader(QThread):
    """The thread that owns the connection, from making it to closing it."""

    #: The run it belongs to, and the block.
    block = Signal(int, object)
    note = Signal(str)
    warning = Signal(str)
    failed = Signal(str)
    opened = Signal(str)
    started_run = Signal(int)
    stopped_run = Signal(int)

    def __init__(self, scope: Scope, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._scope = scope
        self._asked: queue.SimpleQueue = queue.SimpleQueue()
        scope.interrupted = lambda: not self._asked.empty()

    def ask(self, *command) -> None:
        """("start", settings, run, trigger), ("stop",) or ("close",): done in the order asked."""
        self._asked.put(command)

    def _say(self) -> None:
        notes, self._scope.notes = self._scope.notes, []
        for text, is_warning in notes:
            (self.warning if is_warning else self.note).emit(text)

    def run(self) -> None:
        scope = self._scope
        run = 0
        try:
            scope.open()
            self._say()
            self.opened.emit(scope.model)
            while True:
                try:
                    command = self._asked.get(timeout=POLL_S if scope.running else IDLE_S)
                except queue.Empty:
                    command = None
                if command is None:
                    scope.check_there()
                if command is not None:
                    if command[0] == "close":
                        break
                    was_running = scope.running
                    scope.stop()
                    if was_running:
                        self.stopped_run.emit(run)
                    if command[0] == "start":
                        run = command[2]
                        scope.start(command[1], command[3])
                        self._say()
                        self.started_run.emit(run)
                    continue
                if scope.running:
                    block = scope.poll()
                    if block is not None:
                        self.block.emit(run, block)
                    self._say()
        except ScopeError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # report, never die: nothing else would say why
            self.failed.emit(f"Rigol scope: {type(exc).__name__}: {exc}")
        finally:
            self._say()
            scope.close()


class Rigol1000Z(Instrument):
    SETTINGS = SETTINGS

    def __init__(self, parent: QObject | None = None, options: dict | None = None) -> None:
        super().__init__(parent)
        self.settings = Settings(options)
        self._options = dict(options) if isinstance(options, dict) else {}
        self._reader: _Reader | None = None
        self._scope: Scope | None = None
        self._is_open = False
        self._running = False
        #: Which run the blocks that count belong to: one more at each start.
        self._run = 0
        self._trigger = Trigger()
        #: The rate of the last sweep, which follows from the scope's timebase.
        self._sweep_rate = 0.0

    @property
    def sweeps(self) -> bool:
        return True

    def diagnostics(self) -> list[str]:
        """How it is reached, and what answered."""
        settings = self.settings
        where = (
            f"USB, {settings.usb_device or 'the first Rigol found'}"
            if settings.usb
            else f"network, {settings.host or 'no address'} port {settings.port}"
        )
        scope = self._scope
        said = scope.model if scope is not None and scope.model else "not opened"
        return [f"connection: {where}", f"scope: {said}; sweeps at {self._sweep_rate:,.0f} S/s"]

    def triggers_itself(self, condition: Condition, source: str | None) -> bool:
        return triggers_itself(condition, source, self.settings.keys())

    def set_trigger(
        self,
        source: str | None,
        level: float,
        rising: bool,
        position: float,
        auto: bool,
        condition: Condition | None = None,
    ) -> None:
        if condition is None or not self.triggers_itself(condition, source):
            condition = Condition()
        wanted = Trigger(source, level, rising, position, auto, condition)
        if wanted == self._trigger:
            return
        self._trigger = wanted
        if self._running and self._scope is not None:
            self._scope.wanted_trigger = wanted

    def set(self, key: str, value: object) -> None:
        self._options[key] = value
        self.settings = Settings(self._options)
        if self._running and self._scope is not None:
            self._scope.wanted = self.settings

    def channels(self) -> list[Channel]:
        return [
            Channel(
                key,
                key,
                unit=self.settings.probe[key].unit,
                full_scale=self.settings.scale[key] * UP / 2,
                # The offset moves nought up the screen: the middle is minus it.
                middle=-self.settings.offset[key],
                detail=self._detail(key),
                group=f"Channel {key[2:]}",
                colour=COLOURS.get(key, ""),
            )
            for key in self.settings.keys()
        ]

    def _detail(self, key: str) -> str:
        settings = self.settings
        probe = settings.probe[key]
        said = (
            f"{probes.per_division(settings.scale[key], probe.unit)}, {probe.label()}, "
            f"{settings.coupling[key]}"
        )
        if settings.limit[key]:
            said += ", 20 MHz"
        if settings.offset[key]:
            said += f", offset {settings.offset[key]:g} {probe.unit}"
        return said

    @property
    def rate(self) -> float:
        return self._sweep_rate or SCREEN_POINTS / (ACROSS * self.settings.time_div)

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
        self._scope = Scope(self.settings)
        reader = _Reader(self._scope, self)
        reader.block.connect(self._on_block)
        reader.note.connect(self.note)
        reader.warning.connect(self.warning)
        reader.failed.connect(self.error)
        reader.opened.connect(self._on_opened)
        reader.started_run.connect(self._on_started)
        reader.stopped_run.connect(self._on_stopped)
        reader.finished.connect(self._on_finished)
        self._reader = reader
        reader.start()

    def close(self) -> None:
        if self._reader is None:
            return
        self._reader.ask("close")
        self._reader.wait(int((CONNECT_S + ANSWER_S) * 1000) + 2000)

    def _on_opened(self, _model: str) -> None:
        self._is_open = True
        self.opened_changed.emit(True)

    def _on_finished(self) -> None:
        """The thread has gone: the connection is closed, however that came about."""
        was_running, was_open = self._running, self._is_open
        self._running = self._is_open = False
        if was_running:
            self.state_changed.emit(False)
        if was_open:
            self.note.emit("Rigol scope closed.")
        self.opened_changed.emit(False)

    # --- running ---------------------------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self.open()
        self._run += 1
        self._running = True
        self._sweep_rate = 0.0
        # Nothing asked for before now is still waiting: this start carries it all.
        self._scope.wanted = self._scope.wanted_trigger = None
        self._reader.ask("start", self.settings, self._run, self._trigger)

    def stop(self) -> None:
        if not self._running or self._reader is None:
            return
        self._running = False
        self._reader.ask("stop")
        self.state_changed.emit(False)

    def _on_block(self, run: int, block: Block) -> None:
        if run == self._run and self._running:
            self._sweep_rate = block.rate
            self.block.emit(block)

    def _on_started(self, run: int) -> None:
        if run == self._run:
            self.state_changed.emit(True)

    def _on_stopped(self, run: int) -> None:
        if run == self._run and self._running:
            self._running = False
            self.state_changed.emit(False)
