# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Triggers beyond an edge, found in samples as they arrive: whole, or a block at a time."""

import numpy as np
import pytest

from pyscopegui.core.triggers import (
    BETWEEN,
    EDGE,
    EITHER,
    ENTER,
    FALLING,
    HIGH,
    LEAVE,
    LONGER,
    LOW,
    PATTERN,
    PULSE,
    RUNT,
    SHORTER,
    TIMEOUT,
    WINDOW,
    Condition,
    Finder,
)

RATE = 1000.0  # so a sample is a millisecond
RNG = np.random.default_rng(3)


def signal(*runs):
    """Runs of (value, how many samples)."""
    return np.concatenate([np.full(n, value, dtype=np.float32) for value, n in runs])


def find(condition, samples, level=0.5, pieces=1, margin=0.05, extra=None):
    """Where the condition is met: all at once, or cut into this many blocks."""
    finder = Finder(condition, level, margin, RATE)
    data = {"X": samples, **(extra or {})}
    length = len(samples)
    cuts = (
        sorted(RNG.choice(np.arange(1, length), pieces - 1, replace=False).tolist())
        if pieces > 1
        else []
    )
    found = []
    for start, stop in zip([0, *cuts], [*cuts, length], strict=True):
        part = {key: values[start:stop] for key, values in data.items()}
        found += finder.find(part, start).tolist()
    return found


SQUARE = signal((0, 10), (1, 10), (0, 10), (1, 10), (0, 10))


@pytest.mark.parametrize("pieces", [1, 4, 30])
def test_an_edge_either_way_or_both(pieces):
    assert find(Condition(EDGE), SQUARE, pieces=pieces) == [10, 30]
    assert find(Condition(EDGE, edge=FALLING), SQUARE, pieces=pieces) == [20, 40]
    assert find(Condition(EDGE, edge=EITHER), SQUARE, pieces=pieces) == [10, 20, 30, 40]


def test_noise_on_a_slow_edge_is_one_edge():
    ramp = np.linspace(0, 1, 200).astype(np.float32)
    noisy = ramp + RNG.normal(0, 0.01, 200).astype(np.float32)
    assert len(find(Condition(EDGE, edge=EITHER), noisy)) == 1


@pytest.mark.parametrize("pieces", [1, 5, 40])
def test_a_window_entered_and_left(pieces):
    # Below, into the band between 0.5 and 1.5, above it, and back down through it.
    samples = signal((0, 10), (1, 10), (2, 10), (1, 10), (0, 10))
    window = Condition(WINDOW, upper=1.5)
    assert find(window, samples, pieces=pieces) == [10, 30]
    assert find(Condition(WINDOW, upper=1.5, direction=LEAVE), samples, pieces=pieces) == [20, 40]


@pytest.mark.parametrize("pieces", [1, 6, 50])
def test_a_pulse_shorter_longer_or_between(pieces):
    samples = signal((0, 10), (1, 5), (0, 10), (1, 20), (0, 10), (1, 50), (0, 10))
    ends = [15, 45, 105]  # where each of the three pulses ends

    def pulses(compare, shortest, longest=0.0, polarity=HIGH, data=samples):
        condition = Condition(
            PULSE, polarity=polarity, compare=compare, shortest=shortest, longest=longest
        )
        return find(condition, data, pieces=pieces)

    assert pulses(LONGER, 0.010) == ends[1:]
    assert pulses(SHORTER, 0.010) == ends[:1]
    assert pulses(BETWEEN, 0.010, 0.030) == ends[1:2]
    assert pulses(LONGER, 0.010, polarity=LOW, data=1 - samples) == ends[1:]


@pytest.mark.parametrize("pieces", [1, 5, 40])
def test_a_runt_is_a_pulse_that_does_not_reach_the_upper_level(pieces):
    # A full pulse to 1.0, then a runt to 0.6, with 0.3 and 0.8 the two levels.
    samples = signal((0, 10), (1, 10), (0, 10), (0.6, 10), (0, 10))
    runt = Condition(RUNT, upper=0.8)
    assert find(runt, samples, level=0.3, pieces=pieces) == [40]
    # Upside down: down from 1 through 0.8, back without reaching 0.3.
    low = Condition(RUNT, upper=0.8, polarity=LOW)
    assert find(low, 1 - samples, level=0.3, pieces=pieces) == [40]


@pytest.mark.parametrize("pieces", [1, 4, 30])
def test_a_timeout_is_the_moment_a_level_has_lasted_too_long(pieces):
    samples = signal((0, 20), (1, 100), (0, 100))
    assert find(Condition(TIMEOUT, polarity=HIGH, shortest=0.030), samples, pieces=pieces) == [50]
    assert find(Condition(TIMEOUT, polarity=LOW, shortest=0.030), samples, pieces=pieces) == [150]
    either = Condition(TIMEOUT, polarity=EITHER, shortest=0.030)
    assert find(either, samples, pieces=pieces) == [50, 150], "and the low before is too short"


