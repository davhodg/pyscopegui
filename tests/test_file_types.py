# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Opening a capture by double-clicking it: the file types, however pyscopegui
was installed, a capture handed to the pyscopegui already open, and the window
opening what it was given."""

import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from pyscopegui.core import capture_file, file_types, shortcut
from pyscopegui.ui import handoff

PROJECT = Path(__file__).resolve().parent.parent


@pytest.fixture
def no_launcher(monkeypatch):
    monkeypatch.setattr(shortcut, "launcher", lambda platform=None: None)


# --- what starts pyscopegui ---------------------------------------------------------------
def test_an_installed_build_is_started_by_its_own_program(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert file_types.command("win32") == [sys.executable]


def test_a_source_folder_is_started_by_its_launcher(tmp_path, monkeypatch):
    (tmp_path / "pyscopegui.cmd").write_text("@echo off\n")
    monkeypatch.setattr(shortcut, "root", lambda: tmp_path)
    assert file_types.command("win32") == [str(tmp_path / "pyscopegui.cmd")]


def test_a_pip_installation_is_started_by_its_python(no_launcher):
    start = file_types.command("linux")
    assert start[0] == sys.executable and start[1:] == ["-m", "pyscopegui"]
    start = file_types.command("win32")
    assert Path(start[0]).parent == Path(sys.executable).parent
    assert start[1:] == ["-m", "pyscopegui"]


def test_there_is_nothing_to_register_with_on_macos(no_launcher):
    assert file_types.command("darwin") is None
    with pytest.raises(OSError):
        file_types.register("darwin")


# --- what is registered -------------------------------------------------------------------
def test_windows_opens_its_own_and_only_offers_itself_for_npz():
    start = [r"C:\Program Files\pyscopegui\pyscopegui.exe"]
    values = {
        (key, name): value for key, name, value in file_types.windows_entries(start, Path(start[0]))
    }
    for extension, prog_id, _description in (file_types.OWN, file_types.SHARED):
        assert (rf"Software\Classes\{extension}\OpenWithProgids", prog_id) in values
        opens = values[(rf"Software\Classes\{prog_id}\shell\open\command", "")]
        assert opens.startswith('"C:\\Program Files\\pyscopegui\\pyscopegui.exe"'), "quoted"
        assert opens.endswith('"%1"')
    assert values[(r"Software\Classes\.pyscp", "")] == "pyscopegui.capture", "its own: the default"
    assert (r"Software\Classes\.npz", "") not in values, "numpy's: left as it is"


def test_the_installer_writes_what_tools_settings_does():
    installer = (PROJECT / "build" / "installer.iss").read_text(encoding="utf-8")
    assert "ChangesAssociations=yes" in installer
    for key, name, _value in file_types.windows_entries(["x.exe"], Path("x.exe")):
        assert f'Subkey: "{key}"; ValueType: string; ValueName: "{name}"' in installer, key


def test_linux_says_what_a_capture_is_and_who_opens_it(tmp_path, monkeypatch):
    monkeypatch.setattr(file_types.shutil, "which", lambda _tool: None)
    start = ["/opt/py thon/bin/python", "-m", "pyscopegui"]
    where = file_types._register_linux(start, {"XDG_DATA_HOME": str(tmp_path)})
    types = (tmp_path / "mime" / "packages" / file_types.MIME_PACKAGE).read_text(encoding="utf-8")
    entry = Path(where).read_text(encoding="utf-8")
    assert '"*.pyscp"' in types and file_types.MIME in types
    assert "npz" not in types, "not every .npz is a capture"
    assert f"MimeType={file_types.MIME};" in entry
    exec_line = next(line for line in entry.splitlines() if line.startswith("Exec="))
    assert '"/opt/py thon/bin/python"' in exec_line and exec_line.endswith("%f")


REGISTERS = file_types.command() is not None


@pytest.mark.skipif(not REGISTERS, reason="file types are registered on Windows and Linux only")
def test_tools_settings_registers_them(app, tmp_path, monkeypatch):
    from pyscopegui.ui.main_window import MainWindow

    QSettings().clear()
    asked = []
    monkeypatch.setattr(file_types, "register", lambda: asked.append(1) or "somewhere")
    window = MainWindow()
    try:
        assert window.file_types_action in window.settings_menu.actions()
        window.file_types_action.trigger()
        assert asked == [1]
        assert "now opens in pyscopegui" in window.log.toPlainText()
    finally:
        window.close()
        window.deleteLater()


# --- started with a file --------------------------------------------------------------------
def test_the_files_are_what_is_not_an_option(tmp_path):
    from pyscopegui.__main__ import files_given

    given = files_given(["pyscopegui", str(tmp_path / "shot.pyscp"), "--selftest", ""])
    assert given == [(tmp_path / "shot.pyscp").resolve()]


def test_a_capture_given_is_opened_and_the_window_brought_forward(window, tmp_path, app):
    window.set_mode("auto")
    window.instrument._started -= 0.05
    window.instrument._tick()
    window.set_mode("stop")
    saved = window.scope.save_captures(tmp_path / "shot")
    assert saved == [tmp_path / f"shot{capture_file.SUFFIX}"]
    window.open_files(saved)
    app.processEvents()
    assert "file" in window.session.units and "Opened shot.pyscp" in window.log.toPlainText()


def test_a_file_given_that_is_not_there_says_so(window, tmp_path):
    window.open_files([tmp_path / "gone.pyscp"])
    assert "it is not there" in window.log.toPlainText()


# --- handing over to the one open -----------------------------------------------------------
@pytest.fixture
def name():
    return f"pyscopegui-test-{uuid.uuid4().hex[:12]}"


SECOND = """
import sys
from pathlib import Path
from PySide6.QtCore import QCoreApplication
app = QCoreApplication([])
from pyscopegui.ui import handoff
# Half a second to connect is right for somebody waiting on a double-click, and
# not for a machine running a thousand tests at once.
handoff.CONNECT_MS = 10000
sys.exit(0 if handoff.hand_over([Path(f) for f in sys.argv[2:]], sys.argv[1]) else 1)
"""


def hand_over_from_a_second_pyscopegui(app, files, name):
    """A second pyscopegui, as a process of its own -- a local socket is between
    processes -- while this one's event loop answers."""
    second = subprocess.Popen([sys.executable, "-c", SECOND, name, *map(str, files)], cwd=PROJECT)
    while second.poll() is None:
        app.processEvents()
        time.sleep(0.01)
    return second.returncode == 0


