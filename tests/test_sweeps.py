# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Sweeps: captures an instrument takes around its own trigger, each complete in itself."""

import time

import numpy as np
import pytest

from pyscopegui.backends import picoscope2000 as pico
from pyscopegui.backends.base import Block, Channel
from pyscopegui.core.acquire import NORMAL, SINGLE, STOP, Acquisition
from pyscopegui.core.capture import Capture
from pyscopegui.ui.scope_view import FREE, STOPPED, TRIGGERED


def sweep(samples, rate=1000.0, trigger=None, triggered=False):
    data = {"A": np.asarray(samples, dtype=np.float32)}
    return Block(0, rate, data, sweep=True, trigger=trigger, triggered=triggered)


# --- held ----------------------------------------------------------------------------------
@pytest.fixture
def capture(app):
    made = Capture(history_s=10.0)
    made.set_channels([Channel("A", "A", full_scale=5.0)], rate=1000.0, capacity=1)
    return made


def test_a_sweep_takes_the_place_of_what_was_held(capture):
    capture.add(sweep([1, 2, 3, 4]))
    capture.add(sweep([5, 6, 7, 8]))
    record = capture.records["A"]
    assert record.view().tolist() == [5, 6, 7, 8]
    assert (record.first, record.total) == (0, 4), "counted from nought each time"


def test_a_sweep_is_held_at_its_own_rate_and_length(capture):
    capture.add(sweep(np.zeros(100), rate=1e6))
    record = capture.records["A"]
    assert (record.rate, record.capacity, record.count) == (1e6, 100, 100)
    assert record.channel.full_scale == 5.0, "the same channel"
    capture.add(sweep(np.zeros(4000), rate=50e6))
    assert capture.records["A"].count == 4000 and capture.newest() == pytest.approx(80e-6)


def test_a_sweep_is_not_a_gap(capture):
    gaps = []
    capture.gap.connect(gaps.append)
    capture.add(sweep([1, 2, 3]))
    capture.add(sweep([1, 2, 3]))
    assert gaps == []


# --- triggered ---------------------------------------------------------------------------------
def test_the_instruments_trigger_stands_in_for_any_found_here(capture):
    acquisition = Acquisition(capture)
    acquisition.set_trigger(source="A", level=0.0)
    acquisition.set_mode(NORMAL)
    block = sweep([-1, -1, 1, 1, -1, 1], trigger=2, triggered=True)
    capture.add(block)
    acquisition.examine(block)
    assert acquisition.sweep.trigger == 2 and acquisition.sweep.length == 6
    assert acquisition.trigger_for(1000) == 2, "however much a plot would like after it"


def test_single_is_done_at_the_first_sweep(capture):
    acquisition = Acquisition(capture)
    done = []
    acquisition.single_done.connect(lambda: done.append(True))
    acquisition.set_mode(SINGLE)
    for _ in range(2):
        block = sweep([-1, 1], trigger=1, triggered=True)
        capture.add(block)
        acquisition.examine(block)
    assert done == [True]
    acquisition.set_mode(STOP)
    assert acquisition.frozen == 1


def test_starting_again_forgets_the_sweep(capture):
    acquisition = Acquisition(capture)
    block = sweep([-1, 1], trigger=1)
    capture.add(block)
    acquisition.examine(block)
    acquisition.reset()
    assert acquisition.sweep is None


# --- in the window, from a scope reading blocks ------------------------------------------------
@pytest.fixture
def scope_window(window, monkeypatch):
    """The window with a pretend PicoScope chosen and set to read blocks."""
    from tests.test_picoscope2000 import FakeLibrary

    window.library = FakeLibrary()
    monkeypatch.setattr(pico, "load_library", lambda: window.library)
    window.ctx.settings.set("instrument.picoscope2000", {"mode": "block"})
    window.choose("picoscope2000")
    yield window
    window.close_instrument()


