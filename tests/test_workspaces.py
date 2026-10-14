# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""One workspace per bench or setup, and one called default nobody has to meet.

Somebody who never asked for workspaces must not be able to tell that they
were built: there is a ``default`` one, made silently, and everything is kept
in it -- including what was kept before there were workspaces.
"""

import json
import shutil

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QInputDialog, QMessageBox

from pyscopegui import APP_NAME, __version__
from pyscopegui.core import paths, workspaces
from pyscopegui.core.context import Context
from pyscopegui.core.layout import Layout
from pyscopegui.ui import messages

RIGOL = "instrument.rigol1000z"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("PYSCOPEGUI_HOME", str(tmp_path))
    return tmp_path


def test_a_fresh_install_just_gets_a_default(home):
    assert workspaces.active() == workspaces.DEFAULT
    assert workspaces.names() == [workspaces.DEFAULT]
    assert workspaces.dir_for(workspaces.DEFAULT).is_dir()


# --- what there was before there were workspaces ----------------------------------------------
def test_what_was_kept_before_is_the_default_workspaces_now(home):
    """Somebody upgrading finds the instruments and panes as they left them."""
    (home / "settings.json").write_text(json.dumps({RIGOL: {"address": "x"}}), encoding="utf-8")
    (home / "layout.json").write_text(json.dumps({"window": "AAEC"}), encoding="utf-8")
    ctx = Context()
    assert ctx.settings.get(RIGOL) == {"address": "x"}
    assert ctx.layout.get("window") == b"\x00\x01\x02"
    assert not (home / "settings.json").exists() and not (home / "layout.json").exists()
    assert (ctx.workspace_dir / "settings.json").exists()


def test_what_was_kept_before_is_moved_once_and_not_over_what_is_there(home):
    workspaces._ensure()
    default = workspaces.dir_for(workspaces.DEFAULT)
    (default / "settings.json").write_text(json.dumps({"mine": 1}), encoding="utf-8")
    # One put back by hand, or by an older pyscopegui run since: left alone.
    (home / "settings.json").write_text(json.dumps({"older": 1}), encoding="utf-8")
    assert Context().settings.get("mine") == 1
    assert (home / "settings.json").exists()


# --- which one is in use -------------------------------------------------------------------
def test_the_choice_is_remembered(home):
    workspaces.create("Work bench")
    workspaces.set_active("Work bench")
    assert workspaces.active() == "Work bench"


def test_a_pointer_to_a_workspace_that_is_gone_falls_back(home):
    """Deleted by hand, or a file typed wrong: still a working tool."""
    workspaces.create("gone")
    workspaces.set_active("gone")
    shutil.rmtree(workspaces.dir_for("gone"))
    assert workspaces.active() == workspaces.DEFAULT


def test_a_damaged_pointer_falls_back_too(home):
    workspaces._ensure()
    (home / workspaces.POINTER).write_text("not json at all", encoding="utf-8")
    assert workspaces.active() == workspaces.DEFAULT


def test_default_is_listed_first(home):
    for name in ("zebra", "alpha"):
        workspaces.create(name)
    assert workspaces.names() == [workspaces.DEFAULT, "alpha", "zebra"]


# --- naming one ------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["Work bench", "home-2", "rev_1.4", "A"])
def test_names_people_would_type(home, name):
    assert workspaces.why_not(name) == ""


@pytest.mark.parametrize(
    ("name", "because"),
    [
        ("", "needs a name"),
        ("   ", "needs a name"),
        ("../escape", "folder name"),
        ("bench/2", "folder name"),
        (".hidden", "folder name"),
        ("con", "Windows"),
        ("COM7", "Windows"),
        ("x" * 65, "at most"),
    ],
)
def test_names_that_would_not_survive_being_a_folder(home, name, because):
    """A reason rather than a silent tidy-up: they typed it, so tell them."""
    assert because in workspaces.why_not(name)


def test_the_space_around_a_typed_name_is_not_part_of_it(home):
    assert workspaces.why_not(" bench ") == ""
    workspaces.create(" bench ")
    assert workspaces.exists("bench")


def test_a_name_already_taken_is_refused(home):
    workspaces.create("bench")
    assert "already a workspace" in workspaces.why_not("bench")


def test_creating_a_bad_name_raises_rather_than_making_a_mess(home):
    with pytest.raises(ValueError):
        workspaces.create("../escape")


def test_a_name_offered_is_one_that_will_do(home):
    workspaces.create("workspace")
    assert workspaces.next_free() == "workspace 2"
    assert workspaces.next_free("bad/name") == "workspace 2"


# --- making, renaming, removing ---------------------------------------------------------------
def filled_default():
    workspaces._ensure()
    default = workspaces.dir_for(workspaces.DEFAULT)
    (default / "settings.json").write_text(json.dumps({RIGOL: {"address": "a"}}), "utf-8")


def test_save_as_keeps_what_was_on_screen(home):
    filled_default()
    workspaces.create("Work bench", copy_from=workspaces.DEFAULT)
    forked = workspaces.dir_for("Work bench")
    assert json.loads((forked / "settings.json").read_text())[RIGOL] == {"address": "a"}


def test_a_fork_is_a_copy_and_not_a_share(home):
    filled_default()
    workspaces.create("other", copy_from=workspaces.DEFAULT)
    (workspaces.dir_for("other") / "settings.json").write_text("{}", encoding="utf-8")
    default = workspaces.dir_for(workspaces.DEFAULT)
    assert json.loads((default / "settings.json").read_text())[RIGOL] == {"address": "a"}


def test_renaming_takes_the_pointer_with_it(home):
    workspaces.create("old name")
    workspaces.set_active("old name")
    workspaces.rename("old name", "new name")
    assert workspaces.active() == "new name"
    assert not workspaces.exists("old name")


def test_the_default_cannot_be_renamed_or_deleted(home):
    with pytest.raises(ValueError):
        workspaces.rename(workspaces.DEFAULT, "something else")
    with pytest.raises(ValueError):
        workspaces.delete(workspaces.DEFAULT)


def test_the_one_in_use_cannot_be_deleted(home):
    workspaces.create("bench")
    workspaces.set_active("bench")
    with pytest.raises(ValueError, match="Switch to another one first"):
        workspaces.delete("bench")


def test_deleting_takes_the_folder_with_it(home):
    workspaces.create("scrap")
    workspaces.delete("scrap")
    assert not workspaces.exists("scrap")
    assert "scrap" not in workspaces.names()


# --- what belongs to which -------------------------------------------------------------------
def test_the_settings_and_layout_live_in_the_workspace_folder(home):
    ctx = Context()
    ctx.settings.set(RIGOL, {"address": "b"})
    ctx.layout.set("window", b"\x01\x02\x03")
    assert ctx.workspace_dir == workspaces.dir_for(workspaces.DEFAULT)
    assert (ctx.workspace_dir / "settings.json").exists()
    assert Layout(ctx.workspace_dir / "layout.json").get("window") == b"\x01\x02\x03"


def test_the_user_folder_itself_is_still_the_user_folder(home):
    (home / "capture.csv").write_text("x", encoding="utf-8")
    workspaces._ensure()
    assert (home / "capture.csv").exists()
    assert paths.user_dir() == home


# --- the menu, the title and the switch ----------------------------------------------------
@pytest.fixture
def win(app, home):
    from pyscopegui.ui.main_window import MainWindow

    QSettings().clear()
    made = MainWindow()
    made.show()
    app.processEvents()
    yield made
    made.close()
    made.deleteLater()


def switch_menu(window):
    """The Switch to submenu, rebuilt as opening the menu would rebuild it."""
    window.workspace_menu._build()
    return next(a.menu() for a in window.workspace_menu.menu.actions() if a.menu())


def test_one_bench_never_meets_the_word(win):
    assert win.windowTitle() == f"{APP_NAME} {__version__}"
    assert [a.text() for a in switch_menu(win).actions()] == [workspaces.DEFAULT]


def test_the_workspace_menu_is_in_the_file_menu_above_exit(win):
    file_menu = next(a.menu() for a in win.menuBar().actions() if a.text() == "&File")
    texts = [a.text() for a in file_menu.actions() if not a.isSeparator()]
    assert texts == [
        "Open capture...",
        "Save capture...",
        "Export CSV...",
        "Export PNG...",
        "Workspace",
        "Exit",
    ]
    inside = [a.text() for a in win.workspace_menu.menu.actions()]
    assert inside == ["New...", "Save as...", "Switch to", "Manage...", "", "Open folder"]


def test_switch_to_lists_them_all_and_ticks_the_one_in_use(win):
    workspaces.create("bench")
    actions = switch_menu(win).actions()
    assert [a.text() for a in actions] == [workspaces.DEFAULT, "bench"]
    assert [a.isChecked() for a in actions] == [True, False]


def test_new_makes_an_empty_one_and_asks_to_open_it(win, monkeypatch):
    win.add_instrument("rigol1000z")
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Test rig", True))
    asked: list[str] = []
    win.workspace_menu.switch_requested.connect(asked.append)
    win.workspace_menu.new_empty()
    assert asked == ["Test rig"]
    made = workspaces.dir_for("Test rig") / "settings.json"
    assert not made.exists() or "instruments.added" not in json.loads(made.read_text())


def test_save_as_forks_what_is_on_screen_and_asks_to_open_it(win, monkeypatch):
    win.add_instrument("rigol1000z")
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Home bench", True))
    asked: list[str] = []
    win.workspace_menu.switch_requested.connect(asked.append)
    win.workspace_menu._save_as()
    assert asked == ["Home bench"], "and switching to it is somebody else's job"
    forked = json.loads((workspaces.dir_for("Home bench") / "settings.json").read_text())
    assert forked["instruments.added"] == ["demo", "rigol1000z"]


def test_save_as_with_a_name_that_will_not_do_makes_nothing(win, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("../escape", True))
    said: list[str] = []
    monkeypatch.setattr(messages, "warning", lambda _p, _t, text, *a, **k: said.append(text))
    asked: list[str] = []
    win.workspace_menu.switch_requested.connect(asked.append)
    win.workspace_menu._save_as()
    assert asked == []
    assert said and "folder name" in said[0], "told why, rather than quietly repaired"
    assert workspaces.names() == [workspaces.DEFAULT]


def test_cancelling_save_as_does_nothing(win, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("bench", False))
    win.workspace_menu._save_as()
    assert workspaces.names() == [workspaces.DEFAULT]


def test_switching_to_the_one_you_are_in_does_nothing(win):
    asked: list[str] = []
    win.reopen_requested.connect(asked.append)
    win._switch_workspace(workspaces.DEFAULT)
    assert asked == []


def test_switching_with_nothing_open_does_not_ask(win, monkeypatch):
    monkeypatch.setattr(QMessageBox, "exec", lambda *a, **k: pytest.fail("nothing to lose"))
    workspaces.create("bench")
    asked: list[str] = []
    win.reopen_requested.connect(asked.append)
    win._switch_workspace("bench")
    assert asked == ["bench"]


def test_switching_away_from_an_open_instrument_asks_first(win, monkeypatch):
    win.open_instrument()
    assert win.instrument.is_open
    workspaces.create("bench")
    seen: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "exec",
        lambda box: (seen.append(box.text() + " " + box.informativeText()), QMessageBox.Cancel)[1],
    )
    asked: list[str] = []
    win.reopen_requested.connect(asked.append)
    win._switch_workspace("bench")
    assert asked == [], "cancelled means stay"
    assert "Demo signals is open" in seen[0] and "Open bench anyway?" in seen[0]
    assert "closes it" in seen[0]
    monkeypatch.setattr(QMessageBox, "exec", lambda _box: QMessageBox.Yes)
    win._switch_workspace("bench")
    assert asked == ["bench"]


def test_several_open_are_counted_in_the_question(win, monkeypatch):
    win.open_instrument()
    win.add_instrument("demo")
    win.open_instrument()
    workspaces.create("bench")
    seen: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "exec", lambda box: (seen.append(box.informativeText()), QMessageBox.No)[1]
    )
    win._switch_workspace("bench")
    assert seen[0].startswith("2 instruments are open") and "closes them" in seen[0]


def test_the_title_names_a_workspace_that_is_not_the_default(app, home):
    from pyscopegui.ui.main_window import MainWindow

    workspaces.create("Work bench")
    workspaces.set_active("Work bench")
    made = MainWindow()
    assert made.windowTitle().endswith(" - Work bench")
    made.close()
    made.deleteLater()


def test_what_a_switch_actually_does(app, home):
    """The window is replaced rather than persuaded: the settings and the layout
    are read once, while it is being built."""
    from pyscopegui.ui.main_window import MainWindow
    from pyscopegui.ui.windows import Windows

    QSettings().clear()
    windows = Windows(MainWindow)
    first = windows.open()
    first.add_instrument("rigol1000z")
    first.open_instrument("demo")
    demo = first.session.units["demo"].instrument
    workspaces.create("second")

    second = windows.reopen("second")
    assert second is not first
    assert not first.isVisible(), "the one that asked is the one that goes"
    assert not demo.is_open, "and what it had open is closed"
    assert second.ctx.workspace == "second"
    assert second.added == ["demo"], "a workspace of its own"
    assert second.windowTitle().endswith(" - second")

    back = windows.reopen(workspaces.DEFAULT)
    assert back.added == ["demo", "rigol1000z"], "and the first is as it was"
    back.close()
    back.deleteLater()


def test_choosing_another_on_the_menu_opens_it(app, home):
    from pyscopegui.ui.main_window import MainWindow
    from pyscopegui.ui.windows import Windows

    QSettings().clear()
    workspaces.create("bench")
    windows = Windows(MainWindow)
    first = windows.open()
    first.workspace_menu._switch("bench")
    app.processEvents()
    assert windows.window is not first
    assert windows.window.ctx.workspace == "bench"
    assert workspaces.active() == "bench", "and it is the one opened next time"
    windows.window.close()
    windows.window.deleteLater()


def test_switching_to_a_workspace_that_is_not_there_stays_put(app, home):
    from pyscopegui.ui.main_window import MainWindow
    from pyscopegui.ui.windows import Windows

    QSettings().clear()
    windows = Windows(MainWindow)
    windows.open()
    windows.reopen("never made")
    assert windows.window.ctx.workspace == workspaces.DEFAULT
    windows.window.close()
    windows.window.deleteLater()


def test_open_folder_opens_the_workspace_in_use(win, monkeypatch):
    """The settings and the layout are in it: there is no other folder to open."""
    from PySide6.QtGui import QDesktopServices

    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url))
    win.workspace_menu.folder_action.trigger()
    assert opened[0].toLocalFile().rstrip("/\\").endswith(workspaces.DEFAULT)
    tools = next(a.menu() for a in win.menuBar().actions() if a.text() == "&Tools")
    assert "Open settings folder" not in [a.text() for a in tools.actions()]


# --- managing them ----------------------------------------------------------------------------
def rows_of(dialog) -> dict[str, int]:
    return {dialog.list.item(i).data(Qt.UserRole): i for i in range(dialog.list.count())}


def test_manage_will_not_offer_to_remove_the_ground_you_stand_on(app, home):
    from pyscopegui.ui.workspace_menu import ManageWorkspaces

    workspaces.create("bench")
    workspaces.create("spare")
    dialog = ManageWorkspaces(None, current="bench")
    rows = rows_of(dialog)
    for name, enabled, why in (
        (workspaces.DEFAULT, False, "always there"),
        ("bench", False, "Switch to another one first"),
        ("spare", True, ""),
    ):
        dialog.list.setCurrentRow(rows[name])
        assert dialog.delete.isEnabled() == enabled, name
        assert dialog.rename.isEnabled() == enabled, name
        assert why in dialog.rename.toolTip()
    dialog.deleteLater()


def test_manage_deletes_one_that_is_not_in_use(app, home, monkeypatch):
    from pyscopegui.ui.workspace_menu import ManageWorkspaces

    workspaces.create("scrap")
    dialog = ManageWorkspaces(None, current=workspaces.DEFAULT)
    dialog.list.setCurrentRow(rows_of(dialog)["scrap"])
    monkeypatch.setattr(messages, "warning", lambda *a, **k: QMessageBox.Cancel)
    dialog._delete()
    assert workspaces.exists("scrap"), "Cancel keeps it"
    monkeypatch.setattr(messages, "warning", lambda *a, **k: QMessageBox.Yes)
    dialog._delete()
    assert not workspaces.exists("scrap")
    dialog.deleteLater()


def test_manage_renames_and_the_list_follows(app, home, monkeypatch):
    from pyscopegui.ui.workspace_menu import ManageWorkspaces

    workspaces.create("old")
    dialog = ManageWorkspaces(None, current=workspaces.DEFAULT)
    dialog.list.setCurrentRow(rows_of(dialog)["old"])
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("new", True))
    dialog._rename()
    assert workspaces.exists("new") and not workspaces.exists("old")
    assert "new" in rows_of(dialog)
    dialog.deleteLater()
