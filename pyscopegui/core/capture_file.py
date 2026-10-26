# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Captures in files: pyscopegui's own, and CSV.

pyscopegui's own is a ``.pyscp``, which is a numpy ``.npz`` under a name of its
own, so that it can be double-clicked: each channel's samples as they were held,
and one line of JSON saying what they are: names, units, colours, the rate,
and which sample the plot measured time from. A PicoScope's channels are the
scope's own 16-bit counts, with what each stretch of them is in volts -- the
range may have changed part way -- and a mixed-signal scope's logic inputs
are packed eight to a byte in their port, as the scope sent them: half the
size of volts, and an eighth of a byte each. Anything else is volts as 32-bit
floats, or a logic level as a byte. It comes back exactly as it went, and
anything that reads numpy can read it. A file of the first version, all
volts and bytes, still opens, and so does one saved as ``.npz`` before there
was a name of its own.

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
import zipfile
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

import numpy as np

from pyscopegui.backends.base import ANALOG, DIGITAL, Channel, Scale

#: What a file of pyscopegui's own says it is, so another .npz is not taken for one.
FORMAT = "pyscopegui capture"
#: The version written; and those read, the first of them all volts and bytes.
VERSION = 2
READ = (1, 2)
SUFFIX = ".pyscp"
#: What is read as pyscopegui's own: its name, and the one before there was one.
SUFFIXES = (SUFFIX, ".npz")
#: Samples of a channel written at a time.
PIECE = 1 << 20
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
    #: Channel key -> samples: float32 volts, int16 counts for one in
    #: ``scales``, or uint8 0 and 1; and a port's key -> its inputs packed.
    data: dict[str, np.ndarray]
    #: The sample the time axis is measured from -- a trigger -- or None.
    zero: int | None = None
    #: Said about the file while reading it: steps that were not even, say.
    notes: list[str] = field(default_factory=list)
    #: A channel held as counts -> (the sample each scale is from, the scale),
    #: oldest first, counted from the first sample.
    scales: dict[str, list[tuple[int, Scale]]] = field(default_factory=dict)
    #: A logic input held packed -> (its port's key in ``data``, its bit).
    bits: dict[str, tuple[str, int]] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(next(iter(self.data.values()), ()))


