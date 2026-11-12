# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""A parallel bus: words read off its lines together, with a clock or without, a
channel select saying which of two channels each is from, and an enable."""

from itertools import pairwise

import numpy as np
import pytest

from pyscopegui.core.parallel_decode import (
    BOTH,
    FALLING,
    MOST_WORDS,
    SELECT,
    ParallelDecoder,
    encode,
    word_values,
)

ADC = [0x7FF, 0x123, 0x800, 0x001, 0xABC, 0xFFF]


def lines_of(samples, width):
    return [samples[f"D{b}"] for b in range(width)]


def decode(samples, width, pieces=1, use=("CLK",), **how):
    """Fed in this many blocks, as an instrument sends them, and flushed."""
    decoder = ParallelDecoder(width, **how)
    count = len(samples["D0"])
    cuts = np.linspace(0, count, pieces + 1).astype(int)
    found = []
    for a, b in pairwise(cuts):
        part = {key: value[a:b] for key, value in samples.items()}
        found += decoder.feed(
            int(a),
            lines_of(part, width),
            clock=part["CLK"] if "CLK" in use else None,
            select=part["SEL"] if "SEL" in use else None,
            enable=part["EN"] if "EN" in use else None,
        )
    return found + decoder.flush()


def words_in(found):
    return [w for transfer in found for w in transfer.words]


def test_a_word_is_its_lines_bit_0_first():
    lines = [np.array([1, 0]), np.array([0, 0]), np.array([1, 1])]
    assert word_values(lines).tolist() == [0b101, 0b100]
    assert word_values(lines, np.array([1])).tolist() == [0b100]


@pytest.mark.parametrize("pieces", [1, 3, 37])
def test_every_word_comes_back_read_on_the_clock_however_it_is_fed(pieces):
    assert words_in(decode(encode(ADC, 12, per_word=6), 12, pieces)) == ADC


def test_a_word_is_read_as_it_was_just_before_the_edge():
    samples = encode([0x5, 0xA], 4, per_word=4)
    # The falling edge ends each word: just before it the word is still there.
    assert words_in(decode(samples, 4, edge=FALLING)) == [0x5, 0xA]


@pytest.mark.parametrize("pieces", [1, 4, 29])
def test_without_a_clock_a_word_is_read_where_the_lines_settle(pieces):
    found = decode(encode(ADC, 12, per_word=6), 12, pieces, use=(), clocked=False, settle=3)
    assert words_in(found) == ADC


def test_lines_changing_a_sample_apart_are_not_read_as_a_word_of_their_own():
    samples = encode([0x0F, 0xF0], 8, per_word=8)
    # Bit 7 a sample late: for that sample the bus says 0x70, which is not a word.
    late = samples["D7"].copy()
    rise = int(np.flatnonzero(late)[0])
    late[rise] = False
    samples["D7"] = late
    found = decode(samples, 8, use=(), clocked=False, settle=2)
    assert words_in(found) == [0x0F, 0xF0]


def test_a_channel_select_says_which_channel_each_word_is_from():
    streams = [0, 1, 0, 1, 0, 1]
    found = decode(encode(ADC, 12, per_word=6, streams=streams), 12, use=("CLK", "SEL"), mux=SELECT)
    (transfer,) = found
    assert transfer.streams == streams
    assert transfer.of(0) == [0x7FF, 0x800, 0xABC] and transfer.of(1) == [0x123, 0x001, 0xFFF]


def test_the_ad9238_s_clock_is_its_own_channel_select_read_on_both_edges():
    """A word each half clock: A while the clock is low, B while it is high."""
    a, b = [0x100, 0x101, 0x102], [0xE00, 0xE01, 0xE02]
    per_half = 4
    clock, words = [0] * 8, [0] * 8
    for word_a, word_b in zip(a, b, strict=True):
        clock += [0] * per_half + [1] * per_half
        words += [word_a] * per_half + [word_b] * per_half
    clock += [0] * 8
    words += [0] * 8
    samples = {f"D{bit}": np.array([(w >> bit) & 1 for w in words], bool) for bit in range(12)}
    samples["CLK"] = np.array(clock, bool)
    samples["SEL"] = samples["CLK"]
    found = decode(samples, 12, pieces=5, use=("CLK", "SEL"), edge=BOTH, mux=SELECT)
    together = [(w, s) for t in found for w, s in zip(t.words, t.streams, strict=True)]
    assert [w for w, s in together if s == 0][-3:] == a
    assert [w for w, s in together if s == 1] == b


def test_an_enable_makes_each_transfer():
    samples = encode([1, 2, 3, 4], 4, per_word=4)
    enable = np.ones(len(samples["D0"]), bool)  # active low: off to begin with
    enable[8:16] = False  # the first two words
    enable[18:24] = False  # the next two
    samples["EN"] = enable
    found = decode(samples, 4, use=("CLK", "EN"))
    assert [t.words for t in found] == [[1, 2], [3, 4]]
    assert found[0].start == 8 and found[0].end == 16


def test_a_pause_ends_a_transfer_and_a_bus_that_never_pauses_is_cut_up():
    first = encode([1, 2, 3], 4, per_word=4)
    gap = encode([], 4, per_word=40)
    second = encode([7, 8], 4, per_word=4)
    samples = {k: np.concatenate((first[k], gap[k], second[k])) for k in first}
    assert [t.words for t in decode(samples, 4)] == [[1, 2, 3], [7, 8]]
    many = list(range(MOST_WORDS * 2 + 5))
    found = decode(encode([w & 0xF for w in many], 4, per_word=4), 4, pieces=7)
    assert [len(t.words) for t in found] == [MOST_WORDS, MOST_WORDS, 5]


def test_a_long_run_is_the_same_whole_or_in_blocks_with_its_channels_and_times():
    many = [w & 0xFFF for w in range(MOST_WORDS * 3 + 7)]
    streams = [n % 2 for n in range(len(many))]
    samples = encode(many, 12, per_word=4, streams=streams)

    def read(pieces):
        found = decode(samples, 12, pieces=pieces, use=("CLK", "SEL"), mux=SELECT)
        return [(t.start, t.end, t.words, t.streams) for t in found]

    whole = read(1)
    assert [len(words) for _s, _e, words, _st in whole] == [MOST_WORDS] * 3 + [7]
    assert [w for _s, _e, words, _st in whole for w in words] == many
    assert [s for *_rest, st in whole for s in st] == streams
    assert read(5) == read(13) == whole


def test_samples_lost_end_a_transfer_and_say_so():
    samples = encode([1, 2, 3, 4], 4, per_word=4)
    decoder = ParallelDecoder(4)
    half = {k: v[:18] for k, v in samples.items()}
    found = decoder.feed(0, lines_of(half, 4), clock=half["CLK"])
    rest = {k: v[30:] for k, v in samples.items()}
    found += decoder.feed(30, lines_of(rest, 4), clock=rest["CLK"])
    assert found[0].error == "samples were lost" and found[0].words == [1, 2]


def test_no_such_bus_is_refused():
    with pytest.raises(ValueError):
        ParallelDecoder(0)
    with pytest.raises(ValueError):
        ParallelDecoder(8, edge="sideways")
