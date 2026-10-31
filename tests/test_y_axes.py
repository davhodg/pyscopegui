# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Y1 and Y2: a channel in another unit drawn against a voltage axis of its own on
the right, or put there by hand, each axis fitted to its own channels."""

import numpy as np
import pytest

from pyscopegui.ui.scope_view import Y1, Y2
from pyscopegui.ui.scripting import Scripting


@pytest.fixture
def held(window):
    """The demo, run and stopped, with what is held drawn."""
    window.set_mode("auto")
    window.instrument._started -= 0.3
    window.instrument._tick()
    window.set_mode("stop")
    window.scope.redraw()
    return window


def amps(window, k=10.0):
    """A maths channel in amps, as a current probe's would be: its id."""
    called = Scripting(window).maths("A", "scale", k=k, unit="A")
    window.scope.redraw()
    return next(key for key, name in window.scope._names.items() if name == called)


def shown_range(window, axis):
    return window.scope._y_boxes[axis].viewRange()[1]


def right_axis_shown(window):
    return window.scope.analog.getPlotItem().getAxis("right").isVisible()


def test_volts_alone_have_the_one_axis(held):
    scope = held.scope
    assert set(scope._axis.values()) == {Y1}
    assert not right_axis_shown(held)


def test_a_channel_in_amps_goes_on_y2_by_itself_and_says_so(held):
    key = amps(held)
    scope = held.scope
    assert scope.axis_of(key) == Y2 and scope.axis_of("demo:A") == Y1
    assert right_axis_shown(held), "Y2 is there while a channel is on it"
    assert scope.digital.getPlotItem().getAxis("right").isVisible(), "the lanes keep in line"
    assert scope.channel_list._items[key].text(0).endswith(" (Y2)")
    assert scope.analog.getAxis("right").labelUnits == "A"
    assert scope.analog.getAxis("left").labelUnits == "V"


def test_each_axis_is_fitted_to_its_own_channels(held):
    key = amps(held, k=100.0)
    scope = held.scope
    curve = scope._curves[key]
    low, high = float(np.nanmin(curve.yData)), float(np.nanmax(curve.yData))
    y2_low, y2_high = shown_range(held, Y2)
    assert y2_low <= low and high <= y2_high and (high - low) > 0.8 * (y2_high - y2_low)
    a = scope._curves["demo:A"].yData
    y1_low, y1_high = shown_range(held, Y1)
    assert y1_high - y1_low < 0.2 * (y2_high - y2_low), "Y1 not stretched to the amps"
    assert y1_low <= float(np.nanmin(a)) and float(np.nanmax(a)) <= y1_high


def test_with_only_amps_shown_they_are_on_y1(held):
    key = amps(held)
    scope = held.scope
    for other in [k for k in scope._curves if k != key and k not in scope._lanes]:
        scope._on_shown(other, False)
    assert scope.axis_of(key) == Y1 and not right_axis_shown(held)


def test_a_channel_put_on_y2_by_hand_stays_there(held, app):
    from pyscopegui.ui.main_window import MainWindow

    held.scope.set_axis("demo:B", Y2)
    assert held.scope.axis_of("demo:B") == Y2 and right_axis_shown(held)
    assert held.ctx.settings.get("scope.axes") == {"demo:B": Y2}
    held.close()
    again = MainWindow()
    try:
        again.set_mode("auto")
        again.instrument._started -= 0.1
        again.instrument._tick()
        again.set_mode("stop")
        assert again.scope.axis_of("demo:B") == Y2, "kept with the workspace"
    finally:
        again.close()
        again.deleteLater()


def test_the_list_offers_the_other_axis(held):
    lister = held.scope.channel_list
    asked = []
    lister.axis_asked.connect(lambda key, axis: asked.append((key, axis)))
    assert lister.axes["demo:A"] == Y1
    lister.axis_asked.emit("demo:A", Y2)
    assert asked == [("demo:A", Y2)] and held.scope.axis_of("demo:A") == Y2


def test_range_is_each_axis_own(held):
    from dataclasses import replace

    scope = held.scope
    capture = held.capture
    a = capture.records["A"].channel
    b = capture.records["B"].channel
    capture.update_channels([replace(a, full_scale=5.0), replace(b, full_scale=0.5)])
    scope.set_axis("demo:B", Y2)
    scope.y_mode.setCurrentText("Range")
    y1_low, y1_high = shown_range(held, Y1)
    y2_low, y2_high = shown_range(held, Y2)
    assert -5.6 < y1_low < -5 and 5 < y1_high < 5.6
    assert -0.56 < y2_low < -0.5 and 0.5 < y2_high < 0.56


def test_zooming_y2_holds_the_axes_at_manual(held):
    amps(held)
    scope = held.scope
    scope._y_boxes[Y2].sigRangeChangedManually.emit([False, True])
    assert scope.y_mode.currentText() == "Manual"


def test_the_trigger_level_is_drawn_against_its_channels_axis(held):
    key = amps(held)
    scope = held.scope
    held.acquisition.set_trigger(source=key.split(":", 1)[1], level=2.0)
    scope._show_trigger()
    line = scope._level_lines[0]
    assert line.parentItem() is scope._y_boxes[Y2].childGroup and line.value() == 2.0
    held.acquisition.set_trigger(source="A", level=0.1)
    scope._show_trigger()
    assert line.parentItem() is scope._y_boxes[Y1].childGroup


def test_the_console_moves_a_channel(held):
    names = Scripting(held).names()
    assert names["axis"]("B", 2) == 2
    assert held.scope.axis_of("demo:B") == Y2
    assert names["axis"]("B", 1) == 1
    with pytest.raises(Exception, match="1 or 2"):
        names["axis"]("B", 3)
