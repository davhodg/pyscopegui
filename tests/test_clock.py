# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""When an instrument's samples were taken, on the computer's clock."""

import numpy as np
import pytest

from pyscopegui.backends.base import Block
from pyscopegui.core.clock import WINDOW_S, SampleClock


def block(first, count, rate=1000.0, sweep=False):
    return Block(first, rate, {"A": np.zeros(count, np.float32)}, sweep=sweep)


def test_nothing_is_known_until_a_block_arrives():
    clock = SampleClock()
    assert not clock.known and clock.zero is None
    clock.saw(block(0, 100), arrived=10.1)
    assert clock.known and clock.zero == pytest.approx(10.0)
    clock.reset()
    assert not clock.known


def test_the_block_that_came_soonest_says_when_sample_nought_was():
    clock = SampleClock()
    # Started at 10 s; each block took a little while to arrive, some longer.
    clock.saw(block(0, 100), arrived=10.104)
    clock.saw(block(100, 100), arrived=10.201)
    clock.saw(block(200, 100), arrived=10.330)
    assert clock.zero == pytest.approx(10.001)


def test_only_the_last_few_seconds_count_as_the_clocks_drift_apart():
    clock = SampleClock()
    clock.saw(block(0, 100), arrived=10.1)  # a quick one, long ago
    for second in range(1, int(WINDOW_S) + 3):
        first = second * 1000
        clock.saw(block(first, 100), arrived=10.0 + (first + 100) / 1000 + 0.003)
    assert clock.zero == pytest.approx(10.003), "the quick one has been forgotten"


def test_a_sweep_began_its_length_before_it_arrived():
    clock = SampleClock()
    clock.saw(block(0, 100), arrived=5.1)
    clock.saw(block(0, 1200, rate=100_000.0, sweep=True), arrived=20.0)
    assert clock.zero == pytest.approx(19.988)
    clock.saw(block(0, 1200, rate=100_000.0, sweep=True), arrived=21.0)
    assert clock.zero == pytest.approx(20.988), "each sweep by itself"
