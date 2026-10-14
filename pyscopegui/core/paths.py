# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
r"""Where your own things live: the folder the workspaces all sit under.

The settings and the pane arrangement are in a workspace -- see
``core/workspaces.py`` -- because they are about what is being measured
rather than about this computer.

Windows:  %APPDATA%\pyscopegui        (e.g. C:\Users\you\AppData\Roaming\pyscopegui)
Linux:    $XDG_CONFIG_HOME/pyscopegui  (default ~/.config/pyscopegui)
macOS:    ~/Library/Application Support/pyscopegui

Set ``PYSCOPEGUI_HOME`` to override (used by the tests).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from pyscopegui import APP_NAME


def made(path: Path) -> Path:
    """The folder, made if it is not there. Asked about before it is made.

    On a profile redirected to a network share, or one a scanner is watching,
    creating a directory is the expensive operation and asking whether it
    exists is not.
    """
    if not path.is_dir():
        path.mkdir(parents=True, exist_ok=True)
    return path


def user_dir() -> Path:
    if override := os.environ.get("PYSCOPEGUI_HOME"):
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME
    return made(base)
