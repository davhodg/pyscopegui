# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""A long stretch drawn from what was summed up as it arrived is drawn just as
it was from every sample: the same lowest and highest in every column.

Summed up a few samples at a time here, rather than 256, so that columns
start and end part way through what was summed far more often.
"""

import numpy as np
import pytest

from pyscopegui.backends.base import DIGITAL, LOST, Channel, Scale
from pyscopegui.core import capture
from pyscopegui.core.capture import Record, min_max, min_max_packed


@pytest.fixture(autouse=True)
def summed_a_few_at_a_time(monkeypatch):
    monkeypatch.setattr(capture, "SUMMED", 4)
    monkeypatch.setattr(capture, "SUMMARY_FROM", 2)


@pytest.fixture
def used(monkeypatch):
    """How often the summary was drawn from."""
    count = [0]
    ends = Record._ends

    def counting(*args):
        count[0] += 1
        return ends(*args)

    monkeypatch.setattr(Record, "_ends", counting)
    return count


def filled(kind, rng, capacity):
    channel = {
        "values": Channel("A", "A"),
        "counts": Channel("A", "A", counts=True),
    }.get(kind, Channel("D", "D", DIGITAL))
    record = Record(channel, 1000.0, capacity)
    for _ in range(30):
        count = int(rng.integers(1, capacity // 2))
        if kind == "values":
            samples = rng.normal(0, 1, count).astype(np.float32)
            if rng.random() < 0.4:
                samples[rng.integers(0, count) :][: rng.integers(1, 300)] = np.nan
            record.append(samples)
        elif kind == "counts":
            samples = rng.integers(-32767, 32768, count).astype(np.int16)
            if rng.random() < 0.2:
                samples[:] = 32767  # full scale: a reading, not a gap
            if rng.random() < 0.4:
                samples[rng.integers(0, count) :][: rng.integers(1, 300)] = LOST
            record.append(samples, Scale(0.001 if rng.random() < 0.5 else 0.002))
        elif kind == "logic":
            record.append((rng.random(count) < 0.5).astype(np.uint8))
        else:
            record.append(rng.integers(0, 256, count).astype(np.uint8))
        if rng.random() < 0.1:
            record.skip(int(rng.integers(1, 2 * capacity)))
        yield record


@pytest.mark.parametrize("seed", range(3))
@pytest.mark.parametrize("kind", ["values", "counts", "logic", "port"])
def test_every_column_is_what_every_sample_makes_it(kind, seed, used):
    rng = np.random.default_rng(seed)
    packed = kind == "port"
    cut = min_max_packed if packed else min_max
    for record in filled(kind, rng, int(rng.integers(500, 5000))):
        for _ in range(8):
            start = int(rng.integers(record.first, record.total))
            stop = int(rng.integers(start, record.total + 1))
            columns = int(rng.integers(1, 60))
            positions, values = record._cut_down(start, stop, columns, packed)
            want_positions, want_values = cut(record._held(start, stop), columns)
            assert np.array_equal(positions, want_positions)
            assert np.array_equal(values, want_values, equal_nan=kind == "values")
    assert used[0] > 20, "and the summary was drawn from"


def test_a_column_of_nothing_but_gaps_is_a_gap(used):
    record = Record(Channel("A", "A", counts=True), 1000.0, 1000)
    record.append(np.full(1000, LOST, dtype=np.int16), Scale(0.1))
    _positions, values = record._cut_down(0, 1000, 10, False)
    assert used[0] == 1 and (values == LOST).all()
    drawn = record.drawn(0.0, 1.0, 10)[2]
    assert np.isnan(drawn).all()


def test_samples_held_again_under_later_numbers_are_drawn_one_by_one(used):
    record = Record(Channel("A", "A"), 1000.0, 100)
    record.append(np.arange(100, dtype=np.float32))
    record.skip(500)  # more than it holds: what it holds is numbered on from here
    record._cut_down(record.first, record.total, 5, False)
    assert used[0] == 0
    record.append(np.arange(100, dtype=np.float32))
    record._cut_down(record.first, record.total, 5, False)
    assert used[0] == 1, "once what is held arrived after the jump"
