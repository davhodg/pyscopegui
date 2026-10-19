# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Stop, Single, Normal and Auto, and the trigger they wait for.

The trigger is found here, in the samples as they arrive, rather than by the
instrument. That makes it the same for every instrument, lets one instrument's
channel trigger the view of another's, and leaves the samples either side of a
trigger where they were: the whole of what is held can still be gone back
over. It finds nothing an instrument cannot stream, which is what an
instrument's own trigger is for.

A trigger is only a sample's number. Each plot draws its own stretch of time
around the newest one that it has the samples to draw, so two plots with
different windows are both held still by the same edge.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QObject, Signal

from pyscopegui.backends.base import ANALOG, Block
from pyscopegui.core.capture import Capture, Record
from pyscopegui.core.triggers import (
    EDGE,
    EITHER,
    FALLING,
    PATTERN,
    PROTOCOL,
    RISING,
    Condition,
    Finder,
    item_matches,
)

STOP, SINGLE, NORMAL, AUTO = "stop", "single", "normal", "auto"
MODES = (STOP, SINGLE, NORMAL, AUTO)

#: How far the signal has to go back past the level before it can cross it
#: again, as a share of the channel's range. Without it, the noise on a slow
#: edge crosses the level a dozen times on the way through.
HYSTERESIS = 0.02
#: How long Auto waits for a trigger before showing what there is anyway, at
#: the least. A plot showing a longer stretch than this waits that long.
AUTO_S = 0.25
#: The most triggers remembered as they came, and the most older ones,
#: thinned out over the history: see Acquisition._keep.
MOST_TRIGGERS = 4096


@dataclass(frozen=True)
class Sweep:
    """A capture an instrument took around its own trigger."""

    #: The sample its trigger is at, or None if it was taken without one.
    trigger: int | None
    length: int
    #: Whether the signal crossed the level, or the instrument gave up waiting.
    triggered: bool


def find_triggers(
    samples: np.ndarray, level: float, low: float, rising: bool, armed: bool
) -> tuple[np.ndarray, bool]:
    """Where the samples cross the level, and whether a crossing is still owed.

    A rising trigger is the first sample at or above ``level`` since the
    signal was last at or below ``low``. ``armed`` says whether it had been,
    by the end of the samples before these; what is returned with the
    positions says the same of the end of these. Falling is the same thing
    upside down, and ``low`` is then above the level.

    No loop over samples or over triggers: a 100 kHz signal has a thousand
    edges in every block.
    """
    if not rising:
        samples, level, low = -samples.astype(np.float32), -level, -low
    count = len(samples)
    if count == 0:
        return np.empty(0, dtype=np.int64), armed
    above = samples >= level
    below = samples <= low
    numbers = np.arange(1, count + 1)
    #: For each sample, the number of the last one at or above the level, and
    #: of the last at or below the low one, up to and including it. Zero is none.
    last_above = np.maximum.accumulate(np.where(above, numbers, 0))
    last_below = np.maximum.accumulate(np.where(below, numbers, 0))
    before = np.concatenate(([0], last_above[:-1]))
    # Armed when the last time it was low is more recent than the last time
    # it was high. Before either has happened here, what was carried in decides.
    ready = (2 * last_below + int(armed)) > 2 * before
    found = np.flatnonzero(above & ready).astype(np.int64)
    if last_below[-1] > last_above[-1]:
        armed = True
    elif last_above[-1] > last_below[-1]:
        armed = False
    return found, armed


