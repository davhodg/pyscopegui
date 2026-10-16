# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Instruments by name, and the one that needs no hardware."""

import importlib

import numpy as np
import pytest

from pyscopegui import backends
from pyscopegui.backends import demo
from pyscopegui.backends.base import ANALOG, DIGITAL, Instrument


@pytest.mark.parametrize("name", backends.names())
def test_every_back_end_named_is_there_and_is_an_instrument(name):
    backend = backends.BACKENDS[name]
    cls = getattr(importlib.import_module(backend.module), backend.cls)
    assert issubclass(cls, Instrument)
    assert backends.title(name)


def test_the_default_is_one_of_them():
    assert backends.DEFAULT in backends.names()


def test_the_demo_has_both_kinds_of_channel(app):
    instrument = backends.create("demo")
    kinds = [c.kind for c in instrument.channels()]
    assert kinds.count(ANALOG) == 2 and kinds.count(DIGITAL) == 5, "four lines and a CAN bus"
    assert len({c.key for c in instrument.channels()}) == len(kinds)


def test_demo_samples_are_typed_as_a_back_end_promises():
    data = demo.samples(0, 1000)
    assert set(data) == {c.key for c in demo.CHANNELS}
    for channel in demo.CHANNELS:
        samples = data[channel.key]
        assert len(samples) == 1000
        if channel.kind == ANALOG:
            assert samples.dtype == np.float32
        else:
            assert samples.dtype == np.uint8 and set(samples.tolist()) <= {0, 1}


def test_demo_samples_depend_on_their_number_and_not_on_the_block():
    whole = demo.samples(0, 3000)
    parts = [demo.samples(0, 1234), demo.samples(1234, 1766)]
    for key, samples in whole.items():
        assert np.array_equal(samples, np.concatenate([part[key] for part in parts]))


def test_the_demo_sends_blocks_that_follow_on_from_each_other(app):
    instrument = backends.create("demo")
    blocks, states = [], []
    instrument.block.connect(blocks.append)
    instrument.state_changed.connect(states.append)
    instrument.start()
    instrument._started -= 0.02  # as if twenty milliseconds had gone by
    instrument._tick()
    instrument._started -= 0.02
    instrument._tick()
    instrument.stop()
    assert states == [True, False]
    assert len(blocks) == 2
    assert blocks[0].first == 0 and blocks[1].first == len(blocks[0])
    assert len(blocks[0]) >= 0.02 * demo.RATE


def test_time_lost_is_skipped_rather_than_sent_all_at_once(app):
    instrument = backends.create("demo")
    blocks = []
    instrument.block.connect(blocks.append)
    instrument.start()
    instrument._started -= 5.0  # the computer was asleep
    instrument._tick()
    instrument.stop()
    assert len(blocks[0]) == int(demo.MOST_S * demo.RATE)
    assert blocks[0].first > 0  # said as a gap, so later samples keep their time
