# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The Instrument pane, and what the window does with a change made in it."""

import pytest
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox

from pyscopegui import backends
from pyscopegui.backends import picoscope2000 as pico
from pyscopegui.backends.base import Setting
from pyscopegui.ui.instrument_view import NOTHING, InstrumentView

SETTINGS = (
    Setting("range", "Range", "5V", choices=(("1V", "±1 V"), ("5V", "±5 V")), group="Channel A"),
    Setting("level", "Level", 1.5, minimum=0.0, maximum=4.0, decimals=2, unit="V", live=True),
    Setting("enabled", "Enabled", True, group="Channel A"),
)


def choose(view, key, value):
    """Pick from a list the way somebody does: change it, and say it was chosen."""
    box = view.controls[key]
    box.setCurrentIndex(box.findData(value))
    box.activated.emit(box.currentIndex())


# --- the pane ----------------------------------------------------------------------------------
def test_a_list_and_a_number_are_built_at_their_defaults(app):
    view = InstrumentView()
    view.show_settings(SETTINGS, {})
    assert isinstance(view.controls["range"], QComboBox)
    assert view.controls["range"].currentData() == "5V"
    assert isinstance(view.controls["level"], QDoubleSpinBox)
    assert view.controls["level"].value() == 1.5
    assert view.controls["level"].suffix() == " V"


def test_saved_values_are_shown_over_the_defaults(app):
    view = InstrumentView()
    view.show_settings(SETTINGS, {"range": "1V", "level": 3.25})
    assert view.controls["range"].currentData() == "1V"
    assert view.controls["level"].value() == 3.25


@pytest.mark.parametrize("saved", [{"range": "3V"}, {"level": "high"}, {"range": None}])
def test_a_saved_value_nobody_can_read_is_shown_as_the_default(app, saved):
    view = InstrumentView()
    view.show_settings(SETTINGS, saved)
    assert view.controls["range"].currentData() == "5V"
    assert view.controls["level"].value() == 1.5


def test_a_change_says_its_key_its_value_and_whether_it_is_live(app):
    view = InstrumentView()
    view.show_settings(SETTINGS, {})
    said = []
    view.changed.connect(lambda *change: said.append(change))
    choose(view, "range", "1V")
    view.controls["level"].setValue(2.0)
    assert said == [("range", "1V", False), ("level", 2.0, True)]


def test_on_or_off_is_a_tick_box_and_not_a_list_of_two(app):
    view = InstrumentView()
    view.show_settings(SETTINGS, {})
    tick = view.controls["enabled"]
    assert isinstance(tick, QCheckBox)
    assert tick.text() == "Enabled" and tick.isChecked()
    said = []
    view.changed.connect(lambda *change: said.append(change))
    tick.click()
    assert said == [("enabled", False, False)]


@pytest.mark.parametrize(("saved", "ticked"), [(False, False), ("no", True), (None, True)])
def test_a_tick_shows_what_was_saved_or_the_default(app, saved, ticked):
    view = InstrumentView()
    view.show_settings(SETTINGS, {"enabled": saved})
    assert view.controls["enabled"].isChecked() is ticked


def test_showing_settings_is_not_a_change(app):
    view = InstrumentView()
    said = []
    view.changed.connect(lambda *change: said.append(change))
    view.show_settings(SETTINGS, {"range": "1V", "level": 3.0, "enabled": False})
    assert said == []


def test_an_instrument_with_nothing_to_set_says_so(app):
    view = InstrumentView()
    view.show_settings(SETTINGS, {})
    view.show_settings((), {})
    assert view.controls == {}
    # And still Open, on the line of instruments' tabs.
    assert view._layout.itemAt(0).widget().text() == NOTHING
    assert view.open.isVisibleTo(view)


# --- in the window -----------------------------------------------------------------------------
class FakeScope:
    """Stands in for load_library, so the PicoScope can be chosen with none installed."""

    def __init__(self, monkeypatch):
        from tests.test_picoscope2000 import FakeLibrary

        self.library = FakeLibrary()
        monkeypatch.setattr(pico, "load_library", lambda: self.library)


