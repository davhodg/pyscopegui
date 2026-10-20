# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Captures in files: pyscopegui's own, and CSV.

pyscopegui's own is a numpy ``.npz``: each channel's samples as they were held
-- volts as 32-bit floats, a logic level as a byte -- and one line of JSON
saying what they are: names, units, colours, the rate, and which sample the
plot measured time from. It comes back exactly as it went, and anything that
reads numpy can read it.

A CSV is any table of numbers, with a column of time or without one: what
pyscopegui's own Export CSV writes, or what a scope, a spreadsheet or a
script did. What is in it is said in ``CsvLayout`` -- lines to skip, the
separator, which columns, and what each one is -- and ``guess_layout`` works
that out for pyscopegui's own and makes a start on anything else.

Either way what comes back is a ``Loaded``: one instrument's channels and
samples, and where its time is measured from.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from pyscopegui.backends.base import ANALOG, DIGITAL, Channel

#: What a Channel says about how it is held, and not about what it is.
HELD_AS = ("counts", "port", "bit")
#: What a file of pyscopegui's own says it is, so another .npz is not taken for one.
FORMAT = "pyscopegui capture"
VERSION = 1
SUFFIX = ".npz"
#: Rows shown to choose columns by.
PREVIEW_ROWS = 12
#: How far apart time steps may be, as a share of the usual one, and still be one rate.
UNEVEN = 0.01


class CaptureError(Exception):
    """A file that cannot be read as a capture, in words."""


@dataclass
class Loaded:
    """One instrument's capture, as it came out of a file."""

    channels: list[Channel]
    rate: float
    #: Channel key -> samples: float32 volts, or uint8 0 and 1.
    data: dict[str, np.ndarray]
    #: The sample the time axis is measured from -- a trigger -- or None.
    zero: int | None = None
    #: Said about the file while reading it: steps that were not even, say.
    notes: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(next(iter(self.data.values()), ()))


# --- pyscopegui's own ---------------------------------------------------------------------------
def save(path: Path, loaded: Loaded, instrument: str = "") -> None:
    """Write one instrument's capture as pyscopegui's own file."""
    meta = {
        "format": FORMAT,
        "version": VERSION,
        "instrument": instrument,
        "rate": loaded.rate,
        "zero": loaded.zero,
        # Written in their units and on their own, never as counts or packed:
        # what says so is left out, for an older pyscopegui to read the file too.
        "channels": [
            {key: value for key, value in asdict(channel).items() if key not in HELD_AS}
            for channel in loaded.channels
        ],
    }
    arrays = {f"channel{index}": loaded.data[c.key] for index, c in enumerate(loaded.channels)}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as file:
        np.savez_compressed(file, meta=np.array(json.dumps(meta)), **arrays)


def load(path: Path) -> Loaded:
    """Read a file of pyscopegui's own. CaptureError if it is not one."""
    try:
        with np.load(path, allow_pickle=False) as held:
            meta = json.loads(str(held["meta"]))
            if meta.get("format") != FORMAT:
                raise CaptureError(f"{path.name} is not a capture saved by pyscopegui.")
            channels = [Channel(**c) for c in meta["channels"]]
            data = {c.key: np.array(held[f"channel{i}"]) for i, c in enumerate(channels)}
            rate = float(meta["rate"])
    except CaptureError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CaptureError(f"{path.name} could not be read as a capture: {exc}.") from exc
    if rate <= 0 or not data:
        raise CaptureError(f"{path.name} has no samples in it.")
    zero = meta.get("zero")
    return Loaded(channels, rate, data, zero if isinstance(zero, int) else None)


# --- CSV ----------------------------------------------------------------------------------------
TIME, ANALOG_ROLE, LOGIC = "time", "analog", "logic"
SEPARATORS = {",": "Comma", ";": "Semicolon", "\t": "Tab"}


@dataclass
class Column:
    """One column of a CSV, and what is to be made of it."""

    index: int
    name: str
    #: Time, an analog channel, or a logic one.
    role: str = ANALOG_ROLE
    #: What an analog one is measured in.
    unit: str = "V"
    used: bool = True


@dataclass
class CsvLayout:
    """How to read a CSV: what to skip, how it is divided, and which columns are what."""

    skip: int = 0
    separator: str = ","
    #: The first row after those skipped is the columns' names.
    names: bool = True
    columns: list[Column] = field(default_factory=list)
    #: Samples a second, for a file with no column of time.
    rate: float = 1000.0

    def time_column(self) -> Column | None:
        return next((c for c in self.columns if c.used and c.role == TIME), None)

    def channel_columns(self) -> list[Column]:
        return [c for c in self.columns if c.used and c.role != TIME]

    def as_options(self) -> dict:
        return asdict(self)

    @classmethod
    def from_options(cls, options: object) -> CsvLayout:
        """From what was saved, or the defaults for anything that is not right."""
        if not isinstance(options, dict):
            return cls()
        try:
            columns = [Column(**c) for c in options.get("columns", [])]
            return cls(
                skip=max(0, int(options.get("skip", 0))),
                separator=str(options.get("separator", ",")) or ",",
                names=bool(options.get("names", True)),
                columns=columns,
                rate=float(options.get("rate", 1000.0)),
            )
        except (TypeError, ValueError):
            return cls()


def rows(path: Path, skip: int, separator: str, count: int | None = None) -> list[list[str]]:
    """The rows of a CSV after the lines skipped, as text: ``count`` of them, or all."""
    found: list[list[str]] = []
    try:
        with path.open(encoding="utf-8-sig", errors="replace", newline="") as file:
            for number, row in enumerate(csv.reader(file, delimiter=separator)):
                if number < skip:
                    continue
                found.append([cell.strip() for cell in row])
                if count is not None and len(found) >= count:
                    break
    except OSError as exc:
        raise CaptureError(f"{path.name} could not be read: {exc}.") from exc
    return found