def wait_for(app, done, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not done() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert done(), "timed out"


def choose_source(window, key):
    box = window.trigger_bar.source
    box.setCurrentIndex(box.findData(key))
    box.activated.emit(box.currentIndex())


def test_a_block_is_drawn_whole_with_nought_at_the_scopes_trigger(scope_window, app):
    window = scope_window
    window.instrument_view.open.click()
    choose_source(window, "A")
    window.trigger_bar.position.setValue(25)
    window.set_mode("normal")
    wait_for(app, lambda: window.acquisition.sweep is not None)
    wait_for(app, lambda: window.acquisition.sweep.trigger == 781)
    window.scope.redraw()
    low, high = window.scope.analog.getViewBox().viewRange()[0]
    length = 3125 / 3_125_000  # a millisecond
    assert low == pytest.approx(-0.25 * length, rel=1e-3)
    assert high == pytest.approx(0.75 * length, rel=1e-3)
    assert window.scope.trigger_lines[0].isVisible()
    assert window.capture.records["A"].rate == pytest.approx(3_125_000)
    window._update_status()
    assert "3.125 MS/s, 1 ms held" in window.status.text()
    assert not window.scope.window_s.isEnabled(), "the whole block is shown"
    assert "2 channels in blocks" in window.log.toPlainText()
    assert not window.instrument_view.controls["rate"].isEnabled()


def test_what_the_trigger_toolbar_says_is_what_the_scope_is_told(scope_window, app):
    window = scope_window
    window.instrument_view.open.click()
    choose_source(window, "B")
    window.trigger_bar.level.setValue(2.5)
    window.set_mode("normal")
    told = ("trigger", pico.CHANNEL_B, round(pico.MAX_VALUE / 2), pico.RISING, -50, 0)
    wait_for(app, lambda: told in window.library.calls)


def test_auto_tells_the_scope_to_give_up_waiting_and_says_when_it_did(scope_window, app):
    window = scope_window
    window.library.block_wave = lambda n: np.full(n, -16000)  # never near the level
    window.instrument_view.open.click()
    choose_source(window, "A")
    window.set_mode("auto")
    wait_for(app, lambda: window.acquisition.sweep is not None)
    assert any(c[0] == "trigger" and c[-1] >= pico.AUTO_TRIGGER_MS for c in window.library.calls)
    window.scope.redraw()
    assert window.scope.state.text() == FREE


def test_a_triggered_block_says_so(scope_window, app):
    window = scope_window
    window.instrument_view.open.click()
    choose_source(window, "A")
    window.set_mode("normal")
    wait_for(app, lambda: window.acquisition.sweep is not None)
    window.scope.redraw()
    assert window.scope.state.text() == TRIGGERED


def test_single_takes_one_block_and_stops(scope_window, app):
    window = scope_window
    window.instrument_view.open.click()
    choose_source(window, "A")
    window.instrument_bar.modes["single"].click()
    wait_for(app, lambda: not window.instrument.running)
    assert window.instrument_bar.mode() == "stop"
    assert window.capture.records["A"].count == 3125
    window.scope.redraw()
    assert window.scope.state.text() == STOPPED
    assert window.instrument.is_open


def test_with_no_trigger_blocks_follow_one_another_from_nought(scope_window, app):
    window = scope_window
    window.set_mode("auto")
    wait_for(app, lambda: window.acquisition.sweep is not None)
    window.scope.redraw()
    low, high = window.scope.analog.getViewBox().viewRange()[0]
    assert low == pytest.approx(0.0, abs=1e-9) and high == pytest.approx(0.001, rel=1e-3)
    assert not window.scope.trigger_lines[0].isVisible()
    assert window.scope.state.text() == ""


def test_no_history_is_set_aside_for_blocks(scope_window, app):
    """Ten seconds at a hundred million samples a second is not what is wanted."""
    window = scope_window
    window.set_mode("auto")
    wait_for(app, lambda: window.acquisition.sweep is not None)
    assert window.capture.memory_bytes() < 1_000_000
    assert "Keeping the last" not in window.log.toPlainText()
    assert "Blocks of 3125 samples" in window.log.toPlainText()


def test_going_back_to_streaming_is_a_stream_again(scope_window, app):
    window = scope_window
    window.set_mode("auto")
    wait_for(app, lambda: window.acquisition.sweep is not None)
    box = window.instrument_view.controls["mode"]
    box.setCurrentIndex(box.findData("stream"))
    box.activated.emit(box.currentIndex())
    assert not window.instrument.sweeps
    assert window.acquisition.sweep is None
    assert window.capture.records["A"].rate == pico.DEFAULT_RATE
    assert window.instrument.running
    assert window.library.calls.count(("open",)) == 1
    window.scope.redraw()
    assert window.scope.window_s.isEnabled()
    assert window.instrument_view.controls["rate"].isEnabled()


def test_the_settings_offered_follow_the_model_once_it_is_open(window, monkeypatch, app):
    from tests.test_picoscope2000 import FakeLibrary

    library = FakeLibrary(info={pico.INFO_VARIANT: b"2202"})
    monkeypatch.setattr(pico, "load_library", lambda: library)
    window.choose("picoscope2000")
    assert "gen_wave" in window.instrument_view.controls, "before it is known which it is"
    window.instrument_view.open.click()
    wait_for(app, lambda: window.instrument.is_open)
    assert "gen_wave" not in window.instrument_view.controls
    assert "scale_a" in window.instrument_view.controls
    window.close_instrument()
