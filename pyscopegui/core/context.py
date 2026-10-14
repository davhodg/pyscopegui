# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""What every pane is handed: where things are kept, and the way to say something.

Keep this small and stable: a pane should need nothing else to remember a
choice or to report a problem.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pyscopegui.core import paths, workspaces
from pyscopegui.core.events import ERROR, GOOD, INFORMATION, WARNING, EventLog
from pyscopegui.core.layout import Layout
from pyscopegui.core.settings import Settings


class Context:
    def __init__(
        self,
        log: Callable[[str], None] | None = None,
        events: EventLog | None = None,
    ) -> None:
        self.user_dir: Path = paths.user_dir()
        #: Which bench or setup is being worked on. Everything below belongs to it.
        self.workspace: str = workspaces.active()
        self.workspace_dir: Path = workspaces.active_dir()
        self.settings = Settings(workspaces.settings_path())
        #: The dock arrangement, in the workspace folder rather than in
        #: QSettings, so that the workspace is one thing that can be copied.
        self.layout = Layout(workspaces.layout_path())
        #: Everything said to the user goes through here, with a level.
        self.events = events if events is not None else EventLog()
        if events is None:
            # A plain one-argument sink, which is what a script or a test
            # wants: the level is the window's business, not theirs.
            sink = log or print
            self.events.posted.connect(lambda message, _level: sink(message))

    def log(self, message: str, level: str = INFORMATION) -> None:
        """Write a line to the Event Log pane."""
        self.events.post(message, level)

    def warn(self, message: str) -> None:
        """Say that what was asked for did not happen."""
        self.events.post(message, WARNING)

    def error(self, message: str) -> None:
        """Say that something went wrong that nobody asked for."""
        self.events.post(message, ERROR)

    def good(self, message: str) -> None:
        """Say that something that was wrong is right again."""
        self.events.post(message, GOOD)
