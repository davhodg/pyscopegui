# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The instruments pyscopegui can read, by name.

An instrument in use is named for its back end -- ``rigol1000z`` -- and a second
of the same kind for that and a number: ``rigol1000z#2``. Everything here takes
either, so that nothing above has to know there can be two.

Each is a module imported only when it is asked for, which is how python-can
keeps its adapters: a back end may need a maker's library that is not on this
machine, and one that cannot load must not take the others with it. The
maker's library is never bundled: it is installed separately.
"""

from __future__ import annotations

import importlib
from typing import NamedTuple

from PySide6.QtCore import QObject

from pyscopegui.backends.base import Instrument, Setting


class Backend(NamedTuple):
    module: str
    cls: str
    #: What the instrument list calls it.
    title: str
    #: A word for it, to tell its channels from another instrument's.
    short: str
    #: Offered under Add instrument. A capture file is opened, not added.
    listed: bool = True


#: Name -> where it lives. The name is what is remembered between runs.
BACKENDS: dict[str, Backend] = {
    "demo": Backend("pyscopegui.backends.demo", "DemoInstrument", "Demo signals", "Demo"),
    "picoscope2000": Backend(
        "pyscopegui.backends.picoscope2000",
        "PicoScope2000",
        "PicoScope 2000 series (ps2000)",
        "Pico",
    ),
    "file": Backend(
        "pyscopegui.backends.capture_file", "CaptureFile", "Capture file", "File", listed=False
    ),
    "rigol1000z": Backend(
        "pyscopegui.backends.rigol1000z", "Rigol1000Z", "Rigol DS1000Z series", "Rigol"
    ),
    "tektronix2000": Backend(
        "pyscopegui.backends.tektronix2000",
        "Tektronix2000",
        "Tektronix TDS/TPS 2000 series",
        "Tek",
    ),
}

#: Chosen on a first run: something to look at with nothing plugged in.
DEFAULT = "demo"
#: Between a back end's name and which one of several it is.
NUMBERED = "#"


def names() -> list[str]:
    """The kinds of instrument there are to add."""
    return [name for name, backend in BACKENDS.items() if backend.listed]


def kind(name: str) -> str:
    """The back end an instrument is one of: ``rigol1000z`` for ``rigol1000z#2``."""
    return name.split(NUMBERED, 1)[0]


def number(name: str) -> int:
    """Which one of its kind an instrument is: 1 for the first, which has no number."""
    _kind, _hash, digits = name.partition(NUMBERED)
    return int(digits) if digits.isdigit() and int(digits) > 1 else 1


def known(name: object) -> bool:
    """Whether this names an instrument of a kind there is."""
    if not isinstance(name, str) or kind(name) not in BACKENDS:
        return False
    _kind, hashed, digits = name.partition(NUMBERED)
    return not hashed or (digits.isdigit() and int(digits) > 1 and str(int(digits)) == digits)


def another(of_kind: str, taken) -> str:
    """A name for one more instrument of this kind, beside the ones there are."""
    if of_kind not in taken:
        return of_kind
    count = 2
    while f"{of_kind}{NUMBERED}{count}" in taken:
        count += 1
    return f"{of_kind}{NUMBERED}{count}"


def _numbered(text: str, name: str) -> str:
    return text if number(name) == 1 else f"{text} {number(name)}"


def title(name: str) -> str:
    return _numbered(BACKENDS[kind(name)].title, name)


def short(name: str) -> str:
    return _numbered(BACKENDS[kind(name)].short, name)


def settings(name: str) -> tuple[Setting, ...]:
    """What this instrument lets you set. Needs its module, not its library."""
    backend = BACKENDS[kind(name)]
    return getattr(importlib.import_module(backend.module), backend.cls).SETTINGS


def create(name: str, parent: QObject | None = None, options: dict | None = None) -> Instrument:
    """Make the instrument called this. ImportError if its library is missing."""
    backend = BACKENDS[kind(name)]
    module = importlib.import_module(backend.module)
    return getattr(module, backend.cls)(parent, options)
