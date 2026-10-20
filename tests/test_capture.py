# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The samples held, and how they are cut down to be drawn."""

import numpy as np
import pytest

from pyscopegui.backends.base import DIGITAL, LOST, Block, Channel, Scale
from pyscopegui.core.capture import Capture, Record, min_max
from pyscopegui.core.maths import Maths


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


# --- held as counts ----------------------------------------------------------------------------
def counted(capacity=10):
    return Record(Channel("A", "A", counts=True), rate=10.0, capacity=capacity)


def test_counts_take_half_the_memory_of_volts():
    capture = Capture(history_s=1.0)
    capture.set_channels([Channel("A", "A", counts=True)], rate=1000.0)
    assert capture.records["A"].counts
    assert capture.memory_bytes() == 1500 * 2


def test_counts_are_held_as_they_came_and_read_in_volts():
    r = counted()
    r.append(np.array([100, -200, 300], dtype=np.int16), Scale(0.01, 0.5))
    assert r._held(0, 3).tolist() == [100, -200, 300], "held as sent"
    assert r.values().dtype == np.float32
    assert r.values().tolist() == pytest.approx([0.5, -2.5, 2.5])
    assert r.values(1, 2).tolist() == pytest.approx([-2.5])


def test_each_stretch_of_counts_is_read_at_the_scale_it_came_with():
    """A range changed while running: the samples before it keep their volts."""
    r = counted(capacity=10)
    r.append(np.full(4, 1000, dtype=np.int16), Scale(0.001))
    r.append(np.full(4, 1000, dtype=np.int16), Scale(0.01))
    assert r.values().tolist() == pytest.approx([1.0] * 4 + [10.0] * 4)
    assert r.values(3, 5).tolist() == pytest.approx([1.0, 10.0])
    r.append(np.full(6, 1000, dtype=np.int16), Scale(0.01))
    assert r.values().tolist() == pytest.approx([10.0] * 10)
    assert len(r._scales) == 1, "what is no longer held is let go of"


def test_a_lost_count_and_a_gap_are_read_as_nothing():
    r = counted(capacity=20)
    r.append(np.array([10, LOST, 30], dtype=np.int16), Scale(0.1))
    r.skip(2)
    r.append(np.array([50], dtype=np.int16), Scale(0.1))
    got = r.values()
    assert np.isnan(got).tolist() == [False, True, False, True, True, False]
    assert got[[0, 2, 5]].tolist() == pytest.approx([1.0, 3.0, 5.0])


def test_counts_with_no_scale_are_refused():
    with pytest.raises(ValueError, match="needs their scale"):
        counted().append(np.zeros(2, dtype=np.int16))


def test_counts_are_drawn_as_volts_and_only_those_drawn_are_worked_out():
    r = Record(Channel("A", "A", counts=True), rate=1.0, capacity=10_000)
    counts = np.zeros(10_000, dtype=np.int16)
    counts[1234], counts[5678] = 20_000, -10_000
    counts[100:110] = LOST
    r.append(counts, Scale(1e-4, 1.0))
    first, _positions, values = r.drawn(0.0, 10_000.0, columns=50)
    assert first == 0 and len(values) <= 2 * 50 + 2
    assert values.max() == pytest.approx(1.0) and values.min() == pytest.approx(-2.0)
    assert not np.isnan(values).any(), "a lost count does not blank its column"
    _first, as_volts = r.between(0.0, 10_000.0)
    _positions, expected = min_max(as_volts, 50)
    assert values.tolist() == pytest.approx(expected.tolist())


def test_a_column_of_nothing_but_lost_counts_is_a_gap():
    r = Record(Channel("A", "A", counts=True), rate=1.0, capacity=1000)
    counts = np.ones(1000, dtype=np.int16)
    counts[:100] = LOST
    r.append(counts, Scale(1.0))
    _first, _positions, values = r.drawn(0.0, 1000.0, columns=10)
    assert np.isnan(values[:2]).all() and not np.isnan(values[2:]).any()


