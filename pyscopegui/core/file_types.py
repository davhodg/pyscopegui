# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Open pyscopegui's captures by double-clicking them in the file manager.

A capture is a ``.pyscp``, an extension of pyscopegui's own, so pyscopegui is
made what opens it. A capture saved before there was one is a ``.npz``, which
is numpy's and many another program's, so there pyscopegui is only added to
*Open with* on Windows, and whatever opens them now keeps them.

The installer offers this as a task. Everything else -- a source folder, a pip
installation, an installed build whose task was left unticked -- gets it from
Tools > Settings, which is this module. Written for the user only, so no
administrator is asked.

How pyscopegui is started with a file depends on how it got here:

* the installed build: its own pyscopegui.exe;
* a source folder: the launcher, which is what notices a library added since
  the last pull, exactly as the Start menu entry does;
* a pip installation: the Python it is installed in, with ``-m pyscopegui``.

Not on macOS, where a file type belongs to an application bundle and there is
none to name.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from pyscopegui.core import shortcut

#: pyscopegui's own: the extension, the name the registry knows it by, and
#: what Explorer calls it.
OWN = (".pyscp", "pyscopegui.capture", "pyscopegui capture")
#: Older captures, in a format that is not pyscopegui's alone: Open with only.
SHARED = (".npz", "pyscopegui.npz", "pyscopegui capture or NumPy archive")
#: There is no registered type for it, so this is pyscopegui's own.
MIME = "application/x-pyscopegui-capture"
DESKTOP_NAME = "pyscopegui-open.desktop"
MIME_PACKAGE = "pyscopegui.xml"


def command(platform: str | None = None) -> list[str] | None:
    """What starts this pyscopegui, to which the file is added. None where there
    is nothing to register it with."""
    platform = sys.platform if platform is None else platform
    if platform not in ("win32", "linux"):
        return None
    if getattr(sys, "frozen", False):
        return [sys.executable]
    if (script := shortcut.launcher(platform)) is not None:
        return [str(script)]
    python = Path(sys.executable)
    if platform == "win32" and (windowed := python.with_name("pythonw.exe")).is_file():
        python = windowed  # no console behind the window
    return [str(python), "-m", "pyscopegui"]


def icon() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    name = "pyscopegui.ico" if sys.platform == "win32" else "pyscopegui.png"
    return Path(__file__).resolve().parent.parent / "resources" / name


# --- Windows ------------------------------------------------------------------------------
def windows_entries(start: list[str], icon_path: Path) -> list[tuple[str, str, str]]:
    """The registry values, as (key under HKCU, value name, value). The same
    ones the installer writes, so either can follow the other."""
    opens = subprocess.list2cmdline(start) + ' "%1"'
    shown = f"{icon_path},0" if icon_path.suffix.lower() == ".exe" else str(icon_path)
    entries = []
    for extension, prog_id, description in (OWN, SHARED):
        base = rf"Software\Classes\{prog_id}"
        entries += [
            (rf"Software\Classes\{extension}\OpenWithProgids", prog_id, ""),
            (base, "", description),
            (rf"{base}\DefaultIcon", "", shown),
            (rf"{base}\shell\open\command", "", opens),
        ]
    # Its own extension is pyscopegui's to open: nothing else has a claim on it.
    extension, prog_id, _description = OWN
    entries.append((rf"Software\Classes\{extension}", "", prog_id))
    return entries


def _register_windows(start: list[str]) -> str:
    import ctypes
    import winreg

    for key, name, value in windows_entries(start, icon()):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:
            winreg.SetValueEx(handle, name, 0, winreg.REG_SZ, value)
    # Explorer keeps what it knew until it is told to look again.
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED
    return "the registry, for this user"


# --- Linux --------------------------------------------------------------------------------
def mime_package() -> str:
    """The shared-mime-info file that says which files are a pyscopegui capture.
    Only its own extension: saying every .npz is one would be wrong of most."""
    extension, _prog_id, description = OWN
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">\n'
        f'  <mime-type type="{MIME}">\n'
        f"    <comment>{description}</comment>\n"
        f'    <glob pattern="*{extension}"/>\n'
        f'    <glob pattern="*{extension.upper()}"/>\n'
        "  </mime-type>\n"
        "</mime-info>\n"
    )


def _desktop_quoted(text: str) -> str:
    for reserved in ("\\", '"', "`", "$"):
        text = text.replace(reserved, "\\" + reserved)
    return f'"{text}"'


def desktop_entry(start: list[str], icon_path: Path) -> str:
    """The entry that opens a capture with pyscopegui. Not in the menu: the
    menu's own entry is the Start menu one, and this is only for its files."""
    through_launcher = len(start) == 1
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=pyscopegui\n"
        "Comment=Open a pyscopegui capture\n"
        f"Exec={' '.join(_desktop_quoted(part) for part in start)} %f\n"
        f"Icon={icon_path}\n"
        # The launcher may install libraries after a pull, and says so there.
        f"Terminal={'true' if through_launcher else 'false'}\n"
        f"MimeType={MIME};\n"
        "NoDisplay=true\n"
    )


def _register_linux(start: list[str], environ=None) -> str:
    environ = os.environ if environ is None else environ
    data = Path(environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    packages = data / "mime" / "packages"
    applications = data / "applications"
    packages.mkdir(parents=True, exist_ok=True)
    applications.mkdir(parents=True, exist_ok=True)
    (packages / MIME_PACKAGE).write_text(mime_package(), encoding="utf-8")
    (applications / DESKTOP_NAME).write_text(desktop_entry(start, icon()), encoding="utf-8")
    # The desktop reads caches of both; a missing tool leaves it to the next login.
    for tool, folder in (
        ("update-mime-database", data / "mime"),
        ("update-desktop-database", applications),
    ):
        if (found := shutil.which(tool)) is not None:
            subprocess.run([found, str(folder)], capture_output=True, check=False)
    # Its own type, so the one to open it: nothing else has a claim on it.
    if (found := shutil.which("xdg-mime")) is not None:
        subprocess.run(
            [found, "default", DESKTOP_NAME, MIME], capture_output=True, check=False, env=environ
        )
    return str(applications / DESKTOP_NAME)


def register(platform: str | None = None) -> str:
    """Have this pyscopegui open .pyscp captures, and be offered for .npz ones on
    Windows. Returns where that was written; OSError if it could not be."""
    platform = sys.platform if platform is None else platform
    start = command(platform)
    if start is None:
        raise OSError("File types cannot be registered on this system.")
    return _register_windows(start) if platform == "win32" else _register_linux(start)
