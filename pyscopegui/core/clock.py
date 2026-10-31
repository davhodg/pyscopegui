# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""When an instrument's samples were taken, on the computer's clock: so that
two instruments can be shown at the same moment.

Each instrument counts its own samples, from nought when its run began, at its
own rate. Nothing says when its sample nought was -- but each block says how
many samples there are by the time it arrives, so the moment of sample nought
is when it arrived, less the time those samples took. A block arrives later
than its last sample by however long it took to get here, and that varies:
the earliest of them comes nearest, so the earliest over the last few seconds
is what is used. A few seconds, and not the whole run, because a scope's
crystal and the computer's clock drift apart, a little, all the time.

A sweep is numbered from its own start, and arrives once it is complete: its
sample nought is when it arrived, less its length. Over a slow link that is
less sure -- a Tektronix on a serial port takes seconds to send one -- so an
instrument that streams is the one to line others up by.

Good to a millisecond or a few: the jitter of a USB transfer, and of the
computer noticing it.
"""

from __future__ import annotations

import time
from collections import deque

from pyscopegui.backends.base import Block

#: The computer's clock: seconds, from anywhere, never going back.
now = time.monotonic
#: How far back the earliest arrival is looked for, in seconds.
WINDOW_S = 5.0


class SampleClock:
    """One instrument's sample nought, on the computer's clock."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """A new run: nothing known until its first block arrives."""
        #: (when a block arrived, what it put sample nought at), the last few seconds' worth.
        self._seen: deque[tuple[float, float]] = deque()
        #: When sample nought was, on the computer's clock; None until a block says.
        self.zero: float | None = None

    def saw(self, block: Block, arrived: float | None = None) -> None:
        """A block arrived, now or at this time on the computer's clock."""
        arrived = now() if arrived is None else arrived
        if block.zero is not None:
            # Known exactly, so nothing to work out from when it arrived.
            self._seen.clear()
            self.zero = block.zero
            return
        if block.sweep:
            # Complete in itself, and numbered from its own start.
            self._seen.clear()
            self.zero = arrived - len(block) / block.rate
            return
        self._seen.append((arrived, arrived - (block.first + len(block)) / block.rate))
        while self._seen and arrived - self._seen[0][0] > WINDOW_S:
            self._seen.popleft()
        self.zero = min(at for _arrived, at in self._seen)

    @property
    def known(self) -> bool:
        return self.zero is not None
