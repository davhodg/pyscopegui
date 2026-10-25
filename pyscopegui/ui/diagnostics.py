# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""What Help > Diagnostics says beyond versions, instruments and samples, and its window.

The report is for answering "what is pyscopegui doing?" on the spot, and for
a bug report afterwards. Beyond what every instrument has, each says what
only it knows -- a PicoScope's driver and how its stream is keeping up, how a
Rigol or a Tektronix is reached -- and the report says what the trigger is
and who finds it, what memory there is for the history, what is decoded and
sent on, and what went wrong lately.

Each section is built on its own and a failure costs only that section: a
report that cannot be made because one part of the window is in an odd state
is no use at exactly the moment it is wanted. Every section says "nothing"
rather than being left out, so a missing line is never mistaken for an empty
one. Names, files and settings are listed; samples are not.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from pyscopegui import backends
from pyscopegui.core import memory, sharing
from pyscopegui.ui import fonts

#: How many warnings and errors the window keeps for the report.
RECENT_PROBLEMS = 20


def _units(window) -> list:
    """The instruments in the pane, the chosen one first, as their units."""
    names = [window.chosen, *(n for n in window.added if n != window.chosen)]
    return [window.session.units[n] for n in names if n in window.session.units]


def _megabytes(count: int | None) -> str:
    """Bytes as MB, or GB from a thousand MB: "13.1 MB", "16.3 GB"."""
    if count is None:
        return "not known"
    return f"{count / 1e9:,.1f} GB" if count >= 1e9 else f"{count / 1e6:,.1f} MB"


# --- each instrument, and its trigger ------------------------------------------------------
def instruments(window) -> list[str]:
    """What each instrument says of itself beyond what every instrument has."""
    lines = []
    for unit in _units(window):
        lines.append(f"{backends.title(unit.name)} ({unit.name}):")
        if unit.instrument is None:
            lines.append("  not made: it has not been opened")
            continue
        lines += [f"  {line}" for line in unit.instrument.diagnostics() or ["nothing more"]]
    return lines


def triggers(window) -> list[str]:
    """What each instrument waits for, who finds it, and how many have been found."""
    lines = []
    for unit in _units(window):
        acquisition, instrument = unit.acquisition, unit.instrument
        condition = acquisition.condition
        if not acquisition.keys():
            lines.append(f"{unit.name}: no trigger")
            continue
        said = condition.summary() or f"{'rising' if acquisition.rising else 'falling'} edge"
        sweeps = instrument is not None and instrument.sweeps
        if sweeps:
            itself = instrument.triggers_itself(condition, acquisition.source)
            finder = "the instrument, in its own hardware" if itself else "nobody: it cannot"
        else:
            finder = "pyscopegui, in what is streamed"
        lines.append(
            f"{unit.name}: {condition.kind} on {acquisition.source or 'its pattern or bus'}, "
            f"{said}; level {acquisition.level:g}; holdoff {condition.holdoff:g} s"
        )
        lines.append(f"  found by {finder}; {len(acquisition._triggers):,} found and kept")
        if acquisition.sweep is not None:
            sweep = acquisition.sweep
            lines.append(
                f"  last sweep: {sweep.length:,} samples, trigger at {sweep.trigger}, "
                f"{'triggered' if sweep.triggered else 'taken without one'}"
            )
    return lines


# --- memory, what is worked out, and what is sent on -------------------------------------
def held(window) -> list[str]:
    """What the history is, what is kept, and the memory it is kept in."""
    lines = [
        f"history asked for: {window.session.history_s:g} s; a run may take "
        f"{window._saved_share():.0%} of what is free",
        f"free now: {_megabytes(memory.available())} of {_megabytes(memory.total())}",
    ]
    for unit in _units(window):
        capture = unit.capture
        if not capture.records:
            continue
        lines.append(
            f"{unit.name}: {capture.held_s():g} s kept, taking {_megabytes(capture.memory_bytes())}"
        )
    return lines


def worked_out(window) -> list[str]:
    """Each instrument's maths channels, and the buses it decodes."""
    lines = []
    for unit in _units(window):
        capture = unit.capture
        for maths in capture.maths:
            lines.append(f"{unit.name}: maths {maths.key}")
        for decoding in capture.decodings:
            state = "paused" if decoding.paused else "decoding"
            problem = f"; {decoding.problem}" if decoding.problem else ""
            share = getattr(decoding.setup, "share", "")
            sent = f"; sent on to {share}" if share else ""
            lines.append(
                f"{unit.name}: {decoding.key} {state}, {len(decoding.items):,} read{sent}{problem}"
            )
    return lines


