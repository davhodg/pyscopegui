# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The window: its panes, running an instrument, and what it remembers."""

from pyscopegui import backends
from pyscopegui.backends import demo
from pyscopegui.core.capture import HISTORIES, HISTORY_S
from pyscopegui.ui.main_window import (
    DEFAULT_VISIBLE,
    MainWindow,
    short_bytes,
    short_rate,
    short_time,
)


def feed(window, seconds=0.05):
    """Have the running demo send one block holding this much time."""
    window.instrument._started -= seconds
    window.instrument._tick()


def test_it_opens_with_the_settings_the_plot_and_the_log(window):
    assert set(window.panes.names()) == set(DEFAULT_VISIBLE)
    assert all(window.panes.on_screen(name) for name in DEFAULT_VISIBLE)


def test_the_view_menu_lists_every_pane_ticked(window):
    window._build_view_menu()
    assert list(window._view_actions) == ["instrument", "scope", "log"]
    assert all(action.isChecked() for action in window._view_actions.values())


def test_run_fills_the_plot_from_the_demo(window):
    window.set_mode("auto")
    assert window.instrument.running
    feed(window)
    assert set(window.capture.records) == {c.key for c in demo.CHANNELS}
    assert window.capture.newest() >= 0.05
    window.scope.redraw()
    times, values = window.scope._curves["demo:A"].getData()
    assert len(times) == len(values) > 0
    assert "running" in window.log.toPlainText()


def test_stop_keeps_what_was_collected(window):
    window.set_mode("auto")
    feed(window)
    window.set_mode("stop")
    assert not window.instrument.running
    assert window.capture.stored() > 0
    assert window.instrument_bar.mode() == "stop"
    assert window.instrument.is_open, "stopped, and still open"


def test_a_long_capture_is_drawn_as_a_few_points_a_column(window):
    window.set_mode("auto")
    for _ in range(8):
        feed(window, 0.4)
    window.scope.time.setCurrentText("All")
    window.scope.redraw()
    times, _values = window.scope._curves["demo:A"].getData()
    assert window.capture.records["A"].count > 200_000
    assert len(times) <= 2 * window.scope.analog.getViewBox().width() + 2


def test_an_unticked_channel_is_not_drawn_and_stays_unticked(window, app):
    window.set_mode("auto")
    feed(window)
    window.scope._on_shown("demo:D1", False)
    assert "demo:D1" not in window.scope.shown()
    assert "demo:D1" not in window.scope._lanes
    window.close()
    again = MainWindow()
    try:
        again.run("demo")
        assert "demo:D1" not in again.scope.shown()
    finally:
        again.close()


def test_dragging_the_plot_stops_it_following(window):
    window.scope._on_dragged()
    assert window.scope.time.currentText() == "Manual"
    assert not window.scope.window_s.isEnabled()


def test_a_second_plot_can_be_opened_and_removed(window):
    name = window.panes.add("scope", floating=True)
    assert name == "scope 2"
    assert window.panes.docks[name].windowTitle() == "Channels and Plot 2"
    window.panes.remove(name)
    assert name not in window.panes.names()


def test_a_back_end_that_will_not_load_is_said_and_not_raised(window, monkeypatch):
    def broken(name, parent=None, options=None):
        raise ImportError("no such library")

    monkeypatch.setattr(backends, "create", broken)
    window.set_mode("auto")
    assert "could not be started" in window.log.toPlainText()
    assert window.instrument is None
    assert window.instrument_bar.mode() == "stop"
    assert window.instrument_view.open.text() == "Open"


def test_the_instrument_chosen_is_remembered(window):
    assert window.chosen == backends.DEFAULT and window.added == [backends.DEFAULT]
    window.choose("picoscope2000")
    assert window.ctx.settings.get("instrument.name") == "picoscope2000"
    assert window.ctx.settings.get("instruments.added") == [backends.DEFAULT, "picoscope2000"]


# --- open and close, and the four a scope has --------------------------------------------------
def press(window, mode):
    """Press a mode's button the way somebody does."""
    window.instrument_bar.modes[mode].click()


def test_it_starts_closed_and_stopped(window):
    assert window.instrument_view.open.text() == "Open"
    assert window.instrument_bar.mode() == "stop"
    assert window.instrument is None


def test_open_connects_and_reads_nothing(window):
    view = window.instrument_view
    view.open.click()
    assert window.instrument.is_open and not window.instrument.running
    assert view.open.text() == "Close"
    assert view.instruments.tabText(0) == "Demo \u25cf"
    assert "Open." in view.instruments.tabToolTip(0)
    assert window.instrument_bar.add.isEnabled(), "another can be added, and opened beside it"
    assert window.capture.stored() == 0
    assert set(window.capture.records) == {c.key for c in demo.CHANNELS}, "its channels, empty"
    assert "open, stopped" in window.status.text()


def test_close_lets_go_and_keeps_what_is_on_the_plot(window):
    press(window, "auto")
    feed(window)
    window.instrument_view.open.click()  # which says Close while it is open
    assert not window.instrument.is_open and not window.instrument.running
    assert window.instrument_view.open.text() == "Open"
    assert window.instrument_bar.mode() == "stop"
    assert window.capture.stored() > 0


def test_a_run_button_opens_the_instrument_if_it_is_not_open(window):
    press(window, "normal")
    assert window.instrument.is_open and window.instrument.running
    assert window.instrument_view.open.text() == "Close"
    assert window.instrument_bar.mode() == "normal" == window.acquisition.mode


