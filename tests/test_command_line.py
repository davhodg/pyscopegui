# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The command line: --workspace, --run with its exit code and --stay, as pycangui's."""

import pytest

from pyscopegui import __main__ as entry
from pyscopegui.core import cli, script_run, workspaces


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(workspaces, "_this_run", "")
    return tmp_path


def script(tmp_path, text, name="job.py"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# --- reading it -----------------------------------------------------------------------------
def test_files_and_options_are_told_apart(home):
    workspaces.create("bench")
    job = script(home, "pass")
    options = cli.parse(["pyscopegui", "--workspace", "bench", f"--run={job}", "--stay", "a.pyscp"])
    assert not options.problem
    assert options.workspace == "bench" and options.run == job.resolve() and options.stay
    assert [f.name for f in options.files] == ["a.pyscp"]
    assert not options.hand_over, "a workspace or a script means a pyscopegui of its own"


def test_qt_options_and_their_values_are_left_for_qt(home):
    options = cli.parse(["pyscopegui", "-platform", "offscreen", "-reverse", "x.pyscp"])
    assert not options.problem and [f.name for f in options.files] == ["x.pyscp"]
    assert options.hand_over, "files alone go to the pyscopegui already open"


@pytest.mark.parametrize(
    "argv",
    [
        ["--wrokspace", "bench"],
        ["--workspace", "nowhere"],
        ["--run", "missing.py"],
        ["--workspace"],
        ["--stay"],
    ],
)
def test_a_command_line_that_cannot_be_followed_is_refused(home, argv):
    assert cli.parse(["pyscopegui", *argv]).problem


def test_help_and_a_mistake_are_said_where_they_can_be_seen(capsys):
    assert entry.tell(cli.USAGE, problem=False) == 0
    assert "--stay" in capsys.readouterr().out
    assert entry.tell("--wrong is not something pyscopegui understands.", problem=True) == 2
    assert "--wrong" in capsys.readouterr().err


def test_a_workspace_named_on_the_command_line_is_for_this_run_only(home):
    workspaces.create("bench")
    workspaces.use("bench")
    assert workspaces.active() == "bench"
    workspaces.use("")
    assert workspaces.active() == workspaces.DEFAULT, "next time opens what it did before"


# --- running a script -----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("x = 1", 0),
        ("import sys; sys.exit()", 0),
        ("import sys; sys.exit(3)", 3),
        ("import sys; sys.exit('no trigger came')", 1),
        ("raise RuntimeError('broken')", 1),
        ("assert value == 7", 0),
        ("assert value == 8", 1),
    ],
)
def test_the_exit_code_is_the_scripts(tmp_path, text, code):
    assert script_run.run(script(tmp_path, text), {"value": 7}, print, print) == code


def test_what_a_script_prints_is_kept_line_by_line(tmp_path):
    said = []
    script_run.run(script(tmp_path, "print('one'); print('two', end='')"), {}, said.append, print)
    assert said == ["one", "two"]


def test_a_script_that_is_not_there_fails(tmp_path):
    complained = []
    assert script_run.run(tmp_path / "gone.py", {}, print, complained.append) == 1
    assert complained


# --- in the window --------------------------------------------------------------------------
def test_a_script_has_what_the_console_has_and_says_how_it_went(window, tmp_path):
    job = script(
        tmp_path,
        "run('auto')\nwait(0.05)\nstop()\nprint(channels())\nimport sys\nsys.exit(4)\n",
    )
    assert window.run_script(job) == 4
    log = window.log.toPlainText()
    assert f"Running {job}" in log and "A: sine" in log, "what it printed is in the Event Log"
    assert "job.py finished: exit code 4" in log


class _Windows:
    def __init__(self, window):
        self.window = window


def test_run_closes_the_window_unless_it_is_to_stay(window, tmp_path, app):
    job = script(tmp_path, "pass")
    for stay in (True, False):
        window.show()
        ran = {}
        entry.run_when_started(_Windows(window), job, stay, ran)
        app.processEvents()
        assert ran == {"exit code": 0}
        assert window.isVisible() is stay


STARTED = """
import sys
from PySide6.QtCore import QSettings
# Settings in the test's folder, never in the person's own.
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, sys.argv[1])
from pyscopegui.__main__ import main
sys.argv = ["pyscopegui", *sys.argv[2:]]
sys.exit(main())
"""


def test_pyscopegui_started_with_run_ends_with_the_scripts_exit_code(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    job = script(tmp_path, "add('demo')\nopen()\nsingle(timeout=10)\nimport sys\nsys.exit(5)\n")
    env = {
        **os.environ,
        "PYSCOPEGUI_HOME": str(tmp_path / "home"),
        "QT_QPA_PLATFORM": "offscreen",
    }
    done = subprocess.run(
        [sys.executable, "-c", STARTED, str(tmp_path / "qsettings"), "--run", str(job)],
        cwd=Path(__file__).resolve().parent.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 5, done.stderr
