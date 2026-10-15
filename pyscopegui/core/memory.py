# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""How much memory there is to spare, so that a run keeps only the history there is room for.

A history is set aside whole when a run starts: ten seconds of four channels
at 31.25 MS/s is 7.5 GB, more than many a laptop has. Asked for anyway, the
operating system gives it and then pages it out to disk as it fills, and the
whole computer grinds; so the history is cut down to fit, at the start,
rather than finding out. Only the standard library is used: what the
operating system says is free, read the way each one says it.
"""

from __future__ import annotations

import ctypes
import os
import sys

#: How much of what is free a run's history may take. The rest is for
#: drawing, measuring and saving it, and for everything else on the computer.
SHARE = 0.5


def available() -> int | None:
    """Bytes of memory free for use now, without paging anything out to
    disk. None where the operating system will not say."""
    try:
        if sys.platform == "win32":
            return _windows()
        if sys.platform.startswith("linux"):
            return _linux()
        # Elsewhere -- macOS has no such count -- nothing is cut down.
        return None
    except (OSError, ValueError, AttributeError):
        return None


def room() -> int | None:
    """Bytes a run's history may take: a share of what is free. None where
    that cannot be told, and the history is then as long as it was asked to be."""
    free = available()
    return None if free is None else int(free * SHARE)


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _windows() -> int | None:
    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(_MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.ullAvailPhys)


def _linux() -> int | None:
    # What the kernel says could be had without swapping, page cache and all;
    # the pages that are simply unused are far fewer.
    with open("/proc/meminfo", encoding="ascii") as info:
        for line in info:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