def test_a_capture_goes_to_the_pyscopegui_already_open(app, name):
    listener = handoff.Listener(name)
    got = []
    listener.deliver(got.extend)
    try:
        assert listener.listening
        assert hand_over_from_a_second_pyscopegui(app, [Path("C:/x/shot.pyscp")], name)
        app.processEvents()
        assert [f.name for f in got] == ["shot.pyscp"]
    finally:
        listener.close()


def test_captures_that_come_before_the_window_wait_for_it(app, name):
    listener = handoff.Listener(name)
    try:
        assert hand_over_from_a_second_pyscopegui(app, [Path("early.pyscp")], name)
        app.processEvents()
        got = []
        listener.deliver(got.extend)
        assert [f.name for f in got] == ["early.pyscp"]
    finally:
        listener.close()


def test_with_nobody_open_this_one_opens_them(name):
    assert not handoff.hand_over([Path("a.pyscp")], name)


def test_a_second_copy_leaves_the_first_listening(app, name):
    first = handoff.Listener(name)
    second = handoff.Listener(name)
    try:
        assert first.listening and not second.listening
    finally:
        second.close()
        first.close()


def test_the_name_belongs_to_the_user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("PYSCOPEGUI_HOME", str(tmp_path / "one"))
    one = handoff.server_name()
    monkeypatch.setenv("PYSCOPEGUI_HOME", str(tmp_path / "two"))
    assert handoff.server_name() != one
