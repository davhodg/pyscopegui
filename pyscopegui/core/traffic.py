# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Everything said to an instrument and back, for the Instrument traffic pane.

For finding out why an instrument is slow, or will not do what it is told:
each command sent, each answer and how long it took to come, each call into a
maker's library and what it returned.

Nothing is kept unless somebody is looking. Recording is switched on while
the pane is on screen and off when it is put away, and while it is off a
back end pays for one test of a flag and nothing more: a scope streaming a
hundred calls a second into its driver must not be slowed, or fill memory,
for a pane nobody opened.

A back end does not record anything itself. Its connection -- a socket, a
serial port, a VISA session, a maker's library -- is wrapped once, where it
is made, by ``traced`` or ``traced_library``, and every command and answer
that goes through it is noted. Notes come from the threads instruments are
read on, so they are queued here and the pane takes them on its own thread.
"""

from __future__ import annotations

import ctypes
import threading
import time
from collections import deque
from dataclasses import dataclass

#: Which way: to the instrument, from it, or a call into its library.
SENT, RECEIVED, CALL = "sent", "received", "call"
#: The most notes kept between two looks by the pane. A scope's library
#: called a hundred times a second is ten thousand in less than two minutes
#: of a pane that is paused; the oldest go first.
MOST = 20_000
#: How much of a long answer is shown, before it is cut short.
LONGEST = 200


@dataclass(frozen=True)
class Note:
    """One thing that went to an instrument or came back."""

    #: When, by the computer's clock, in seconds since the epoch.
    when: float
    #: Which instrument, as its connection is known: "Rigol 192.168.1.13", "Tektronix COM7".
    who: str
    direction: str
    text: str
    #: For an answer or a call: how long it took, in seconds.
    took: float | None = None


class Traffic:
    """Where every note goes, and whether anybody is listening."""

    def __init__(self) -> None:
        #: Whether notes are kept. Read without the lock, which is fine: a
        #: note made a moment either side of the pane opening is no loss.
        self.on = False
        self._notes: deque[Note] = deque(maxlen=MOST)
        self._lock = threading.Lock()

    def listen(self, on: bool) -> None:
        """Start or stop keeping notes. What was kept is kept until it is taken."""
        self.on = on

    def note(self, who: str, direction: str, text: str, took: float | None = None) -> None:
        if not self.on:
            return
        with self._lock:
            self._notes.append(Note(time.time(), who, direction, text, took))

    def take(self) -> list[Note]:
        """Every note since the last time, oldest first, and forget them here."""
        with self._lock:
            taken = list(self._notes)
            self._notes.clear()
        return taken


#: The one every back end and the pane use.
traffic = Traffic()


def shortened(text: str) -> str:
    """An answer as it is shown: on one line, and cut short if it is long."""
    text = text.replace("\r", "\\r").replace("\n", "\\n")
    return text if len(text) <= LONGEST else f"{text[:LONGEST]}... ({len(text)} characters)"


class TracedLink:
    """A connection to an instrument, as it was, with what goes through it noted.

    Takes the shape of whatever it wraps: ``write``, ``ask`` and ``ask_bytes``
    are noted, an ``answer`` read on its own is noted, and anything else --
    closing it, its port's name -- is the connection's own.
    """

    def __init__(self, link, who: str) -> None:
        self._link = link
        self.who = who

    def __getattr__(self, name: str):
        return getattr(self._link, name)

    def write(self, command: str) -> None:
        traffic.note(self.who, SENT, command)
        self._link.write(command)

    def ask(self, command: str, *args, **kwargs) -> str:
        traffic.note(self.who, SENT, command)
        return self._answered(lambda: self._link.ask(command, *args, **kwargs))

    def answer(self, *args, **kwargs) -> str:
        return self._answered(lambda: self._link.answer(*args, **kwargs))

    def ask_bytes(self, command: str) -> bytes:
        traffic.note(self.who, SENT, command)
        began = time.perf_counter()
        try:
            data = self._link.ask_bytes(command)
        except Exception as exc:
            traffic.note(self.who, RECEIVED, f"no answer: {exc}", time.perf_counter() - began)
            raise
        traffic.note(self.who, RECEIVED, f"{len(data):,} bytes", time.perf_counter() - began)
        return data

    def _answered(self, asking) -> str:
        began = time.perf_counter()
        try:
            said = asking()
        except Exception as exc:
            traffic.note(self.who, RECEIVED, f"no answer: {exc}", time.perf_counter() - began)
            raise
        traffic.note(self.who, RECEIVED, shortened(said), time.perf_counter() - began)
        return said


def traced(link, who: str) -> TracedLink:
    """This connection, with every command and answer noted while anybody is looking."""
    return TracedLink(link, who)


def _argument(value) -> str:
    """One argument of a call into a library, in a few characters."""
    if value is None:
        return "NULL"
    if isinstance(value, bool | int | float | str):
        return repr(value)
    if isinstance(value, ctypes.Array):
        return f"buffer[{len(value)}]"
    if isinstance(value, ctypes._SimpleCData):
        return repr(value.value)
    if callable(value):
        return "callback"
    if type(value).__name__ == "CArgObject":
        return "&out"  # something the call fills in
    # A pointer to something the call fills in: what it is matters, not where.
    return type(value).__name__


class TracedLibrary:
    """A maker's library, as it was, with each call into it noted."""

    def __init__(self, library, who: str) -> None:
        self._library = library
        self.who = who

    def __getattr__(self, name: str):
        function = getattr(self._library, name)
        if not traffic.on or not callable(function):
            return function

        def noted(*args):
            began = time.perf_counter()
            try:
                result = function(*args)
            except Exception as exc:
                said = f"{name}({', '.join(_argument(a) for a in args)}) failed: {exc}"
                traffic.note(self.who, CALL, said, time.perf_counter() - began)
                raise
            said = f"{name}({', '.join(_argument(a) for a in args)}) -> {_argument(result)}"
            traffic.note(self.who, CALL, said, time.perf_counter() - began)
            return result

        return noted


def traced_library(library, who: str) -> TracedLibrary:
    """This library, with every call into it noted while anybody is looking."""
    return TracedLibrary(library, who)
