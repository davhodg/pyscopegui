# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Cursors on the plot, and what the channel list reads at them.

Against the demo, whose every sample is a function of its number: what a
channel read at a time is known without having been there.
"""

import numpy as np
import pytest

from pyscopegui.backends import demo
from pyscopegui.ui import scope_view
from pyscopegui.ui.scope_view import DETAIL, DIFFERENCE, NOTHING_HELD, SECOND, VALUE


def feed(window, seconds=0.2):
    window.instrument._started -= seconds
    window.instrument._tick()


@pytest.fixture
def held(window):
    """The window with a fifth of a second of the demo on the plot, stopped."""
    window.set_mode("auto")
    feed(window)
    window.set_mode("stop")
    window.scope.redraw()
    return window


def texts(window, key, columns=(VALUE, SECOND, DIFFERENCE)):
    item = window.scope.channel_list._items[key]
    return tuple(item.text(column) for column in columns)


def headings(window):
    header = window.scope.channel_list.headerItem()
    return [header.text(column) for column in range(DETAIL + 1)]


def at(seconds):
    """What every demo channel reads at this time."""
    return {key: values[0] for key, values in demo.samples(round(seconds * demo.RATE), 1).items()}


def choose(window, count):
    window.scope.cursors.setCurrentIndex(count)


# --- none ------------------------------------------------------------------------------------
def test_with_no_cursor_the_list_has_no_readings_and_the_plot_has_the_room(held):
    window = held
    assert window.scope.cursor_count() == 0
    tree = window.scope.channel_list
    assert all(tree.isColumnHidden(c) for c in (VALUE, SECOND, DIFFERENCE))
    assert not tree.isColumnHidden(DETAIL)
    window.scope._show_values()
    assert texts(window, "demo:A") == ("", "", "")
    assert window.scope.cursor_times.text() == "" and window.scope.cursor_times.isHidden()
    assert not any(line.isVisible() for lines in window.scope._cursor_lines for line in lines)


# --- one -------------------------------------------------------------------------------------
def test_one_cursor_is_a_line_on_both_plots_put_in_view(held):
    window = held
    choose(window, 1)
    first, second = window.scope._cursor_lines
    assert all(line.isVisible() for line in first) and not any(line.isVisible() for line in second)
    low, high = window.scope.analog.getViewBox().viewRange()[0]
    assert low < window.scope.cursor_time(0) < high
    assert first[0].value() == first[1].value() == window.scope.cursor_time(0)
    assert headings(window)[VALUE] == "At cursor"
    assert not window.scope.channel_list.isColumnHidden(VALUE)
    assert window.scope.channel_list.isColumnHidden(SECOND)


def test_the_list_reads_every_channel_at_the_cursor(held):
    window = held
    choose(window, 1)
    window.scope.set_cursor(0, 0.005)  # a quarter of the way round the 50 Hz sine: its top
    assert texts(window, "demo:A")[0] == "2.000 V"
    for bit in range(4):
        assert texts(window, f"demo:D{bit}")[0] == str(at(0.005)[f"D{bit}"])
    assert texts(window, "demo:B")[0] == f"{at(0.005)['B']:.3f} V"
    assert window.scope.cursor_times.text() == "Cursor at 5 ms"
    assert not window.scope.cursor_times.isHidden()


def test_a_reading_is_the_nearest_sample_and_not_one_made_up_between_two(held):
    window = held
    choose(window, 1)
    rate = demo.RATE
    # A sample and a third on from the hundredth: the hundredth is the nearest.
    window.scope.set_cursor(0, (100 + 1 / 3) / rate)
    assert texts(window, "demo:B")[0] == f"{demo.samples(100, 1)['B'][0]:.3f} V"
    window.scope.set_cursor(0, (100 + 2 / 3) / rate)
    assert texts(window, "demo:B")[0] == f"{demo.samples(101, 1)['B'][0]:.3f} V"


def test_dragging_a_line_on_either_plot_moves_the_cursor_and_its_twin(held):
    window = held
    choose(window, 1)
    upper, lower = window.scope._cursor_lines[0]
    lower.setValue(0.015)  # which is what dragging it does
    assert window.scope.cursor_time(0) == 0.015 and upper.value() == 0.015
    assert texts(window, "demo:A")[0] == "-2.000 V"


def test_where_nothing_is_held_the_list_says_so(held):
    window = held
    choose(window, 1)
    for nowhere in (-1.0, 100.0):
        window.scope.set_cursor(0, nowhere)
        assert texts(window, "demo:A")[0] == NOTHING_HELD
        assert texts(window, "demo:D0")[0] == NOTHING_HELD


def test_a_gap_reads_as_nothing_held(held):
    window = held
    choose(window, 1)
    window.capture.records["A"].view()[500] = np.nan
    window.scope.set_cursor(0, 0.005)
    assert texts(window, "demo:A")[0] == NOTHING_HELD


# --- two -------------------------------------------------------------------------------------
def test_two_cursors_read_at_each_and_say_how_far_apart(held):
    window = held
    choose(window, 2)
    assert headings(window)[VALUE : DIFFERENCE + 1] == ["Cursor 1", "Cursor 2", "2 \u2212 1"]
    tree = window.scope.channel_list
    assert not tree.isColumnHidden(SECOND) and not tree.isColumnHidden(DIFFERENCE)
    window.scope.set_cursor(0, 0.005)
    window.scope.set_cursor(1, 0.015)
    assert texts(window, "demo:A") == ("2.000 V", "-2.000 V", "-4.000 V")
    said = "Cursor 1 at 5 ms, cursor 2 at 15 ms: Δ 10 ms, 100 Hz"
    assert window.scope.cursor_times.text() == said


def test_a_difference_that_is_up_says_so_and_a_logic_channel_has_none(held):
    window = held
    choose(window, 2)
    window.scope.set_cursor(0, 0.015)
    window.scope.set_cursor(1, 0.005)
    assert texts(window, "demo:A")[2] == "+4.000 V"
    assert window.scope.cursor_times.text().endswith("Δ -10 ms, 100 Hz")
    first, second, apart = texts(window, "demo:D0")
    assert (first, second) == (str(at(0.015)["D0"]), str(at(0.005)["D0"])) and apart == ""


def test_with_one_of_two_off_what_is_held_there_is_no_difference(held):
    window = held
    choose(window, 2)
    window.scope.set_cursor(0, 0.005)
    window.scope.set_cursor(1, 100.0)
    assert texts(window, "demo:A") == ("2.000 V", NOTHING_HELD, NOTHING_HELD)


def test_two_cursors_start_a_third_and_two_thirds_of_the_way_across(held):
    window = held
    choose(window, 2)
    low, high = window.scope.analog.getViewBox().viewRange()[0]
    assert window.scope.cursor_time(0) == pytest.approx(low + (high - low) / 3)
    assert window.scope.cursor_time(1) == pytest.approx(low + 2 * (high - low) / 3)


# --- staying, and coming back ------------------------------------------------------------------
def test_a_cursor_stays_at_its_time_when_the_plot_moves_on(held):
    window = held
    choose(window, 1)
    window.scope.set_cursor(0, 0.005)
    window.scope.time.setCurrentText("Manual")
    window.scope.analog.setXRange(0.1, 0.15, padding=0)
    window.scope.redraw()
    assert window.scope.cursor_time(0) == 0.005 and texts(window, "demo:A")[0] == "2.000 V"


def test_choosing_again_brings_back_a_cursor_that_is_out_of_sight(held):
    window = held
    choose(window, 2)
    window.scope.time.setCurrentText("Manual")
    window.scope.analog.setXRange(0.10, 0.16, padding=0)
    window.scope.set_cursor(0, 0.005)  # out of sight, to the left
    window.scope.set_cursor(1, 0.13)  # and one that is in view, which stays
    window.scope.cursors.activated.emit(2)
    assert window.scope.cursor_time(0) == pytest.approx(0.12)
    assert window.scope.cursor_time(1) == 0.13


def test_going_to_time_from_a_trigger_puts_the_cursors_where_the_plot_now_is(held):
    window = held
    choose(window, 1)
    window.scope.set_cursor(0, 0.15)
    box = window.trigger_bar.source
    box.setCurrentIndex(box.findData("A"))
    box.activated.emit(box.currentIndex())
    window.set_mode("normal")
    feed(window, 0.3)
    window.scope.redraw()
    assert window.scope._relative
    low, high = window.scope.analog.getViewBox().viewRange()[0]
    assert low < window.scope.cursor_time(0) < high


def test_how_many_cursors_is_remembered(held):
    from pyscopegui.ui.main_window import MainWindow

    choose(held, 2)
    again = MainWindow()
    try:
        assert again.scope.cursor_count() == 2
        assert headings(again)[SECOND] == "Cursor 2"
    finally:
        again.close()
        again.deleteLater()


def test_the_lines_are_put_back_when_the_channels_change(held):
    window = held
    choose(window, 1)
    window.scope._rebuild()
    upper, lower = window.scope._cursor_lines[0]
    assert upper in window.scope.analog.items() and lower in window.scope.digital.items()
    assert upper.isVisible()


def test_a_picture_of_the_plot_has_the_cursors_and_their_readings_in_it(held, tmp_path):
    from PySide6.QtGui import QColor, QImage

    window = held
    assert window.scope.export_png(tmp_path / "none.png")
    choose(window, 1)
    window.scope.set_cursor(0, window.scope.cursor_time(0))
    assert window.scope.export_png(tmp_path / "one.png")

    def has_cursor_colour(path):
        picture = QImage(str(path))
        wanted = QColor(scope_view.CURSOR_COLOURS[0]).rgb()
        return any(
            picture.pixel(x, y) == wanted
            for x in range(picture.width())
            for y in range(0, picture.height(), 7)
        )

    assert has_cursor_colour(tmp_path / "one.png") and not has_cursor_colour(tmp_path / "none.png")


# --- how times are said ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("seconds", "said"),
    [(1.5, "1.5 s"), (0.0123, "12.3 ms"), (-0.002, "-2 ms"), (4.5e-6, "4.5 µs"), (0.0, "0 ns")],
)
def test_a_time_is_said_in_the_unit_that_suits_it(seconds, said):
    assert scope_view.time_text(seconds) == said


def test_a_frequency_is_said_in_the_unit_that_suits_it():
    assert scope_view.frequency_text(100.0) == "100 Hz"
    assert scope_view.frequency_text(2500.0) == "2.5 kHz"
    assert scope_view.frequency_text(3.2e6) == "3.2 MHz"


def test_the_list_is_fitted_to_its_columns_as_cursors_come_and_go(held, app):
    window = held
    splitter, tree = window.scope.splitter, window.scope.channel_list
    splitter.setSizes([200, 900])
    app.processEvents()
    choose(window, 2)
    readings = sum(tree.columnWidth(c) for c in (0, VALUE, SECOND, DIFFERENCE))
    two = splitter.sizes()[0]
    assert two >= readings, "all three readings in sight"
    choose(window, 1)
    one = splitter.sizes()[0]
    choose(window, 0)
    none = splitter.sizes()[0]
    assert none < one < two, "and narrower again with fewer, for the plot"
    assert none >= tree.columnWidth(0) + tree.sizeHintForColumn(DETAIL), (
        "names and settings in sight"
    )
    assert tree.isColumnHidden(VALUE), "with no cursor there is nothing to read"


def test_a_list_dragged_shut_is_left_shut(held, app):
    window = held
    window.scope.splitter.setSizes([0, 1100])
    app.processEvents()
    choose(window, 2)
    assert window.scope.splitter.sizes()[0] == 0
