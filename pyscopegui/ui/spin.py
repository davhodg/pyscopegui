# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""A number box whose arrows go 1, 2, 5, 10, 20, 50, as a scope's knobs do.

A timebase runs from a millisecond to an hour, and a fixed step is wrong for
nearly all of it: a step of a second took a plot showing one millisecond to
one showing a thousand of them in a single press. Stepping through 1, 2 and 5
of each power of ten is a useful change at every size, and is the sequence
anybody who has used a scope already expects.

Only the arrows are changed. Any number can still be typed.
"""

from __future__ import annotations

import math

from PySide6.QtWidgets import QDoubleSpinBox

#: The steps within each power of ten.
SEQUENCE = (1.0, 2.0, 5.0)
#: How near a step a value has to be to count as on it, as a share of itself:
#: 0.002 is not exactly twice 0.001 in binary.
NEAR = 1e-9


def step_125(value: float, up: bool) -> float:
    """The next of 1, 2, 5, 10, 20, 50... above this value, or the next below it."""
    if value <= 0:
        return value
    exponent = math.floor(math.log10(value))
    mantissa = value / 10**exponent
    if up:
        for step in (*SEQUENCE, 10.0):
            if step > mantissa * (1 + NEAR):
                return step * 10**exponent
    for step in reversed(SEQUENCE):
        if step < mantissa * (1 - NEAR):
            return step * 10**exponent
    return SEQUENCE[-1] * 10 ** (exponent - 1)


class SequenceSpin(QDoubleSpinBox):
    """A QDoubleSpinBox that steps through 1, 2 and 5 of each power of ten."""

    def stepBy(self, steps: int) -> None:
        value = self.value()
        for _ in range(abs(steps)):
            value = step_125(value, up=steps > 0)
        # Rounded to what the box can show, or 0.002 would be shown as 0.002
        # and held as 0.0020000000000000005, which is not on a step.
        self.setValue(round(min(max(value, self.minimum()), self.maximum()), self.decimals()))
