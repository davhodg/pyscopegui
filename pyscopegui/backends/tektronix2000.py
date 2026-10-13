# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Tektronix TDS200, TDS1000, TDS2000 and TPS2000 scopes, over a serial port.

One family, with one set of commands: lines of text, answered in text, and a
waveform as a block of bytes. They differ in how many channels they have and
in what they are plugged in by. The TPS2000 has an RS-232 port of its own and
the older TDS scopes have one on a module; that is what is used here, through
pyserial. The commands and the port are kept apart, so that another way in
-- USB, on the later models -- has only the port to bring.

A waveform is 2500 points, and RS-232 is slow: about three seconds a channel
at 9600 baud. So this is for taking a capture off the scope, not for
watching one. Like any scope that triggers itself it sends sweeps, each a
capture complete in itself.

Two ways of reading. The scope can be set up from here and made to take one
sweep after another. Or it can be left exactly as it is, and what is on its
screen read off: the way to fetch something that was captured at the bench.
"""

from __future__ import annotations

import queue
import re
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from pyscopegui.backends.base import Block, Channel, Instrument, Setting

CHANNELS = ("CH1", "CH2", "CH3", "CH4")
#: Divisions on the screen: across, and up.
ACROSS = 10
UP = 8
POINTS = 2500

#: Seconds to wait for an answer to a question, and for a waveform, which at
#: the slowest speed the scope has is most of a minute by itself.
ANSWER_S = 3.0
#: Seconds the scope may take over one setting. It takes each in turn, and
#: most of a second for some, so a question asked after twenty of them is
#: not answered for a long while.
SETTING_S = 1.5
WAVEFORM_BITS = (POINTS + 16) * 10

SET_UP = "set"
AS_IS = "asis"
SAMPLE, PEAK, AVERAGE = "SAMPLE", "PEAKDETECT", "AVERAGE"

#: Seconds between two looks at whether it has taken its sweep, and between
#: two looks at whether anything has been asked while it is not running.
POLL_S = 0.2
IDLE_S = 0.1
#: How near the trigger the signal has to cross the level, in samples, for
#: the sweep to count as triggered and not as taken because nothing came.
NEAR_TRIGGER = 3


class ScopeError(Exception):
    """The scope could not be reached, or stopped answering. In words for the Event Log."""


# --- the settings ---------------------------------------------------------------------------
def _engineering(value: float, unit: str) -> str:
    for scale, prefix in ((1.0, ""), (1e-3, "m"), (1e-6, "u"), (1e-9, "n")):
        if value >= scale * 0.999:
            return f"{value / scale:g} {prefix}{unit}"
    return f"{value:g} {unit}"


#: Seconds a division: 1, 2.5 and 5 in each power of ten, from 5 ns to 50 s.
TIMES = tuple(
    round(m * 10.0**e, 10) for e in range(-9, 2) for m in (1, 2.5, 5) if 5e-9 <= m * 10.0**e <= 50
)
PROBES = (1, 10, 100, 1000)
#: Volts a division as the screen shows them, probe and all: 2 mV to 5 V
#: through a 1x probe, and so on up through the others.
SCALES = tuple(
    sorted({round(m * 10.0**e, 4) for e in range(-3, 4) for m in (1, 2, 5) if m * 10.0**e >= 2e-3})
)
COUPLINGS = (("DC", "DC"), ("AC", "AC"), ("GND", "Ground"))
BAUDS = (19200, 9600, 4800, 2400, 1200, 600, 300)
NO_FLOW, HARD_FLOW = "none", "hard"
#: What the scope ends each answer with, by the name its menu gives it.
ENDS = {"LF": b"\n", "CR": b"\r", "CR/LF": b"\r\n", "LF/CR": b"\n\r"}
#: Parity, by the name the scope's menu gives it -> the letter pyserial knows it by.
PARITIES = {"None": "N", "Even": "E", "Odd": "O"}
_AS_THE_SCOPE = "As the scope is set, under Utility > Options > RS232 Setup."
ACQUISITIONS = ((SAMPLE, "Sample"), (PEAK, "Peak detect"), (AVERAGE, "Average"))
AVERAGES = (4, 16, 64, 128)

_ONLY_SET_UP = "\nUsed when the scope is set up from here, and not when it is read as it is."


def serial_ports() -> list[tuple[str, str]]:
    """The serial ports there are now, as (name, what to call it in a list).

    Nothing where pyserial is not installed: opening says so.
    """
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    found = []
    for port in sorted(list_ports.comports(), key=lambda port: port.device):
        said = port.description or ""
        # Windows describes a port with its name at the end, which is said already.
        if said and said != "n/a" and said != port.device:
            found.append((port.device, f"{port.device}   {said}"))
        else:
            found.append((port.device, port.device))
    return found


def make_settings(channels: int = 4) -> tuple[Setting, ...]:
    """The settings to offer for a scope with this many channels."""
    made = [
        Setting(
            "port",
            "Port",
            "",
            group="Connection",
            closed=True,
            found=serial_ports,
            empty="Choose a port",
            tip=(
                "The serial port the scope is on. The list is of the ports there are\n"
                "now; a name can be typed too: COM3 on Windows, /dev/ttyUSB0 on\n"
                "Linux. Changed while the scope is closed."
            ),
        ),
        Setting(
            "baud",
            "Speed",
            9600,
            choices=tuple((baud, f"{baud} baud") for baud in BAUDS),
            group="Connection",
            closed=True,
            tip=(
                "As the scope is set, under Utility > Options > RS232 Setup. The\n"
                "fastest it has is the one to choose, on the scope and here.\n"
                "Changed while the scope is closed."
            ),
        ),
        Setting(
            "flow",
            "Flow control",
            HARD_FLOW,
            choices=((HARD_FLOW, "Hard flagging (RTS/CTS)"), (NO_FLOW, "None")),
            group="Connection",
            closed=True,
            tip=(
                "As the scope is set, under Utility > Options > RS232 Setup. Hard\n"
                "flagging needs a cable with all its wires. Soft flagging is not\n"
                "offered: a waveform is sent as bytes that it would mistake for\n"
                "its own. Changed while the scope is closed."
            ),
        ),
        Setting(
            "parity",
            "Parity",
            "None",
            choices=tuple((name, name) for name in PARITIES),
            group="Connection",
            closed=True,
            tip=_AS_THE_SCOPE + "\nChanged while the scope is closed.",
        ),
        Setting(
            "eol",
            "End of line",
            "LF",
            choices=tuple((name, name) for name in ENDS),
            group="Connection",
            closed=True,
            tip=(
                _AS_THE_SCOPE + " It is what the scope ends each\n"
                "answer with, and an answer is waited for until it comes.\n"
                "Changed while the scope is closed."
            ),
        ),
        Setting(
            "read",
            "Reading",
            SET_UP,
            choices=((SET_UP, "Set it up, and take sweeps"), (AS_IS, "What it shows, as it is")),
            group="Sampling",
            tip=(
                "Set up from here, the scope is put as this pane says and takes one\n"
                "sweep after another. As it is, nothing on the scope is changed and\n"
                "what is on its screen is read off: for fetching something that\n"
                "was captured at the bench."
            ),
        ),
        Setting(
            "time_div",
            "Time",
            1e-3,
            choices=tuple((t, _engineering(t, "s/div")) for t in TIMES),
            group="Sampling",
            live=True,
            needs=("read", SET_UP),
            tip="Seconds a division, of the ten across the scope's screen.",
        ),
        Setting(
            "acquire",
            "Acquisition",
            SAMPLE,
            choices=ACQUISITIONS,
            group="Sampling",
            live=True,
            needs=("read", SET_UP),
            tip=(
                "How the scope makes each point. Sample keeps one sample for each.\n"
                "Peak detect keeps the lowest and highest, so nothing narrow is\n"
                "missed. Average takes several sweeps and averages them, which is\n"
                "quieter and needs a signal that repeats."
            ),
        ),
        Setting(
            "averages",
            "Averages",
            16,
            choices=tuple((count, str(count)) for count in AVERAGES),
            group="Sampling",
            live=True,
            needs=("acquire", AVERAGE),
            tip="How many sweeps go into each average.",
        ),
    ]
    for number in range(1, channels + 1):
        group = f"Channel {number}"
        made += [
            Setting(
                f"enabled_{number}",
                "Enabled",
                number == 1,
                group=group,
                tip=(
                    f"Whether channel {number} is read. Set up from here, it is also\n"
                    "switched on or off on the scope."
                ),
            ),
            Setting(
                f"scale_{number}",
                "Scale",
                1.0,
                choices=tuple((v, _engineering(v, "V/div")) for v in SCALES),
                group=group,
                live=True,
                needs=("read", SET_UP),
                tip=(
                    "Volts a division, of the eight up the scope's screen, with the probe counted."
                    + _ONLY_SET_UP
                ),
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
                needs=("read", SET_UP),
                tip=(
                    "Added to the signal before it is drawn: it moves nought volts up the screen."
                    + _ONLY_SET_UP
                ),
            ),
            Setting(
                f"coupling_{number}",
                "Coupling",
                "DC",
                choices=COUPLINGS,
                group=group,
                live=True,
                needs=("read", SET_UP),
            ),
            Setting(
                f"limit_{number}",
                "20 MHz limit",
                False,
                group=group,
                live=True,
                needs=("read", SET_UP),
                tip="Leave out what is above 20 MHz, which for a slow signal is noise.",
            ),
            Setting(
                f"probe_{number}",
                "Probe",
                10,
                choices=tuple((p, f"{p}x") for p in PROBES),
                group=group,
                live=True,
                needs=("read", SET_UP),
                tip="What the probe divides by, as its switch says." + _ONLY_SET_UP,
            ),
        ]
    return tuple(made)


SETTINGS = make_settings()


def channels_of(model: str) -> int:
    """How many channels a model has: four where its number ends in 4, and two otherwise.

    TDS224, TDS2014, TDS2024, TPS2014 and TDS2004B have four; TDS210, TDS1002,
    TDS2012, TPS2012 and TDS1001B have two.
    """
    digits = re.findall(r"\d+", model)
    return 4 if digits and digits[-1].endswith("4") else 2


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
        self.port = str(options.get("port") or "").strip()
        self.baud = int(_nearest(options.get("baud"), BAUDS, 9600))
        self.hard_flow = options.get("flow") != NO_FLOW
        self.parity = PARITIES.get(options.get("parity"), "N")
        #: What the scope ends each answer with.
        self.eol = ENDS.get(options.get("eol"), b"\n")
        #: Read what the scope shows, and change nothing on it.
        self.as_is = options.get("read") == AS_IS
        self.time_div = _nearest(options.get("time_div"), TIMES, 1e-3)
        acquire = options.get("acquire")
        self.acquire = acquire if acquire in dict(ACQUISITIONS) else SAMPLE
        self.averages = int(_nearest(options.get("averages"), AVERAGES, 16))
        self.enabled: dict[str, bool] = {}
        self.scale: dict[str, float] = {}
        self.offset: dict[str, float] = {}
        self.coupling: dict[str, str] = {}
        self.probe: dict[str, int] = {}
        self.limit: dict[str, bool] = {}
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
            self.probe[key] = int(_nearest(options.get(f"probe_{number}"), PROBES, 10))
            self.limit[key] = options.get(f"limit_{number}") is True

    def keys(self, channels: int = 4) -> list[str]:
        """The channels that are on, in order, of as many as the scope has."""
        return [key for key in CHANNELS[:channels] if self.enabled[key]]


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


def setup(settings: Settings, trigger: Trigger, channels: int = 4) -> dict[str, str]:
    """Every command that sets the scope up, as what is set -> what to.

    Kept apart like this so that a change sends only what changed.
    """
    wanted: dict[str, str] = {}
    for key in CHANNELS[:channels]:
        wanted[f"SELECT:{key}"] = "ON" if settings.enabled[key] else "OFF"
        if not settings.enabled[key]:
            continue
        # The probe first: the scope scales what it has by it when it changes.
        wanted[f"{key}:PROBE"] = str(settings.probe[key])
        wanted[f"{key}:COUPLING"] = settings.coupling[key]
        wanted[f"{key}:SCALE"] = f"{settings.scale[key]:g}"
        # The scope places a trace in divisions up the screen, not in volts.
        wanted[f"{key}:POSITION"] = f"{settings.offset[key] / settings.scale[key]:g}"
        wanted[f"{key}:BANDWIDTH"] = "ON" if settings.limit[key] else "OFF"
    wanted["ACQUIRE:MODE"] = settings.acquire
    if settings.acquire == AVERAGE:
        wanted["ACQUIRE:NUMAVG"] = str(settings.averages)
    wanted["HORIZONTAL:MAIN:SCALE"] = f"{settings.time_div:g}"
    # The scope's position is where the middle of its screen is, measured
    # from the trigger: nought has the trigger in the middle.
    position = trigger.position if trigger.source is not None else 0.5
    wanted["HORIZONTAL:MAIN:POSITION"] = f"{(0.5 - position) * ACROSS * settings.time_div:g}"
    triggered = trigger.source in CHANNELS[:channels] and settings.enabled[trigger.source]
    if triggered:
        wanted["TRIGGER:MAIN:TYPE"] = "EDGE"
        wanted["TRIGGER:MAIN:EDGE:SOURCE"] = trigger.source
        wanted["TRIGGER:MAIN:EDGE:SLOPE"] = "RISE" if trigger.rising else "FALL"
        wanted["TRIGGER:MAIN:LEVEL"] = f"{trigger.level:g}"
    # The scope gives up waiting by itself when it is told it may.
    wanted["TRIGGER:MAIN:MODE"] = "AUTO" if trigger.auto or not triggered else "NORMAL"
    return wanted


def crossed(samples: np.ndarray, at: int, level: float, rising: bool) -> bool:
    """Whether the signal goes through the level at this sample, the way asked for.

    The scope does not say whether a sweep was triggered or taken because
    nothing came, so the samples either side of where the trigger is are
    looked at instead.
    """
    before = samples[max(at - NEAR_TRIGGER, 0) : at + 1]
    after = samples[at : at + NEAR_TRIGGER + 1]
    if not len(before) or not len(after):
        return False
    if rising:
        return bool(before.min() <= level <= after.max()) and bool(before.min() < after.max())
    return bool(after.min() <= level <= before.max()) and bool(after.min() < before.max())


# --- the wire -------------------------------------------------------------------------------
def open_port(port: str, baud: int, hard_flow: bool, parity: str = "N"):
    """The serial port, opened. ImportError where pyserial is not installed."""
    import serial  # here, so that the other instruments do not need it

    return serial.Serial(
        port,
        baudrate=baud,
        # Eight, whatever the parity: a waveform is sent as whole bytes.
        bytesize=8,
        parity=parity,
        stopbits=1,
        rtscts=hard_flow,
        timeout=ANSWER_S,
        write_timeout=ANSWER_S,
    )


class Link:
    """Lines of commands to the scope and back, on a serial port."""

    def __init__(
        self, port: str, baud: int, hard_flow: bool, parity: str = "N", eol: bytes = b"\n"
    ) -> None:
        self.port, self.baud = port, baud
        self._eol = eol
        try:
            self._serial = open_port(port, baud, hard_flow, parity)
        except ImportError as exc:
            raise ScopeError(
                "A serial port needs pyserial, which is not installed: "
                "pip install pyserial, and open the scope again."
            ) from exc
        except (OSError, ValueError) as exc:
            raise ScopeError(
                f"The serial port {port} could not be opened: {exc}. Check its name, and "
                "that no other program has it."
            ) from exc
        #: Long enough for a waveform at this speed, with as much again to spare.
        self._waveform_s = max(ANSWER_S, 2 * WAVEFORM_BITS / baud)

    def _fail(self, what: str, exc: Exception | None = None) -> ScopeError:
        said = f": {exc}" if exc is not None else ""
        return ScopeError(
            f"The scope did not answer {what} on {self.port} at {self.baud} baud{said}. Check "
            "the cable, and that the speed, flow control, parity and end of line here are "
            "what the scope has under Utility > Options > RS232 Setup."
        )

    def write(self, command: str) -> None:
        try:
            self._serial.write(command.encode("ascii") + b"\n")
        except OSError as exc:  # pyserial's own errors are OSErrors
            raise self._fail(command, exc) from exc

    def ask(self, command: str, wait: float | None = None) -> str:
        """Ask, and wait for the answer: for ``wait`` seconds where the scope
        has other things to finish first."""
        self.write(command)
        before = self._serial.timeout
        if wait is not None:
            self._serial.timeout = wait
        try:
            line = self._serial.read_until(self._eol)
        except OSError as exc:
            raise self._fail(command, exc) from exc
        finally:
            self._serial.timeout = before
        if not line.endswith(self._eol):
            raise self._fail(command)
        return line.decode("ascii", "replace").strip()

    def ask_bytes(self, command: str) -> bytes:
        """The answer to a query that comes as a block: #, how many digits, how many bytes."""
        self.write(command)
        before = self._serial.timeout
        self._serial.timeout = self._waveform_s
        try:
            head = self._serial.read(2)
            if len(head) < 2:
                raise self._fail(command)
            if head[:1] != b"#" or not head[1:].isdigit():
                raise ScopeError(f"The scope answered {command} with something else: {head!r}.")
            length = int(self._serial.read(int(head[1:])))
            data = self._serial.read(length)
            self._serial.read_until(self._eol)  # the end of the line after it
        except (OSError, ValueError) as exc:
            raise self._fail(command, exc) from exc
        finally:
            self._serial.timeout = before
        if len(data) < length:
            raise self._fail(f"{command} in full")
        return data

    def clear(self) -> None:
        """Throw away whatever the scope sent that nobody asked for."""
        try:
            self._serial.reset_input_buffer()
        except OSError:
            pass

    def close(self) -> None:
        try:
            self._serial.close()
        except OSError:
            pass


