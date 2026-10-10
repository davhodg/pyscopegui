# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The samples held, and how they are cut down to be drawn."""

import numpy as np

from pyscopegui.backends.base import DIGITAL, Block, Channel
from pyscopegui.core.capture import Capture, Record, min_max


def record(capacity=10, kind="analog"):
    return Record(Channel("A", "A", kind), rate=10.0, capacity=capacity)


def test_a_record_holds_what_it_is_given_in_order():
    r = record()
    r.append(np.arange(4, dtype=np.float32))
    r.append(np.arange(4, 7, dtype=np.float32))
    assert r.view().tolist() == [0, 1, 2, 3, 4, 5, 6]
    assert (r.first, r.count, r.total) == (0, 7, 7)


def test_a_full_record_keeps_the_newest_through_every_wrap():
    """Blocks of an awkward size, so the copy back to the start happens at
    every possible offset: what is held is always the last ten, in order."""
    r = record(capacity=10)
    written = 0
    for size in [3, 7, 4, 9, 1, 6, 8, 2, 5, 10, 3, 3, 3]:
        r.append(np.arange(written, written + size, dtype=np.float32))
        written += size
        held = min(written, 10)
        assert r.view().tolist() == list(range(written - held, written))
        assert r.first == written - held


def test_a_block_bigger_than_the_record_leaves_its_newest_end():
    r = record(capacity=4)
    r.append(np.arange(11, dtype=np.float32))
    assert r.view().tolist() == [7, 8, 9, 10]
    assert r.total == 11


def test_a_stretch_of_time_is_cut_out_by_sample_number():
    r = record(capacity=100)
    r.append(np.arange(50, dtype=np.float32))
    first, samples = r.between(1.0, 2.0)  # ten a second: samples 10 to 20
    assert first == 10
    assert samples.tolist() == list(range(10, 21))


def test_time_outside_what_is_held_is_empty_rather_than_an_error():
    r = record()
    r.append(np.arange(5, dtype=np.float32))
    assert len(r.between(10.0, 20.0)[1]) == 0
    assert len(r.between(-5.0, -1.0)[1]) == 0


def test_missing_samples_are_held_as_a_gap_and_later_ones_keep_their_time():
    capture = Capture(history_s=10.0)
    capture.set_channels([Channel("A", "A"), Channel("D0", "D0", DIGITAL, "")], rate=10.0)
    gaps = []
    capture.gap.connect(gaps.append)
    block = {"A": np.ones(3, dtype=np.float32), "D0": np.ones(3, dtype=np.uint8)}
    capture.add(Block(0, 10.0, block))
    capture.add(Block(5, 10.0, block))  # samples 3 and 4 never came
    assert gaps == [2]
    analog = capture.records["A"].view()
    assert np.isnan(analog[3:5]).all() and analog[5] == 1
    assert capture.records["D0"].view().tolist() == [1, 1, 1, 0, 0, 1, 1, 1]
    assert capture.newest() == 0.8


def test_a_pause_the_instrument_took_is_a_gap_without_a_warning():
    capture = Capture(history_s=10.0)
    capture.set_channels([Channel("A", "A")], rate=10.0)
    gaps = []
    capture.gap.connect(gaps.append)
    samples = {"A": np.ones(3, dtype=np.float32)}
    capture.add(Block(0, 10.0, samples))
    capture.add(Block(5, 10.0, samples, after_pause=True))
    assert gaps == []
    assert np.isnan(capture.records["A"].view()[3:5]).all()
    assert capture.newest() == 0.8


def test_the_history_is_how_many_seconds_each_record_holds():
    capture = Capture(history_s=2.0)
    capture.set_channels([Channel("A", "A"), Channel("D0", "D0", DIGITAL, "")], rate=1000.0)
    assert {r.capacity for r in capture.records.values()} == {2000}
    capture.add(Block(0, 1000.0, {"A": np.zeros(5000, dtype=np.float32)}))
    assert capture.records["A"].count == 2000
    assert capture.oldest() == 3.0 and capture.newest() == 5.0


def test_memory_is_half_as_much_again_as_the_samples_held():
    capture = Capture(history_s=1.0)
    capture.set_channels([Channel("A", "A"), Channel("D0", "D0", DIGITAL, "")], rate=1000.0)
    assert capture.memory_bytes() == 1500 * 4 + 1500 * 1


def test_clearing_counts_from_zero_again():
    capture = Capture(history_s=1.0)
    capture.set_channels([Channel("A", "A")], rate=10.0)
    capture.add(Block(0, 10.0, {"A": np.ones(5, dtype=np.float32)}))
    capture.clear()
    assert capture.newest() is None
    assert capture.stored() == 0


def test_few_samples_are_drawn_as_they_are():
    samples = np.arange(10, dtype=np.float32)
    positions, values = min_max(samples, columns=100)
    assert positions.tolist() == list(range(10))
    assert values is samples


def test_a_spike_narrower_than_a_column_is_still_drawn():
    """The reason for a lowest and a highest rather than every nth sample."""
    samples = np.zeros(100_000, dtype=np.float32)
    samples[54_321] = 5.0
    samples[12_345] = -3.0
    positions, values = min_max(samples, columns=500)
    assert len(values) <= 2 * 500 + 2
    assert values.max() == 5.0 and values.min() == -3.0
    assert positions[0] == 0 and positions[-1] == len(samples) - 1
    assert (np.diff(positions) >= 0).all()


def test_a_count_that_does_not_divide_keeps_its_last_samples():
    samples = np.zeros(1003, dtype=np.float32)
    samples[-1] = 9.0
    _positions, values = min_max(samples, columns=100)
    assert values.max() == 9.0


def test_a_gap_does_not_blank_the_column_it_is_in():
    samples = np.ones(1000, dtype=np.float32)
    samples[100:103] = np.nan
    _positions, values = min_max(samples, columns=10)
    assert not np.isnan(values).any()


def test_logic_levels_are_cut_down_too():
    samples = (np.arange(10_000) // 50 % 2).astype(np.uint8)
    _positions, values = min_max(samples, columns=20)
    assert values.dtype == np.uint8
    assert values[0::2].tolist() == [0] * 20 and values[1::2].tolist() == [1] * 20
