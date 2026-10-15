# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Maths channels: two channels of one instrument, added, taken away, multiplied or divided.

Worked out sample by sample as each block arrives, and held as a channel of
the instrument like any other: so a maths channel is drawn, read by the
cursors, measured, exported, saved in a capture and given to the console with
nothing done twice. Two channels of one instrument are sampled together, at
one rate, which is what makes them two samples at a time to work on; two
instruments' are not, so a maths channel is of one instrument's.

Only analog channels: a logic level plus another is not a level.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pyscopegui.backends.base import ANALOG, Channel

#: Operation -> how it is written in a name.
OPERATIONS = {"+": "+", "-": "\u2212", "*": "\u00d7", "/": "\u00f7"}


@dataclass(frozen=True)
class Maths:
    """One maths channel: what it is worked out from, and how."""

    a: str
    op: str
    b: str

    @property
    def key(self) -> str:
        """What its samples are held under: unlike any instrument's own channel."""
        return f"maths:{self.a}{self.op}{self.b}"

    def as_saved(self) -> list[str]:
        return [self.a, self.op, self.b]

    @classmethod
    def from_saved(cls, saved: object) -> Maths | None:
        """From what was saved, or None for anything that is not one."""
        if (
            isinstance(saved, list | tuple)
            and len(saved) == 3
            and all(isinstance(part, str) for part in saved)
            and saved[1] in OPERATIONS
        ):
            return cls(saved[0], saved[1], saved[2])
        return None

    def channel(self, a: Channel, b: Channel) -> Channel:
        """What the channel is, from the two it is worked out from."""
        unit = _unit(a.unit, self.op, b.unit)
        reach = max(a.full_scale, b.full_scale)
        full_scale = {"+": 2 * reach, "-": 2 * reach}.get(self.op, 0.0)
        return Channel(
            self.key,
            f"{a.name} {OPERATIONS[self.op]} {b.name}",
            ANALOG,
            unit,
            full_scale,
            detail="maths",
        )

    def work_out(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """The samples, from the two channels' samples: a gap in either is a gap."""
        a = a.astype(np.float32, copy=False)
        b = b.astype(np.float32, copy=False)
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            if self.op == "+":
                out = a + b
            elif self.op == "-":
                out = a - b
            elif self.op == "*":
                out = a * b
            else:
                out = a / b
        # Dividing by nought is no number, as a lost sample is.
        out[~np.isfinite(out)] = np.nan
        return out


def _unit(a: str, op: str, b: str) -> str:
    """What a maths channel is measured in: volts plus volts is volts."""
    if op in "+-":
        return a if a == b else ""
    if op == "*":
        return f"{a}\u00b2" if a == b and a else f"{a}\u00b7{b}".strip("\u00b7")
    return "" if a == b else f"{a}/{b}"