class Scope:
    """One scope, from opening its port to letting go. Used from one thread."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.trigger = Trigger()
        self._link: Link | None = None
        #: What the scope said it is, and how many channels that has.
        self.model = ""
        self.channels = 4
        self.running = False
        #: (text, whether it is a warning), for whoever is listening.
        self.notes: list[tuple[str, bool]] = []
        #: Settings and a trigger asked for while it runs, taken up between
        #: two looks. Set from another thread, which is safe for one reference.
        self.wanted: Settings | None = None
        self.wanted_trigger: Trigger | None = None
        self._sent: dict[str, str] = {}
        self._said_reading = False
        #: Told what it is busy with, in a few words: everything here is slow.
        self.doing = lambda _text: None
        #: How the scope was acquiring before it was made to take single
        #: sweeps -- (stop after, running) -- to be put back when the run ends.
        self._before: tuple[str, bool] | None = None

    # --- opening ---------------------------------------------------------------------------
    def open(self) -> None:
        if not self.settings.port:
            raise ScopeError(
                "No port to open. Put the serial port the scope is on in the Instrument "
                "pane: COM3, or /dev/ttyUSB0."
            )
        settings = self.settings
        self._link = Link(
            settings.port, settings.baud, settings.hard_flow, settings.parity, settings.eol
        )
        self._link.clear()
        # Answers with nothing in front of them, whatever the scope was left at.
        self._link.write("HEADER OFF")
        said = self._link.ask("*IDN?")
        parts = [part.strip() for part in said.split(",")]
        if len(parts) < 2 or "TEK" not in parts[0].upper():
            raise ScopeError(f"What answered on {self.settings.port} is not this scope: {said!r}.")
        self.model = parts[1]
        self.channels = channels_of(self.model)
        self.notes.append((f"{parts[0]} {self.model}: {self.channels} channels.", False))
        if not re.match(r"T[DP]S ?[12]\d\d", self.model):
            self.notes.append(
                (
                    "This was written for the TDS200, TDS1000, TDS2000 and TPS2000 scopes, "
                    f"and a {self.model} may not understand all of it.",
                    True,
                )
            )

    # --- running ---------------------------------------------------------------------------
    def start(self, settings: Settings, trigger: Trigger) -> None:
        self.settings, self.trigger = settings, trigger
        self._said_reading = False
        self.running = True
        if settings.as_is:
            self.notes.append(("Reading what the scope shows, with nothing on it changed.", False))
            return
        self._set_up()
        if self._before is None:
            after = self._link.ask("ACQUIRE:STOPAFTER?")
            self._before = (after, self._link.ask("ACQUIRE:STATE?") in ("1", "RUN"))
        self._arm()

    def _put_back(self) -> None:
        """Leave the scope acquiring as it was found.

        Taking sweeps has it stop after each one, and a scope left like that
        sits with a still screen and looks as if it has hung.
        """
        if self._before is None or self._link is None:
            return
        (after, was_running), self._before = self._before, None
        try:
            self._link.write(f"ACQUIRE:STOPAFTER {after or 'RUNSTOP'}")
            if was_running:
                self._link.write("ACQUIRE:STATE RUN")
        except ScopeError:
            pass  # it has gone, and there is nothing to put back

    def _set_up(self) -> None:
        """Send whatever of the setup is not what was last sent."""
        wanted = setup(self.settings, self.trigger, self.channels)
        changed = [(what, to) for what, to in wanted.items() if self._sent.get(what) != to]
        if not changed:
            return
        if len(changed) > 3:
            self.notes.append(
                (
                    f"Setting the scope up: {len(changed)} settings, which it takes up to a "
                    "second over each.",
                    False,
                )
            )
        self.doing("setting up the scope")
        for what, to in changed:
            self._link.write(f"{what} {to}")
        self._sent.update(wanted)
        # Answered once all of it has been done, which is not soon: nothing is
        # read before then.
        self._link.ask("*OPC?", wait=ANSWER_S + SETTING_S * len(changed))

    def _arm(self) -> None:
        """Have the scope take one sweep and stop, which is its Single."""
        self._link.write("ACQUIRE:STOPAFTER SEQUENCE")
        self._link.write("ACQUIRE:STATE RUN")
        self.doing("waiting for a sweep")

    def stop(self) -> None:
        self.running = False
        self._put_back()
        self.doing("")

    def poll(self) -> Block | None:
        """The next sweep, if the scope has one."""
        if self.wanted is not None or self.wanted_trigger is not None:
            settings, self.wanted = self.wanted or self.settings, None
            trigger, self.wanted_trigger = self.wanted_trigger or self.trigger, None
            self.settings, self.trigger = settings, trigger
            if not settings.as_is:
                self._set_up()
                self._arm()
            return None
        if self.settings.as_is:
            return self._read()
        if self._link.ask("ACQUIRE:STATE?") != "0":
            return None  # still waiting for its trigger, or still averaging
        block = self._read()
        self._arm()
        return block

    def _shown(self, key: str) -> bool:
        """Whether a channel is on the scope's screen: it has no waveform to send if not."""
        return self._link.ask(f"SELECT:{key}?") in ("1", "ON")

    def _read(self) -> Block:
        settings, link = self.settings, self._link
        data: dict[str, np.ndarray] = {}
        rate, at = 0.0, None
        link.write("DATA:ENCDG RIBINARY")
        link.write("DATA:WIDTH 1")
        link.write("DATA:START 1")
        link.write(f"DATA:STOP {POINTS}")
        keys = settings.keys(self.channels)
        for number, key in enumerate(keys, start=1):
            if settings.as_is and not self._shown(key):
                continue
            self.doing(
                f"reading {key} ({number} of {len(keys)})" if len(keys) > 1 else f"reading {key}"
            )
            link.write(f"DATA:SOURCE {key}")
            try:
                x_step = float(link.ask("WFMPRE:XINCR?"))
                x_zero = float(link.ask("WFMPRE:XZERO?"))
                x_offset = float(link.ask("WFMPRE:PT_OFF?"))
                y_step = float(link.ask("WFMPRE:YMULT?"))
                y_offset = float(link.ask("WFMPRE:YOFF?"))
            except ValueError as exc:
                raise ScopeError(f"The scope described {key}'s waveform oddly: {exc}.") from exc
            if x_step <= 0:
                raise ScopeError(f"The scope described {key}'s waveform oddly: a step of {x_step}.")
            raw = np.frombuffer(link.ask_bytes("CURVE?"), dtype=np.int8).astype(np.float32)
            data[key] = (raw - np.float32(y_offset)) * np.float32(y_step)
            rate = 1.0 / x_step
            # Nought on the scope's time axis is its trigger.
            at = round(x_offset - x_zero / x_step)
        shortest = min((len(samples) for samples in data.values()), default=0)
        if not shortest:
            raise ScopeError(
                "None of the channels ticked here is on the scope's screen, so there was "
                "nothing to read."
            )
        data = {key: samples[:shortest] for key, samples in data.items()}
        if not self._said_reading:
            self._said_reading = True
            self.notes.append(
                (f"Sweeps of {shortest} points at {rate:,.0f} a second, from each channel.", False)
            )
        trigger = self.trigger
        if settings.as_is:
            # Whatever the scope triggered on is its own business: where, it says.
            if at is None or not 0 <= at < shortest:
                return Block(0, rate, data, sweep=True)
            return Block(0, rate, data, sweep=True, trigger=at, triggered=True)
        if trigger.source not in data or at is None or not 0 <= at < shortest:
            return Block(0, rate, data, sweep=True)
        triggered = not trigger.auto or crossed(
            data[trigger.source], at, trigger.level, trigger.rising
        )
        return Block(0, rate, data, sweep=True, trigger=at, triggered=triggered)

    def close(self) -> None:
        self._put_back()
        if self._link is not None:
            self._link.close()
        self._link = None
        self.running = False