def pick_picoscope(window):
    window.choose("picoscope2000")


def test_the_pane_follows_the_instrument_chosen(window):
    assert window.instrument_view.controls == {}  # the demo has nothing to set
    pick_picoscope(window)
    assert set(window.instrument_view.controls) == {s.key for s in pico.SETTINGS}


def test_a_change_is_saved_under_the_instrument_it_belongs_to(window):
    pick_picoscope(window)
    choose(window.instrument_view, "scale_a", 0.2)
    assert window.ctx.settings.get("instrument.picoscope2000") == {"scale_a": 0.2}
    choose(window.instrument_view, "rate", 100_000)
    assert window.ctx.settings.get("instrument.picoscope2000") == {
        "scale_a": 0.2,
        "rate": 100_000,
    }


def test_a_setup_change_while_stopped_is_used_at_the_next_run(window, monkeypatch, app):
    FakeScope(monkeypatch)
    pick_picoscope(window)
    choose(window.instrument_view, "scale_a", 0.05)
    window.set_mode("auto")
    assert window.instrument.channels()[0].detail == "50 mV/div, 1x, DC"
    assert window.instrument.settings.ranges["A"] == "200mV"
    window.stop()


def test_a_setup_change_while_running_starts_it_again_with_the_change(window, monkeypatch, app):
    fake = FakeScope(monkeypatch)
    pick_picoscope(window)
    window.set_mode("normal")
    first = window.instrument
    choose(window.instrument_view, "rate", 100_000)
    assert window.instrument is first, "the same scope, still open"
    assert window.instrument.running
    assert window.instrument.rate == 100_000
    assert window.capture.records["A"].rate == 100_000
    assert window.instrument_bar.mode() == "normal", "and doing what it was doing"
    window.close_instrument()
    assert fake.library.calls.count(("open",)) <= 1, "it was not opened again for it"


def test_a_generator_change_while_running_does_not_start_it_again(window, monkeypatch, app):
    FakeScope(monkeypatch)
    pick_picoscope(window)
    window.set_mode("auto")
    first = window.instrument
    choose(window.instrument_view, "gen_wave", "sine")
    assert window.instrument is first
    assert window.instrument.settings.generator[0] == "sine"
    assert window.ctx.settings.get("instrument.picoscope2000") == {"gen_wave": "sine"}
    window.stop()


def test_settings_saved_as_something_else_are_treated_as_none(window):
    window.ctx.settings.set("instrument.picoscope2000", "fast")
    pick_picoscope(window)
    assert window.instrument_view.controls["rate"].currentData() == pico.DEFAULT_RATE


def test_every_back_end_can_say_what_it_lets_you_set():
    for name in backends.names():
        assert all(isinstance(s, Setting) for s in backends.settings(name))


def test_either_channel_is_switched_off_with_a_tick(window, monkeypatch, app):
    FakeScope(monkeypatch)
    pick_picoscope(window)
    window.instrument_view.controls["enabled_b"].click()
    window.set_mode("auto")
    assert [c.key for c in window.instrument.channels()] == ["A"]
    window.instrument_view.controls["enabled_b"].click()
    window.instrument_view.controls["enabled_a"].click()
    assert [c.key for c in window.instrument.channels()] == ["B"]
    assert set(window.capture.records) == {"B"}
    window.stop()


def test_a_run_that_was_replaced_cannot_mark_its_replacement_stopped(window, monkeypatch, app):
    """The one before says it has stopped from its own thread, after the next has started."""
    FakeScope(monkeypatch)
    pick_picoscope(window)
    window.set_mode("auto")
    choose(window.instrument_view, "rate", 100_000)  # stopped, and started again
    for _ in range(20):
        app.processEvents()
    assert window.instrument.running
    assert window.instrument_bar.mode() == "auto"
    window.stop()


