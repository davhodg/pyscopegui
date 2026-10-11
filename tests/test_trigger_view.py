# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The trigger toolbar, and what a plot draws with a trigger chosen."""

import numpy as np

from pyscopegui.backends import demo
from pyscopegui.ui.main_window import MainWindow
from pyscopegui.ui.scope_view import FREE, STOPPED, TRIGGERED, WAITING


def feed(window, seconds=0.1):
    """Have the running demo send one block holding this much time."""
    window.instrument._started -= seconds
    window.instrument._tick()


def choose_source(window, key):
    box = window.trigger_bar.source
    box.setCurrentIndex(box.findData(key))
    box.activated.emit(box.currentIndex())


def x_range(scope):
    return scope.analog.getViewBox().viewRange()[0]


# --- the toolbar -------------------------------------------------------------------------------
def test_the_trigger_starts_as_none_with_nothing_to_set(window):
    bar = window.trigger_bar
    assert bar.source.currentText() == "None"
    assert not bar.level.isEnabled() and not bar.edge.isEnabled()
    assert not window.acquisition.triggered()


def test_the_sources_are_the_channels_of_the_instrument_that_is_open(window):
    window.instrument_bar.open.click()
    box = window.trigger_bar.source
    listed = [box.itemData(i) for i in range(box.count())]
    assert listed == [None, *(c.key for c in demo.CHANNELS)]


def test_a_level_is_offered_for_an_analog_source_and_not_for_a_digital_one(window):
    window.instrument_bar.open.click()
    choose_source(window, "A")
    assert window.trigger_bar.level.isEnabled() and window.trigger_bar.edge.isEnabled()
    choose_source(window, "D0")
    assert not window.trigger_bar.level.isEnabled() and window.trigger_bar.edge.isEnabled()


def test_what_the_toolbar_says_is_what_is_waited_for(window):
    window.instrument_bar.open.click()
    choose_source(window, "A")
    bar = window.trigger_bar
    bar.level.setValue(0.75)
    bar.edge.setCurrentText("Falling")
    bar.edge.activated.emit(1)
    bar.position.setValue(20)
    acquisition = window.acquisition
    assert (acquisition.source, acquisition.level, acquisition.rising) == ("A", 0.75, False)
    assert acquisition.position == 0.2


def test_the_trigger_is_remembered(window):
    window.instrument_bar.open.click()
    choose_source(window, "A")
    window.trigger_bar.level.setValue(1.25)
    window.trigger_bar.position.setValue(30)
    window.close()
    again = MainWindow()
    try:
        assert again.trigger_bar.level.value() == 1.25
        assert again.trigger_bar.position.value() == 30
        again.instrument_bar.open.click()
        assert again.trigger_bar.source.currentData() == "A"
        assert again.acquisition.source == "A"
    finally:
        again.close()


def test_a_source_the_next_instrument_does_not_have_is_none(window, monkeypatch):
    from tests.test_instrument_view import FakeScope

    FakeScope(monkeypatch)
    window.instrument_bar.open.click()
    choose_source(window, "D2")
    window.close_instrument()
    box = window.instrument_bar.instrument
    box.setCurrentIndex(box.findData("picoscope2000"))
    window.instrument_bar.open.click()
    assert window.trigger_bar.source.currentData() is None
    assert not window.acquisition.triggered()
    window.close_instrument()


# --- the plot ----------------------------------------------------------------------------------
def test_with_no_trigger_the_plot_follows_the_newest_samples(window):
    window.set_mode("auto")
    feed(window, 0.3)
    window.scope.redraw()
    _low, high = x_range(window.scope)
    assert abs(high - window.capture.newest()) < 1e-6
    assert window.scope.state.text() == ""
    assert not window.scope.trigger_lines[0].isVisible()


def test_with_a_trigger_time_is_measured_from_it_and_it_sits_where_position_says(window):
    window.set_mode("normal")
    choose_source(window, "A")  # the demo's sine: a rising crossing of 0 V every 20 ms
    window.trigger_bar.position.setValue(25)
    window.scope.window_s.setValue(0.04)
    feed(window, 0.3)
    window.scope.redraw()
    low, high = x_range(window.scope)
    assert abs(low - -0.01) < 1e-6 and abs(high - 0.03) < 1e-6
    assert window.scope.state.text() == TRIGGERED
    assert window.scope.trigger_lines[0].isVisible()
    # At nought the sine is crossing 0 V on its way up.
    times, values = window.scope._curves["demo:A"].getData()
    at_trigger = int(np.argmin(np.abs(times)))
    assert abs(values[at_trigger]) < 0.1 and values[at_trigger + 5] > values[at_trigger - 5]


def test_each_new_trigger_is_drawn_in_the_same_place(window):
    """What a trigger is for: a repeating signal stands still."""
    window.set_mode("normal")
    choose_source(window, "A")
    window.scope.window_s.setValue(0.04)
    feed(window, 0.2)
    window.scope.redraw()
    first = window.scope._curves["demo:A"].getData()
    origin = window.scope._origin
    feed(window, 0.137)  # no whole number of periods later
    window.scope.redraw()
    second = window.scope._curves["demo:A"].getData()
    assert window.scope._origin > origin
    assert np.allclose(first[0], second[0], atol=1e-5)
    assert np.allclose(first[1], second[1], atol=0.05)


