# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""A channel given a name of its own: shown with which channel it is, in the list,
the trigger's sources and an export's headings, and kept with the workspace and
in a saved capture."""

import pytest
from PySide6.QtWidgets import QInputDialog

from pyscopegui.ui.scope_view import LABELS, NAME


@pytest.fixture
def held(window):
    """A window with half a second of the demo held, and stopped."""
    window.set_mode("auto")
    window.instrument._started -= 0.5
    window.instrument._tick()
    window.set_mode("stop")
    return window


def listed(window, key):
    return window.scope.channel_list._items[key].text(NAME)


def test_a_name_given_is_shown_with_which_channel_it_is(held):
    held.scope.rename("demo:A", "  5V   rail ")
    assert listed(held, "demo:A") == "5V rail (A: sine)", "spaces tidied"
    assert held.session.labels == {"demo:A": "5V rail"}
    assert held.ctx.settings.get(LABELS) == {"demo:A": "5V rail"}, "kept with the workspace"


def test_with_two_instruments_it_says_whose_as_well(held):
    held.add_instrument("demo")
    held.open_instrument()  # the second, on the plot beside the first
    held.scope.rename("demo:A", "5V rail")
    assert listed(held, "demo:A") == "5V rail (Demo A: sine)"


def test_an_empty_name_puts_back_the_instruments_own(held):
    held.scope.rename("demo:A", "5V rail")
    held.scope.rename("demo:A", " ")
    assert listed(held, "demo:A") == "A: sine" and held.session.labels == {}


def test_the_trigger_offers_it_by_its_name(held):
    held.scope.rename("demo:A", "5V rail")
    source = held.trigger_bar.source
    assert source.itemText(source.findData("A")) == "5V rail (A: sine)"


def test_an_export_is_headed_with_it(held, tmp_path):
    held.scope.rename("demo:A", "5V rail")
    held.scope.window_s.setValue(0.01)
    written = held.scope.export_csv(tmp_path / "shot.csv")
    heading = written[0].path.read_text(encoding="utf-8").splitlines()[0]
    assert "5V rail (A: sine) (V)" in heading


def test_a_saved_capture_keeps_the_names_and_opens_with_them(held, tmp_path, app):
    held.scope.rename("demo:A", "5V rail")
    saved = held.scope.save_captures(tmp_path / "shot")
    held.open_capture(saved[0])
    app.processEvents()
    assert held.session.labels.get("file:A") == "5V rail"
    assert listed(held, "file:A").startswith("5V rail (")


def test_rename_asks_for_the_name_and_cancel_changes_nothing(held, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Clock", True))
    held.scope._on_rename_asked("demo:B")
    assert held.session.labels == {"demo:B": "Clock"}
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Other", False))
    held.scope._on_rename_asked("demo:B")
    assert held.session.labels == {"demo:B": "Clock"}


def test_the_names_are_there_on_starting_again(app):
    from pyscopegui.ui.main_window import MainWindow

    window = MainWindow()
    try:
        window.scope.rename("demo:A", "5V rail")
    finally:
        window.close()
        window.deleteLater()
    again = MainWindow()
    try:
        assert again.session.labels == {"demo:A": "5V rail"}
    finally:
        again.close()
        again.deleteLater()