def test_a_range_change_while_running_keeps_what_is_on_the_plot(window, monkeypatch, app):
    """The samples are held in volts, so a range is taken up without starting again."""
    import time

    fake = FakeScope(monkeypatch)
    pick_picoscope(window)
    fake.library.waiting.append(([1000] * 50, [1000] * 50))
    window.set_mode("auto")
    deadline = time.monotonic() + 5
    while not window.capture.stored() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    held = window.capture.stored()
    assert held == 100
    choose(window.instrument_view, "scale_a", 0.2)
    assert window.capture.stored() == held, "nothing was thrown away"
    assert window.capture.records["A"].channel.detail == "200 mV/div, 1x, DC"
    assert window.capture.records["A"].channel.full_scale == 1.0
    assert window.instrument.running
    window.close_instrument()


# --- the plot's voltage axis -------------------------------------------------------------------
def y_range(scope):
    return scope.analog.getViewBox().viewRange()[1]


def y_mode(window, choice):
    window.scope.y_mode.setCurrentText(choice)


def test_the_voltage_axis_fits_the_signal_to_start_with(window):
    assert window.scope.y_mode.currentText() == "Auto"
    assert window.scope.analog.getViewBox().autoRangeEnabled()[1]


def test_range_is_the_largest_range_shown(window, monkeypatch, app):
    FakeScope(monkeypatch)
    pick_picoscope(window)
    choose(window.instrument_view, "scale_a", 0.2)
    choose(window.instrument_view, "scale_b", 2.0)
    y_mode(window, "Range")
    window.set_mode("auto")
    low, high = y_range(window.scope)
    assert -11.5 < low < -10 and 10 < high < 11.5
    assert not window.scope.analog.getViewBox().autoRangeEnabled()[1]
    # A channel that is not shown does not hold the axis open for itself.
    window.scope._on_shown("picoscope2000:B", False)
    low, high = y_range(window.scope)
    assert -1.15 < low < -1 and 1 < high < 1.15
    y_mode(window, "Auto")
    assert window.scope.analog.getViewBox().autoRangeEnabled()[1]
    window.stop()


def test_range_follows_an_offset(window):
    from dataclasses import replace

    window.set_mode("auto")
    window.set_mode("stop")
    capture = window.capture
    sine = capture.records["A"].channel
    # A 1 V offset on a range of 5 V either way: what is read is -6 V to 4 V.
    capture.update_channels([replace(sine, full_scale=5.0, middle=-1.0)])
    y_mode(window, "Range")
    low, high = y_range(window.scope)
    assert -6.6 < low < -6 and 4 < high < 4.6
    window.scope._on_shown("demo:B", False)
    assert y_range(window.scope)[0] < -6, "and with only that channel shown too"


def test_manual_holds_the_axis_where_it_was(window):
    from dataclasses import replace

    window.set_mode("auto")
    window.set_mode("stop")
    capture = window.capture
    sine = capture.records["A"].channel
    capture.update_channels([replace(sine, full_scale=5.0)])
    y_mode(window, "Range")
    held = y_range(window.scope)
    y_mode(window, "Manual")
    assert y_range(window.scope) == held, "from Range"
    # A change of scale, which Range would follow, leaves it alone.
    capture.update_channels([replace(sine, full_scale=0.5)])
    assert y_range(window.scope) == held
    y_mode(window, "Auto")
    fitted = y_range(window.scope)
    y_mode(window, "Manual")
    assert y_range(window.scope) == fitted, "and from Auto"


def test_zooming_the_voltage_axis_chooses_manual_and_leaves_time_alone(window):
    scope = window.scope
    scope.time.setCurrentText("Follow")
    scope.analog.getViewBox().sigRangeChangedManually.emit([False, True])
    assert scope.y_mode.currentText() == "Manual" and scope.time.currentText() == "Follow"


