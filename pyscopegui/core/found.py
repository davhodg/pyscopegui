# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""What a decoded bus has read, kept for as long as the samples it was read from.

Two kinds of keeping, one way of asking. Frames, messages and the like are kept
as they are, in a list. A parallel bus's words are not: an ADC on one, clocked
at a megahertz with a word on each edge, reads two million words a second, and
as Python numbers in lists they would take thirty times the room of the words
themselves. So they are kept in arrays, every word one after another, with a
table saying where each transfer starts and ends, and a transfer is made from
them only when it is asked for.

Either way the oldest go as the history moves on, the whole of it is there to
be asked for, and what started in a stretch of samples is found by halving,
not by looking at everything.
"""

from __future__ import annotations

import bisect
from itertools import chain
from operator import attrgetter

import numpy as np

from pyscopegui.core.parallel_decode import Transfer

#: The most frames, messages or transfers of another bus kept, whatever the
#: history: about a minute of a CAN bus as busy as it gets.
MOST_ITEMS = 500_000
#: The most words of a parallel bus kept, whatever the history: about half a
#: minute of a bus clocked at 1 MHz with a word on each edge, in some 300 MB.
MOST_WORDS_KEPT = 64_000_000
#: What an array is made to hold to begin with, and grows from by doubling.
FIRST_ROOM = 4096

_start = attrgetter("start")


class Found:
    """Frames, messages or transfers as they were read, oldest first."""

    def __init__(self, most: int = MOST_ITEMS) -> None:
        self.most = most
        self.clear()

    def clear(self) -> None:
        self._items: list = []
        #: Where the first still kept is: the ones before it are gone, and are
        #: let go of in one go now and then rather than one at a time.
        self._head = 0
        self._wrong = 0
        #: Counted up whenever what is kept changes, so that a list showing it
        #: knows when to look again.
        self.version = 0

    def __len__(self) -> int:
        return len(self._items) - self._head

    def __bool__(self) -> bool:
        return len(self) > 0

    def __iter__(self):
        return iter(self._items[self._head :])

    def __getitem__(self, number: int):
        return self._items[self._head + _index(number, len(self))]

    def extend(self, found: list) -> None:
        if not found:
            return
        self._items += found
        self._wrong += sum(1 for item in found if item.error)
        if len(self) > self.most:
            self._drop(len(self) - self.most)
        self.version += 1

    def forget_before(self, first: int) -> None:
        """Let go of what starts before this sample."""
        gone = bisect.bisect_left(self._items, first, lo=self._head, key=_start) - self._head
        if gone:
            self._drop(gone)
            self.version += 1

    def _drop(self, count: int) -> None:
        end = self._head + count
        self._wrong -= sum(1 for item in self._items[self._head : end] if item.error)
        self._head = end
        if self._head > 1024 and self._head * 2 > len(self._items):
            del self._items[: self._head]
            self._head = 0

    def errors(self) -> int:
        return self._wrong

    def between(self, first: int, last: int) -> tuple[int, int]:
        """Which of those kept start from sample ``first`` to ``last``: their
        numbers, from and up to but not including."""
        lo = bisect.bisect_left(self._items, first, lo=self._head, key=_start)
        hi = bisect.bisect_right(self._items, last, lo=lo, key=_start)
        return lo - self._head, hi - self._head

    def starts(self, lo: int, hi: int) -> np.ndarray:
        """The samples these start at."""
        items = self._items[self._head + lo : self._head + hi]
        return np.fromiter((item.start for item in items), dtype=np.int64, count=len(items))


class Transfers:
    """A parallel bus's transfers, oldest first, kept as arrays: the words one
    after another, as many bits as the bus has, and a row of a table for each
    transfer saying where it starts and ends, which words are its, and what
    was wrong with it."""

    def __init__(self, width: int, select: bool, most_words: int = MOST_WORDS_KEPT) -> None:
        self.dtype = np.uint16 if width <= 16 else np.uint32
        self.select = select
        self.most_words = most_words
        self.clear()

    def clear(self) -> None:
        self._starts = np.zeros(FIRST_ROOM, dtype=np.int64)
        self._ends = np.zeros(FIRST_ROOM, dtype=np.int64)
        #: Where each transfer's words begin, counted from the first word ever
        #: kept, so that letting old words go changes none of them.
        self._from = np.zeros(FIRST_ROOM, dtype=np.int64)
        self._problem = np.zeros(FIRST_ROOM, dtype=np.int16)
        self._words = np.zeros(FIRST_ROOM, dtype=self.dtype)
        self._streams = np.zeros(FIRST_ROOM if self.select else 0, dtype=np.uint8)
        #: The transfers kept are [head, count) of the table; the words kept are
        #: [word_head, word_count), and the first of them is word number ``gone``.
        self._head = self._count = 0
        self._word_head = self._word_count = 0
        self._gone = 0
        #: What a problem is called, by its number in the table: 0 is none.
        self._problems = [""]
        self._wrong = 0
        self.version = 0

    def __len__(self) -> int:
        return self._count - self._head

    def __bool__(self) -> bool:
        return len(self) > 0

    def __iter__(self):
        return (self[n] for n in range(len(self)))

    def __getitem__(self, number: int) -> Transfer:
        row = self._head + _index(number, len(self))
        begin = int(self._from[row]) - self._gone
        end = int(self._from[row + 1]) - self._gone if row + 1 < self._count else self._word_count
        words = self._words[begin:end].tolist()
        streams = self._streams[begin:end].tolist() if self.select else []
        error = self._problems[self._problem[row]]
        return Transfer(int(self._starts[row]), int(self._ends[row]), words, streams, error)

    @property
    def words_kept(self) -> int:
        return self._word_count - self._word_head

    def extend(self, found: list[Transfer]) -> None:
        if not found:
            return
        counts = np.fromiter((len(t.words) for t in found), dtype=np.int64, count=len(found))
        total = int(counts.sum())
        self._room(len(found), total)
        rows = slice(self._count, self._count + len(found))
        self._starts[rows] = np.fromiter((t.start for t in found), np.int64, len(found))
        self._ends[rows] = np.fromiter((t.end for t in found), np.int64, len(found))
        before = np.concatenate(([0], np.cumsum(counts)[:-1]))
        self._from[rows] = self._gone + self._word_count + before
        problems = [self._problem_number(t.error) for t in found]
        self._problem[rows] = problems
        self._wrong += sum(1 for p in problems if p)
        words = slice(self._word_count, self._word_count + total)
        self._words[words] = np.fromiter(
            chain.from_iterable(t.words for t in found), self.dtype, total
        )
        if self.select:
            self._streams[words] = np.fromiter(
                chain.from_iterable(t.streams for t in found), np.uint8, total
            )
        self._count += len(found)
        self._word_count += total
        if self.words_kept > self.most_words:
            # The oldest go, whole transfers at a time, until it is back in bounds.
            first_kept = self._gone + self._word_head + self.words_kept - self.most_words
            self._drop(int(np.searchsorted(self._from[self._head : self._count], first_kept)))
        self.version += 1

    def _problem_number(self, error: str) -> int:
        if not error:
            return 0
        if error not in self._problems:
            self._problems.append(error)
        return self._problems.index(error)

    def _room(self, rows: int, words: int) -> None:
        """Room for this many more transfers and words: what is let go of moved
        out of the way first, and only then the arrays made bigger."""
        if self._count + rows > len(self._starts):
            kept = len(self)
            for name in ("_starts", "_ends", "_from", "_problem"):
                old = getattr(self, name)
                new = (
                    old
                    if kept + rows <= len(old) // 2
                    else np.zeros(_grown(len(old), kept + rows), dtype=old.dtype)
                )
                new[:kept] = old[self._head : self._count]
                setattr(self, name, new)
            self._head, self._count = 0, kept
        if self._word_count + words > len(self._words):
            kept = self.words_kept
            names = ("_words", "_streams") if self.select else ("_words",)
            for name in names:
                old = getattr(self, name)
                new = (
                    old
                    if kept + words <= len(old) // 2
                    else np.zeros(_grown(len(old), kept + words), dtype=old.dtype)
                )
                new[:kept] = old[self._word_head : self._word_count]
                setattr(self, name, new)
            self._gone += self._word_head
            self._word_head, self._word_count = 0, kept

    def forget_before(self, first: int) -> None:
        """Let go of what starts before this sample."""
        gone = int(np.searchsorted(self._starts[self._head : self._count], first))
        if gone:
            self._drop(gone)
            self.version += 1

    def _drop(self, count: int) -> None:
        end = self._head + count
        self._wrong -= int(np.count_nonzero(self._problem[self._head : end]))
        self._head = end
        if self._head < self._count:
            self._word_head = int(self._from[self._head]) - self._gone
        else:
            self._word_head = self._word_count

    def errors(self) -> int:
        return self._wrong

    def between(self, first: int, last: int) -> tuple[int, int]:
        """Which of those kept start from sample ``first`` to ``last``: their
        numbers, from and up to but not including."""
        starts = self._starts[self._head : self._count]
        return (
            int(np.searchsorted(starts, first, side="left")),
            int(np.searchsorted(starts, last, side="right")),
        )

    def starts(self, lo: int, hi: int) -> np.ndarray:
        """The samples these start at."""
        return self._starts[self._head + lo : self._head + hi]


def _index(number: int, length: int) -> int:
    if number < 0:
        number += length
    if not 0 <= number < length:
        raise IndexError("nothing kept there")
    return number


def _grown(size: int, needed: int) -> int:
    """Doubled until it holds what is needed: never more than twice that."""
    while size < needed:
        size *= 2
    return size
