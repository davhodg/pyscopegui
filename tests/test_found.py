# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""What a decoded bus has read, kept: as it was read, or a parallel bus's words as arrays."""

from dataclasses import dataclass

import pytest

from pyscopegui.core.found import Found, Transfers
from pyscopegui.core.parallel_decode import Transfer


@dataclass
class Item:
    start: int
    error: str = ""


def transfers(count, words=4, every=10, select=True, first=0):
    """Transfers one after another, each of ``words`` words numbered on from the last."""
    made = []
    for n in range(first, first + count):
        values = [(n * words + w) & 0xFFF for w in range(words)]
        made.append(
            Transfer(
                n * every,
                n * every + every - 1,
                values,
                [w % 2 for w in range(words)] if select else [],
                "samples were lost" if n % 7 == 3 else "",
            )
        )
    return made


def same(kept, made):
    return [(t.start, t.end, t.words, t.streams, t.error) for t in kept] == [
        (t.start, t.end, t.words, t.streams, t.error) for t in made
    ]


# --- a parallel bus's transfers, as arrays --------------------------------------------------
def test_transfers_come_back_as_they_went_in_however_many_times_the_arrays_grow():
    kept = Transfers(12, select=True)
    made = transfers(5000, words=32)
    for n in range(0, len(made), 333):
        kept.extend(made[n : n + 333])
    assert len(kept) == 5000 and same(kept, made)
    assert kept[-1].words == made[-1].words and kept[0].start == 0
    assert kept.errors() == sum(1 for t in made if t.error)


def test_without_a_select_there_are_no_streams_and_wider_words_fit():
    kept = Transfers(20, select=False)
    made = [Transfer(0, 5, [0xFFFFF, 1, 2], [])]
    kept.extend(made)
    assert same(kept, made)


def test_the_oldest_go_as_the_history_moves_on_and_their_room_is_used_again():
    kept = Transfers(12, select=True)
    made = transfers(3000, words=16)
    for n in range(0, len(made), 100):
        kept.extend(made[n : n + 100])
        kept.forget_before((n - 400) * 10)
    assert kept[0].start == (len(made) - 100 - 400) * 10
    assert same(kept, made[-500:])
    assert kept.errors() == sum(1 for t in made[-500:] if t.error)
    assert len(kept._words) < 3000 * 16, "what was let go of made room, not more arrays"


def test_past_the_most_words_kept_whole_transfers_go_oldest_first():
    kept = Transfers(12, select=False, most_words=100)
    made = transfers(60, words=8, select=False)
    kept.extend(made)
    assert kept.words_kept <= 100 and len(kept) == 12
    assert same(kept, made[-12:])


def test_what_started_in_a_stretch_is_found_by_its_samples():
    kept = Transfers(12, select=True)
    kept.extend(transfers(100))
    assert kept.between(250, 300) == (25, 31)
    assert list(kept.starts(25, 31)) == [250, 260, 270, 280, 290, 300]
    kept.forget_before(200)
    assert kept.between(250, 300) == (5, 11), "counted from the first still kept"
    assert kept.between(5000, 6000) == (80, 80)


def test_cleared_it_holds_nothing():
    kept = Transfers(12, select=True)
    kept.extend(transfers(10))
    kept.clear()
    assert not kept and kept.errors() == 0
    with pytest.raises(IndexError):
        kept[0]


# --- anything else, as it was read ------------------------------------------------------------
def test_found_keeps_the_newest_up_to_its_most_and_counts_those_with_problems():
    kept = Found(most=5)
    kept.extend([Item(n, "bad" if n % 2 else "") for n in range(8)])
    assert [item.start for item in kept] == [3, 4, 5, 6, 7]
    assert kept.errors() == 3 and kept[0].start == 3 and kept[-1].start == 7


def test_found_lets_go_before_a_sample_and_finds_a_stretch():
    kept = Found()
    for n in range(0, 5000, 50):
        kept.extend([Item(m * 10) for m in range(n, n + 50)])
        kept.forget_before((n - 1000) * 10)
    assert kept[0].start == 39_500 and len(kept) == 1050
    assert kept.between(40_000, 40_100) == (50, 61)
    assert list(kept.starts(50, 53)) == [40_000, 40_010, 40_020]
    version = kept.version
    kept.forget_before(0)
    assert kept.version == version, "nothing let go of, nothing changed"