def test_dragging_time_chooses_manual_time_and_leaves_the_voltage_axis_alone(window):
    scope = window.scope
    for plot in (scope.analog, scope.digital):
        y_mode(window, "Range")
        scope.time.setCurrentText("Follow")
        plot.getViewBox().sigRangeChangedManually.emit([True, False])
        assert scope.time.currentText() == "Manual" and scope.y_mode.currentText() == "Range"


def test_the_axis_set_by_hand_from_its_menu_is_manual(window):
    view = window.scope.analog.getViewBox()
    assert window.scope.y_mode.currentText() == "Auto"
    view.setYRange(-3, 3)  # as the right-click menu's Y axis does
    assert window.scope.y_mode.currentText() == "Manual"
    assert y_range(window.scope)[0] < -2.9


def started_again_with(app, choice):
    """The Y chosen after starting pyscopegui with this chosen last time."""
    from pyscopegui.ui.main_window import MainWindow

    window = MainWindow()
    try:
        window.scope.y_mode.setCurrentText(choice)
    finally:
        window.close()
        window.deleteLater()
    again = MainWindow()
    try:
        return again.scope.y_mode.currentText()
    finally:
        again.close()
        again.deleteLater()


def test_range_is_remembered_and_an_axis_held_by_hand_fits_again_next_time(app):
    assert started_again_with(app, "Range") == "Range"
    assert started_again_with(app, "Manual") == "Auto"


def test_an_axis_held_by_hand_stays_so_from_one_run_to_the_next(window):
    window.set_mode("auto")
    window.set_mode("stop")
    y_mode(window, "Manual")
    window.set_mode("auto")
    window.set_mode("stop")
    assert window.scope.y_mode.currentText() == "Manual"


def test_another_instrument_added_is_fitted_and_range_is_left_as_it_is(window):
    y_mode(window, "Manual")
    window.add_instrument("rigol1000z")
    assert window.scope.y_mode.currentText() == "Auto"
    y_mode(window, "Range")
    window.add_instrument("picoscope2000")
    assert window.scope.y_mode.currentText() == "Range"


def test_auto_y_unticked_from_before_is_range(app):
    from pyscopegui.ui.main_window import MainWindow

    window = MainWindow()
    try:
        window.ctx.settings.set("scope.auto_y", False)
    finally:
        window.close()
        window.deleteLater()
    again = MainWindow()
    try:
        assert again.scope.y_mode.currentText() == "Range"
    finally:
        again.close()
        again.deleteLater()


# --- the plot's colours ------------------------------------------------------------------------
def test_the_plots_are_drawn_in_the_windows_own_colours(window, app):
    """A white plot in a dark window is the brightest thing on the screen."""
    scope = window.scope
    palette = scope.palette()
    palette.setColor(QPalette.Base, "#101418")
    palette.setColor(QPalette.Text, "#e8e8e8")
    scope.setPalette(palette)  # as a change of theme does, by way of changeEvent
    app.processEvents()
    for plot in (scope.analog, scope.digital):
        assert plot.backgroundBrush().color().name() == "#101418"
        assert plot.getAxis("bottom").textPen().color().name() == "#e8e8e8"


def test_a_setting_is_greyed_out_while_the_one_it_needs_is_at_something_else(app):
    view = InstrumentView()
    view.show_settings(pico.SETTINGS, {})
    rate, length, mode = (view.controls[key] for key in ("rate", "block_ms", "mode"))
    assert rate.isEnabled() and not length.isEnabled(), "streaming to start with"
    mode.setCurrentIndex(mode.findData(pico.BLOCKS))
    mode.activated.emit(mode.currentIndex())
    assert not rate.isEnabled() and length.isEnabled()
    view.show_settings(pico.SETTINGS, {"mode": pico.BLOCKS})
    assert not view.controls["rate"].isEnabled(), "as it was saved"


# --- no more than has a say --------------------------------------------------------------------
def shown(view, key):
    """Whether a setting is on screen: its own line, or beside another's."""
    if key in view._rows:
        form, field = view._rows[key]
        return form.isRowVisible(field)
    return not view.controls[key].isHidden()