class Acquisition(QObject):
    """Which of Stop, Single, Normal and Auto is chosen, and where the triggers are."""

    #: The trigger's settings or the mode changed: whatever draws them should look again.
    changed = Signal()
    #: Single has its capture. Whoever runs the instrument stops it.
    single_done = Signal()

    def __init__(self, capture: Capture, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.capture = capture
        self.mode = STOP
        #: The key of the channel triggered on, or None for no trigger.
        self.source: str | None = None
        self.level = 0.0
        self.rising = True
        #: What is waited for beyond a rising or falling edge: see
        #: pyscopegui.core.triggers. A plain edge is found here, as it always was.
        self.condition = Condition()
        #: Where the trigger sits in a plot's stretch of time, from 0 at its
        #: left edge to 1 at its right.
        self.position = 0.5
        #: The longest stretch of time any plot is showing, in seconds. Asked
        #: for by Single, which has to wait for the plot that needs most.
        self.longest_window: Callable[[], float] = lambda: 0.0
        #: Goes up whenever the triggers found so far stop meaning anything.
        self.generation = 0
        self.reset()
        # A protocol trigger is what is read off a decoded bus, as it is read.
        capture.decoded.connect(self._on_decoded)

    # --- settings --------------------------------------------------------------------------
    def set_trigger(
        self,
        source: str | None = None,
        level: float | None = None,
        rising: bool | None = None,
        position: float | None = None,
        clear_source: bool = False,
        condition: Condition | None = None,
    ) -> None:
        """Change what is waited for. What was found for the old settings is forgotten."""
        if clear_source:
            self.source = None
        elif source is not None:
            self.source = source
        if level is not None:
            self.level = float(level)
        if rising is not None:
            self.rising = bool(rising)
        if position is not None:
            self.position = min(max(float(position), 0.0), 1.0)
        if condition is not None:
            self.condition = condition
            if condition.kind == EDGE and condition.edge in (RISING, FALLING):
                self.rising = condition.edge == RISING
        self._forget(from_now=True)
        self.changed.emit()

    def set_mode(self, mode: str) -> None:
        self.mode = mode if mode in MODES else STOP
        if self.mode != STOP:
            self._frozen = None
        if self.mode == SINGLE:
            record = self.record()
            self._single = None
            self._single_from = record.total if record is not None else self._newest()
            self._single_said = False
        self.changed.emit()

    def reset(self) -> None:
        """The instrument is starting again, counting samples from zero."""
        self._forget(from_now=False)
        self._single_from = 0

    def _forget(self, from_now: bool) -> None:
        self._triggers = np.empty(0, dtype=np.int64)
        #: The last sweep an instrument sent, if it sends sweeps: its own
        #: trigger stands in for any found here.
        self.sweep: Sweep | None = None
        record = self.record()
        self._scanned = record.total if from_now and record is not None else 0
        self._armed = False
        #: What finds anything but a plain edge, made once there are samples.
        self._finder: Finder | None = None
        self._single: int | None = None
        self._single_said = False
        #: What Single caught, kept on screen once the instrument has stopped.
        self._frozen: int | None = None
        self.generation += 1

    # --- the samples ---------------------------------------------------------------------
    def record(self) -> Record | None:
        """The record triggered on, or None with no trigger or no such channel.
        For a logic pattern, its first channel's."""
        keys = self.keys()
        return self.capture.records.get(keys[0]) if keys else None

    def keys(self) -> list[str]:
        """The channels the trigger reads: the source, or a pattern's channels."""
        condition = self.condition
        if condition.kind == PATTERN:
            return [key for key, _level in condition.pattern]
        if condition.kind == PROTOCOL:
            decoding = self._decoding()
            return list(decoding.setup.channels()) if decoding is not None else []
        return [self.source] if self.source is not None else []

    def _decoding(self):
        """The decoded bus a protocol trigger waits on, if it is decoded."""
        bus = self.condition.bus
        return next((d for d in self.capture.decodings if d.key == bus), None)

    def finds_plain_edge(self) -> bool:
        """Whether it is a rising or falling edge and nothing more: what any
        instrument can trigger on by itself."""
        condition = self.condition
        return condition.kind == EDGE and condition.edge != EITHER and not condition.holdoff

    def _newest(self) -> int:
        return max((r.total for r in self.capture.records.values()), default=0)

    def _rate(self) -> float:
        record = self.record() or next(iter(self.capture.records.values()), None)
        return record.rate if record is not None else 1.0

    def levels(self, record: Record) -> tuple[float, float]:
        """The level to cross, and the one to go back past before crossing it again.

        A digital channel has one level, between its 0 and its 1, whatever
        the level box says.
        """
        if record.channel.kind != ANALOG:
            return 0.5, 0.5
        margin = HYSTERESIS * record.channel.full_scale
        return self.level, self.level - margin if self.rising else self.level + margin

    def examine(self, block: Block | None = None) -> None:
        """Look for triggers in whatever has arrived since the last look.

        Given the block that arrived, a sweep is taken as it is: the
        instrument has triggered already, and says where.
        """
        if block is not None and block.sweep:
            self.sweep = Sweep(block.trigger, len(block), block.triggered)
            if self.mode == SINGLE and not self._single_said:
                self._single_said = True
                self._frozen = block.trigger or 0
                self.single_done.emit()
            return
        if not self.finds_plain_edge():
            if self.condition.kind != PROTOCOL:
                self._examine_condition()
            if self.mode == SINGLE:
                self._watch_single()
            return
        record = self.record()
        if record is not None and record.total > self._scanned:
            if self._scanned < record.first:
                # More arrived than is held: what was dropped cannot be searched.
                self._scanned, self._armed = record.first, False
            samples = record.view()[self._scanned - record.first :]
            level, low = self.levels(record)
            found, self._armed = find_triggers(samples, level, low, self.rising, self._armed)
            if len(found):
                self._keep(found + self._scanned)
            self._scanned = record.total
        if self.mode == SINGLE:
            self._watch_single()

    def _examine_condition(self) -> None:
        """Look for the condition in what has arrived on its channels since the last look."""
        keys = self.keys()
        records = [self.capture.records.get(key) for key in keys]
        if not records or any(record is None for record in records):
            return
        end = min(record.total for record in records)
        held_from = max(record.first for record in records)
        if self._scanned < held_from:
            # More arrived than is held: what was dropped cannot be searched.
            self._scanned, self._finder = held_from, None
        if end <= self._scanned:
            return
        if self._finder is None:
            first = records[0]
            analog = first.channel.kind == ANALOG
            margin = HYSTERESIS * first.channel.full_scale if analog else 0.0
            self._finder = Finder(self.condition, self.level, margin, first.rate)
        data = {
            key: record.view()[self._scanned - record.first : end - record.first]
            for key, record in zip(keys, records, strict=True)
        }
        found = self._finder.find(data, self._scanned)
        if len(found):
            self._keep(found)
        self._scanned = end

    def _on_decoded(self, decoding, found: list, _received: int) -> None:
        """What was read off a bus as a block arrived: a trigger at the start of
        each thing that matches, if it is the bus waited on."""
        condition = self.condition
        if condition.kind != PROTOCOL or decoding.key != condition.bus:
            return
        protocol = decoding.setup.protocol
        hits = [item.start for item in found if item_matches(protocol, item, condition)]
        if hits and condition.holdoff:
            holdoff = round(condition.holdoff * decoding.rate)
            kept = []
            for at in hits:
                if not len(self._triggers) or at - int(self._triggers[-1]) >= holdoff:
                    if not kept or at - kept[-1] >= holdoff:
                        kept.append(at)
            hits = kept
        if hits:
            found_at = np.array(hits, dtype=np.int64)
            self._keep(found_at)

    def _keep(self, found: np.ndarray) -> None:
        """Remember these triggers too: the newest MOST_TRIGGERS of all of them,
        and before those, the first in each MOST_TRIGGERS'th of the history.

        A plot waits for the newest trigger with half its span still to come
        after it, so one that far back has to be remembered: a 10 s span
        needs one from 5 s ago, and the newest 4096 of a 1 kHz signal go
        back only 4.1 s. Thinned, those older ones reach back over the
        whole history and never number more than MOST_TRIGGERS.
        """
        triggers = np.concatenate((self._triggers, found))
        if len(triggers) > MOST_TRIGGERS:
            older, newest = triggers[:-MOST_TRIGGERS], triggers[-MOST_TRIGGERS:]
            held = max((r.capacity for r in self.capture.records.values()), default=0)
            buckets = older // max(1, held // MOST_TRIGGERS)
            first = np.concatenate(([True], buckets[1:] != buckets[:-1]))
            triggers = np.concatenate((older[first][-MOST_TRIGGERS:], newest))
        self._triggers = triggers

    def _watch_single(self) -> None:
        """Take the first trigger since Single was pressed, and say when its capture is in."""
        window = round(self.longest_window() * self._rate())
        if self._single is None:
            if self.record() is None:
                # With no trigger, Single is one plot's worth from when it was pressed.
                self._single = self._single_from + round(self.position * window)
            else:
                later = self._triggers[self._triggers >= self._single_from]
                if len(later):
                    self._single = int(later[0])
        if self._single is None or self._single_said:
            return
        if self._newest() >= self._single + round((1 - self.position) * window):
            self._single_said = True
            self._frozen = self._single
            self.single_done.emit()

    # --- for a plot ------------------------------------------------------------------------
    def triggered(self) -> bool:
        """Whether there is a trigger to wait for at all."""
        return self.record() is not None

    @property
    def frozen(self) -> int | None:
        """The trigger Single caught, once it has its capture."""
        return self._frozen

    def trigger_for(self, after: int) -> int | None:
        """The newest trigger with ``after`` samples following it already here.

        Single's one trigger while it is waited for, and afterwards for as
        long as the instrument stays stopped.
        """
        if self._frozen is not None:
            return self._frozen
        if self.sweep is not None:
            return self.sweep.trigger
        newest = self._newest()
        if self.mode == SINGLE:
            ready = self._single is not None and self._single + after <= newest
            return self._single if ready else None
        usable = self._triggers[self._triggers + after <= newest]
        return int(usable[-1]) if len(usable) else None

    def quiet_for(self, seconds: float) -> bool:
        """Whether no trigger has come in the last this many seconds of samples."""
        last = int(self._triggers[-1]) if len(self._triggers) else self._scanned_from()
        return (self._newest() - last) > seconds * self._rate()

    def _scanned_from(self) -> int:
        record = self.record()
        return record.first if record is not None else 0