@pytest.mark.parametrize("pieces", [1, 5, 40])
def test_a_logic_pattern_as_soon_as_it_is_there_or_once_it_has_lasted(pieces):
    a = np.array([0] * 10 + [1] * 30 + [0] * 10 + [1] * 5 + [0] * 5, dtype=np.uint8)
    b = np.array([0] * 20 + [1] * 40, dtype=np.uint8)
    # A high and B low: from 10 to 20 only.
    at_once = Condition(PATTERN, pattern=(("X", 1), ("B", 0)))
    assert find(at_once, a, pieces=pieces, extra={"B": b}) == [10]
    both = Condition(PATTERN, pattern=(("X", 1), ("B", 1)))
    assert find(both, a, pieces=pieces, extra={"B": b}) == [20, 50]
    held = Condition(PATTERN, pattern=(("X", 1), ("B", 1)), held=0.010)
    assert find(held, a, pieces=pieces, extra={"B": b}) == [30], "the second is too short"


def test_a_holdoff_takes_no_trigger_too_soon_after_the_last():
    square = signal(*[(v, 10) for v in [0, 1] * 10])
    assert find(Condition(EDGE, holdoff=0.025), square) == [10, 50, 90, 130, 170]


# --- kept with the instrument --------------------------------------------------------------------
def test_a_condition_is_saved_and_comes_back_and_nonsense_is_the_usual():
    condition = Condition(PULSE, polarity=LOW, compare=BETWEEN, shortest=1e-6, longest=5e-6)
    assert Condition.from_saved(condition.as_saved()) == condition
    pattern = Condition(PATTERN, pattern=(("D0", 1), ("D3", 0)), held=0.002, holdoff=0.1)
    assert Condition.from_saved(pattern.as_saved()) == pattern
    odd = Condition.from_saved({"kind": "glitch", "shortest": -1, "pattern": [["D0", 2]]})
    assert odd == Condition()
    assert Condition.from_saved("pulse") == Condition()
    assert Condition.from_saved({"upper": -2.5}).upper == -2.5, "a level may be below nought"


def test_each_says_what_it_is_in_a_few_words():
    assert Condition(EDGE).summary() == ""
    assert Condition(EDGE, edge=EITHER).summary() == "either edge"
    assert Condition(PULSE, compare=LONGER, shortest=0.001).summary() == "high pulse > 1 ms"
    assert Condition(WINDOW, upper=2.0, direction=ENTER).summary() == "entering window, to 2 V"
    pattern = Condition(PATTERN, pattern=(("D0", 1), ("D1", 0)), held=2e-6)
    assert pattern.summary() == "pattern D0=1 D1=0 for 2 µs"


# --- as the acquisition finds them -------------------------------------------------------------
def acquisition_with(condition, source="D0", seconds=0.01, pieces=7):
    """The demo's samples, a block at a time, looked through for the condition."""
    from pyscopegui.backends import demo
    from pyscopegui.core.acquire import AUTO, Acquisition
    from pyscopegui.core.capture import Capture

    capture = Capture(history_s=1.0)
    capture.set_channels(demo.CHANNELS, demo.RATE)
    acquisition = Acquisition(capture)
    acquisition.set_trigger(source=source, level=0.5, condition=condition)
    acquisition.set_mode(AUTO)
    total = round(seconds * demo.RATE)
    for start, stop in zip(
        [round(total * i / pieces) for i in range(pieces)],
        [round(total * (i + 1) / pieces) for i in range(pieces)],
        strict=True,
    ):
        from pyscopegui.backends.base import Block

        block = Block(start, demo.RATE, demo.samples(start, stop - start))
        capture.add(block)
        acquisition.examine(block)
    return acquisition._triggers.tolist()


def test_the_acquisition_finds_either_edge_of_a_counters_lowest_bit():
    # D0 changes every 50 samples: the demo's 1 kHz clock.
    assert acquisition_with(Condition(EDGE, edge=EITHER))[:4] == [50, 100, 150, 200]


def test_the_acquisition_finds_a_pulse_by_its_width():
    # D1 is high for 100 samples at a time, D0 for 50: a pulse over 0.75 ms is D1's.
    longer = Condition(PULSE, compare=LONGER, shortest=0.00075)
    assert acquisition_with(longer, source="D1")[:2] == [200, 400]
    assert acquisition_with(longer, source="D0") == []


def test_the_acquisition_finds_a_pattern_across_channels():
    # D0 and D1 both high: the counter at 3, 7, 11 ... every 200 samples from 150.
    both = Condition(PATTERN, pattern=(("D0", 1), ("D1", 1)))
    assert acquisition_with(both, source=None)[:3] == [150, 350, 550]


def test_a_holdoff_on_a_plain_edge_is_found_by_the_condition():
    from pyscopegui.core.acquire import Acquisition
    from pyscopegui.core.capture import Capture

    acquisition = Acquisition(Capture())
    acquisition.set_trigger(condition=Condition(EDGE, holdoff=0.001))
    assert not acquisition.finds_plain_edge()
    acquisition.set_trigger(condition=Condition(EDGE, edge=FALLING))
    assert acquisition.finds_plain_edge() and acquisition.rising is False
