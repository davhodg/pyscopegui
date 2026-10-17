# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The launchers, and a .venv whose Python has gone.

A .venv is made from one Python. Uninstall that one, or replace it with a
newer version, and the .venv cannot start: under pythonw that was a window
that never opened, and the shell launcher took a dangling link for a first run.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent


def test_every_python_the_launcher_chooses_is_tested_on_windows():
    """What the launcher picks on Windows is what CI tests there."""
    import re

    chosen = re.search(r"for %%V in \(([\d. ]+)\)", (PROJECT / "pyscopegui.cmd").read_text("utf-8"))
    ci = (PROJECT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    tested = set(re.findall(r'os: windows-latest, python: "([\d.]+)"', ci))
    newest = chosen.group(1).split()[:2]
    assert set(newest) <= tested, f"CI tests {sorted(tested)}, the launcher prefers {newest}"


@pytest.mark.parametrize("name", ("pyscopegui.cmd", "pyscopegui.sh"))
def test_the_launcher_offers_to_make_a_venv_again_when_its_python_has_gone(name):
    text = (PROJECT / name).read_text(encoding="utf-8")
    assert "not there any more" in text
    assert "Delete .venv and set it up again" in text


@pytest.mark.parametrize("name", ("pyscopegui.cmd", "pyscopegui.sh"))
def test_uv_makes_the_venv_from_the_python_that_was_checked(name):
    text = (PROJECT / name).read_text(encoding="utf-8")
    assert "uv venv --python" in text


def test_the_windows_launcher_prefers_a_python_every_library_has_a_download_for():
    """Newest first, and only those tested on Windows: a preview Python on the
    PATH may have no download yet for a library, and pip would build it."""
    text = (PROJECT / "pyscopegui.cmd").read_text(encoding="utf-8")
    assert "for %%V in (3.15 3.14 3.13 3.12)" in text
    assert "py -%%V" in text and '"%PYEXE%" -m venv .venv' in text
    assert "python -m venv" not in text, "never the python on the PATH by name"


def test_a_failed_setup_does_not_keep_a_venv_made_with_the_wrong_python():
    """After a failed setup, installing another Python changed nothing while
    the .venv made with the first one was still there and used again."""
    text = (PROJECT / "pyscopegui.cmd").read_text(encoding="utf-8")
    failed = text[text.index("\n:fail\nset") :]
    assert "if defined FIRSTRUN goto :failfirst" in failed, "a first setup's goes unasked"
    label = failed.index("\n:failfirst\n")
    assert 'rmdir /s /q ".venv"' in failed[label:]
    asked = failed[:label]
    assert "choice /c YN" in asked and 'rmdir /s /q ".venv"' in asked, "a later one's is asked"


def _broken_venv(folder: Path, home: str) -> None:
    (folder / ".venv" / "Scripts").mkdir(parents=True)
    (folder / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
    (folder / ".venv" / "pyvenv.cfg").write_text(
        f"home = {home}\ninclude-system-site-packages = false\nversion = 3.14.6\n",
        encoding="utf-8",
    )


@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe")
@pytest.mark.parametrize("answer", ("N", "Y"))
def test_the_windows_launcher_asks_before_deleting_a_venv_whose_python_has_gone(tmp_path, answer):
    shutil.copy(PROJECT / "pyscopegui.cmd", tmp_path)
    _broken_venv(tmp_path, r"C:\Program Files\No Such Python 3.14")
    # No Python on the PATH: after Yes, setting up again stops at the first step.
    system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    said = subprocess.run(
        ["cmd", "/c", str(tmp_path / "pyscopegui.cmd")],
        cwd=tmp_path,
        input=f"{answer}\r\n\r\n",
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": str(system)},
        timeout=60,
    ).stdout
    assert r"C:\Program Files\No Such Python 3.14" in said, "the whole path, spaces and all"
    if answer == "N":
        assert "left as it is" in said and (tmp_path / ".venv").exists()
    else:
        assert not (tmp_path / ".venv").exists()
        assert "First run: setting up pyscopegui" in said


def _shell_check(folder: Path) -> Path:
    """The shell launcher, as far as its .venv check, and a word if it got past it."""
    text = (PROJECT / "pyscopegui.sh").read_text(encoding="utf-8")
    cut = text.index("if [ ! -x .venv/bin/python ]; then\n")
    script = folder / "pyscopegui.sh"
    script.write_text(text[:cut] + 'echo "GOT PAST THE CHECK"\n', encoding="utf-8")
    return script


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links and sh")
def test_the_shell_launcher_takes_a_link_to_a_python_that_has_gone_for_what_it_is(tmp_path):
    script = _shell_check(tmp_path)
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").symlink_to(tmp_path / "no-such-python3.14")
    said = subprocess.run(
        ["sh", str(script)], cwd=tmp_path, capture_output=True, text=True, stdin=subprocess.DEVNULL
    )
    assert said.returncode == 1, "no terminal to ask in, so it says what to do and stops"
    assert "not there any more" in said.stdout and "GOT PAST" not in said.stdout
    assert (tmp_path / ".venv").exists(), "and deletes nothing it was not told to"


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links and sh")
@pytest.mark.parametrize("made", ("3.1", "this one"))
def test_the_shell_launcher_notices_a_python_replaced_by_another_version(tmp_path, made):
    script = _shell_check(tmp_path)
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    python = Path(sys.executable).resolve()
    (tmp_path / ".venv" / "bin" / "python").symlink_to(python)
    version = (
        f"{sys.version_info.major}.{sys.version_info.minor}.0" if made == "this one" else "3.1.0"
    )
    (tmp_path / ".venv" / "pyvenv.cfg").write_text(f"version = {version}\n", encoding="utf-8")
    said = subprocess.run(
        ["sh", str(script)], cwd=tmp_path, capture_output=True, text=True, stdin=subprocess.DEVNULL
    )
    if made == "this one" or not python.name.startswith("python3."):
        assert "GOT PAST THE CHECK" in said.stdout, said.stdout + said.stderr
    else:
        assert "It was made with Python 3.1" in said.stdout
