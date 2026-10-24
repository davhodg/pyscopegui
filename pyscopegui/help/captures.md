[&larr; Contents](manual.md)

# Saving and opening captures

## Saving

*File > Save capture...* keeps everything held, of every instrument on the first plot, in a
file to open again later exactly as it is: every sample as it was held, each channel's name,
unit and colour, the sample rate, and where the trigger was. With several instruments there
is a file for each, named for it -- `capture-Rigol.npz`, `capture-Pico.npz` -- as
[Export CSV](plot.md) does. A large one is written while the instruments go on running,
with a bar showing how far it has got, and **Cancel**.

Each channel is saved as it is held. A PicoScope's channels are the scope's own 16-bit
counts, with what they are in volts -- a third smaller than volts once compressed -- and
every logic input is a bit a sample, which its long runs at one level make next to nothing:
a tenth of what it took before, or less. Opened again, a mixed-signal scope's inputs are back
in their ports, eight to a byte, as the scope sent them. A file saved by an earlier
pyscopegui, all volts and bytes, still opens.

The file is a numpy `.npz`, so a script can read it too:

```python
import json, numpy as np

held = np.load("capture.npz")
meta = json.loads(str(held["meta"]))
first = meta["channels"][0]
if first["kind"] == "analog":
    samples = held["channel0"].astype(np.float64)
    if first["counts"]:  # the scope's counts: into volts, a stretch at a time
        scales = meta["scales"][first["key"]]
        for (start, per_count, offset), after in zip(scales, scales[1:] + [[len(samples)]]):
            samples[start : after[0]] = samples[start : after[0]] * per_count - offset
else:  # a logic input, a bit a sample
    samples = np.unpackbits(held["bits0"])[: meta["samples"]]
seconds = np.arange(len(samples)) / meta["rate"]
```

## Opening

*File > Open capture...* opens one or more files, each as an instrument of its own: a tab in
the [Instrument](instruments.md) pane, *File*, *File 2* and so on -- point at one to see which
file it is -- and its channels on the plot beside the instruments that are open, lined up on
its trigger. Everything that works on an
instrument works on it -- the channel list, [cursors](plot.md), colours, Export, the
[Python Console](console.md) -- and the cross on its tab closes it.

It is read as a snapshot of a scope's screen is: all of it is put on the plot, there is no
trigger to set, and **Read** puts it there again. The file is read again each time it is
opened, so one written since is seen as it is now.

A file of pyscopegui's own opens as it was saved. A **CSV** opens through a dialog first.

## As a reference

Tick **Draw as a reference**, in the Instrument pane, for a capture that has been opened, and
its traces are drawn faded and behind the instruments' own: a known good capture, say, with
what a scope shows now drawn over it, lined up on the trigger. What has changed -- an edge
that comes later, a level that is lower, a glitch that was not there -- is plain to see.

The channel list says *reference* beside each of its channels, and cursors read it as they
read any other channel, so the two can be compared in numbers as well. It is kept with the
[workspace](files.md); untick it to draw the capture as any other.

## Opening a CSV

pyscopegui's own **Export CSV** is right as it opens: press **Open**. Anything else -- a
scope's own CSV, a spreadsheet's -- may have lines of its own at the top, or columns that are
not channels, and the dialog is where they are left out:

| Setting | What it does |
|---------|--------------|
| Skip lines | Lines at the top that are not the table: a scope's settings, say |
| Separator | Comma, semicolon or tab. It is found by itself, and can be changed |
| The first row is names | Whether the first row after those skipped names the columns |
| Sample rate | For a file with no column of time: how many rows a second |

Below them are the first rows as they would be read, and a line for each column:

- **Use** -- untick a column to leave it out. A column that is not numbers starts unticked.
- **Name** -- what the channel is called.
- **Is** -- **Time**, an **Analog** channel, or a **Logic** one, 0 or 1. One column can be
  time: the sample rate is worked out from it, and nought on it is where the plot measures
  time from. A column of only noughts and ones with no unit starts as logic.
- **Unit** -- what an analog channel is measured in.

Times that are not evenly spaced are read as if they were, and the
[Event Log](event-log.md) says so: a channel is drawn a sample at a time, at one rate. How
the file was read is kept with the workspace, so it opens the same way next time.