def test_a_block_of_counts_is_held_and_decoded_and_worked_out_in_volts():
    capture = Capture(history_s=1.0)
    capture.set_channels([Channel("A", "A", counts=True)], rate=10.0)
    capture.set_maths([Maths("A", "neg")])
    capture.add(Block(0, 10.0, {"A": np.array([10, 20], dtype=np.int16)}, scales={"A": Scale(0.1)}))
    assert capture.records["A"].values().tolist() == pytest.approx([1.0, 2.0])
    assert capture.records[Maths("A", "neg").key].values().tolist() == pytest.approx([-1.0, -2.0])


# --- logic inputs held packed ------------------------------------------------------------------
def inputs(port="port0", first=0):
    return [
        Channel(f"D{first + bit}", f"D{first + bit}", DIGITAL, "", port=port, bit=bit)
        for bit in range(8)
    ]


def packed_block(first, port_samples, port="port0"):
    data = {port: np.asarray(port_samples, dtype=np.int16)}
    bits = {f"D{bit}": (port, bit) for bit in range(8)}
    return Block(first, 10.0, data, bits=bits)


def test_a_port_of_eight_inputs_takes_a_byte_a_sample():
    capture = Capture(history_s=1.0)
    capture.set_channels([Channel("A", "A", counts=True), *inputs()], rate=1000.0)
    assert list(capture.records) == ["A"] + [f"D{bit}" for bit in range(8)]
    assert list(capture.ports) == ["port0"]
    assert capture.memory_bytes() == 1500 * 2 + 1500 * 1


def test_each_input_is_read_out_of_its_port_where_it_is_looked_at():
    capture = Capture(history_s=1.0)
    capture.set_channels(inputs(), rate=10.0)
    capture.add(packed_block(0, [0b0000_0001, 0b1000_0010, 0b1000_0011]))
    assert capture.ports["port0"].values().tolist() == [1, 130, 131], "held as sent"
    assert capture.records["D0"].values().tolist() == [1, 0, 1]
    assert capture.records["D1"].values().tolist() == [0, 1, 1]
    assert capture.records["D7"].values(1, 3).tolist() == [1, 1]
    assert capture.records["D7"].values().dtype == np.uint8
    d0 = capture.records["D0"]
    assert (d0.first, d0.total, d0.count, d0.rate) == (0, 3, 3, 10.0)


def test_every_input_of_a_port_is_drawn_from_one_pass_over_it():
    rng = np.random.default_rng(1)
    port = rng.integers(0, 256, 10_000).astype(np.int16)
    port[5000:6000] = 0b0000_0100  # a stretch of D2 alone
    capture = Capture(history_s=1000.0)
    capture.set_channels(inputs(), rate=10.0)
    capture.add(packed_block(0, port))
    for bit in range(8):
        record = capture.records[f"D{bit}"]
        first, positions, values = record.drawn(0.0, 1000.0, columns=50)
        _positions, expected = min_max(((port >> bit) & 1).astype(np.uint8), 50)
        assert values.tolist() == expected.tolist(), f"D{bit}"
        assert first == 0 and len(positions) == len(values)


def test_a_port_s_sweep_and_a_clear_keep_its_inputs_reading_it():
    capture = Capture(history_s=1.0)
    capture.set_channels(inputs(), rate=10.0, capacity=1)
    sweep = packed_block(0, [1, 0, 1, 1])
    capture.add(Block(0, 20.0, sweep.data, sweep=True, bits=sweep.bits))
    assert capture.records["D0"].values().tolist() == [1, 0, 1, 1]
    assert capture.records["D0"].rate == 20.0
    capture.clear()
    capture.add(packed_block(0, [2]))
    assert capture.records["D1"].values().tolist() == [1]


def test_a_decoding_and_a_trigger_read_inputs_out_of_a_port():
    block = packed_block(0, [0b10, 0b01])
    assert block.values("D1").tolist() == [1, 0]
    alone = block.in_units(["D0"])
    assert list(alone.data) == ["D0"] and alone.data["D0"].tolist() == [0, 1]
    assert not alone.bits


def test_a_packed_input_is_written_to_a_file_on_its_own():
    channel = inputs()[3]
    assert channel.plain() == Channel("D3", "D3", DIGITAL, "")
