# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""A run keeps only as much history as there is memory for."""

import sys

import pytest

from pyscopegui.backends.base import DIGITAL, Channel
from pyscopegui.core import memory
from pyscopegui.core.capture import SLACK, Capture
from pyscopegui.core.maths import Maths

TWO = [Channel("A", "A"), Channel("B", "B")]


@pytest.mark.skipif(
    not sys.platform.startswith(("win32", "linux")), reason="only these say what is free"
)
def test_what_is_free_is_read_from_the_operating_system():
    free = memory.available()
    assert isinstance(free, int) and free > 0


def test_a_run_may_take_a_share_of_what_is_free(monkeypatch):
    monkeypatch.setattr(memory, "available", lambda: 1000)
    assert memory.room() == 1000 * memory.SHARE
    monkeypatch.setattr(memory, "available", lambda: None)
    assert memory.room() is None


def test_a_history_that_fits_is_kept_whole():
    held = Capture(history_s=10.0)
    held.set_channels(TWO, 1000.0, room=lambda: 10**9)
    assert held.held_s() == 10.0
    held.set_channels(TWO, 1000.0, room=lambda: None)
    assert held.held_s() == 10.0, "and where nobody can say what is free"


def test_one_that_does_not_is_cut_down_to_what_does():
    held = Capture(history_s=10.0)
    # Two float32 channels and the slack: 12 bytes a sample. A second's worth.
    held.set_channels(TWO, 1000.0, room=lambda: int(1000 * 2 * 4 * (1 + SLACK)))
    assert held.held_s() == pytest.approx(1.0)
    assert held.memory_bytes() <= 1000 * 2 * 4 * (1 + SLACK) + 16


def test_a_logic_input_counts_a_byte_and_a_maths_channel_four():
    held = Capture(history_s=10.0)
    held.set_maths([Maths("A", "-", "B")])
    channels = [*TWO, Channel("D0", "D0", DIGITAL, "")]
    each = (4 + 4 + 1 + 4) * (1 + SLACK)
    held.set_channels(channels, 1000.0, room=lambda: int(2000 * each))
    assert held.held_s() == pytest.approx(2.0)
    assert "maths:A-B" in held.records


def test_what_was_held_is_let_go_before_the_room_is_asked():
    held = Capture(history_s=1.0)
    held.set_channels(TWO, 1000.0)
    asked = []
    held.set_channels(TWO, 1000.0, room=lambda: asked.append(dict(held.records)) or None)
    assert asked == [{}]


def test_too_little_for_even_a_moment_is_a_memory_error_and_nothing_held():
    held = Capture(history_s=10.0)
    held.set_channels(TWO, 1000.0)
    with pytest.raises(MemoryError):
        held.set_channels(TWO, 1_000_000.0, room=lambda: 1000)
    assert held.records == {}


def test_sweeps_are_not_cut_down():
    held = Capture(history_s=10.0)
    held.set_channels(TWO, 1e9, capacity=1, room=lambda: 0)
    assert all(record.capacity == 1 for record in held.records.values())


# --- in the window ---------------------------------------------------------------------------
def test_a_run_short_of_memory_keeps_less_and_says_so(window, monkeypatch):
    from pyscopegui.backends import demo

    # The demo's two analog channels, and four logic ones and a CAN bus: with
    # the slack, 19.5 bytes a sample, held.
    monkeypatch.setattr(memory, "room", lambda: int(demo.RATE * 5 * 19.5))
    window.set_mode("auto")
    assert window.instrument.running
    assert window.capture.held_s() == pytest.approx(5.0)
    said = window.log.toPlainText()
    assert "Keeping the last 5 s of each channel, not 10 s" in said
    assert window.session.history_s == 10.0, "the setting itself is left alone"
    window.set_mode("stop")


def test_a_run_with_no_memory_to_speak_of_is_not_started(window, monkeypatch):
    monkeypatch.setattr(memory, "room", lambda: 100)
    window.set_mode("auto")
    assert not window.instrument.running
    assert "not enough memory" in window.log.toPlainText()