# --- pyscopegui's own ---------------------------------------------------------------------------
def save(
    path: Path,
    loaded: Loaded,
    instrument: str = "",
    progress: Callable[[int], None] | None = None,
) -> None:
    """Write one instrument's capture as pyscopegui's own file.

    Each channel is written PIECE samples at a time, and ``progress`` told
    how many of them have been, all channels together, after each. A
    channel's samples are an array, or anything that has a length and a
    dtype and gives an array for a slice: read a piece at a time too.

    A logic input is written a bit a sample, eight samples to a byte, on its
    own: its long runs of the same level then take next to nothing once the
    file is compressed, where eight inputs to a byte, as a port has them,
    would not. It is put back in its port as it is read.
    """
    count = len(loaded)
    meta = {
        "format": FORMAT,
        "version": VERSION,
        "instrument": instrument,
        "rate": loaded.rate,
        "zero": loaded.zero,
        "samples": count,
        "channels": [asdict(channel) for channel in loaded.channels],
        # What each stretch of counts is in its unit.
        "scales": {
            key: [[start, scale.per_count, scale.offset] for start, scale in stretches]
            for key, stretches in loaded.scales.items()
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    # What numpy's savez_compressed writes, written by hand so that it can
    # be a piece at a time: a zip of one .npy file for each array.
    written = 0
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        with archive.open("meta.npy", "w") as file:
            np.lib.format.write_array(file, np.array(json.dumps(meta)), allow_pickle=False)
        for index, channel in enumerate(loaded.channels):
            logic = channel.kind != ANALOG
            samples = _levels_of(loaded, channel) if logic else loaded.data[channel.key]
            dtype = np.dtype(np.uint8) if logic else np.dtype(samples.dtype)
            name = f"bits{index}" if logic else f"channel{index}"
            with archive.open(f"{name}.npy", "w", force_zip64=True) as file:
                header = {
                    "descr": np.lib.format.dtype_to_descr(dtype),
                    "fortran_order": False,
                    "shape": (-(-count // 8) if logic else count,),
                }
                np.lib.format.write_array_header_1_0(file, header)
                # PIECE is a whole number of bytes of bits: only the last is padded.
                for start in range(0, count, PIECE):
                    piece = np.ascontiguousarray(samples[start : start + PIECE], dtype=dtype)
                    file.write((np.packbits(piece) if logic else piece).data)
                    written += len(piece)
                    if progress is not None:
                        progress(written)


class _Levels:
    """A logic input's 0s and 1s, read out of its port a piece at a time."""

    def __init__(self, port, bit: int) -> None:
        self._port, self._bit = port, bit
        self.dtype = np.dtype(np.uint8)

    def __len__(self) -> int:
        return len(self._port)

    def __getitem__(self, piece: slice) -> np.ndarray:
        return (np.asarray(self._port[piece]) >> self._bit) & 1


def _levels_of(loaded: Loaded, channel: Channel):
    """A logic channel's 0s and 1s: its own, or read out of its port."""
    if channel.key in loaded.bits:
        port, bit = loaded.bits[channel.key]
        return _Levels(loaded.data[port], bit)
    return loaded.data[channel.key]


def load(path: Path) -> Loaded:
    """Read a file of pyscopegui's own. CaptureError if it is not one."""
    try:
        with np.load(path, allow_pickle=False) as held:
            meta = json.loads(str(held["meta"]))
            if meta.get("format") != FORMAT:
                raise CaptureError(f"{path.name} is not a capture saved by pyscopegui.")
            version = meta.get("version", 1)
            if version not in READ:
                raise CaptureError(
                    f"{path.name} was saved by a newer pyscopegui, as version {version} of "
                    f"its captures: this one reads up to {VERSION}."
                )
            known = set(Channel.__dataclass_fields__)
            channels = [
                Channel(**{k: v for k, v in c.items() if k in known}) for c in meta["channels"]
            ]
            loaded = Loaded(channels, float(meta["rate"]), {})
            for index, channel in enumerate(channels):
                if version == 1:
                    loaded.data[channel.key] = np.array(held[f"channel{index}"])
                elif channel.kind == ANALOG:
                    loaded.data[channel.key] = np.array(held[f"channel{index}"])
                else:
                    levels = np.unpackbits(held[f"bits{index}"])[: int(meta["samples"])]
                    _put_back(loaded, channel, levels)
            if version > 1:
                _scales_from(loaded, meta.get("scales") or {})
    except CaptureError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CaptureError(f"{path.name} could not be read as a capture: {exc}.") from exc
    if loaded.rate <= 0 or not loaded.data:
        raise CaptureError(f"{path.name} has no samples in it.")
    zero = meta.get("zero")
    loaded.zero = zero if isinstance(zero, int) else None
    return loaded


def _put_back(loaded: Loaded, channel: Channel, levels: np.ndarray) -> None:
    """A logic input as it was held: on its own, or in its port, packed."""
    if not channel.port:
        loaded.data[channel.key] = levels
        return
    port = loaded.data.setdefault(channel.port, np.zeros(len(levels), dtype=np.uint8))
    port |= levels << np.uint8(channel.bit)
    loaded.bits[channel.key] = (channel.port, channel.bit)


def _scales_from(loaded: Loaded, saved: dict) -> None:
    """Each channel of counts with what it is in its unit. One whose range
    changed part way is turned into its unit as it is read: a capture is
    taken in at one scale a channel."""
    for index, channel in enumerate(loaded.channels):
        if not channel.counts:
            continue
        stretches = [
            (int(start), Scale(float(per), float(off))) for start, per, off in saved[channel.key]
        ]
        if len(stretches) == 1:
            loaded.scales[channel.key] = stretches
            continue
        counts = loaded.data[channel.key]
        volts = np.empty(len(counts), dtype=np.float32)
        ends = [start for start, _scale in stretches[1:]] + [len(counts)]
        for (start, scale), end in zip(stretches, ends, strict=True):
            scale.apply(counts[start:end], out=volts[start:end])
        loaded.data[channel.key] = volts
        loaded.channels[index] = replace(channel, counts=False)


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
    return path.suffix.lower() in SUFFIXES
