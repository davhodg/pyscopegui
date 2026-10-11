# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The trigger, found in the samples, and Single, Normal and Auto around it."""

import numpy as np
import pytest

from pyscopegui.backends.base import DIGITAL, Block, Channel
from pyscopegui.core.acquire import AUTO, NORMAL, SINGLE, STOP, Acquisition, find_triggers
from pyscopegui.core.capture import Capture

RATE = 1000.0


def find(samples, level=0.0, low=None, rising=True, armed=False):
    low = level if low is None else low
    found, armed = find_triggers(np.asarray(samples, dtype=np.float32), level, low, rising, armed)
    return found.tolist(), armed


# --- finding a crossing ------------------------------------------------------------------------
def test_a_rising_trigger_is_the_first_sample_at_or_above_the_level():
    assert find([-1, -1, 0.5, 1, 1, -1, -1, 2], level=0.5, low=0.0) == ([2, 7], False)


def test_a_falling_trigger_is_the_same_thing_upside_down():
    assert find([1, 1, -0.5, -1, 1, 1, -2], level=-0.5, low=0.0, rising=False) == ([2, 6], False)


def test_a_signal_that_starts_above_the_level_has_not_crossed_it():
    assert find([1, 1, 1, 1], level=0.0, low=-0.1) == ([], False)


def test_noise_on_the_way_through_the_level_triggers_once():
    """The reason for a second level to go back past: without it this is three."""
    noisy = [-1, -0.5, 0.05, -0.05, 0.05, -0.05, 0.05, 0.5, 1]
    assert find(noisy, level=0.0, low=-0.2) == ([2], False)
    assert find(noisy, level=0.0, low=0.0)[0] == [2, 4, 6]


def test_being_ready_to_trigger_is_carried_from_one_block_to_the_next():
    first, armed = find([1, 1, -1, -1], level=0.0, low=-0.5)
    assert first == [] and armed is True
    assert find([-1, 1, 1], level=0.0, low=-0.5, armed=armed) == ([1], False)
    # ...and not being ready is carried too: this block starts above the level.
    assert find([1, 1, 1], level=0.0, low=-0.5, armed=False) == ([], False)


def test_a_block_that_says_nothing_either_way_leaves_it_as_it_was():
    assert find([-0.2, -0.2], level=0.0, low=-0.5, armed=True) == ([], True)
    assert find([-0.2, -0.2], level=0.0, low=-0.5, armed=False) == ([], False)


def test_a_gap_is_neither_above_nor_below():
    assert find([-1, np.nan, np.nan, 1], level=0.0, low=-0.5) == ([3], False)


def test_logic_levels_trigger_on_their_edges():
    bits = np.array([0, 0, 1, 1, 0, 1, 1, 0], dtype=np.uint8)
    rising, _ = find_triggers(bits, 0.5, 0.5, True, False)
    falling, _ = find_triggers(bits, 0.5, 0.5, False, False)
    assert rising.tolist() == [2, 5] and falling.tolist() == [4, 7]


def test_every_edge_of_a_fast_signal_is_found_without_a_loop():
    samples = np.sin(np.arange(1_000_000) * 2 * np.pi / 10).astype(np.float32)
    found, _ = find_triggers(samples, 0.0, -0.1, True, False)
    assert len(found) in (99_999, 100_000)


# --- an acquisition over a capture -------------------------------------------------------------
@pytest.fixture
def acquisition(app):
    capture = Capture(history_s=100.0)
    capture.set_channels(
        [Channel("A", "A", full_scale=1.0), Channel("D0", "D0", DIGITAL, "")], rate=RATE
    )
    made = Acquisition(capture)
    made.longest_window = lambda: 0.1  # a hundred samples
    return made


def feed(acquisition, samples, bits=None):
    """Add a block and have the acquisition look at it, as the window does."""
    capture = acquisition.capture
    first = capture.records["A"].total
    samples = np.asarray(samples, dtype=np.float32)
    bits = np.zeros(len(samples), dtype=np.uint8) if bits is None else np.asarray(bits, np.uint8)
    capture.add(Block(first, RATE, {"A": samples, "D0": bits}))
    acquisition.examine()


def square(periods, half=50):
    """So many periods of a square wave, starting low: an edge every hundred samples."""
    return np.tile(np.concatenate((-np.ones(half), np.ones(half))), periods)


def test_with_no_trigger_chosen_nothing_is_waited_for(acquisition):
    acquisition.set_mode(AUTO)
    feed(acquisition, square(5))
    assert not acquisition.triggered()
    assert acquisition.trigger_for(10) is None


def test_the_newest_trigger_with_its_samples_already_here_is_the_one_to_draw(acquisition):
    acquisition.set_trigger(source="A", level=0.0)
    acquisition.set_mode(NORMAL)
    feed(acquisition, square(5))  # edges at 50, 150, 250, 350, 450 of 500
    assert acquisition.trigger_for(50) == 450
    assert acquisition.trigger_for(51) == 350, "450 has only fifty after it yet"
    assert acquisition.trigger_for(1000) is None


