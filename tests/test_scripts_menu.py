# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""File > Run script... and File > Recent scripts."""

from PySide6.QtWidgets import QFileDialog

from pyscopegui.ui import messages
from pyscopegui.ui.scripts_menu import MOST_RECENT, RECENT_KEY


def script(folder, name="test.py", text="print('ran', 6 * 7)\n"):
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


def test_run_script_runs_it_in_the_console_and_shows_the_console(window, tmp_path, monkeypatch):
    path = script(tmp_path)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), ""))
    window.scripts_menu.run_dialog()
    assert "ran 42" in window.console.text()
    assert window.panes.on_screen("console"), "where what it printed is"


def test_what_was_run_is_listed_newest_first_once_each(window, tmp_path):
    first, second = script(tmp_path, "a.py"), script(tmp_path, "b.py")
    for path in (first, second, first):
        window.run_script_in_console(str(path))
    assert window.scripts_menu.recent() == [first.resolve(), second.resolve()]


def test_the_consoles_own_button_is_remembered_too(window, tmp_path):
    path = script(tmp_path)
    window.console.run_file(path)
    assert window.scripts_menu.recent() == [path.resolve()]


def test_only_the_last_few_are_kept(window, tmp_path):
    paths = [script(tmp_path, f"s{n}.py") for n in range(MOST_RECENT + 2)]
    for path in paths:
        window.run_script_in_console(str(path))
    assert window.scripts_menu.recent() == [p.resolve() for p in reversed(paths)][:MOST_RECENT]


def test_a_recent_script_runs_from_the_menu(window, tmp_path):
    path = script(tmp_path)
    window.run_script_in_console(str(path))
    window.console.output.clear()
    menu = window.scripts_menu.recent_menu
    menu.aboutToShow.emit()
    assert menu.actions()[0].text() == "test.py"
    menu.actions()[0].trigger()
    assert "ran 42" in window.console.text()


def test_with_none_run_the_list_says_so(window):
    menu = window.scripts_menu.recent_menu
    menu.aboutToShow.emit()
    assert [a.text() for a in menu.actions()] == ["No scripts run yet"]
    assert not menu.actions()[0].isEnabled()


def test_one_that_has_gone_is_said_and_taken_off(window, tmp_path, monkeypatch):
    path = script(tmp_path)
    window.run_script_in_console(str(path))
    path.unlink()
    said = []
    monkeypatch.setattr(messages, "warning", lambda *a, **k: said.append(a))
    window.scripts_menu.run_recent(path.resolve())
    assert said and window.scripts_menu.recent() == []


def test_one_that_cannot_be_read_is_not_remembered(window, tmp_path):
    window.console.run_file(tmp_path / "nowhere.py")
    assert window.scripts_menu.recent() == []


def test_one_in_the_workspace_is_remembered_relative_to_it(window):
    """So a workspace taken to another computer still finds its own scripts."""
    folder = window.ctx.workspace_dir / "scripts"
    folder.mkdir(parents=True, exist_ok=True)
    path = script(folder)
    window.run_script_in_console(str(path))
    assert window.ctx.settings.get(RECENT_KEY) == ["scripts/test.py"]
    assert window.scripts_menu.recent()[0].resolve() == path.resolve()


def test_a_list_saved_wrong_by_hand_is_an_empty_one(window):
    window.ctx.settings.set(RECENT_KEY, "not a list")
    assert window.scripts_menu.recent() == []
