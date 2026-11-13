# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Clear on the right-click of the Event Log, the Python Console and Instrument traffic."""

from pyscopegui.ui import icons


def cleared_by_its_menu(text):
    """Press Clear in the menu the text pane's right-click makes: what it offered."""
    menu = text.clear_menu()
    offered = [a.text().split("\t")[0].replace("&", "") for a in menu.actions() if a.text()]
    last = menu.actions()[-1]
    assert last.text() == "Clear all" and last.property(icons.PROPERTY) == icons.CLEAR
    last.trigger()
    menu.deleteLater()
    return offered


def test_the_console_and_the_log_clear_from_their_menus_under_copy(window):
    for text in (window.console.output, window.log):
        text.setPlainText("something said")
        offered = cleared_by_its_menu(text)
        assert offered[0] == "Copy" and offered[-2:] == ["Save all...", "Clear all"]
        assert text.toPlainText() == ""


def test_traffic_clears_what_it_holds_too_not_only_the_text(window, monkeypatch):
    view = window.traffic
    cleared = []
    monkeypatch.setattr(type(view), "clear", lambda self: cleared.append(True))
    view.text.setPlainText("> *IDN?")
    # The pane's own Clear, as its button is, which forgets what is held as well.
    cleared_by_its_menu(view.text)
    assert cleared == [True]


def test_save_all_writes_the_whole_pane_and_remembers_the_folder(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from pyscopegui.ui import clear_menu

    offered = []

    def asked(parent, title, start, kinds):
        offered.append((title, start))
        return str(tmp_path / "log.txt"), kinds

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(asked))
    window.log.setPlainText("first\nsecond")
    window.log.selectAll()  # whatever is selected, it is all of it
    save = next(a for a in window.log.clear_menu().actions() if a.text() == "Save all...")
    save.trigger()
    assert (tmp_path / "log.txt").read_text(encoding="utf-8") == "first\nsecond\n"
    title, start = offered[0]
    assert title == "Save Event Log" and "event-log_" in start and start.endswith(".txt")
    assert window.ctx.settings.get(clear_menu.TEXT_FOLDER) == str(tmp_path)
    assert "Event Log written to" in window.log.toPlainText()


def test_save_all_is_greyed_out_with_nothing_to_save(window):
    window.console.output.clear()
    menu = window.console.output.clear_menu()
    save = next(a for a in menu.actions() if a.text() == "Save all...")
    assert not save.isEnabled()


def test_a_stamped_name_sorts_by_when():
    from datetime import datetime

    from pyscopegui.ui.clear_menu import stamped

    assert stamped("event-log", ".txt", datetime(2026, 11, 13, 14, 30, 12)) == (
        "event-log_2026-11-13_143012.txt"
    )
