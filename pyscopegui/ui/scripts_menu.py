# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""File > Run script... and File > Recent scripts.

A script was run from a button in the Python Console, which is a pane that
has to be opened before the button can be found, and it was forgotten as
soon as it had run. Running the same measurement script again is the usual
case, so the last few are kept, for each workspace, a click away.

The running is the console's: a script sees the names the console has, and
what it prints and any traceback is written there, which is why the console
is shown first. A script whose output went nowhere would look like a menu
entry that does nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QMenu, QWidget

from pyscopegui.ui import messages
from pyscopegui.ui.console_view import SCRIPT_FOLDER

if TYPE_CHECKING:
    from pyscopegui.core.context import Context

#: In the workspace's settings: the scripts run, most recent first.
RECENT_KEY = "scripts.recent"
#: How many are kept.
MOST_RECENT = 5
RUN_TIP = (
    "Run a Python file in the Python Console, which is shown so that what it\n"
    "prints can be read: it has the console's commands -- add, open, set, run,\n"
    "single, data, export_csv, wait and the rest."
)
RECENT_TIP = "The last scripts run in this workspace, newest first."
GONE = "{name} is not there any more, so it has been taken off the list:\n\n{path}"


def stored(path: Path, workspace: Path) -> str:
    """How a script is written down: inside the workspace, relative to it, so a
    workspace taken to another computer still finds its own; anywhere else, in full."""
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def found(value: str, workspace: Path) -> Path:
    """A script as it was written down, where it is now."""
    path = Path(value)
    return path if path.is_absolute() else workspace / path


class ScriptsMenu(QObject):
    """The two entries, and the list behind the second."""

    #: Run this file: the window shows the console and runs it there.
    run_wanted = Signal(str)

    def __init__(self, window: QWidget, ctx: Context) -> None:
        super().__init__(window)
        self.window = window
        self.ctx = ctx
        self.recent_menu = QMenu("Recent scripts")
        self.recent_menu.setToolTipsVisible(True)
        self.recent_menu.aboutToShow.connect(self._build_recent)

    def install(self, file_menu: QMenu, before=None) -> None:
        """Put the two entries in the File menu, above ``before`` if that is given."""
        run = QAction("Run script...", file_menu)
        run.triggered.connect(lambda _checked=False: self.run_dialog())
        run.setToolTip(RUN_TIP)
        if before is not None:
            file_menu.insertAction(before, run)
            recent = file_menu.insertMenu(before, self.recent_menu)
            file_menu.insertSeparator(before)
        else:
            file_menu.addAction(run)
            recent = file_menu.addMenu(self.recent_menu)
        recent.setToolTip(RECENT_TIP)

    # --- the list -------------------------------------------------------------------
    def recent(self) -> list[Path]:
        """The scripts run in this workspace, newest first."""
        values = self.ctx.settings.get(RECENT_KEY, [])
        if not isinstance(values, list):
            return []
        workspace = self.ctx.workspace_dir
        return [found(str(value), workspace) for value in values if isinstance(value, str)]

    def remember(self, path: str | Path) -> None:
        """Put a script at the top of the list: run again, it moves up rather
        than being listed twice."""
        workspace = self.ctx.workspace_dir
        mine = Path(path).resolve()
        kept = [p for p in self.recent() if p.resolve() != mine]
        values = [stored(p, workspace) for p in [mine, *kept][:MOST_RECENT]]
        self.ctx.settings.set(RECENT_KEY, values)

    def forget(self, path: Path) -> None:
        mine = path.resolve()
        workspace = self.ctx.workspace_dir
        values = [stored(p, workspace) for p in self.recent() if p.resolve() != mine]
        self.ctx.settings.set(RECENT_KEY, values)

    def _build_recent(self) -> None:
        self.recent_menu.clear()
        scripts = self.recent()
        for path in scripts:
            action = self.recent_menu.addAction(path.name, lambda p=path: self.run_recent(p))
            action.setToolTip(str(path))
        if not scripts:
            nothing = self.recent_menu.addAction("No scripts run yet")
            nothing.setEnabled(False)

    # --- running --------------------------------------------------------------------
    def run_dialog(self) -> None:
        folder = self.ctx.settings.get(SCRIPT_FOLDER)
        start = folder if isinstance(folder, str) else str(self.ctx.workspace_dir)
        chosen, _filter = QFileDialog.getOpenFileName(
            self.window, "Run Python script", start, "Python (*.py)"
        )
        if chosen:
            self.ctx.settings.set(SCRIPT_FOLDER, str(Path(chosen).parent))
            self.run_wanted.emit(chosen)

    def run_recent(self, path: Path) -> None:
        if not path.is_file():
            # Said in a box: chosen from a menu, an answer in the Event Log
            # is one in a pane that may not be open.
            self.forget(path)
            messages.warning(
                self.window, "Script not found", GONE.format(name=path.name, path=path)
            )
            return
        self.run_wanted.emit(str(path))
