# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Clear on the right-click of the Event Log, the Python Console and Instrument traffic."""

from pyscopegui.ui import icons


def cleared_by_its_menu(text):
    """Press Clear in the menu the text pane's right-click makes: what it offered."""
    menu = text.clear_menu()
    offered = [a.text().split("\t")[0].replace("&", "") for a in menu.actions() if a.text()]
    last = menu.actions()[-1]
    assert last.text() == "Clear" and last.property(icons.PROPERTY) == icons.CLEAR
    last.trigger()
    menu.deleteLater()
    return offered


def test_the_console_and_the_log_clear_from_their_menus_under_copy(window):
    for text in (window.console.output, window.log):
        text.setPlainText("something said")
        offered = cleared_by_its_menu(text)
        assert offered[0] == "Copy" and offered[-1] == "Clear"
        assert text.toPlainText() == ""


def test_traffic_clears_what_it_holds_too_not_only_the_text(window, monkeypatch):
    view = window.traffic
    cleared = []
    monkeypatch.setattr(type(view), "clear", lambda self: cleared.append(True))
    view.text.setPlainText("> *IDN?")
    # The pane's own Clear, as its button is, which forgets what is held as well.
    cleared_by_its_menu(view.text)
    assert cleared == [True]