def test_changing_between_normal_and_auto_keeps_the_run_going(window):
    press(window, "auto")
    feed(window)
    held = window.capture.stored()
    press(window, "normal")
    assert window.instrument.running and window.capture.stored() == held
    assert window.acquisition.mode == "normal"


def test_stop_then_a_run_button_starts_from_an_empty_plot(window):
    press(window, "auto")
    feed(window)
    press(window, "stop")
    assert window.capture.stored() > 0
    press(window, "auto")
    assert window.capture.stored() == 0
    assert window.instrument.running


def test_choosing_another_instrument_lets_go_of_the_one_there_was(window, monkeypatch):
    from tests.test_instrument_view import FakeScope

    fake = FakeScope(monkeypatch)
    press(window, "auto")
    first = window.instrument
    window.close_instrument()
    window.choose("picoscope2000")
    window.instrument_view.open.click()
    assert window.instrument is not first
    assert set(window.capture.records) == {"A", "B"}
    window.close_instrument()
    assert ("close",) in fake.library.calls or ("open",) not in fake.library.calls


def test_an_instrument_that_stops_by_itself_is_shown_stopped(window):
    press(window, "auto")
    window.instrument.stop()  # as a scope that was unplugged would
    assert window.instrument_bar.mode() == "stop" == window.acquisition.mode


# --- how much is kept --------------------------------------------------------------------------
def history_actions(window):
    return {action.text(): action for action in window.history_menu.actions()}


def test_the_history_menu_offers_every_length_with_the_default_ticked(window):
    actions = history_actions(window)
    assert list(actions) == [short_time(s) for s in HISTORIES]
    assert [text for text, a in actions.items() if a.isChecked()] == [short_time(HISTORY_S)]
    assert window.capture.history_s == HISTORY_S


def test_a_history_chosen_is_used_at_the_next_run_and_remembered(window, app):
    history_actions(window)["1 s"].trigger()
    window.set_mode("auto")
    assert window.capture.records["A"].capacity == 100_000
    assert "Keeping the last 1 s of each channel" in window.log.toPlainText()
    window.close()
    again = MainWindow()
    try:
        assert again.capture.history_s == 1.0
        assert history_actions(again)["1 s"].isChecked()
    finally:
        again.close()


def test_changing_the_history_while_running_starts_it_again_at_that_size(window):
    window.set_mode("auto")
    feed(window)
    history_actions(window)["30 s"].trigger()
    assert window.instrument.running
    assert window.capture.records["A"].capacity == 3_000_000
    assert window.capture.stored() == 0, "from an empty plot"


def test_a_saved_history_that_is_not_one_of_the_choices_is_the_default(window):
    window.ctx.settings.set("capture.history_s", "forever")
    window.close()
    again = MainWindow()
    try:
        assert again.capture.history_s == HISTORY_S
    finally:
        again.close()


def test_a_history_there_is_no_room_for_is_said_and_nothing_is_started(window, monkeypatch):
    def no_room(channels, rate, capacity=None):
        raise MemoryError

    monkeypatch.setattr(window.capture, "set_channels", no_room)
    window.set_mode("auto")
    assert "not enough memory to keep 10 s" in window.log.toPlainText()
    assert not window.instrument.running
    assert window.instrument_bar.mode() == "stop"


def test_lengths_of_time_and_memory_are_said_the_way_they_are_spoken():
    assert [short_time(s) for s in (1, 30, 60, 600)] == ["1 s", "30 s", "1 min", "10 min"]
    assert [short_time(s) for s in (2.3742, 0.001, 80e-6, 0)] == ["2.37 s", "1 ms", "80 us", "0 s"]
    assert short_bytes(120_000_000) == "120 MB"
    assert short_bytes(7_200_000_000) == "7.2 GB"
    assert short_bytes(9_000) == "9 kB"


def test_a_rate_is_said_the_way_it_is_spoken():
    assert short_rate(100_000) == "100 kS/s"
    assert short_rate(1_000_000) == "1 MS/s"
    assert short_rate(48_800) == "48.8 kS/s"
    assert short_rate(500) == "500 S/s"


# --- where a shortcut is made, said once ---------------------------------------------------------
def test_the_first_start_says_where_a_shortcut_is_made_and_the_next_does_not(window, monkeypatch):
    from PySide6.QtCore import QSettings

    from pyscopegui.core import shortcut
    from pyscopegui.ui.main_window import SHORTCUT_TOLD_KEY

    monkeypatch.setattr(shortcut, "made", lambda *_a, **_k: False)
    window.close()
    QSettings().remove(SHORTCUT_TOLD_KEY)
    first = MainWindow()
    try:
        assert "Tools > Settings > Add shortcut. This is said once." in first.log.toPlainText()
    finally:
        first.close()
    again = MainWindow()
    try:
        assert "Add shortcut" not in again.log.toPlainText()
    finally:
        again.close()


def test_it_is_not_said_where_there_is_a_shortcut_already(window, monkeypatch):
    from PySide6.QtCore import QSettings

    from pyscopegui.core import shortcut
    from pyscopegui.ui.main_window import SHORTCUT_TOLD_KEY

    monkeypatch.setattr(shortcut, "made", lambda *_a, **_k: True)
    window.close()
    QSettings().remove(SHORTCUT_TOLD_KEY)
    again = MainWindow()
    try:
        assert "Add shortcut" not in again.log.toPlainText()
    finally:
        again.close()


def test_settings_offers_a_shortcut_in_each_place_there_is(window):
    import sys

    assert window.shortcut_action is not None, "a source folder has a launcher to point at"
    assert (window.desktop_action is not None) == (sys.platform == "win32")
