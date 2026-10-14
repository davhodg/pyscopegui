# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Writing what a plot shows as CSV, for a spreadsheet or a script.

One file for each instrument. Two instruments sample at different rates
and at different moments, so their samples do not share rows; a file with
both would be mostly empty cells.

Every sample in the stretch of time asked for is written, not the few a
plot draws of them. Time is as the plot's axis has it: from the trigger
where there is one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from pyscopegui.backends.base import ANALOG
from pyscopegui.core.capture import Record

#: Rows written at a time: enough to be quick, without a second copy of a
#: deep capture in memory as text.
CHUNK = 100_000
ANALOG_FORMAT = "%.6g"
DIGITAL_FORMAT = "%d"


@dataclass(frozen=True)
class Written:
    """One file that was written."""

    path: Path
    rows: int
    channels: int


def paths_for(path: Path, names: list[str]) -> dict[str, Path]:
    """Where each instrument's file goes: the path asked for when there is
    one instrument, and that path with the instrument's name in it for more."""
    if len(names) <= 1:
        return {name: path for name in names}
    return {name: path.with_name(f"{path.stem}-{name}{path.suffix}") for name in names}


def time_format(rate: float) -> str:
    """Time in seconds to a tenth of the time between two samples, however far
    into a run it is.

    A number of figures will not do: nine of them are a nanosecond a second
    into a run, and a microsecond a thousand seconds in, where every sample
    at 1 MS/s would be written at the same time as its neighbours. So the
    places after the point are what the rate needs, and the figures before it
    are as many as there are.
    """
    interval = 1.0 / rate if rate > 0 else 1.0
    return f"%.{max(0, math.ceil(-math.log10(interval))) + 1}f"


def heading(record: Record, name: str) -> str:
    """A column's heading: the channel, and what it is measured in."""
    unit = record.channel.unit if record.channel.kind == ANALOG else ""
    # A comma or a quote in a name would be a column of its own.
    name = name.replace(",", " ").replace('"', "")
    return f"{name} ({unit})" if unit else name


def write_csv(
    path: Path, records: dict[str, Record], origin: float, t_from: float, t_to: float
) -> Written:
    """Write these channels of one instrument, between two times on the plot's axis.

    ``records`` is what to call each channel -> what is held of it; they are
    one instrument's, so they have a rate and a count of samples in common.
    ``origin`` is the time, in the instrument's own seconds, that the axis
    calls nought.
    """
    held = [record for record in records.values() if record.count]
    if not held:
        raise ValueError("there are no samples to write")
    rate = held[0].rate
    pieces = {
        name: record.between(t_from + origin, t_to + origin)
        for name, record in records.items()
        if record.count
    }
    # The stretch every channel has: they arrive together, and are the same
    # to within the block that was arriving as this was asked for.
    first = max(start for start, _samples in pieces.values())
    last = min(start + len(samples) for start, samples in pieces.values())
    if last <= first:
        raise ValueError("there are no samples in the stretch of time shown")
    columns = [
        (heading(records[name], name), samples[first - start : last - start], records[name])
        for name, (start, samples) in pieces.items()
    ]
    formats = [time_format(rate)] + [
        ANALOG_FORMAT if record.channel.kind == ANALOG else DIGITAL_FORMAT
        for _heading, _samples, record in columns
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        file.write(",".join(["time (s)"] + [said for said, _samples, _record in columns]) + "\n")
        for start in range(first, last, CHUNK):
            stop = min(start + CHUNK, last)
            rows = np.empty((stop - start, len(columns) + 1), dtype=np.float64)
            rows[:, 0] = np.arange(start, stop) / rate - origin
            for index, (_said, samples, _record) in enumerate(columns, start=1):
                rows[:, index] = samples[start - first : stop - first]
            np.savetxt(file, rows, fmt=formats, delimiter=",")
    return Written(path, last - first, len(columns))
