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

#: How much of what is free a run's history may take, unless Tools >
#: Settings > Memory says otherwise. The rest is for drawing, measuring and
#: saving it, and for everything else on the computer.
SHARE = 0.5
#: What Memory offers.
SHARES = (0.25, 0.5, 0.75, 0.9)


def available() -> int | None:
    """Bytes of memory free for use now, without paging anything out to
    disk. None where the operating system will not say."""
    return _asked(_windows, "MemAvailable:")


def total() -> int | None:
    """Bytes of memory the computer has in all. None where it will not say."""
    return _asked(_windows_total, "MemTotal:")


def _asked(windows, linux: str) -> int | None:
    try:
        if sys.platform == "win32":
            return windows()
        if sys.platform.startswith("linux"):
            return _linux(linux)
        # Elsewhere -- macOS has no such count -- nothing is cut down.
        return None
    except (OSError, ValueError, AttributeError):
        return None


def room(share: float = SHARE) -> int | None:
    """Bytes a run's history may take: this share of what is free. None where
    that cannot be told, and the history is then as long as it was asked to be."""
    free = available()
    return None if free is None else int(free * share)


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


def _status() -> _MemoryStatus | None:
    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(_MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return status


def _windows() -> int | None:
    status = _status()
    return None if status is None else int(status.ullAvailPhys)


def _windows_total() -> int | None:
    status = _status()
    return None if status is None else int(status.ullTotalPhys)


def _linux(line_of: str) -> int | None:
    # Available is what the kernel says could be had without swapping, page
    # cache and all; the pages that are simply unused are far fewer.
    with open("/proc/meminfo", encoding="ascii") as info:
        for line in info:
            if line.startswith(line_of):
                return int(line.split()[1]) * 1024
    pages = "SC_AVPHYS_PAGES" if line_of == "MemAvailable:" else "SC_PHYS_PAGES"
    return os.sysconf(pages) * os.sysconf("SC_PAGE_SIZE")
