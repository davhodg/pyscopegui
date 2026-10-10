# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The instruments pyscopegui can read, by name.

Each is a module imported only when it is asked for, which is how python-can
keeps its adapters: a back end may need a maker's library that is not on this
machine, and one that cannot load must not take the others with it. The
maker's library is never bundled. Install it, and its back end finds it.
"""

from __future__ import annotations

import importlib
from typing import NamedTuple

from PySide6.QtCore import QObject

from pyscopegui.backends.base import Instrument


class Backend(NamedTuple):
    module: str
    cls: str
    #: What the instrument list calls it.
    title: str


#: Name -> where it lives. The name is what is remembered between runs.
BACKENDS: dict[str, Backend] = {
    "demo": Backend("pyscopegui.backends.demo", "DemoInstrument", "Demo signals"),
    "picoscope2000": Backend(
        "pyscopegui.backends.picoscope2000", "PicoScope2000", "PicoScope 2204A (ps2000)"
    ),
}

#: Chosen on a first run: something to look at with nothing plugged in.
DEFAULT = "demo"


def names() -> list[str]:
    return list(BACKENDS)


def title(name: str) -> str:
    return BACKENDS[name].title


def create(name: str, parent: QObject | None = None, options: dict | None = None) -> Instrument:
    """Make the instrument called this. ImportError if its library is missing."""
    backend = BACKENDS[name]
    module = importlib.import_module(backend.module)
    return getattr(module, backend.cls)(parent, options)