def test_what_has_no_say_is_not_shown_until_it_has(app):
    from pyscopegui.backends import picoscope2000a as pa

    view = InstrumentView()
    view.show_settings(pa.make_settings(2, True), {})
    assert shown(view, "rate") and not shown(view, "block_ms"), "streaming to start with"
    choose(view, "mode", pa.BLOCKS)
    assert not shown(view, "rate") and shown(view, "block_ms")
    # A generator that is off has nothing else to set.
    generator = ("gen_frequency", "gen_amplitude", "gen_offset", "gen_start")
    assert not any(shown(view, key) for key in generator) and shown(view, "gen_wave")
    choose(view, "gen_wave", "sine")
    assert all(shown(view, key) for key in generator)
    assert not shown(view, "gen_cycles"), "cycles only on the scope's trigger"
    choose(view, "gen_start", pa.ON_TRIGGER)
    assert shown(view, "gen_cycles")
    choose(view, "gen_wave", "off")
    assert not shown(view, "gen_cycles"), "and nothing that needs what is not shown"


def test_a_port_and_its_threshold_share_a_line_and_line_up(app):
    from pyscopegui.backends import picoscope2000a as pa

    view = InstrumentView()
    view.show_settings(pa.make_settings(2, True), {"digital_0": True})
    form, field = view._rows["digital_0"]
    assert view.controls["threshold_0"].parent() is field, "on the port's line"
    assert "threshold_0" not in view._rows and form.rowCount() == 2
    assert shown(view, "threshold_0") and not shown(view, "threshold_1"), "D8 to D15 is off"
    first, second = (view.controls[key] for key in ("digital_0", "digital_1"))
    assert first.minimumWidth() == second.minimumWidth() > 0, "so the thresholds line up"


def test_each_channels_enabled_is_on_the_line_with_the_channels_tabs(app):
    from pyscopegui.backends import rigol1000z as rigol

    view = InstrumentView()
    view.show_settings(rigol.SETTINGS, {})
    assert "enabled_1" not in view._rows
    assert view._ticks.currentWidget() is view.controls["enabled_1"]
    view.tabs.setCurrentIndex(2)
    assert view._ticks.currentWidget() is view.controls["enabled_3"]
    # The offset beside the scale, and the 20 MHz limit beside the coupling, lined up.
    _form, field = view._rows["coupling_3"]
    assert view.controls["limit_3"].parent() is field
    _form, field = view._rows["scale_3"]
    assert view.controls["offset_3"].parent() is field
    assert view.controls["scale_3"].minimumWidth() == view.controls["coupling_3"].minimumWidth()


def test_a_current_probes_sensitivity_is_beside_it_said_by_its_unit(app):
    from pyscopegui.backends import rigol1000z as rigol

    view = InstrumentView()
    view.show_settings(rigol.SETTINGS, {"probe_1": "current"})
    _form, field = view._rows["probe_1"]
    assert view.controls["sensitivity_1"].parent() is field
    assert view._beside["sensitivity_1"] is None, "no name: V/A says what it is"
    assert shown(view, "sensitivity_1") and not shown(view, "sensitivity_2"), "a 10x probe"
    # And the pane is no wider for it than with a 10x probe, whatever the fonts.
    plain = InstrumentView()
    plain.show_settings(rigol.SETTINGS, {})
    view.show()
    plain.show()
    assert view.minimumSizeHint().width() <= plain.minimumSizeHint().width()


def test_every_instruments_tab_is_on_screen_where_there_is_room_for_them(app):
    """None behind the tab bar's scroll arrows: the tabs have their line to themselves."""
    view = InstrumentView()
    named = [(f"x{n}", name, name, False) for n, name in enumerate(("Pico", "Pico 2", "Rigol"))]
    view.set_instruments(named, "x0")
    view.show_settings(SETTINGS, {})
    view.resize(view.instruments.sizeHint().width() + 20, 400)
    view.show()
    app.processEvents()
    assert view.instruments.width() >= view.instruments.sizeHint().width()
