# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""A run keeps only as much history as there is memory for."""

import sys

import pytest

from pyscopegui.backends.base import DIGITAL, Channel
from pyscopegui.core import memory
from pyscopegui.core.capture import SUMMED, Capture
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
    assert memory.room(0.25) == 250
    monkeypatch.setattr(memory, "available", lambda: None)
    assert memory.room() is None


@pytest.mark.skipif(
    not sys.platform.startswith(("win32", "linux")), reason="only these say what there is"
)
def test_what_there_is_in_all_is_more_than_what_is_free():
    whole = memory.total()
    assert isinstance(whole, int) and whole >= memory.available()


def test_a_history_that_fits_is_kept_whole():
    held = Capture(history_s=10.0)
    held.set_channels(TWO, 1000.0, room=lambda: 10**9)
    assert held.held_s() == 10.0
    held.set_channels(TWO, 1000.0, room=lambda: None)
    assert held.held_s() == 10.0, "and where nobody can say what is free"


def test_one_that_does_not_is_cut_down_to_what_does():
    held = Capture(history_s=10.0)
    # Two float32 channels, and what is summed up of them: 8 bytes a sample
    # and a little. A second's worth, to the next whole SUMMED of each.
    each = 2 * 4 * (1 + 2 / SUMMED)
    held.set_channels(TWO, 1000.0, room=lambda: int(1000 * each) + 1)
    assert held.held_s() == pytest.approx(1.0)
    assert held.memory_bytes() <= 1000 * each + 2 * SUMMED * 4 * (1 + 2 / SUMMED)


def test_a_logic_input_counts_a_byte_and_a_maths_channel_four():
    held = Capture(history_s=10.0)
    held.set_maths([Maths("A", "-", "B")])
    channels = [*TWO, Channel("D0", "D0", DIGITAL, "")]
    each = (4 + 4 + 1 + 4) * (1 + 2 / SUMMED)
    held.set_channels(channels, 1000.0, room=lambda: int(2000 * each) + 1)
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

    # The demo's two analog channels, and four logic ones and a CAN bus: 13
    # bytes a sample, held, and what is summed up of them.
    each = 13 * (1 + 2 / SUMMED)
    monkeypatch.setattr(memory, "room", lambda share: int(demo.RATE * 5 * each) + 1)
    window.set_mode("auto")
    assert window.instrument.running
    assert window.capture.held_s() == pytest.approx(5.0)
    said = window.log.toPlainText()
    assert "Keeping the last 5 s of each channel, not 10 s" in said
    assert window.session.history_s == 10.0, "the setting itself is left alone"
    window.set_mode("stop")


def test_a_run_with_no_memory_to_speak_of_is_not_started(window, monkeypatch):
    monkeypatch.setattr(memory, "room", lambda share: 100)
    window.set_mode("auto")
    assert not window.instrument.running
    assert "not enough memory" in window.log.toPlainText()


def memory_actions(window):
    return {action.text(): action for action in window.memory_menu.actions()}


def test_the_memory_menu_offers_shares_of_what_is_free_with_half_ticked(window):
    actions = memory_actions(window)
    assert list(actions) == [
        "25% of what is free",
        "50% of what is free",
        "75% of what is free",
        "90% of what is free",
    ]
    assert [text for text, a in actions.items() if a.isChecked()] == ["50% of what is free"]


def test_the_share_chosen_is_what_a_run_may_take_and_is_remembered(window, monkeypatch):
    from pyscopegui.ui.main_window import MainWindow

    asked = []
    monkeypatch.setattr(memory, "room", lambda share: asked.append(share) or None)
    memory_actions(window)["25% of what is free"].trigger()
    window.set_mode("auto")
    assert asked and set(asked) == {0.25}
    window.set_mode("stop")
    window.close()
    again = MainWindow()
    try:
        assert again.memory_share == 0.25
        assert memory_actions(again)["25% of what is free"].isChecked()
    finally:
        again.close()


def test_the_status_bar_says_what_is_held_and_free_and_offers_the_menu(window, monkeypatch):
    monkeypatch.setattr(memory, "available", lambda: 8_000_000_000)
    monkeypatch.setattr(memory, "total", lambda: 16_000_000_000)
    window.set_mode("auto")
    window._update_status()
    held = window.capture.memory_bytes()
    button = window.memory_button
    assert held > 0
    assert button.text().startswith("Memory: ") and "8 GB free" in button.text()
    assert "of 16 GB in all" in button.toolTip() and "4 GB" in button.toolTip()
    assert button.menu() is window.memory_menu
    window.set_mode("stop")
