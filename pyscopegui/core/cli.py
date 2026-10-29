# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""What pyscopegui was asked to do on its command line.

    pyscopegui [--workspace NAME] [--run SCRIPT [--stay]] [FILE ...]

Read by hand rather than with argparse, which prints and exits on a mistake:
started from the installer's shortcut, or by pip's launcher, there is nothing
to print to, so a mistake has to come back as text for somewhere that can be
seen. The same as pycangui's, so that the two are started alike.

Arguments with one dash are Qt's (``-platform offscreen``, ``-style``) and are
left for it. ``--selftest`` is read where it is used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pyscopegui.core import workspaces

USAGE = """pyscopegui [--workspace NAME] [--run SCRIPT [--stay]] [FILE ...]

  --workspace NAME   open that workspace, this time only
  --run SCRIPT       run a Python script once the window is up, with what the
                     Python Console has, then close; the exit code is the
                     script's: 0, sys.exit(n), or 1 for an exception
  --stay             with --run: leave the window open when the script is
                     done, to look at what it did
  FILE               a capture (.pyscp, .npz) or a CSV to open. Used alone,
                     it goes to the pyscopegui already open, if there is one."""

#: Ours, and read elsewhere.
ELSEWHERE = frozenset({"--selftest"})

#: Qt's options that take a value, so the value is not taken for a file.
QT_WITH_VALUE = frozenset(
    {
        "-platform",
        "-platformpluginpath",
        "-platformtheme",
        "-plugin",
        "-qmljsdebugger",
        "-qwindowgeometry",
        "-qwindowicon",
        "-qwindowtitle",
        "-session",
        "-style",
        "-stylesheet",
        "-display",
        "-geometry",
        "-title",
        "-name",
    }
)


@dataclass
class Options:
    workspace: str = ""
    run: Path | None = None
    stay: bool = False
    files: list[Path] = field(default_factory=list)
    help: bool = False
    #: Why the command line cannot be followed; empty when it can.
    problem: str = ""

    @property
    def hand_over(self) -> bool:
        """Only files: they can go to a pyscopegui that is already open."""
        return bool(self.files) and not self.workspace and self.run is None


def parse(argv: list[str]) -> Options:
    """The command line, ``argv[0]`` included, as it comes in ``sys.argv``."""
    options = Options()
    args = list(argv[1:])
    while args:
        arg = args.pop(0)
        name, equals, value = arg.partition("=")
        if name in ("--workspace", "--run"):
            if not equals:
                if not args:
                    options.problem = f"{name} needs a value."
                    return options
                value = args.pop(0)
            if name == "--workspace":
                options.workspace = value
            else:
                options.run = Path(value).resolve()
        elif arg == "--stay":
            options.stay = True
        elif arg in ("--help", "-h", "/?"):
            options.help = True
        elif arg in ELSEWHERE:
            pass
        elif arg.startswith("--"):
            options.problem = f"{arg} is not something pyscopegui understands."
            return options
        elif arg.startswith("-"):
            if arg in QT_WITH_VALUE and args:
                args.pop(0)
        elif arg:
            options.files.append(Path(arg).resolve())
    options.problem = _check(options)
    return options


def _check(options: Options) -> str:
    if options.workspace and not workspaces.exists(options.workspace):
        there = ", ".join(workspaces.names())
        return f"There is no workspace called {options.workspace}. There are: {there}."
    if options.run is not None and not options.run.is_file():
        return f"There is no script at {options.run}."
    if options.stay and options.run is None:
        return "--stay is for a script: use it with --run."
    return ""