def _number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _name_and_unit(heading: str) -> tuple[str, str]:
    """ "A: sine (V)" -> ("A: sine", "V"), as pyscopegui's own Export CSV heads a column."""
    heading = heading.strip()
    if heading.endswith(")") and "(" in heading:
        name, _, unit = heading[:-1].rpartition("(")
        return name.strip(), unit.strip()
    return heading, ""


def guess_separator(path: Path, skip: int) -> str:
    """The separator the first rows after those skipped divide most evenly by."""
    try:
        with path.open(encoding="utf-8-sig", errors="replace") as file:
            lines = [line for number, line in enumerate(file) if number >= skip][:PREVIEW_ROWS]
    except OSError:
        return ","
    best, most = ",", 0
    for separator in SEPARATORS:
        counts = {line.count(separator) for line in lines if line.strip()}
        if len(counts) == 1 and (n := counts.pop()) > most:
            best, most = separator, n
    return best


def guess_layout(path: Path, skip: int = 0, separator: str | None = None) -> CsvLayout:
    """What the columns probably are: right for pyscopegui's own Export CSV, a start otherwise.

    A first row that is not numbers is names. A column headed "time" is time.
    A column that holds only 0 and 1, with no unit, is logic. Everything is used.
    """
    separator = separator or guess_separator(path, skip)
    found = rows(path, skip, separator, PREVIEW_ROWS)
    if not found:
        return CsvLayout(skip=skip, separator=separator, names=False)
    first = found[0]
    names = not all(_number(cell) for cell in first if cell)
    body = found[1:] if names else found
    width = max(len(row) for row in found)
    columns = []
    for index in range(width):
        heading = first[index] if names and index < len(first) else f"Column {index + 1}"
        name, unit = _name_and_unit(heading)
        values = [row[index] for row in body if index < len(row) and row[index]]
        if not values or not all(_number(v) for v in values):
            # Not numbers: a label of some kind, not a channel.
            columns.append(Column(index, name or heading, ANALOG_ROLE, unit or "V", used=False))
            continue
        if name.lower().startswith("time") or (unit and unit.lower() == "s"):
            role = TIME
        elif not unit and {float(v) for v in values} <= {0.0, 1.0}:
            role = LOGIC
        else:
            role = ANALOG_ROLE
        # Time is in seconds, a logic level in nothing, and anything else in volts
        # unless its heading says otherwise.
        unit = unit or {TIME: "s", LOGIC: ""}.get(role, "V")
        columns.append(Column(index, name or heading, role, unit))
    # Only one column can be time: the first that looked like it.
    times = [c for c in columns if c.role == TIME]
    for extra in times[1:]:
        extra.role = ANALOG_ROLE
    return CsvLayout(skip=skip, separator=separator, names=names, columns=columns)


def read_csv(path: Path, layout: CsvLayout) -> Loaded:
    """Read a CSV as its layout says. CaptureError if there is nothing to read in it."""
    chosen = layout.channel_columns()
    if not chosen:
        raise CaptureError("No columns are chosen as channels.")
    time_column = layout.time_column()
    wanted = [c.index for c in ([time_column] if time_column else []) + chosen]
    first = layout.skip + (1 if layout.names else 0)
    try:
        table = np.loadtxt(
            path,
            delimiter=layout.separator,
            skiprows=first,
            usecols=wanted,
            ndmin=2,
            encoding="utf-8-sig",
        )
    except (OSError, ValueError, IndexError) as exc:
        raise CaptureError(
            f"{path.name} could not be read with these columns: {exc}. Check the lines "
            "skipped, the separator and the columns chosen."
        ) from exc
    if len(table) < 2:
        raise CaptureError(f"{path.name} has fewer than two rows of numbers.")
    notes = []
    position = {index: at for at, index in enumerate(wanted)}
    zero = None
    if time_column is not None:
        times = table[:, position[time_column.index]]
        steps = np.diff(times)
        step = float(np.median(steps))
        if step <= 0:
            raise CaptureError(f"The time in {time_column.name!r} does not go forward.")
        if np.max(np.abs(steps - step)) > UNEVEN * step:
            notes.append(
                f"The times in {path.name} are not evenly spaced: they are drawn as if they "
                f"were, one every {step:g} s."
            )
        rate = 1.0 / step
        # Nought on its own time axis is where the plot measures from, if it is in it.
        at = round(-float(times[0]) * rate)
        zero = at if 0 <= at < len(times) else None
    else:
        rate = layout.rate
        if rate <= 0:
            raise CaptureError("With no column of time, a sample rate is needed.")
    channels, data = [], {}
    taken: set[str] = set()
    for column in chosen:
        key = column.name or f"Column {column.index + 1}"
        while key in taken:  # two columns of the same name are two channels
            key += "'"
        taken.add(key)
        values = table[:, position[column.index]]
        if column.role == LOGIC:
            channels.append(Channel(key, key, DIGITAL, ""))
            data[key] = (values != 0).astype(np.uint8)
        else:
            channels.append(Channel(key, key, ANALOG, column.unit or "V"))
            data[key] = values.astype(np.float32)
    return Loaded(channels, rate, data, zero, notes)


def is_own(path: Path) -> bool:
    """Whether a file is to be read as pyscopegui's own, by its name."""
    return path.suffix.lower() == SUFFIX
