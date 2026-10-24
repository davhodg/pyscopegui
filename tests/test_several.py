# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""More than one instrument open at once, on one time axis."""

import time

import pytest
from PySide6.QtWidgets import QLabel

from pyscopegui import backends
from pyscopegui.backends import picoscope2000 as pico
from pyscopegui.core.capture import Capture
from pyscopegui.core.session import Session
from pyscopegui.ui.instrument_view import OPEN_MARK
from pyscopegui.ui.main_window import MainWindow
from pyscopegui.ui.scope_view import STOPPED, TRIGGERED, ScopeView
from pyscopegui.ui.trigger_bar import EACH, LEAD_KEY
from tests.test_rigol1000z import fake  # noqa: F401  the stand-in scope, as a fixture

RIGOL = "rigol1000z"


def wait_for(app, done, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not done() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert done(), "timed out"


def choose(window, name):
    window.choose(name)


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
    window.instrument_view.open.click()
    choose(window, RIGOL)
    window.instrument_view.open.click()
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
    bar = window.instrument_view.instruments
    assert [bar.tabText(i) for i in range(bar.count())] == ["Demo" + OPEN_MARK, "Rigol" + OPEN_MARK]
    assert "Demo:" in window.status.text() and "Rigol:" in window.status.text()


def test_the_plot_lists_the_channels_of_both_and_says_whose_each_is(both):
    window = both
    assert set(window.scope._curves) >= {"demo:A", "demo:D0", f"{RIGOL}:CH1"}
    names = window.scope._names
    assert names["demo:A"].startswith("Demo ") and names[f"{RIGOL}:CH1"].startswith("Rigol CH1")


def test_one_instrument_by_itself_is_not_named(window):
    window.instrument_view.open.click()
    assert not window.scope._names["demo:A"].startswith("Demo")


def test_open_and_the_pane_are_about_the_one_chosen(both):
    window = both
    assert "address" in window.instrument_view.controls
    assert window.instrument_view.open.text() == "Close"
    choose(window, "demo")
    assert "address" not in window.instrument_view.controls
    window.instrument_view.open.click()  # which closes the demo, and only the demo
    assert not window.session.units["demo"].is_open
    assert window.session.units[RIGOL].is_open
    assert window.instrument_view.open.text() == "Open"
    choose(window, RIGOL)
    assert window.instrument_view.open.text() == "Close"


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
        again.instrument_view.open.click()
        assert (again.acquisition.source, again.acquisition.level) == ("B", 0.3)
        assert again.trigger_bar.level.value() == 0.3
    finally:
        again.close()


# --- one leading the others -------------------------------------------------------------------
def choose_lead(window, name):
    box = window.trigger_bar.lead
    box.setCurrentIndex(box.findData(name))
    box.activated.emit(box.currentIndex())


def test_a_lead_is_offered_with_two_or_more_and_kept(both):
    bar = both.trigger_bar
    assert bar.lead.isVisibleTo(bar) and bar.lead_label.isVisibleTo(bar)
    assert [bar.lead.itemText(i) for i in range(bar.lead.count())] == [EACH, "Demo", "Rigol"]
    assert both.session.lead is None
    choose_lead(both, "demo")
    assert both.session.lead == "demo" and both.ctx.settings.get(LEAD_KEY) == "demo"
    choose_lead(both, None)
    assert both.session.lead is None and both.ctx.settings.get(LEAD_KEY) is None


def test_one_instrument_by_itself_has_no_lead_to_choose(window):
    window.instrument_view.open.click()
    assert not window.trigger_bar.lead.isVisibleTo(window.trigger_bar)
    assert window.trigger_bar.source.isEnabled()


def test_one_that_follows_has_no_trigger_of_its_own_to_set(both):
    window = both
    choose_lead(window, "demo")
    bar = window.trigger_bar
    assert window.instrument is window.session.units[RIGOL].instrument
    assert not bar.source.isEnabled() and not bar.level.isEnabled()
    assert bar.said.text() == " follows Demo"
    assert "Demo triggers" in bar.source.toolTip()
    assert bar.position.isEnabled(), "where the trigger sits is still everyone's"
    choose(window, "demo")
    assert bar.source.isEnabled(), "the lead's is set as ever"
    choose_lead(window, None)
    choose(window, RIGOL)
    assert bar.source.isEnabled()


def test_the_others_are_shown_at_the_moment_the_lead_triggers(both, monkeypatch):
    window = both
    units = window.session.shown()
    demo, rigol = window.session.units["demo"], window.session.units[RIGOL]
    asked = []

    def own(unit, _timing, _several):
        asked.append(unit.name)
        return (2.0, TRIGGERED, True, None)

    monkeypatch.setattr(window.scope, "_find_origin", own)
    window.scope._origins_found(units, True)
    assert sorted(asked) == ["demo", RIGOL], "each by its own trigger"
    choose_lead(window, "demo")
    assert window.scope.lead() is demo
    asked.clear()
    demo.clock.zero, rigol.clock.zero = 100.0, 100.5
    found = window.scope._origins_found(units, True)
    assert asked == ["demo"]
    # Two seconds into the demo's run is one and a half into the Rigol's.
    assert found[RIGOL] == (pytest.approx(1.5), "", True, None)
    rigol.clock.reset()
    assert window.scope._origins_found(units, True)[RIGOL][0] is None, "not known when"


def test_single_with_a_lead_stops_them_all_when_the_lead_has_its_capture(both, app):
    window = both
    choose(window, RIGOL)
    choose_source(window, "CH1")
    choose(window, "demo")
    choose_source(window, "A")
    window.trigger_bar.level.setValue(50.0)  # which the demo's sine never reaches
    window.scope.window_s.setValue(0.01)
    choose_lead(window, "demo")
    window.instrument_bar.modes["single"].click()
    units = window.session.units
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert units[RIGOL].running, "its own trigger is not waited for"
    window.trigger_bar.level.setValue(0.0)
    wait_for(app, lambda: not units["demo"].running)
    assert units[RIGOL].running, "what it took at the same moment is still to come"
    wait_for(app, lambda: not units[RIGOL].running)
    assert window.instrument_bar.mode() == "stop"


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
    window.instrument_view.open.click()
    choose_source(window, "A")
    choose(window, RIGOL)
    window.instrument_view.open.click()
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
    assert window.chosen == RIGOL, "the instrument it belongs to is chosen"
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
    """What each tab is called, without whether it is open."""
    bar = window.instrument_view.instruments
    return [bar.tabText(i).removesuffix(OPEN_MARK) for i in range(bar.count())]


def test_one_instrument_has_a_tab_that_says_which_it_is_and_can_be_removed(window):
    bar = window.instrument_view.instruments
    assert not bar.isHidden() and tab_names(window) == ["Demo"]
    assert bar.tabsClosable(), "the last one too"
    assert bar.tabToolTip(0).startswith("Demo signals\nNot open.")


@pytest.fixture
def none_left(window):
    window.set_mode("auto")
    window.remove_instrument()
    return window


def test_with_the_last_taken_out_the_pane_is_empty_and_says_so(none_left):
    from pyscopegui.ui.instrument_view import NONE_ADDED

    window = none_left
    assert window.added == [] and window.chosen == "" and window.unit is None
    assert window.instrument is None and tab_names(window) == []
    labels = [label.text() for label in window.instrument_view.findChildren(QLabel)]
    assert NONE_ADDED in labels and window.instrument_view.open.isHidden()
    assert "No instrument" in window.status.text()
    assert [
        window.trigger_bar.source.itemText(i) for i in range(window.trigger_bar.source.count())
    ] == ["None"]
    assert window.session.units == {} or all(
        unit.instrument is None for unit in window.session.units.values()
    )


def test_with_none_the_buttons_do_nothing_and_say_nothing_wrong(none_left):
    window = none_left
    for mode in ("auto", "single", "normal", "stop"):
        window.set_mode(mode)
    window.read_once()
    window.open_instrument()
    window.close_instrument()
    window.remove_instrument()
    assert window.instrument_bar.mode() == "stop"
    assert "Traceback" not in window.log.toPlainText()


def test_with_none_a_script_is_told_to_add_one(none_left):
    from pyscopegui.ui.scripting import ScriptError

    names = none_left.console.namespace
    with pytest.raises(ScriptError, match="add"):
        names["set"]("scale_1", 1.0)
    with pytest.raises(ScriptError, match="add"):
        names["trigger"]("CH1")


def test_an_empty_pane_stays_empty_the_next_time_until_one_is_added(none_left):
    again = MainWindow()
    try:
        assert again.added == [] and again.unit is None
        again.add_instrument("demo")
        assert again.added == ["demo"] and again.chosen == "demo"
        assert "address" not in again.instrument_view.controls
        again.set_mode("auto")
        assert again.instrument.running
        again.set_mode("stop")
    finally:
        again.close()
        again.deleteLater()


def test_the_pane_has_a_tab_for_each_instrument_in_use(both):
    window = both
    bar = window.instrument_view.instruments
    assert not bar.isHidden()
    assert tab_names(window) == ["Demo", "Rigol"]
    assert bar.tabText(bar.currentIndex()) == "Rigol" + OPEN_MARK


def test_a_tab_chooses_its_instrument_as_the_list_does(both):
    window = both
    bar = window.instrument_view.instruments
    bar.setCurrentIndex(0)
    assert window.chosen == "demo"
    assert "address" not in window.instrument_view.controls
    assert window.trigger_bar.label.text() == " Trigger, Demo: "
    assert tab_names(window) == ["Demo", "Rigol"], "still both"
    assert bar.currentIndex() == 0
    choose(window, RIGOL)
    assert bar.tabText(bar.currentIndex()).startswith("Rigol"), "and choosing moves the tab"


def test_an_instrument_added_stays_in_the_pane_until_it_is_removed(both):
    window = both
    window.add_instrument("picoscope2000")
    assert tab_names(window) == ["Demo", "Rigol", "Pico"]
    choose(window, "demo")
    assert tab_names(window) == ["Demo", "Rigol", "Pico"], "opened or not"
    window.remove_instrument("picoscope2000")
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


# --- adding and removing instruments ------------------------------------------------------------
def test_add_instrument_lists_every_kind_and_puts_one_in_the_pane(window):
    bar = window.instrument_bar
    assert [action.data() for action in bar.kinds.actions()] == backends.names()
    bar.add_kind("picoscope2000")
    assert window.added == ["demo", "picoscope2000"] and window.chosen == "picoscope2000"
    assert tab_names(window) == ["Demo", "Pico"]
    assert window.instrument is None, "added, and not opened: how it is reached may come first"
    assert window.instrument_view.open.text() == "Open"


def test_two_of_the_same_kind_are_two_instruments_with_settings_of_their_own(window, fake, app):  # noqa: F811
    window.add_instrument(RIGOL)
    second = window.add_instrument(RIGOL)
    assert second == f"{RIGOL}#2" and window.chosen == second
    assert tab_names(window) == ["Demo", "Rigol", "Rigol 2"]
    assert backends.title(second) == "Rigol DS1000Z series 2"
    # Each is told how it is reached, and remembers it for itself.
    address = window.instrument_view.controls["address"]
    address.setText(fake.address)
    address.editingFinished.emit()
    assert window.ctx.settings.get(f"instrument.{second}") == {"address": fake.address}
    assert window.ctx.settings.get(f"instrument.{RIGOL}") is None
    window.instrument_view.open.click()
    wait_for(app, lambda: window.instrument.is_open)
    assert window.session.units[second].is_open
    assert RIGOL not in window.session.units or not window.session.units[RIGOL].is_open
    assert f"{second}:CH1" in window.scope._curves
    window.close_instrument()


def test_the_cross_on_a_tab_closes_its_instrument_and_takes_it_out(both, app):
    window = both
    bar = window.instrument_view.instruments
    assert bar.tabsClosable() and "cross" in bar.tabToolTip(1)
    rigol = window.session.units[RIGOL]
    bar.tabCloseRequested.emit(1)
    assert window.added == ["demo"] and window.chosen == "demo"
    assert RIGOL not in window.session.units and rigol.instrument is None
    wait_for(app, lambda: "closed" in window.log.toPlainText().lower())
    assert not any(key.startswith(RIGOL) for key in window.scope._curves)
    assert window.session.units["demo"].is_open, "and the other is left as it was"
    assert window.ctx.settings.get(f"instrument.{RIGOL}") is not None, "its settings are kept"
    window.choose(RIGOL)  # for the fixture, which closes both


def test_removing_one_that_is_not_chosen_leaves_the_chosen_one_chosen(both):
    window = both
    window.remove_instrument("demo")
    assert window.added == [RIGOL] and window.chosen == RIGOL
    assert window.instrument.is_open
    window.choose("demo")


def test_the_number_of_one_removed_is_used_again(window):
    for _ in range(3):
        window.add_instrument("demo")
    assert window.added == ["demo", "demo#2", "demo#3", "demo#4"]
    window.remove_instrument("demo#3")
    assert window.add_instrument("demo") == "demo#3"


def test_what_was_in_the_pane_is_there_the_next_time(window, app):
    from pyscopegui.ui.main_window import MainWindow

    window.add_instrument("picoscope2000")
    window.add_instrument("demo")
    window.choose("picoscope2000")
    again = MainWindow()
    try:
        assert again.added == ["demo", "picoscope2000", "demo#2"]
        assert again.chosen == "picoscope2000"
    finally:
        again.close()
        again.deleteLater()


def test_an_instrument_saved_that_there_is_no_longer_is_left_out(window):
    from pyscopegui.ui.main_window import MainWindow

    window.ctx.settings.set("instruments.added", ["nosuch", "demo#2", "demo#2", "demo#x", 7])
    window.ctx.settings.set("instrument.name", "nosuch")
    again = MainWindow()
    try:
        assert again.added == ["demo#2"] and again.chosen == "demo#2"
    finally:
        again.close()
        again.deleteLater()


def test_open_is_under_the_instruments_tabs_and_connection_only_where_it_says_something(both, app):
    window = both
    view = window.instrument_view
    # The tabs have their line to themselves, and Open is on the next.
    assert view.layout().itemAt(0).widget() is view.instruments
    assert view.layout().itemAt(1).layout().indexOf(view.open) == 0
    assert view._forms["Connection"].getWidgetPosition(view.controls["address"])[0] >= 0
    choose(window, "demo")  # which has nothing to say about how it is reached
    assert "Connection" not in view._forms
    app.processEvents()  # new controls are shown when the event loop gets to them
    assert view.open.isVisibleTo(view)
    choose(window, RIGOL)


def test_names_for_instruments_of_a_kind():
    assert backends.another("demo", []) == "demo"
    assert backends.another("demo", ["demo", "demo#2"]) == "demo#3"
    assert (backends.kind("demo#3"), backends.number("demo#3")) == ("demo", 3)
    assert backends.short("demo") == "Demo" and backends.short("demo#2") == "Demo 2"
    assert backends.known("demo") and backends.known("demo#2")
    for wrong in ("demo#1", "demo#02", "demo#", "demo#x", "other", None, 3):
        assert not backends.known(wrong), wrong
