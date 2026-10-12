# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The instruments pyscopegui can read, by name.

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


#: Name -> where it lives. The name is what is remembered between runs.
BACKENDS: dict[str, Backend] = {
    "demo": Backend("pyscopegui.backends.demo", "DemoInstrument", "Demo signals", "Demo"),
    "picoscope2000": Backend(
        "pyscopegui.backends.picoscope2000",
        "PicoScope2000",
        "PicoScope 2000 series (ps2000)",
        "Pico",
    ),
    "rigol1000z": Backend(
        "pyscopegui.backends.rigol1000z", "Rigol1000Z", "Rigol DS1000Z series (network)", "Rigol"
    ),
}

#: Chosen on a first run: something to look at with nothing plugged in.
DEFAULT = "demo"


def names() -> list[str]:
    return list(BACKENDS)


def title(name: str) -> str:
    return BACKENDS[name].title


def short(name: str) -> str:
    return BACKENDS[name].short


def settings(name: str) -> tuple[Setting, ...]:
    """What this instrument lets you set. Needs its module, not its library."""
    backend = BACKENDS[name]
    return getattr(importlib.import_module(backend.module), backend.cls).SETTINGS


def create(name: str, parent: QObject | None = None, options: dict | None = None) -> Instrument:
    """Make the instrument called this. ImportError if its library is missing."""
    backend = BACKENDS[name]
    module = importlib.import_module(backend.module)
    return getattr(module, backend.cls)(parent, options)