def shared(window) -> list[str]:
    """Decoded CAN frames sent on by UDP multicast, where, and how many."""
    sharer = window.sharer
    reach = "this computer only" if sharer.hop_limit == sharing.LOCAL_ONLY else "the local network"
    lines = [f"reaching {reach}"]
    lines += [f"{group}: {count:,} frames sent" for group, count in sharer.sent.items()]
    if not sharer.sent:
        lines.append("no frames sent")
    return lines


# --- panes, what went wrong, and what runs ------------------------------------------------
def panes(window) -> list[str]:
    """Every pane there is beyond the fixed set, on screen or put away."""
    return [
        f"{window.panes.docks[name].windowTitle()} ({name}): "
        f"{'on screen' if window.panes.on_screen(name) else 'put away'}"
        for name in window.panes.extras()
    ]


def problems(window) -> list[str]:
    return [
        f"{when} {level}: {text.splitlines()[0] if text else ''}"
        for when, level, text in getattr(window, "recent_problems", ())
    ]


def threads(_window) -> list[str]:
    return sorted(
        f"{thread.name}{' (daemon)' if thread.daemon else ''}" for thread in threading.enumerate()
    )


#: In the order the report gives them, after what it has always said.
SECTIONS: tuple[tuple[str, Callable], ...] = (
    ("Instruments, in their own words", instruments),
    ("Triggers", triggers),
    ("Memory", held),
    ("Maths and decoding", worked_out),
    ("Sending decoded CAN frames", shared),
    ("Panes beyond the fixed set", panes),
    (f"Last {RECENT_PROBLEMS} warnings and errors", problems),
    ("Threads", threads),
)


def section(title: str, build: Callable, window) -> list[str]:
    """One section, whatever happens in building it."""
    try:
        body = build(window) or ["nothing"]
    except Exception as exc:  # one odd corner must not cost the whole report
        body = [f"could not be read: {type(exc).__name__}: {exc}"]
    return ["", title, *(f"  {line}" for line in body)]


def sections(window) -> list[str]:
    lines: list[str] = []
    for title, build in SECTIONS:
        lines += section(title, build, window)
    return lines


# --- the window -----------------------------------------------------------------------------
class DiagnosticsDialog(QDialog):
    """The report, to read, refresh, copy or save. One, brought forward when asked again."""

    def __init__(self, parent: QWidget, make: Callable[[], str], ctx) -> None:
        super().__init__(parent)
        self.setWindowTitle("Diagnostics")
        self.resize(860, 640)
        self._make = make
        self._ctx = ctx
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(fonts.mono())
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text.setAccessibleName("Diagnostics report")
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        refresh = buttons.addButton("Refresh", QDialogButtonBox.ActionRole)
        refresh.setToolTip("Make the report again, as things are now.")
        refresh.clicked.connect(self.refresh)
        copy = buttons.addButton("Copy", QDialogButtonBox.ActionRole)
        copy.setToolTip("Put the whole report on the clipboard, for a bug report.")
        copy.clicked.connect(self.copy_to_clipboard)
        save = buttons.addButton("Save...", QDialogButtonBox.ActionRole)
        save.setToolTip("Write the report to a text file.")
        save.clicked.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.text)
        layout.addWidget(buttons)
        self.refresh()

    def report(self) -> str:
        return self.text.toPlainText()

    def refresh(self) -> None:
        self.text.setPlainText(self._make())

    def copy_to_clipboard(self) -> None:
        QGuiApplication.clipboard().setText(self.report())

    def save(self) -> None:
        start = str(Path(self._ctx.user_dir) / "pyscopegui-diagnostics.txt")
        path, _kind = QFileDialog.getSaveFileName(
            self, "Save diagnostics", start, "Text (*.txt);;All files (*)"
        )
        if not path:
            return
        try:
            Path(path).write_text(self.report() + "\n", encoding="utf-8")
        except OSError as exc:
            self._ctx.error(f"Could not write {path}: {exc}")
            return
        self._ctx.log(f"Diagnostics written to {path}")
