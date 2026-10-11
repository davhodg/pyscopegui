# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Rigol DS1000Z scopes, over the network: the DS1054Z, and the others of the series.

The series differs in bandwidth, and in whether a model has logic inputs
(MSO, or Plus with the option) or a signal generator (-S). The four analog
channels are the same on all of them, and are what is read here.

The scope speaks SCPI as lines of text on TCP port 5555, so nothing of
Rigol's is needed and nothing is loaded: a socket is the whole of it.

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
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from pyscopegui.backends.base import Block, Channel, Instrument, Setting

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
IDLE_S = 0.1


class ScopeError(Exception):
    """The scope could not be reached, or stopped answering. In words for the Event Log."""


class GivenUpError(Exception):
    """A read was abandoned part way, because something else was asked for."""


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
PROBES = (1, 10, 100)
COUPLINGS = (("DC", "DC"), ("AC", "AC"), ("GND", "Ground"))


def make_settings() -> tuple[Setting, ...]:
    made = [
        Setting(
            "address",
            "Address",
            "",
            group="Connection",
            tip=(
                "The scope's address on the network, as it shows under\n"
                "Utility > IO > LAN Conf: 192.168.1.50. Taken up at the next Open."
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
                tip="Added to the signal before it is drawn: it moves nought volts up the screen.",
            ),
            Setting(
                f"coupling_{number}", "Coupling", "DC", choices=COUPLINGS, group=group, live=True
            ),
            Setting(
                f"probe_{number}",
                "Probe",
                10,
                choices=tuple((p, f"{p}x") for p in PROBES),
                group=group,
                live=True,
                tip="What the probe divides by, as its switch says.",
            ),
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
        self.memory = options.get("read") == MEMORY
        self.time_div = _nearest(options.get("time_div"), TIMES, 1e-3)
        self.enabled: dict[str, bool] = {}
        self.scale: dict[str, float] = {}
        self.offset: dict[str, float] = {}
        self.coupling: dict[str, str] = {}
        self.probe: dict[str, int] = {}
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
        wanted[name + ":PROB"] = str(settings.probe[key])
        wanted[name + ":COUP"] = settings.coupling[key]
        wanted[name + ":SCAL"] = f"{settings.scale[key]:g}"
        wanted[name + ":OFFS"] = f"{settings.offset[key]:g}"
    wanted[":TIM:MAIN:SCAL"] = f"{settings.time_div:g}"
    # The scope's offset is where the middle of its screen is, measured from
    # the trigger: nought has the trigger in the middle.
    position = trigger.position if trigger.source is not None else 0.5
    wanted[":TIM:MAIN:OFFS"] = f"{(0.5 - position) * ACROSS * settings.time_div:g}"
    if trigger.source in CHANNELS and settings.enabled[trigger.source]:
        wanted[":TRIG:MODE"] = "EDGE"
        wanted[":TRIG:EDG:SOUR"] = "CHAN" + trigger.source[2:]
        wanted[":TRIG:EDG:SLOP"] = "POS" if trigger.rising else "NEG"
        wanted[":TRIG:EDG:LEV"] = f"{trigger.level:g}"
    return wanted


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


class NotReadyError(Exception):
    """The scope says it has stopped, and has no sweep to hand over yet."""


class Scope:
    """One scope, from connecting to it to letting go. Used from one thread."""

    def __init__(self, settings: Settings, clock=time.monotonic) -> None:
        self.settings = settings
        self.trigger = Trigger()
        self._clock = clock
        self._link: Link | None = None
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

    # --- opening ---------------------------------------------------------------------------
    def open(self) -> None:
        if not self.settings.host:
            raise ScopeError(
                "No address to connect to. Put the scope's address in the Instrument pane: "
                "it shows it under Utility > IO > LAN Conf."
            )
        self._link = Link(self.settings.host, self.settings.port)
        said = self._link.ask("*IDN?")
        parts = [part.strip() for part in said.split(",")]
        if len(parts) < 4:
            raise ScopeError(f"What answered at {self.settings.host} is not a scope: {said!r}.")
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
        for what, to in changed:
            self._link.write(f"{what} {to}")
        self._sent.update(wanted)
        if changed:
            # Answered once all of it has been done: nothing is read before then.
            self._link.ask("*OPC?")

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
        self.running = False

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
            if (trigger.auto or trigger.source is None) and not self._forced and waited > give_up:
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
        if self.trigger.source is None or at is None or not 0 <= at < shortest:
            return Block(0, rate, data, sweep=True)
        return Block(0, rate, data, sweep=True, trigger=at, triggered=not self._forced)

    def _read_memory(self, points: int) -> bytes:
        parts = []
        for first in range(1, points + 1, CHUNK):
            if self.interrupted():
                raise GivenUpError
            self._link.write(f":WAV:STAR {first}")
            self._link.write(f":WAV:STOP {min(first + CHUNK - 1, points)}")
            parts.append(self._link.ask_bytes(":WAV:DATA?"))
        return b"".join(parts)

    def close(self) -> None:
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
        return [
            Channel(
                key,
                key,
                full_scale=self.settings.scale[key] * UP / 2,
                detail=self._detail(key),
                group=f"Channel {key[2:]}",
            )
            for key in self.settings.keys()
        ]

    def _detail(self, key: str) -> str:
        settings = self.settings
        said = (
            f"{_engineering(settings.scale[key], 'V/div')}, {settings.probe[key]}x, "
            f"{settings.coupling[key]}"
        )
        if settings.offset[key]:
            said += f", offset {settings.offset[key]:g} V"
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
