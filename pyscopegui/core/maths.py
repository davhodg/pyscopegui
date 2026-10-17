# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Maths channels: worked out from an instrument's channels as blocks arrive.

Two channels added, taken away, multiplied or divided; or one channel inverted,
made positive, squared, square-rooted, scaled and offset, differentiated,
integrated or averaged.

Worked out as each block arrives, and held as a channel of the instrument like
any other: so a maths channel is drawn, read by the cursors, measured,
exported, saved in a capture and given to the console with nothing done twice.
Two channels of one instrument are sampled together, at one rate, which is
what makes them two samples at a time to work on; two instruments' are not,
so a maths channel is of one instrument's.

Most work sample by sample. A rate of change, an integral and an average also
need what came before, so they carry it from one block to the next: and start
afresh at a new run, a sweep -- complete in itself -- and a gap.

Only analog channels: a logic level plus another is not a level.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pyscopegui.backends.base import ANALOG, Channel

#: Two channels, sample by sample: operation -> how it is written in a name.
TWO = {"+": "+", "-": "\u2212", "*": "\u00d7", "/": "\u00f7"}
#: One channel: operation -> how it is written, around the channel's name.
ONE = {
    "neg": "\u2212{a}",
    "abs": "|{a}|",
    "sq": "{a}\u00b2",
    "sqrt": "\u221a{a}",
    "scale": "{k}\u00d7{a} + {c}",
    "ddt": "d{a}/dt",
    "int": "\u222b{a} dt",
    "avg": "avg {a}, {span}",
}
#: Every operation there is.
OPERATIONS = {**TWO, **ONE}
#: Those worked out from what came before as well as from each sample.
CARRIED = ("ddt", "int", "avg")
#: The longest an average is taken over, in samples: past it, the memory it
#: carries from one block to the next would be more than the channel's.
MOST_AVERAGED = 1_000_000
#: What a maths channel's name starts with, so that the maths are told apart
#: from an instrument's own channels, and listed together.
PREFIX = "Math: "


@dataclass(frozen=True)
class Maths:
    """One maths channel: what it is worked out from, and how."""

    a: str
    op: str
    #: The second channel, for an operation on two; nothing for one on one.
    b: str = ""
    #: Scale: multiplied by this, then this added, and measured in this --
    #: or in the channel's own unit, with nothing.
    k: float = 1.0
    c: float = 0.0
    unit: str = ""
    #: Average: over this long, in seconds.
    span: float = 1e-3

    @property
    def two(self) -> bool:
        """Whether it is worked out from two channels."""
        return self.op in TWO

    @property
    def sources(self) -> tuple[str, ...]:
        """The channels it is worked out from."""
        return (self.a, self.b) if self.two else (self.a,)

    @property
    def key(self) -> str:
        """What its samples are held under: unlike any instrument's own channel."""
        if self.two:
            return f"maths:{self.a}{self.op}{self.b}"
        if self.op == "scale":
            return f"maths:scale({self.a},{self.k:g},{self.c:g},{self.unit})"
        if self.op == "avg":
            return f"maths:avg({self.a},{self.span:g})"
        return f"maths:{self.op}({self.a})"

    def as_saved(self) -> list | dict:
        if self.two:
            return [self.a, self.op, self.b]
        saved: dict = {"a": self.a, "op": self.op}
        if self.op == "scale":
            saved.update(k=self.k, c=self.c, unit=self.unit)
        elif self.op == "avg":
            saved["span"] = self.span
        return saved

    @classmethod
    def from_saved(cls, saved: object) -> Maths | None:
        """From what was saved, or None for anything that is not one."""
        if (
            isinstance(saved, list | tuple)
            and len(saved) == 3
            and all(isinstance(part, str) for part in saved)
            and saved[1] in TWO
        ):
            return cls(saved[0], saved[1], saved[2])
        if not isinstance(saved, dict):
            return None
        a, op = saved.get("a"), saved.get("op")
        if not isinstance(a, str) or not a or op not in ONE:
            return None
        k, c, span = saved.get("k", 1.0), saved.get("c", 0.0), saved.get("span", 1e-3)
        unit = saved.get("unit", "")
        numbers = all(isinstance(n, int | float) and not isinstance(n, bool) for n in (k, c, span))
        if not numbers or not isinstance(unit, str) or span <= 0:
            return None
        return cls(a, op, k=float(k), c=float(c), unit=unit, span=float(span))

    def name(self, a: str, b: str = "") -> str:
        """What it is called, from what the channels it is worked out from are:
        a name of more than one word in brackets, so that what is done to it
        is plain -- d(A: sine)/dt, and not dA: sine/dt."""
        a, b = (f"({n})" if " " in n else n for n in (a, b))
        if self.two:
            return f"{PREFIX}{a} {TWO[self.op]} {b}"
        if self.op == "scale":
            # Two times A plus a half, A less one, three times A: what is not
            # there is not said.
            said = a if self.k == 1 else f"{self.k:g}\u00d7{a}"
            if self.c:
                said += f" {'+' if self.c > 0 else chr(0x2212)} {abs(self.c):g}"
            return PREFIX + said
        return PREFIX + ONE[self.op].format(a=a, span=_time(self.span))

    def channel(self, a: Channel, b: Channel | None = None) -> Channel:
        """What the channel is, from the one or two it is worked out from."""
        return Channel(
            self.key,
            self.name(a.name, b.name if b is not None else ""),
            ANALOG,
            self._unit(a.unit, b.unit if b is not None else ""),
            self._full_scale(a, b),
            detail="maths",
        )

    def _unit(self, a: str, b: str) -> str:
        """What it is measured in: volts plus volts is volts."""
        op = self.op
        if op in "+-":
            return a if a == b else ""
        if op == "*":
            return f"{a}\u00b2" if a == b and a else f"{a}\u00b7{b}".strip("\u00b7")
        if op == "/":
            return "" if a == b else f"{a}/{b}"
        return {
            "sq": f"{a}\u00b2" if a else "",
            "sqrt": f"\u221a{a}" if a else "",
            "scale": self.unit or a,
            "ddt": f"{a}/s" if a else "",
            "int": f"{a}\u00b7s" if a else "",
        }.get(op, a)

    def _full_scale(self, a: Channel, b: Channel | None) -> float:
        """How far either side of nought it can reach, where that can be said;
        nought where it cannot, and the plot fits it to what it shows."""
        reach = max(a.full_scale, b.full_scale if b is not None else 0.0)
        if self.op in "+-" and self.two:
            return 2 * reach
        if self.op in ("neg", "abs", "avg"):
            return a.full_scale
        if self.op == "scale":
            return abs(self.k) * a.full_scale + abs(self.c)
        return 0.0

    def work_out(self, a: np.ndarray, b: np.ndarray | None = None) -> np.ndarray:
        """The samples, from the channels' samples, for an operation that needs
        nothing from before them: a gap in either is a gap."""
        a = a.astype(np.float32, copy=False)
        if b is not None:
            b = b.astype(np.float32, copy=False)
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            out = {
                "+": lambda: a + b,
                "-": lambda: a - b,
                "*": lambda: a * b,
                "/": lambda: a / b,
                "neg": lambda: -a,
                "abs": lambda: np.abs(a),
                "sq": lambda: a * a,
                "sqrt": lambda: np.sqrt(a),
                "scale": lambda: a * np.float32(self.k) + np.float32(self.c),
            }[self.op]()
        # Dividing by nought, or the root of less than nought, is no number,
        # as a lost sample is.
        out = np.asarray(out, dtype=np.float32)
        out[~np.isfinite(out)] = np.nan
        return out