def test_the_level_is_drawn_on_the_plot_where_the_toolbar_says(window):
    window.instrument_bar.open.click()
    assert not window.scope.level_line.isVisible()
    choose_source(window, "A")
    window.trigger_bar.level.setValue(1.5)
    assert window.scope.level_line.isVisible()
    assert window.scope.level_line.value() == 1.5
    choose_source(window, "D0")
    assert not window.scope.level_line.isVisible(), "a logic channel has no level to draw"


def test_normal_waits_and_holds_what_it_last_drew(window):
    window.set_mode("normal")
    choose_source(window, "A")
    window.trigger_bar.level.setValue(50.0)  # which the sine never reaches
    feed(window, 0.3)
    window.scope.redraw()
    assert window.scope.state.text() == WAITING
    assert len(window.scope._curves["demo:A"].getData()[0] or []) == 0, "nothing drawn yet"
    window.trigger_bar.level.setValue(0.0)
    feed(window, 0.3)
    window.scope.redraw()
    assert window.scope.state.text() == TRIGGERED
    drawn = window.scope._curves["demo:A"].getData()[1].copy()
    window.trigger_bar.level.setValue(50.0)
    feed(window, 0.3)
    window.scope.redraw()
    assert window.scope.state.text() == WAITING
    assert np.array_equal(window.scope._curves["demo:A"].getData()[1], drawn), "held"


def test_auto_shows_what_there_is_when_no_trigger_comes(window):
    window.set_mode("auto")
    choose_source(window, "A")
    window.trigger_bar.level.setValue(50.0)
    feed(window, 0.4)
    window.scope.redraw()
    assert window.scope.state.text() == FREE
    assert len(window.scope._curves["demo:A"].getData()[0]) > 0
    window.trigger_bar.level.setValue(0.0)
    feed(window, 0.4)
    window.scope.redraw()
    assert window.scope.state.text() == TRIGGERED


def test_single_catches_one_trigger_stops_and_keeps_it_on_screen(window):
    window.instrument_bar.open.click()
    choose_source(window, "A")
    window.scope.window_s.setValue(0.04)
    window.instrument_bar.modes["single"].click()
    assert window.instrument.running
    feed(window, 0.2)
    assert not window.instrument.running, "it stopped itself"
    assert window.instrument_bar.mode() == "stop"
    window.scope.redraw()
    assert window.scope.state.text() == STOPPED
    caught = window.acquisition.frozen
    assert caught is not None
    assert abs(window.scope._origin - caught / demo.RATE) < 1e-9
    times, values = window.scope._curves["demo:A"].getData()
    assert abs(values[int(np.argmin(np.abs(times)))]) < 0.1


def test_single_again_catches_another(window):
    window.instrument_bar.open.click()
    choose_source(window, "A")
    window.scope.window_s.setValue(0.04)
    window.instrument_bar.modes["single"].click()
    feed(window, 0.2)
    window.instrument_bar.modes["single"].click()
    assert window.instrument.running and window.acquisition.frozen is None
    feed(window, 0.2)
    assert not window.instrument.running and window.acquisition.frozen is not None


def test_stopping_holds_the_trigger_that_was_on_screen(window):
    window.set_mode("normal")
    choose_source(window, "A")
    feed(window, 0.3)
    window.scope.redraw()
    origin = window.scope._origin
    window.set_mode("stop")
    window.scope.redraw()
    assert window.scope._origin == origin
    assert window.scope.state.text() == STOPPED


def test_going_between_a_trigger_and_none_goes_back_to_following(window):
    window.set_mode("auto")
    choose_source(window, "A")
    feed(window, 0.3)
    window.scope.redraw()
    window.scope._on_dragged()
    assert window.scope.time.currentText() == "Manual"
    choose_source(window, None)
    window.scope.redraw()
    assert window.scope.time.currentText() == "Follow", (
        "a stretch chosen from a trigger means nothing now"
    )
    assert abs(x_range(window.scope)[1] - window.capture.newest()) < 1e-6


def test_two_plots_with_different_windows_are_held_by_the_same_trigger(window):
    second = window.panes.view(window.panes.add("scope", floating=True))
    window.set_mode("normal")
    choose_source(window, "A")
    window.scope.window_s.setValue(0.02)
    second.window_s.setValue(0.1)
    feed(window, 0.4)
    window.scope.redraw()
    second.redraw()
    assert abs(np.diff(x_range(window.scope))[0] - 0.02) < 1e-6
    assert abs(np.diff(x_range(second))[0] - 0.1) < 1e-6
    for scope in (window.scope, second):
        times, values = scope._curves["demo:A"].getData()
        assert abs(values[int(np.argmin(np.abs(times)))]) < 0.1
