# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""What the Python Console and a script are given: the window, and a few commands.

The commands do what the window's own controls do, through the same code, so
what a script does is shown as it happens: the Instrument pane follows a
``set``, the run buttons follow a ``run``, and the plot draws what arrives.

Everything runs on the window's thread, as the console does. An instrument
is read on a thread of its own, so a script waiting for one -- ``open``,
``single``, ``wait`` -- keeps the window going while it waits rather than
holding it still: the samples it is waiting for have to arrive through it.

These are what scripts are written against, so they are few, and each says
what went wrong in words rather than leaving a script to find out later.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QApplication

from pyscopegui import backends
from pyscopegui.core.acquire import MODES, SINGLE, STOP

#: How long ``open`` waits for an instrument to say it is open, at most.
OPEN_S = 30.0
#: How often a wait looks again.
LOOK_S = 0.005


class ScriptError(Exception):
    """Something a script asked for that cannot be done, in words."""


class Scripting:
    """The commands, bound to one window."""

    def __init__(self, window) -> None:
        self._window = window

    def names(self) -> dict:
        """Everything a console or a script starts with."""
        window = self._window
        return {
            "window": window,
            "ctx": window.ctx,
            "session": window.session,
            **{
                name: getattr(self, name)
                for name in (
                    "add",
                    "choose",
                    "open",
                    "close",
                    "set",
                    "get",
                    "run",
                    "stop",
                    "single",
                    "read",
                    "wait",
                    "trigger",
                    "channels",
                    "data",
                    "measure",
                    "maths",
                    "export_csv",
                    "export_png",
                )
            },
        }

    # --- waiting ----------------------------------------------------------------------------
    def wait(self, seconds: float) -> None:
        """Let the window and the instruments run for this long: a script's sleep.

        ``time.sleep`` would hold the window still, and the samples, answers and
        timers a script is waiting for would stop arriving with it.
        """
        self._until(lambda: False, seconds)

    def _until(self, done, seconds: float) -> bool:
        """Keep the window going until ``done()``, or until this long has gone. Whether it was."""
        deadline = time.monotonic() + seconds
        while True:
            QApplication.processEvents()
            if done():
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(LOOK_S)

    # --- which instrument -------------------------------------------------------------------
    def add(self, kind: str) -> str:
        """Add an instrument of this kind -- "rigol1000z" -- and choose it. Its name."""
        if kind not in backends.BACKENDS:
            raise ScriptError(
                f"No kind of instrument called {kind!r}: {', '.join(backends.names())}."
            )
        return self._window.add_instrument(kind)

    def choose(self, name: str) -> None:
        """Choose an instrument by name, as its tab does: what the other commands are about."""
        if not backends.known(name):
            raise ScriptError(f"No instrument called {name!r}. Those in use: {self._added()}.")
        self._window.choose(name)

    def _added(self) -> str:
        return ", ".join(self._window.added)

    def _about(self, name: str | None) -> None:
        if name is not None:
            self.choose(name)

    def open(self, name: str | None = None, timeout: float = OPEN_S) -> None:
        """Open the instrument chosen, or this one, and wait until it is."""
        self._about(name)
        window = self._window
        window.open_instrument()
        unit = window.unit
        if not self._until(lambda: unit.is_open or not unit.wanted_open, timeout):
            raise ScriptError(f"{backends.title(unit.name)} did not open in {timeout:g} s.")
        if not unit.is_open:
            raise ScriptError(
                f"{backends.title(unit.name)} would not open: the Event Log says why."
            )

    def close(self, name: str | None = None) -> None:
        """Close the instrument chosen, or this one. What is on the plot stays."""
        self._about(name)
        self._window.close_instrument()

    # --- its settings -----------------------------------------------------------------------
    def _setting(self, key: str):
        window = self._window
        unit = window.unit
        offered = window.offered(unit.name)
        for setting in offered:
            if setting.key == key:
                return setting
        keys = ", ".join(setting.key for setting in offered)
        raise ScriptError(f"{backends.title(unit.name)} has no setting {key!r}: {keys}.")

    def set(self, key: str, value: object, name: str | None = None) -> None:
        """Set one of the instrument's settings, as the Instrument pane does: "scale_1", 0.5."""
        self._about(name)
        setting = self._setting(key)
        if setting.choices and value not in [choice for choice, _label in setting.choices]:
            allowed = ", ".join(repr(choice) for choice, _label in setting.choices)
            raise ScriptError(f"{key} can be {allowed}; not {value!r}.")
        window = self._window
        window._on_setting(key, value, setting.live)
        # The pane says what it is set to now.
        window._show_settings()

    def get(self, key: str, name: str | None = None) -> object:
        """What one of the instrument's settings is: as saved, or its default."""
        self._about(name)
        setting = self._setting(key)
        saved = self._window.ctx.settings.get(f"instrument.{self._window.chosen}")
        return saved.get(key, setting.default) if isinstance(saved, dict) else setting.default

    # --- running ----------------------------------------------------------------------------
    def run(self, mode: str = "auto") -> None:
        """Press a run button: "auto", "normal", "single" or "stop". For every instrument open."""
        if mode not in MODES:
            raise ScriptError(f"No such way to run: {mode!r}. One of {', '.join(MODES)}.")
        self._window.set_mode(mode)

    def stop(self) -> None:
        """Stop every instrument. What was collected stays on the plot."""
        self._window.set_mode(STOP)

    def single(self, timeout: float = 30.0) -> bool:
        """Press Single and wait until every instrument has its capture.

        False if one had not when the time was up -- no trigger came -- and
        then they are stopped, as Stop would.
        """
        window = self._window
        window.set_mode(SINGLE)
        done = self._until(lambda: not any(u.running for u in window._in_use()), timeout)
        if not done:
            window.set_mode(STOP)
        return done

    def read(self, timeout: float = 120.0) -> bool:
        """Read what an instrument read as it is shows, once, and wait for it: Read."""
        window = self._window
        unit = window.unit
        if not window._as_is(unit):
            raise ScriptError(
                f"{backends.title(unit.name)} is not read as it is: run or single it instead."
            )
        window.read_once()
        return self._until(lambda: not unit.running, timeout)

    def trigger(
        self,
        source: str | None = "",
        level: float | None = None,
        rising: bool | None = None,
        position: float | None = None,
    ) -> None:
        """Set the chosen instrument's trigger, as the toolbar does.

        ``source`` is a channel of its own -- "CH1", "A" -- or None for no trigger;
        left out, it is left as it is. ``position`` is where the trigger sits in
        the plot, from 0 at its left to 1 at its right.
        """
        window = self._window
        # Its channels are there to choose from once it has been made, as a
        # run button makes it: a script need not have run it first.
        if window.unit.instrument is None and not window._have(window.chosen):
            raise ScriptError(
                f"{backends.title(window.chosen)} could not be started: see the Event Log."
            )
        bar = window.trigger_bar
        if source != "":
            index = bar.source.findData(source)
            if index < 0:
                index = bar.source.findText(str(source))
            if index < 0:
                found = [bar.source.itemData(i) for i in range(1, bar.source.count())]
                raise ScriptError(f"No channel {source!r} to trigger on: {found}.")
            bar.source.setCurrentIndex(index)
            bar.source.activated.emit(index)
        if rising is not None:
            bar.edge.setCurrentIndex(0 if rising else 1)
            bar.edge.activated.emit(bar.edge.currentIndex())
        if level is not None:
            bar.level.setValue(float(level))
        if position is not None:
            bar.position.setValue(round(float(position) * 100))

    # --- what was read ----------------------------------------------------------------------
    def channels(self) -> list[str]:
        """Every channel there is to read, by the name the plot gives it."""
        scope = self._window.scope
        scope.redraw()
        return list(scope._names.values())

    def data(self, channel: str) -> tuple[np.ndarray, np.ndarray]:
        """A channel's times and samples, all that is held of it, as numpy arrays.

        Times are as the plot's axis has them: from the trigger where there is
        one. ``channel`` is its name on the plot -- "Rigol CH1" -- or, for the
        instrument chosen, its own -- "CH1".
        """
        scope = self._window.scope
        scope.redraw()  # so that time is measured from where the plot has it now
        key = self._key(channel)
        unit, own = scope._owners[key]
        record = unit.capture.records[own]
        timing = scope._timings.get(unit.name)
        origin = timing.origin if timing is not None else 0.0
        times = (record.first + np.arange(record.count)) / record.rate - origin
        return times, record.view().copy()

    def measure(self, channel: str) -> dict:
        """What a channel measures, as the Measurements pane has it: between the two
        cursors, or over what is in view. Levels in the channel's unit, frequency in
        hertz, period in seconds, duty from 0 to 1; None for what it does not have."""
        scope = self._window.scope
        scope.redraw()
        measured = scope.measure(self._key(channel))
        if measured is None:
            raise ScriptError(f"{channel!r} has nothing to measure there.")
        return {
            "min": measured.minimum,
            "max": measured.maximum,
            "peak_to_peak": measured.peak_to_peak,
            "mean": measured.mean,
            "rms": measured.rms,
            "frequency": measured.frequency,
            "period": measured.period,
            "duty": measured.duty,
            "samples": measured.samples,
        }

    def maths(self, a: str, op: str, b: str) -> str:
        """Make a maths channel of the chosen instrument: maths("CH1", "-", "CH2").
        ``op`` is "+", "-", "*" or "/". The name the plot gives it."""
        from pyscopegui.core.maths import OPERATIONS, Maths

        if op not in OPERATIONS:
            raise ScriptError(f"No such operation {op!r}: one of {', '.join(OPERATIONS)}.")
        window = self._window
        unit = window.unit
        if unit.instrument is None and not window._have(window.chosen):
            raise ScriptError(f"{backends.title(window.chosen)} could not be started.")
        for key in (a, b):
            record = unit.capture.records.get(key)
            if record is None or record.channel.kind != "analog":
                found = [k for k, r in unit.capture.records.items() if r.channel.kind == "analog"]
                raise ScriptError(f"No analog channel {key!r} of this instrument: {found}.")
        made = Maths(a, op, b)
        window.scope.add_maths(unit, made)
        window.scope.redraw()
        return window.scope._names[unit.id(made.key)]

    def _key(self, channel: str) -> str:
        scope = self._window.scope
        for key, name in scope._names.items():
            if name == channel or key == channel:
                return key
        chosen = self._window.unit.id(channel)
        if chosen in scope._names:
            return chosen
        raise ScriptError(f"No channel {channel!r}. There are: {list(scope._names.values())}.")

    def export_csv(self, path: str | Path) -> list[Path]:
        """Write what the plot shows as CSV, as Export CSV does. The files written."""
        return [written.path for written in self._window.scope.export_csv(Path(path))]

    def export_png(self, path: str | Path) -> bool:
        """Save a picture of the plot, as Export PNG does."""
        return self._window.scope.export_png(Path(path))
