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
    assert view._layout.itemAt(0).widget().text() == NOTHING


# --- in the window -----------------------------------------------------------------------------
class FakeScope:
    """Stands in for load_library, so the PicoScope can be chosen with none installed."""

    def __init__(self, monkeypatch):
        from tests.test_picoscope2000 import FakeLibrary

        self.library = FakeLibrary()
        monkeypatch.setattr(pico, "load_library", lambda: self.library)


def pick_picoscope(window):
    box = window.instrument_bar.instrument
    box.setCurrentIndex(box.findData("picoscope2000"))


def test_the_pane_follows_the_instrument_chosen(window):
    assert window.instrument_view.controls == {}  # the demo has nothing to set
    pick_picoscope(window)
    assert set(window.instrument_view.controls) == {s.key for s in pico.SETTINGS}


def test_a_change_is_saved_under_the_instrument_it_belongs_to(window):
    pick_picoscope(window)
    choose(window.instrument_view, "range_a", "1V")
    assert window.ctx.settings.get("instrument.picoscope2000") == {"range_a": "1V"}
    choose(window.instrument_view, "rate", 100_000)
    assert window.ctx.settings.get("instrument.picoscope2000") == {
        "range_a": "1V",
        "rate": 100_000,
    }


def test_a_setup_change_while_stopped_is_used_at_the_next_run(window, monkeypatch, app):
    FakeScope(monkeypatch)
    pick_picoscope(window)
    choose(window.instrument_view, "range_a", "200mV")
    window.set_mode("auto")
    assert window.instrument.channels()[0].name == "A: ±200mV"
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
    choose(window.instrument_view, "range_a", "1V")
    assert window.capture.stored() == held, "nothing was thrown away"
    assert window.capture.records["A"].channel.name == "A: ±1V"
    assert window.capture.records["A"].channel.full_scale == 1.0
    assert window.instrument.running
    window.close_instrument()


# --- the plot's voltage axis -------------------------------------------------------------------
def y_range(scope):
    return scope.analog.getViewBox().viewRange()[1]


def test_the_voltage_axis_fits_the_signal_unless_told_otherwise(window):
    assert window.scope.auto_y.isChecked()
    assert window.scope.analog.getViewBox().autoRangeEnabled()[1]


def test_unticked_the_voltage_axis_is_the_largest_range_shown(window, monkeypatch, app):
    FakeScope(monkeypatch)
    pick_picoscope(window)
    choose(window.instrument_view, "range_a", "1V")
    choose(window.instrument_view, "range_b", "10V")
    window.scope.auto_y.setChecked(False)
    window.set_mode("auto")
    low, high = y_range(window.scope)
    assert -11.5 < low < -10 and 10 < high < 11.5
    assert not window.scope.analog.getViewBox().autoRangeEnabled()[1]
    # A channel that is not shown does not hold the axis open for itself.
    window.scope._on_shown("B", False)
    low, high = y_range(window.scope)
    assert -1.15 < low < -1 and 1 < high < 1.15
    window.scope.auto_y.setChecked(True)
    assert window.scope.analog.getViewBox().autoRangeEnabled()[1]
    window.stop()


def test_the_choice_of_voltage_axis_is_remembered(window):
    window.scope.auto_y.setChecked(False)
    assert window.ctx.settings.get("scope.auto_y") is False


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
