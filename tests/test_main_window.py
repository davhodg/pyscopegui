# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The window: its panes, running an instrument, and what it remembers."""

from pyscopegui import backends
from pyscopegui.backends import demo
from pyscopegui.ui.main_window import DEFAULT_VISIBLE, MainWindow, short_rate


def feed(window, seconds=0.05):
    """Have the running demo send one block holding this much time."""
    window.instrument._started -= seconds
    window.instrument._tick()


def test_it_opens_with_the_plot_and_the_log(window):
    assert set(window.panes.names()) == set(DEFAULT_VISIBLE)
    assert all(window.panes.on_screen(name) for name in DEFAULT_VISIBLE)


def test_the_view_menu_lists_every_pane_ticked(window):
    window._build_view_menu()
    assert list(window._view_actions) == ["scope", "log"]
    assert all(action.isChecked() for action in window._view_actions.values())


def test_run_fills_the_plot_from_the_demo(window):
    window.instrument_bar.run.setChecked(True)
    assert window.instrument.running
    feed(window)
    assert set(window.capture.records) == {c.key for c in demo.CHANNELS}
    assert window.capture.newest() >= 0.05
    window.scope.redraw()
    times, values = window.scope._curves["A"].getData()
    assert len(times) == len(values) > 0
    assert "running" in window.log.toPlainText()


def test_stop_keeps_what_was_collected(window):
    window.instrument_bar.run.setChecked(True)
    feed(window)
    window.instrument_bar.run.setChecked(False)
    assert not window.instrument.running
    assert window.capture.stored() > 0
    assert window.instrument_bar.run.text() == "Run"
    assert window.instrument_bar.instrument.isEnabled()


def test_a_long_capture_is_drawn_as_a_few_points_a_column(window):
    window.instrument_bar.run.setChecked(True)
    for _ in range(8):
        feed(window, 0.4)
    window.scope.time.setCurrentText("All")
    window.scope.redraw()
    times, _values = window.scope._curves["A"].getData()
    assert window.capture.records["A"].count > 200_000
    assert len(times) <= 2 * window.scope.analog.getViewBox().width() + 2


def test_an_unticked_channel_is_not_drawn_and_stays_unticked(window, app):
    window.instrument_bar.run.setChecked(True)
    feed(window)
    window.scope._on_shown("D1", False)
    assert "D1" not in window.scope.shown()
    assert "D1" not in window.scope._lanes
    window.close()
    again = MainWindow()
    try:
        again.run("demo")
        assert "D1" not in again.scope.shown()
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
    def broken(name, parent=None):
        raise ImportError("no such library")

    monkeypatch.setattr(backends, "create", broken)
    window.instrument_bar.run.setChecked(True)
    assert "could not be started" in window.log.toPlainText()
    assert window.instrument is None
    assert not window.instrument_bar.run.isChecked()


def test_the_instrument_chosen_is_remembered(window):
    assert window.instrument_bar.current() == backends.DEFAULT
    window.instrument_bar.instrument.currentIndexChanged.emit(0)
    assert window.ctx.settings.get("instrument.name") == backends.DEFAULT


def test_a_rate_is_said_the_way_it_is_spoken():
    assert short_rate(100_000) == "100 kS/s"
    assert short_rate(1_000_000) == "1 MS/s"
    assert short_rate(48_800) == "48.8 kS/s"
    assert short_rate(500) == "500 S/s"
