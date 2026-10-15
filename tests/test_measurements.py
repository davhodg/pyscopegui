# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Measurements: of a stretch of samples, and in the pane, between the cursors."""

import numpy as np
import pytest

from pyscopegui.core.measure import measure


def sine(hz=50.0, volts=2.0, rate=100_000.0, seconds=1.0):
    t = np.arange(round(rate * seconds)) / rate
    return volts * np.sin(2 * np.pi * hz * t), rate


# --- of a stretch of samples --------------------------------------------------------------------
def test_a_sines_levels_and_frequency():
    samples, rate = sine()
    m = measure(samples, rate)
    assert (m.minimum, m.maximum, m.peak_to_peak) == pytest.approx((-2.0, 2.0, 4.0), abs=1e-3)
    assert m.mean == pytest.approx(0.0, abs=1e-3)
    assert m.rms == pytest.approx(2.0 / np.sqrt(2), rel=1e-3)
    assert m.frequency == pytest.approx(50.0, rel=1e-3) and m.period == pytest.approx(0.02)
    assert m.duty == pytest.approx(0.5, abs=0.01)


def test_a_square_waves_duty_cycle():
    t = np.arange(100_000) / 100_000
    square = (np.sin(2 * np.pi * 1000 * t) > 0.5).astype(np.uint8)
    m = measure(square, 100_000)
    assert m.frequency == pytest.approx(1000.0, rel=1e-3)
    assert m.duty == pytest.approx(1 / 3, abs=0.01)


def test_noise_on_an_edge_is_not_counted_as_more_edges():
    samples, rate = sine()
    noisy = samples + np.random.default_rng(1).normal(0, 0.1, samples.size)
    assert measure(noisy, rate).frequency == pytest.approx(50.0, rel=0.01)


def test_a_flat_signal_or_one_edge_has_no_frequency():
    assert measure(np.ones(100), 1000).frequency is None
    step = np.where(np.arange(100) < 50, 0.0, 1.0)
    m = measure(step, 1000)
    assert m.frequency is None and m.period is None and m.duty is None


def test_gaps_are_left_out_and_too_little_is_nothing():
    samples = np.array([1.0, np.nan, 3.0])
    assert measure(samples, 1000).mean == 2.0
    assert measure(np.array([np.nan, 1.0]), 1000) is None


# --- in the pane --------------------------------------------------------------------------------
def feed(window, seconds=0.2):
    window.instrument._started -= seconds
    window.instrument._tick()


@pytest.fixture
def held(window):
    window.set_mode("auto")
    feed(window, 0.5)
    window.set_mode("stop")
    window.scope.time.setCurrentText("Manual")
    window.scope.analog.setXRange(0.0, 0.4, padding=0)
    window.scope.redraw()
    window.panes.show("measurements")
    return window


def test_over_what_is_in_view_with_fewer_than_two_cursors(held):
    view = held.measurements
    view.refresh()
    assert view.over.text().startswith("Over what is in view: 400 ms")
    row = view.row("A: sine")
    assert row["Frequency"] == "50 Hz" and row["Period"] == "20 ms"
    assert row["Peak to peak"].startswith("4 V") and row["Duty"] == "50.0 %"


def test_between_the_cursors_when_there_are_two(held):
    view = held.measurements
    held.scope.cursors.setCurrentIndex(2)
    held.scope.set_cursor(0, 0.0)
    held.scope.set_cursor(1, 0.1)
    assert view.over.text() == "Between the cursors: 100 ms", "as soon as a cursor moves"
    assert view.row("A: sine")["Frequency"] == "50 Hz"
    held.scope.set_cursor(1, 0.025)  # not two rising edges
    assert view.row("A: sine")["Frequency"] == "\u2014"


def test_a_logic_channel_has_only_how_often_it_repeats(held):
    view = held.measurements
    view.refresh()
    row = view.row("D0")
    assert row["Min"] == row["RMS"] == ""
    assert row["Frequency"] == "1 kHz" and row["Duty"] == "50.0 %"


def test_a_channel_unticked_is_not_measured(held):
    held.scope._on_shown("demo:B", False)
    held.measurements.refresh()
    with pytest.raises(KeyError):
        held.measurements.row("B: ramp")


def test_the_console_gets_the_same_numbers(held):
    numbers = held.console.namespace["measure"]("A: sine")
    assert numbers["frequency"] == pytest.approx(50.0, rel=1e-3)
    assert numbers["peak_to_peak"] == pytest.approx(4.0, abs=0.01)
    assert held.console.namespace["measure"]("D0")["duty"] == pytest.approx(0.5, abs=0.01)
