# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The Instrument traffic pane: every command, answer and library call, while it is open.

What is kept, and why only while the pane is on screen, is in
``pyscopegui.core.traffic``. This is the reading of it: a line for each,
with when it was, which instrument, which way, and how long an answer took.

A scope's library polled a hundred times a second would bury everything
else, so the same line again, straight after itself, is shown once with how
many times it came.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pyscopegui.core.traffic import CALL, RECEIVED, SENT, Note, traffic
from pyscopegui.ui import fonts

#: Lines kept on screen. Past it the oldest go.
MOST_SHOWN = 10_000
#: How often what has been noted is taken and shown.
TAKE_MS = 100
EVERYONE = "Every instrument"
ARROWS = {SENT: "->", RECEIVED: "<-", CALL: "  "}
EMPTY = (
    "Nothing yet. Every command sent to an instrument, every answer and every call into a "
    "maker's library is shown here while this pane is open, and nothing is kept while it is not."
)
PAUSE_TIP = "Stop adding lines, to read what is here. What arrives meanwhile is kept for after."
SAVE_TIP = "Write what is shown to a text file: to attach to a bug report, say."


@dataclass
class Entry:
    """A line on screen: a note, and how many times running it came."""

    note: Note
    count: int = 1

    def same(self, note: Note) -> bool:
        mine = self.note
        return (mine.who, mine.direction, mine.text) == (note.who, note.direction, note.text)

    def text(self) -> str:
        note = self.note
        stamp = time.strftime("%H:%M:%S", time.localtime(note.when))
        stamp += f".{int(note.when * 1000) % 1000:03d}"
        line = f"{stamp}  {note.who:<22} {ARROWS[note.direction]} {note.text}"
        if note.took is not None:
            line += f"   ({note.took * 1000:.0f} ms)"
        if self.count > 1:
            line += f"   x{self.count}"
        return line


class TrafficView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        #: Everything shown, for every instrument, newest last.
        self._entries: deque[Entry] = deque(maxlen=MOST_SHOWN)
        #: How many of the entries matching the filter are on screen, and
        #: whether the last of them has been counted again since it was shown.
        self._instruments: set[str] = set()

        self.pause = QCheckBox("Pause")
        self.pause.setToolTip(PAUSE_TIP)
        self.pause.toggled.connect(lambda _on: self._take())
        self.who = QComboBox()
        self.who.addItem(EVERYONE)
        self.who.setToolTip("Which instrument's traffic is shown.")
        self.who.currentTextChanged.connect(lambda _text: self._show_all())
        clear = QPushButton("Clear")
        clear.setToolTip("Throw away what is shown.")
        clear.clicked.connect(self.clear)
        copy = QPushButton("Copy")
        copy.setToolTip("Copy what is shown, to paste somewhere else.")
        copy.clicked.connect(self.copy)
        save = QPushButton("Save...")
        save.setToolTip(SAVE_TIP)
        save.clicked.connect(self.ask_save)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Show:"))
        bar.addWidget(self.who)
        bar.addWidget(self.pause)
        bar.addStretch()
        for button in (clear, copy, save):
            bar.addWidget(button)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(fonts.mono())
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text.setMaximumBlockCount(MOST_SHOWN)
        self.text.setPlaceholderText(EMPTY)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(bar)
        layout.addWidget(self.text)

        self._timer = QTimer(self, interval=TAKE_MS, timeout=self._take)

    # --- whether anything is kept -----------------------------------------------------------
    def listen(self, on: bool) -> None:
        """Keep notes, and show them, while the pane is on screen; neither while it is not."""
        traffic.listen(on)
        if on:
            self._timer.start()
        else:
            self._timer.stop()
            self._take()  # what came before it was put away is still shown

    # --- showing ----------------------------------------------------------------------------
    def _shown(self, entry: Entry) -> bool:
        wanted = self.who.currentText()
        return wanted == EVERYONE or entry.note.who == wanted

    def _take(self) -> None:
        if self.pause.isChecked():
            return
        for note in traffic.take():
            self._add(note)

    def _add(self, note: Note) -> None:
        if note.who not in self._instruments:
            self._instruments.add(note.who)
            self.who.addItem(note.who)
        last = self._entries[-1] if self._entries else None
        if last is not None and last.same(note):
            # The same again: counted on the line it is already on.
            last.count += 1
            last.note = Note(note.when, note.who, note.direction, note.text, note.took)
            if self._shown(last):
                self._replace_last(last.text())
            return
        entry = Entry(note)
        self._entries.append(entry)
        if self._shown(entry):
            self.text.appendPlainText(entry.text())

    def _replace_last(self, line: str) -> None:
        cursor = self.text.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.select(QTextCursor.LineUnderCursor)
        cursor.insertText(line)

    def _show_all(self) -> None:
        """Show again, from what is kept, for the instrument chosen."""
        self.text.setPlainText(
            "\n".join(entry.text() for entry in self._entries if self._shown(entry))
        )
        self.text.moveCursor(QTextCursor.End)

    def shown_text(self) -> str:
        return self.text.toPlainText()

    # --- the buttons ------------------------------------------------------------------------
    def clear(self) -> None:
        traffic.take()
        self._entries.clear()
        self.text.clear()

    def copy(self) -> None:
        QGuiApplication.clipboard().setText(self.shown_text())

    def ask_save(self) -> None:
        chosen, _filter = QFileDialog.getSaveFileName(
            self, "Save instrument traffic", "traffic.txt", "Text (*.txt)"
        )
        if chosen:
            self.save(Path(chosen))

    def save(self, path: Path) -> None:
        path.write_text(self.shown_text() + "\n", encoding="utf-8")