def test_triggers_are_found_across_the_join_of_two_blocks(acquisition):
    acquisition.set_trigger(source="A", level=0.0)
    acquisition.set_mode(NORMAL)
    feed(acquisition, -np.ones(30))
    feed(acquisition, np.ones(30))
    assert acquisition.trigger_for(0) == 30


def test_a_digital_channel_triggers_whatever_the_level_box_says(acquisition):
    acquisition.set_trigger(source="D0", level=3.3)
    acquisition.set_mode(NORMAL)
    feed(acquisition, np.zeros(8), bits=[0, 0, 1, 1, 0, 0, 1, 1])
    assert acquisition.trigger_for(0) == 6


def test_changing_the_trigger_forgets_what_was_found_for_the_old_one(acquisition):
    acquisition.set_trigger(source="A", level=0.0)
    acquisition.set_mode(NORMAL)
    feed(acquisition, square(3))
    generation = acquisition.generation
    acquisition.set_trigger(rising=False)
    assert acquisition.trigger_for(0) is None
    assert acquisition.generation > generation
    feed(acquisition, square(2))  # falling edges at 100 and 200 of these, 400 and 500 in all
    assert acquisition.trigger_for(0) == 400


def test_single_takes_the_first_trigger_after_it_was_pressed_and_says_when_it_is_in(acquisition):
    done = []
    acquisition.single_done.connect(lambda: done.append(True))
    acquisition.set_trigger(source="A", level=0.0, position=0.5)
    acquisition.set_mode(NORMAL)
    feed(acquisition, square(2))  # edges at 50 and 150, before Single
    acquisition.set_mode(SINGLE)
    feed(acquisition, square(1))  # an edge at 250, with fifty after it: just enough
    assert done == [True]
    assert acquisition.trigger_for(50) == 250
    feed(acquisition, square(3))
    assert done == [True], "said once"
    acquisition.set_mode(STOP)
    assert acquisition.frozen == 250, "and kept on screen once stopped"
    assert acquisition.trigger_for(0) == 250, "not the later ones that came before the stop"


def test_single_waits_for_the_plot_that_shows_the_longest_stretch(acquisition):
    done = []
    acquisition.single_done.connect(lambda: done.append(True))
    acquisition.longest_window = lambda: 0.4  # two hundred samples after the trigger
    acquisition.set_trigger(source="A", level=0.0, position=0.5)
    acquisition.set_mode(SINGLE)
    feed(acquisition, square(2))  # an edge at 50, and 150 after it
    assert done == []
    feed(acquisition, square(1))
    assert done == [True]


def test_single_with_no_trigger_is_one_plots_worth_from_when_it_was_pressed(acquisition):
    done = []
    acquisition.single_done.connect(lambda: done.append(True))
    feed(acquisition, np.zeros(40))
    acquisition.set_mode(SINGLE)
    feed(acquisition, np.zeros(99))
    assert done == []
    feed(acquisition, np.zeros(1))
    assert done == [True]


def test_a_run_button_after_single_lets_go_of_what_it_caught(acquisition):
    acquisition.set_trigger(source="A", level=0.0)
    acquisition.set_mode(SINGLE)
    feed(acquisition, square(2))
    acquisition.set_mode(STOP)
    assert acquisition.frozen is not None
    acquisition.set_mode(NORMAL)
    assert acquisition.frozen is None


def test_quiet_is_no_trigger_for_that_long(acquisition):
    acquisition.set_trigger(source="A", level=0.0)
    acquisition.set_mode(AUTO)
    feed(acquisition, square(1))  # an edge at 50 of 100
    assert not acquisition.quiet_for(0.1)
    feed(acquisition, np.ones(200))
    assert acquisition.quiet_for(0.1)
    assert not acquisition.quiet_for(1.0)


def test_starting_again_forgets_everything_and_counts_from_zero(acquisition):
    acquisition.set_trigger(source="A", level=0.0)
    acquisition.set_mode(NORMAL)
    feed(acquisition, square(3))
    acquisition.capture.set_channels([Channel("A", "A", full_scale=1.0)], rate=RATE)
    acquisition.reset()
    assert acquisition.trigger_for(0) is None
    acquisition.capture.add(Block(0, RATE, {"A": square(1).astype(np.float32)}))
    acquisition.examine()
    assert acquisition.trigger_for(0) == 50


def test_samples_dropped_before_they_were_looked_at_are_not_searched(acquisition):
    """More in one block than is held: the search starts at what is still there."""
    capture = Capture(history_s=0.1)  # a hundred samples
    capture.set_channels([Channel("A", "A", full_scale=1.0)], rate=RATE)
    acquisition = Acquisition(capture)
    acquisition.set_trigger(source="A", level=0.0)
    acquisition.set_mode(NORMAL)
    capture.add(Block(0, RATE, {"A": square(5).astype(np.float32)}))
    acquisition.examine()
    assert acquisition.trigger_for(0) == 450, "only the edge in the last hundred"