class _Reader(QThread):
    """The thread that owns the port, from opening it to closing it."""

    #: The run it belongs to, and the block.
    block = Signal(int, object)
    note = Signal(str)
    warning = Signal(str)
    failed = Signal(str)
    #: How many channels the scope that answered has.
    opened = Signal(int)
    #: What the scope is busy with at this moment.
    doing = Signal(str)
    started_run = Signal(int)
    stopped_run = Signal(int)

    def __init__(self, scope: Scope, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._scope = scope
        self._asked: queue.SimpleQueue = queue.SimpleQueue()
        scope.doing = self._doing

    def _doing(self, text: str) -> None:
        # What was noted on the way is said first: it is about what led to this.
        self._say()
        self.doing.emit(text)

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
            self.opened.emit(scope.channels)
            while True:
                try:
                    command = self._asked.get(timeout=POLL_S if scope.running else IDLE_S)
                except queue.Empty:
                    command = None
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
            self.failed.emit(f"Tektronix scope: {type(exc).__name__}: {exc}")
        finally:
            self._say()
            scope.close()


class Tektronix2000(Instrument):
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
        #: How many channels the scope has, once one has answered.
        self._channels = 4
        #: The rate of the last sweep, which follows from the scope's timebase.
        self._sweep_rate = 0.0

    def settings_offered(self) -> tuple[Setting, ...]:
        return make_settings(self._channels)

    @property
    def sweeps(self) -> bool:
        return True

    def set_trigger(
        self, source: str | None, level: float, rising: bool, position: float, auto: bool
    ) -> None:
        wanted = Trigger(source, level, rising, position, auto)
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
        settings = self.settings
        return [
            Channel(
                key,
                key,
                # Read as it is, the scope's scale is its own and not known here.
                full_scale=0.0 if settings.as_is else settings.scale[key] * UP / 2,
                detail=self._detail(key),
                group=f"Channel {key[2:]}",
            )
            for key in settings.keys(self._channels)
        ]

    def _detail(self, key: str) -> str:
        settings = self.settings
        if settings.as_is:
            return "as the scope has it"
        said = (
            f"{_engineering(settings.scale[key], 'V/div')}, {settings.probe[key]}x, "
            f"{settings.coupling[key]}"
        )
        if settings.limit[key]:
            said += ", 20 MHz"
        if settings.offset[key]:
            said += f", offset {settings.offset[key]:g} V"
        return said

    @property
    def rate(self) -> float:
        return self._sweep_rate or POINTS / (ACROSS * self.settings.time_div)

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
        reader.doing.connect(self.activity)
        reader.started_run.connect(self._on_started)
        reader.stopped_run.connect(self._on_stopped)
        reader.finished.connect(self._on_finished)
        self._reader = reader
        reader.start()

    def close(self) -> None:
        if self._reader is None:
            return
        self._reader.ask("close")
        # A waveform that is on its way cannot be interrupted, and at the
        # slowest speed the scope has it is most of a minute.
        self._reader.wait(int(2 * WAVEFORM_BITS / self.settings.baud * 1000) + 10_000)

    def _on_opened(self, channels: int) -> None:
        self._is_open = True
        self._channels = channels
        self.opened_changed.emit(True)

    def _on_finished(self) -> None:
        """The thread has gone: the port is closed, however that came about."""
        was_running, was_open = self._running, self._is_open
        self._running = self._is_open = False
        if was_running:
            self.state_changed.emit(False)
        if was_open:
            self.note.emit("Tektronix scope closed.")
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
