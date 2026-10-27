# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""A capture in a file, opened as if it were an instrument.

So that everything an instrument's samples can have -- a tab in the
Instrument pane, the channel list, cursors, colours, Export, the console,
lining up beside a live scope on its trigger -- a file's have too, with
nothing written twice. It is read as it is, as a snapshot of a scope's
screen is: Read puts it on the plot, and there is no trigger to set.

Opened from *File > Open capture...*, which says which file and, for a CSV,
which columns are what. It is not offered under *Add instrument*: a file is
chosen, not added empty.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QTimer

from pyscopegui.backends.base import Block, Channel, Instrument, Setting
from pyscopegui.core.capture_file import CaptureError, CsvLayout, Loaded, is_own, load, read_csv

#: Under this, in an instrument's settings, how a CSV is to be read.
LAYOUT = "csv"

SETTINGS = (
    Setting(
        "path",
        "File",
        "",
        group="Connection",
        closed=True,
        empty="File > Open capture... chooses one",
        tip="The file this capture is read from. Another is opened from File > Open capture...",
    ),
    Setting(
        "reference",
        "Draw as a reference",
        False,
        group="Display",
        live=True,
        tip=(
            "Draw this capture faded, behind the instruments' traces, to compare what\n"
            "they show now with it: a known good one, say. Cursors still read it."
        ),
    ),
)


class CaptureFile(Instrument):
    SETTINGS = SETTINGS

    def __init__(self, parent: QObject | None = None, options: dict | None = None) -> None:
        super().__init__(parent)
        self._options = dict(options) if isinstance(options, dict) else {}
        self._loaded: Loaded | None = None
        self._is_open = False
        self._running = False

    @property
    def path(self) -> Path | None:
        text = self._options.get("path")
        return Path(text) if isinstance(text, str) and text else None

    def _load(self) -> Loaded:
        """What is in the file, read the first time it is wanted."""
        if self._loaded is None:
            path = self.path
            if path is None:
                raise CaptureError("No file: File > Open capture... chooses one.")
            if not path.is_file():
                raise CaptureError(f"{path} is not there any more.")
            if is_own(path):
                self._loaded = load(path)
            else:
                self._loaded = read_csv(path, CsvLayout.from_options(self._options.get(LAYOUT)))
        return self._loaded

    def diagnostics(self) -> list[str]:
        """Which file, and what was read from it."""
        loaded = self._loaded
        read = (
            f"{len(loaded.channels)} channels, {len(loaded):,} samples at {loaded.rate:,.6g} S/s"
            if loaded is not None
            else "not read yet"
        )
        return [f"file: {self.path or 'none chosen'}", f"read: {read}"]

    # --- what it is ------------------------------------------------------------------------
    def channels(self) -> list[Channel]:
        try:
            channels = list(self._load().channels)
        except CaptureError:
            return []  # said when it is opened
        if not self.reference:
            return channels
        # Said beside how it is set, so the list says which traces are the faded ones.
        return [
            replace(c, detail=f"{c.detail}, reference" if c.detail else "reference")
            for c in channels
        ]

    @property
    def labels(self) -> dict[str, str]:
        """The names its channels were given when it was saved, by key."""
        return dict(self._loaded.labels) if self._loaded is not None else {}

    @property
    def reference(self) -> bool:
        return self._options.get("reference") is True

    @property
    def rate(self) -> float:
        return self._loaded.rate if self._loaded is not None else 1.0

    @property
    def sweeps(self) -> bool:
        return True

    @property
    def reads_as_is(self) -> bool:
        return True

    @property
    def is_open(self) -> bool:
        return self._is_open

    @property
    def running(self) -> bool:
        return self._running

    def set(self, key: str, value: object) -> None:
        self._options[key] = value
        if key in ("path", LAYOUT):
            self._loaded = None  # another file, or read another way

    # --- opening and reading ----------------------------------------------------------------
    def open(self) -> None:
        if self._is_open:
            return
        try:
            loaded = self._load()
        except CaptureError as exc:
            self.error.emit(str(exc))
            self.opened_changed.emit(False)
            return
        self._is_open = True
        count = len(loaded.channels)
        self.note.emit(
            f"Opened {self.path.name}: {count} {'channel' if count == 1 else 'channels'}, "
            f"{len(loaded):,} samples at {loaded.rate:,.6g} a second."
        )
        for said in loaded.notes:
            self.warning.emit(said)
        self.opened_changed.emit(True)

    def close(self) -> None:
        self.stop()
        if self._is_open:
            self._is_open = False
            # Read again the next time: the file may have been written since.
            self._loaded = None
            self.opened_changed.emit(False)

    def start(self) -> None:
        """Put the whole capture on the plot, once, and stop: it is all there is."""
        if self._running:
            return
        self.open()
        if not self._is_open:
            return
        self._running = True
        self.state_changed.emit(True)
        # After whoever started it has finished saying so: as an instrument's
        # first block would, it arrives from the event loop.
        QTimer.singleShot(0, self._send)

    def _send(self) -> None:
        if not self._running or self._loaded is None:
            return
        loaded = self._loaded
        self.block.emit(
            Block(
                0,
                loaded.rate,
                dict(loaded.data),
                sweep=True,
                trigger=loaded.zero,
                triggered=loaded.zero is not None,
                # Held as they were saved: counts with their scale, inputs packed.
                scales={key: stretches[0][1] for key, stretches in loaded.scales.items()},
                bits=dict(loaded.bits),
            )
        )
        self.stop()

    def stop(self) -> None:
        if self._running:
            self._running = False
            self.state_changed.emit(False)
