# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Measurements: of a stretch of samples, and in the pane, between the cursors."""

import numpy as np
import pytest

from pyscopegui.backends import demo
from pyscopegui.backends.base import Block
from pyscopegui.core import measure as measure_module
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


def old_way(samples, rate):
    """How the frequency and duty were found before: a state for every sample."""
    values = samples[~np.isnan(samples)].astype(np.float64)
    low, high = values.min(), values.max()
    middle, band = (low + high) / 2, (high - low) * measure_module.BAND
    state = np.full(len(values), -1, dtype=np.int8)
    state[values > middle + band] = 1
    state[values < middle - band] = 0
    known = np.where(state >= 0, np.arange(len(state)), 0)
    np.maximum.accumulate(known, out=known)
    held = state[known]
    edges = np.flatnonzero((held[1:] == 1) & (held[:-1] == 0)) + 1
    first, last = edges[0], edges[-1]
    return (len(edges) - 1) * rate / (last - first), np.count_nonzero(held[first:last] == 1) / (
        last - first
    )


@pytest.mark.parametrize("seed", range(5))
def test_edges_found_where_it_gets_clear_are_those_a_state_for_every_sample_found(
    seed, monkeypatch
):
    """And the same again measured in pieces, an edge falling across where one ends."""
    rng = np.random.default_rng(seed)
    t = np.arange(200_000) / 100_000.0
    samples = np.sin(2 * np.pi * rng.uniform(5, 500) * t) + rng.normal(0, 0.3, t.size)
    samples = samples.astype(np.float32)
    expected = old_way(samples, 100_000.0)
    whole = measure(samples, 100_000.0)
    assert (whole.frequency, whole.duty) == pytest.approx(expected, rel=1e-9)
    monkeypatch.setattr(measure_module, "PIECE", 997)
    pieces = measure(samples, 100_000.0)
    assert (pieces.frequency, pieces.duty) == pytest.approx(expected, rel=1e-9)
    assert pieces.mean == pytest.approx(whole.mean) and pieces.rms == pytest.approx(whole.rms)
    assert (pieces.minimum, pieces.maximum) == (whole.minimum, whole.maximum)


def test_a_long_stretch_while_running_is_close_from_a_share_of_it():
    samples, rate = sine(hz=50.0, rate=100_000.0, seconds=60.0)  # six million
    samples[1_234_567] = 9.0  # a spike the spread misses
    looked_at = []

    def values(a, b, step):
        looked_at.append(len(range(a, b, step)))
        return samples[a:b:step]

    close = measure_module.measure_held(values, 0, len(samples), rate, exact=False)
    assert not close.exact and max(looked_at) <= measure_module.LOOKED_AT
    assert close.frequency == pytest.approx(50.0, rel=1e-3)
    assert close.rms == pytest.approx(2.0 / np.sqrt(2), rel=1e-2)
    assert close.samples == pytest.approx(len(samples), rel=1e-3)
    seen = measure_module.measure_held(
        values, 0, len(samples), rate, exact=False, extremes=(-2.0, 9.0)
    )
    assert seen.maximum == 9.0, "the plot's highest stands in for the spread's"
    exact = measure_module.measure_held(values, 0, len(samples), rate)
    assert exact.exact and exact.maximum == 9.0


def test_a_slow_signal_while_running_has_its_frequency_from_the_spread():
    samples, rate = sine(hz=1.0, rate=100_000.0, seconds=30.0)  # far slower than the newest
    close = measure_module.measure_held(
        lambda a, b, step: samples[a:b:step], 0, len(samples), rate, exact=False
    )
    assert close.frequency == pytest.approx(1.0, rel=1e-2)
    assert close.duty == pytest.approx(0.5, abs=0.02)


# --- in the pane --------------------------------------------------------------------------------
def feed(window, seconds=0.2):
    """This much more of the demo's signals, straight after what it has sent,
    however long the computer took to get here: a tick that has fallen too
    far behind skips what it missed, and that gap would be measured across."""
    instrument = window.instrument
    count = round(seconds * demo.RATE)
    instrument._started -= seconds  # so its own next tick is not behind
    instrument.block.emit(Block(instrument._sent, demo.RATE, demo.samples(instrument._sent, count)))
    instrument._sent += count


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


def test_while_running_a_long_span_is_close_and_said_to_be(window, monkeypatch):
    monkeypatch.setattr(measure_module, "LOOKED_AT", 1000)  # far less than the demo sends
    window.set_mode("auto")
    feed(window, 0.5)
    window.scope.time.setCurrentText("Manual")
    window.scope.analog.setXRange(0.0, 0.4, padding=0)
    window.scope.redraw()
    window.panes.show("measurements")
    view = window.measurements
    view.refresh()
    assert view.over.text().endswith(", close while it runs")
    assert view.row("A: sine")["Frequency"].endswith("Hz")
    window.set_mode("stop")
    view.refresh()
    assert not view.over.text().endswith(", close while it runs"), "exact once it stops"
    assert view.row("A: sine")["Frequency"] == "50 Hz"


def test_what_has_stopped_is_measured_once_until_the_span_moves(held, monkeypatch):
    from pyscopegui.ui import scope_view

    calls = []
    real = scope_view.measure_held
    monkeypatch.setattr(
        scope_view, "measure_held", lambda *a, **k: calls.append(1) or real(*a, **k)
    )
    held.measurements.refresh()
    first = len(calls)
    assert first
    held.measurements.refresh()
    assert len(calls) == first, "nothing has changed: what was measured stands"
    held.scope.analog.setXRange(0.0, 0.3, padding=0)
    held.measurements.refresh()
    assert len(calls) == 2 * first
