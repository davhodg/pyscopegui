# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""More than one instrument open at once, on one time axis."""

import time

import pytest

from pyscopegui.backends import picoscope2000 as pico
from pyscopegui.core.capture import Capture
from pyscopegui.core.session import Session
from pyscopegui.ui.instrument_bar import OPEN_MARK
from pyscopegui.ui.main_window import MainWindow
from pyscopegui.ui.scope_view import STOPPED, TRIGGERED, ScopeView
from tests.test_rigol1000z import fake  # noqa: F401  the stand-in scope, as a fixture

RIGOL = "rigol1000z"


def wait_for(app, done, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not done() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert done(), "timed out"


def choose(window, name):
    box = window.instrument_bar.instrument
    box.setCurrentIndex(box.findData(name))


def choose_source(window, key):
    box = window.trigger_bar.source
    box.setCurrentIndex(box.findData(key))
    box.activated.emit(box.currentIndex())


def feed_demo(window, seconds=0.2):
    """Have the running demo send one block holding this much time."""
    demo = window.session.units["demo"].instrument
    demo._started -= seconds
    demo._tick()


@pytest.fixture
def both(window, fake, app):  # noqa: F811
    """The window with the demo and a pretend Rigol both open, the Rigol chosen."""
    window.ctx.settings.set(f"instrument.{RIGOL}", {"address": fake.address})
    choose(window, "demo")
    window.instrument_bar.open.click()
    choose(window, RIGOL)
    window.instrument_bar.open.click()
    wait_for(app, lambda: window.instrument.is_open)
    yield window
    for name in ("demo", RIGOL):
        choose(window, name)
        window.close_instrument()


# --- the session -------------------------------------------------------------------------------
def test_a_capture_by_itself_is_a_session_of_one(app):
    capture = Capture()
    session = Session.of(capture)
    assert [unit.capture for unit in session.units.values()] == [capture]
    assert session.units[""].id("A") == "A", "nothing to tell it apart from"
    view = ScopeView(capture)
    assert view.session.shown() == []


def test_the_same_key_on_two_instruments_is_two_channels(app):
    session = Session()
    assert session.unit("demo", "Demo").id("A") != session.unit("picoscope2000", "Pico").id("A")
    assert session.unit("demo") is session.unit("demo")


# --- opening -----------------------------------------------------------------------------------
def test_a_second_instrument_opens_beside_the_first(both):
    window = both
    units = window.session.units
    assert units["demo"].is_open and units[RIGOL].is_open
    bar = window.instrument_bar
    assert bar.instrument.isEnabled()
    marked = [bar.instrument.itemText(i).endswith(OPEN_MARK) for i in range(bar.instrument.count())]
    assert marked.count(True) == 2
    assert "Demo:" in window.status.text() and "Rigol:" in window.status.text()


def test_the_plot_lists_the_channels_of_both_and_says_whose_each_is(both):
    window = both
    assert set(window.scope._curves) >= {"demo:A", "demo:D0", f"{RIGOL}:CH1"}
    names = window.scope._names
    assert names["demo:A"].startswith("Demo ") and names[f"{RIGOL}:CH1"].startswith("Rigol CH1")


def test_one_instrument_by_itself_is_not_named(window):
    window.instrument_bar.open.click()
    assert not window.scope._names["demo:A"].startswith("Demo")


def test_open_and_the_pane_are_about_the_one_chosen(both):
    window = both
    assert "address" in window.instrument_view.controls
    assert window.instrument_bar.open.text() == "Close"
    choose(window, "demo")
    assert "address" not in window.instrument_view.controls
    window.instrument_bar.open.click()  # which closes the demo, and only the demo
    assert not window.session.units["demo"].is_open
    assert window.session.units[RIGOL].is_open
    assert window.instrument_bar.open.text() == "Open"
    choose(window, RIGOL)
    assert window.instrument_bar.open.text() == "Close"


def test_a_closed_instruments_traces_stay_until_another_is_run(both, app):
    window = both
    choose(window, "demo")
    window.close_instrument()
    assert "demo:A" in window.scope._curves, "still there to be looked at"
    choose(window, RIGOL)
    window.set_mode("auto")
    assert "demo:A" not in window.scope._curves
    assert f"{RIGOL}:CH1" in window.scope._curves
    assert not window.scope._names[f"{RIGOL}:CH1"].startswith("Rigol"), "the only one again"


# --- running -----------------------------------------------------------------------------------
def test_a_run_button_runs_every_instrument_that_is_open_and_stop_stops_them(both, app):
    window = both
    window.instrument_bar.modes["auto"].click()
    units = window.session.units
    assert units["demo"].running and units[RIGOL].running
    assert units["demo"].acquisition.mode == units[RIGOL].acquisition.mode == "auto"
    window.instrument_bar.modes["stop"].click()
    assert not units["demo"].running and not units[RIGOL].running
    assert window.instrument_bar.mode() == "stop"


def test_one_stopping_by_itself_leaves_the_other_running(both, app):
    window = both
    window.set_mode("auto")
    window.session.units["demo"].instrument.stop()
    assert window.instrument_bar.mode() == "auto"
    assert window.session.units[RIGOL].running
    window.session.units[RIGOL].instrument.stop()
    assert window.instrument_bar.mode() == "stop"


def test_single_waits_for_each_to_have_its_capture(both, app):
    window = both
    choose(window, "demo")
    choose_source(window, "A")
    window.trigger_bar.level.setValue(50.0)  # which the demo's sine never reaches
    window.scope.window_s.setValue(0.01)
    window.instrument_bar.modes["single"].click()
    units = window.session.units
    wait_for(app, lambda: not units[RIGOL].running)
    assert units["demo"].running, "the demo has not had its yet"
    assert window.instrument_bar.mode() == "single"
    window.trigger_bar.level.setValue(0.0)
    wait_for(app, lambda: not units["demo"].running)
    assert window.instrument_bar.mode() == "stop"


# --- the trigger -------------------------------------------------------------------------------
def test_each_instrument_has_a_trigger_of_its_own(both):
    window = both
    assert window.trigger_bar.label.text() == " Trigger, Rigol: "
    assert [window.trigger_bar.source.itemData(i) for i in range(2)] == [None, "CH1"]
    choose_source(window, "CH1")
    window.trigger_bar.level.setValue(1.5)
    choose(window, "demo")
    assert window.trigger_bar.label.text() == " Trigger, Demo: "
    assert window.trigger_bar.source.currentData() is None and window.trigger_bar.level.value() == 0
    choose_source(window, "A")
    window.trigger_bar.level.setValue(0.25)
    units = window.session.units
    assert (units[RIGOL].acquisition.source, units[RIGOL].acquisition.level) == ("CH1", 1.5)
    assert (units["demo"].acquisition.source, units["demo"].acquisition.level) == ("A", 0.25)
    choose(window, RIGOL)
    assert window.trigger_bar.source.currentData() == "CH1"
    assert window.trigger_bar.level.value() == 1.5
    saved = window.ctx.settings
    assert saved.get(f"trigger.{RIGOL}.source") == "CH1" and saved.get("trigger.demo.source") == "A"


def test_where_the_trigger_sits_is_the_same_for_all(both):
    window = both
    window.trigger_bar.position.setValue(20)
    assert {unit.acquisition.position for unit in window.session.units.values()} == {0.2}


def test_a_trigger_saved_before_there_were_several_is_still_used(window):
    window.ctx.settings.set("trigger.source", "B")
    window.ctx.settings.set("trigger.level", 0.3)
    window.close()
    again = MainWindow()
    try:
        again.instrument_bar.open.click()
        assert (again.acquisition.source, again.acquisition.level) == ("B", 0.3)
        assert again.trigger_bar.level.value() == 0.3
    finally:
        again.close()


# --- on the plot -------------------------------------------------------------------------------
def test_each_is_drawn_around_its_own_trigger_at_nought(both, fake, app):  # noqa: F811
    window = both
    choose_source(window, "CH1")
    choose(window, "demo")
    choose_source(window, "A")
    window.scope.window_s.setValue(0.02)
    window.set_mode("normal")
    wait_for(app, lambda: window.session.units[RIGOL].acquisition.sweep is not None)
    feed_demo(window)
    window.scope.redraw()
    assert window.scope.state.text() == f"Demo: {TRIGGERED}   Rigol: {TRIGGERED}"
    assert window.scope.trigger_lines[0].isVisible()
    low, high = window.scope.analog.getViewBox().viewRange()[0]
    assert low == pytest.approx(-0.01) and high == pytest.approx(0.01)
    # The Rigol's sweep is twelve milliseconds with its trigger in the middle.
    times, _values = window.scope._curves[f"{RIGOL}:CH1"].getData()
    assert times[0] == pytest.approx(-0.006, abs=1e-5) and times[-1] == pytest.approx(
        0.006, abs=1e-5
    )
    # The demo's sine goes up through nought at its trigger.
    times, values = window.scope._curves["demo:A"].getData()
    assert times[0] < -0.009 and times[-1] > 0.009
    assert values[times < -0.0001][-1] < 0 < values[times > 0.0001][0]
    window.set_mode("stop")
    window.scope.redraw()
    assert window.scope.state.text() == f"Demo: {STOPPED}   Rigol: {STOPPED}"


def test_one_with_no_trigger_is_drawn_as_it_arrives_beside_one_that_has(both, app):
    window = both
    choose_source(window, "CH1")
    window.scope.window_s.setValue(0.02)
    window.set_mode("auto")
    wait_for(app, lambda: window.session.units[RIGOL].acquisition.sweep is not None)
    feed_demo(window)
    window.scope.redraw()
    times, _values = window.scope._curves["demo:A"].getData()
    assert times[0] == pytest.approx(-0.01, abs=1e-4), "its newest, where a trigger would put them"
    assert times[-1] == pytest.approx(0.01, abs=1e-4)
    assert window.scope.window_s.isEnabled(), "the demo's stretch is still asked for"


def test_two_that_send_sweeps_are_shown_whole(window, fake, monkeypatch, app):  # noqa: F811
    from tests.test_picoscope2000 import FakeLibrary

    monkeypatch.setattr(pico, "load_library", lambda: FakeLibrary())
    window.ctx.settings.set(f"instrument.{RIGOL}", {"address": fake.address})
    window.ctx.settings.set("instrument.picoscope2000", {"mode": "block"})
    choose(window, "picoscope2000")
    window.instrument_bar.open.click()
    choose_source(window, "A")
    choose(window, RIGOL)
    window.instrument_bar.open.click()
    choose_source(window, "CH1")
    window.set_mode("normal")
    units = window.session.units
    wait_for(
        app,
        lambda: all(units[n].acquisition.sweep is not None for n in ("picoscope2000", RIGOL)),
    )
    window.scope.redraw()
    low, high = window.scope.analog.getViewBox().viewRange()[0]
    # The longer of the two either side of nought: the Rigol's twelve milliseconds.
    assert low == pytest.approx(-0.006, rel=1e-3) and high == pytest.approx(0.006, rel=1e-3)
    assert not window.scope.window_s.isEnabled()
    assert set(window.scope._curves) == {
        "picoscope2000:A",
        "picoscope2000:B",
        f"{RIGOL}:CH1",
    }
    for name in ("picoscope2000", RIGOL):
        choose(window, name)
        window.close_instrument()


def test_diagnostics_tell_of_every_instrument_in_use(both):
    from pyscopegui.ui.help_menu import diagnostics

    report = diagnostics(both)
    assert "chosen=Rigol DS1000Z series (rigol1000z)" in report
    assert "also in use=Demo signals (demo)" in report
    assert "Samples held, Demo" in report and "Samples held, Rigol" in report


# --- how each channel is set, and changing it ----------------------------------------------------
def test_the_plots_list_says_how_each_channel_is_set(both):
    from pyscopegui.ui.scope_view import DETAIL

    window = both
    items = window.scope.channel_list._items
    assert items[f"{RIGOL}:CH1"].text(DETAIL) == "1 V/div, 10x, DC"
    assert items["demo:A"].text(DETAIL) == "", "the demo has nothing to set"
    box = window.instrument_view.controls["offset_1"]
    box.setValue(-1.5)
    assert window.scope.channel_list._items[f"{RIGOL}:CH1"].text(DETAIL) == (
        "1 V/div, 10x, DC, offset -1.5 V"
    )


def test_channels_are_set_one_at_a_time_under_tabs(both, app):
    view = both.instrument_view
    app.processEvents()  # new controls are shown when the event loop gets to them
    assert [view.tabs.tabText(i) for i in range(view.tabs.count())] == ["1", "2", "3", "4"]
    assert view.controls["scale_1"].isVisibleTo(view)
    assert not view.controls["scale_3"].isVisibleTo(view)
    view.tabs.setCurrentIndex(2)
    assert view.controls["scale_3"].isVisibleTo(view)
    assert not view.controls["scale_1"].isVisibleTo(view)
    assert view.controls["address"].isVisibleTo(view), "what is not a channel's is always there"


def test_the_channel_being_set_is_kept_when_the_settings_are_shown_again(both):
    window = both
    window.instrument_view.tabs.setCurrentIndex(1)
    window._show_settings()
    assert window.instrument_view.tabs.currentIndex() == 1


def test_clicking_a_channel_on_the_plot_brings_its_settings_up(both, app):
    window = both
    choose(window, "demo")
    assert window.instrument_view.tabs is None
    item = window.scope.channel_list._items[f"{RIGOL}:CH1"]
    window.scope.channel_list.itemClicked.emit(item, 0)
    assert window.instrument_bar.current() == RIGOL, "the instrument it belongs to is chosen"
    assert window.instrument_view.tabs.currentIndex() == 0
    app.processEvents()  # new controls are shown when the event loop gets to them
    assert window.instrument_view.controls["scale_1"].isVisibleTo(window.instrument_view)


def test_a_setting_that_starts_the_run_again_says_so(both):
    from pyscopegui.ui.instrument_view import RESTARTS

    view = both.instrument_view
    assert RESTARTS in view.controls["enabled_1"].toolTip()
    assert RESTARTS not in view.controls["scale_1"].toolTip()
    assert RESTARTS not in view.controls["address"].toolTip(), "which says when it is taken up"


# --- a tab for each instrument in the pane -------------------------------------------------------
def tab_names(window):
    bar = window.instrument_view.instruments
    return [bar.tabText(i) for i in range(bar.count())]


def test_one_instrument_has_no_tabs_to_choose_between(window):
    window.instrument_bar.open.click()
    assert window.instrument_view.instruments.isHidden()


def test_the_pane_has_a_tab_for_each_instrument_in_use(both):
    window = both
    bar = window.instrument_view.instruments
    assert not bar.isHidden()
    assert tab_names(window) == ["Demo", "Rigol"] and bar.tabText(bar.currentIndex()) == "Rigol"


def test_a_tab_chooses_its_instrument_as_the_list_does(both):
    window = both
    bar = window.instrument_view.instruments
    bar.setCurrentIndex(0)
    assert window.instrument_bar.current() == "demo"
    assert "address" not in window.instrument_view.controls
    assert window.trigger_bar.label.text() == " Trigger, Demo: "
    assert tab_names(window) == ["Demo", "Rigol"], "still both"
    assert bar.currentIndex() == 0
    choose(window, RIGOL)
    assert bar.tabText(bar.currentIndex()) == "Rigol", "and the list moves the tab"


def test_an_instrument_only_chosen_has_a_tab_while_it_is(both):
    window = both
    choose(window, "picoscope2000")
    assert tab_names(window) == ["Demo", "Rigol", "Pico"]
    choose(window, "demo")
    assert tab_names(window) == ["Demo", "Rigol"]


# --- how an instrument is reached, which cannot change while it is open ------------------------
def test_the_connection_settings_are_greyed_out_while_it_is_open(both, app):
    window = both
    controls = window.instrument_view.controls
    assert not controls["connection"].isEnabled() and not controls["address"].isEnabled()
    assert controls["time_div"].isEnabled(), "everything else can still be set"
    window.close_instrument()
    wait_for(app, lambda: not window.instrument.is_open)
    controls = window.instrument_view.controls
    assert controls["connection"].isEnabled() and controls["address"].isEnabled()
    assert not controls["usb"].isEnabled(), "which is for USB, and the network is chosen"


def test_choosing_another_instrument_shows_whether_that_one_is_open(both):
    window = both
    choose(window, "picoscope2000")  # which has not been opened
    choose(window, RIGOL)
    assert not window.instrument_view.controls["address"].isEnabled()


# --- an instrument read as it is, beside one that is not ----------------------------------------
def test_with_another_instrument_open_single_is_still_for_that_one(both):
    """Single is greyed out only when there is nothing it could run."""
    window = both
    assert window.instrument_bar.modes["single"].isEnabled()
    assert not window.instrument_bar.reads(), "neither of these is read as it is"