class Worker:
    """Works one maths channel out, block after block: with what it carries
    from one block to the next, for those that need what came before."""

    def __init__(self, maths: Maths, rate: float) -> None:
        self.maths = maths
        self.rate = rate
        self.reset()

    def reset(self) -> None:
        """Start afresh: nothing came before."""
        #: The sample before these, for a rate of change.
        self._last = np.float32(np.nan)
        #: What it has added up to, for an integral.
        self._total = 0.0
        #: The samples an average reaches back over, for the next block's first.
        self._tail = np.empty(0, dtype=np.float32)

    def take(self, a: np.ndarray, b: np.ndarray | None = None, rate: float = 0.0) -> np.ndarray:
        """The samples for the next stretch, carried on from the last."""
        if rate and rate != self.rate:
            self.rate = rate
            self.reset()
        op = self.maths.op
        if op not in CARRIED:
            return self.maths.work_out(a, b)
        a = np.asarray(a, dtype=np.float32)
        if not len(a):
            return a
        if op == "ddt":
            out = np.diff(np.concatenate(([self._last], a))) * np.float32(self.rate)
            self._last = a[-1]
        elif op == "int":
            # A lost sample adds nothing, and is no number itself.
            added = np.cumsum(np.nan_to_num(a, nan=0.0), dtype=np.float64) / self.rate
            out = (added + self._total).astype(np.float32)
            self._total += float(added[-1])
            out[np.isnan(a)] = np.nan
        else:
            out = self._average(a)
        out = np.asarray(out, dtype=np.float32)
        out[~np.isfinite(out)] = np.nan
        return out

    def _average(self, a: np.ndarray) -> np.ndarray:
        """Each sample the mean of the span before it, lost samples left out:
        over less at the very start, where there is less before it."""
        n = int(min(max(round(self.maths.span * self.rate), 1), MOST_AVERAGED))
        x = np.concatenate((self._tail, a))
        valid = ~np.isnan(x)
        sums = np.concatenate(([0.0], np.cumsum(np.where(valid, x, 0.0), dtype=np.float64)))
        counts = np.concatenate(([0], np.cumsum(valid)))
        ends = np.arange(len(self._tail) + 1, len(x) + 1)
        starts = np.maximum(ends - n, 0)
        taken = counts[ends] - counts[starts]
        with np.errstate(divide="ignore", invalid="ignore"):
            out = (sums[ends] - sums[starts]) / taken
        self._tail = x[-(n - 1) :] if n > 1 else np.empty(0, dtype=np.float32)
        return out


def _time(seconds: float) -> str:
    for scale, unit in ((1.0, "s"), (1e-3, "ms"), (1e-6, "\u00b5s"), (1e-9, "ns")):
        if seconds >= scale:
            return f"{seconds / scale:g} {unit}"
    return f"{seconds:g} s"
