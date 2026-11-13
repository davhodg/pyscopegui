[&larr; Contents](manual.md)

# Python Console

The **Python Console** pane is a Python prompt with pyscopegui in it: the window, every
instrument, and a few commands that do what the window's own buttons do. For a measurement
done over and over -- set something, capture, read a number, write it down -- typed once
rather than clicked twenty times.

Open it from the **View** menu. It opens behind the [Event Log](event-log.md). It behaves
as the `python` prompt does: a block carries on with `...`, Up and Down go back through what
was typed, and a mistake is shown as Python shows it.

The box typed into takes several lines too. **Shift+Enter** starts another, indented as the
one before and further after a colon, and several lines pasted at once arrive as they are.
**Enter** then runs them all together, each value shown as the prompt shows it, and **Tab**
indents. Within several lines Up and Down move between them, and go back through what was
typed only from the first line or the last. What is printed is shown as it is printed, so a
script that captures ten times says so one capture at a time.

**Run script...** runs a `.py` file with the same names. **Stop** stops what is running at
the command it is in, or the next one it calls: a `wait()`, or a `single()` or `read()`
waiting for a capture -- which is stopped too -- ends at once. A loop of Python's own that
calls none of the commands runs on until it finishes. Nothing else is typed or run while
something is, and pyscopegui will not close until it has stopped.

A right-click in what the console has printed offers *Save all...*, to write it to a text
file, and *Clear all*, as the [Event Log](event-log.md) and
[Instrument traffic](traffic.md) do.

*File > Run script...* does the same from the File menu, and shows the console first, so that
what the script prints and any traceback can be read. *File > Recent scripts* lists the last
five run in the workspace, by either, newest first: one click runs one again. A script kept
in the workspace's own folder is remembered relative to it, and found wherever the workspace
is taken.

## The commands

| Command | What it does |
|---------|--------------|
| `add("rigol1000z")` | Adds an instrument of that kind, as *Add instrument* does, and chooses it. Gives its name |
| `choose(name)` | Chooses an instrument, as its tab does: what the commands below are about |
| `open()`, `close()` | Opens the instrument chosen and waits until it is open; closes it |
| `set(key, value)`, `get(key)` | One of its settings, by the name it is saved under: `set("scale_1", 0.5)` |
| `run("auto")`, `stop()` | The run buttons: `"auto"`, `"normal"`, `"single"` or `"stop"` |
| `single(timeout=30)` | Presses **Single** and waits until every instrument has its capture. False if none came in time |
| `read()` | **Read**, for a scope read as it is, and waits for it |
| `trigger("CH1", level=0.5, rising=True, position=0.5)` | The chosen instrument's trigger. `None` for no trigger |
| `channels()` | Every channel's name, as the plot gives it |
| `axis("CH2", 2)` | Draws a channel against [Y2](plot.md), on the right, or with `1` against Y1, as *Plot on Y2* does; `axis("CH2")` says which it is on |
| `rename("CH1", "5V rail")` | A [name of its own](plot.md) for a channel, as *Rename...* gives it: shown as *5V rail (CH1)*, and kept with the workspace. Gives what the plot now calls it; `""` puts back the instrument's own. The channel can be named by the name it was given, too |
| `data("Rigol CH1")` | A channel's times and samples, all that is held of it, as numpy arrays |
| `maths("CH1", "-", "CH2")` | A [maths channel](plot.md) of the chosen instrument: `"+"`, `"-"`, `"*"` or `"/"`. Of one channel: `maths("CH1", "ddt")`, with `"neg"`, `"abs"`, `"sq"`, `"sqrt"`, `"ddt"` or `"int"`; `maths("CH1", "scale", k=10, c=0, unit="A")`; `maths("CH1", "avg", over=1e-3)`. Gives its name |
| `measure("Rigol CH1")` | What the [Measurements](plot.md) pane says of it, as numbers: `["frequency"]`, `["rms"]` and the rest |
| `export_csv(path)`, `export_png(path)` | What *Export CSV* and *Export PNG* do |
| `wait(seconds)` | Lets the window and the instruments run for that long: a script's sleep |

`window`, `ctx` and `session` are there too: the window itself, the settings, and every
instrument's samples. `help(single)` says what a command does.

A setting's name is what `settings.json` has it as -- `scale_1`, `time_div`, `mode` -- and
`set` with one it does not know says which there are. The Instrument pane follows what a
command does, as it would a click.

## An example

```python
add("demo")
run("auto")
wait(1)
stop()
times, volts = data("A: sine")
print(f"{volts.max() - volts.min():.3f} V peak to peak")
export_csv("sine.csv")
```

## While a command waits

Everything typed runs on the window's own thread. `open`, `single`, `read` and `wait` keep
the window going while they wait, since what they are waiting for arrives through it.
Python's own `time.sleep` does not: it holds the window still, and nothing arrives until it
is done. Use `wait` instead.

A loop of commands holds the window as long as it runs, between its waits; so does anything
slow of your own.

## From the command line

A script can be run as pyscopegui starts, to take the same measurement the same way each time
-- from a batch file, a test bench, or a CI job:

```
pyscopegui --run measure.py
```

The window opens as it always does, the script runs with the same names as one run here,
and pyscopegui closes when it is done. What it prints goes to the
[Event Log](event-log.md), and to the terminal when there is one. The exit code is the
script's: 0 when it runs to its end, `n` for `sys.exit(n)`, and 1 for an exception, a
failed `assert` or `sys.exit("a message")`, so whatever started it can tell whether it
passed.

| Option | What it does |
|--------|--------------|
| `--run SCRIPT` | Runs the script once the window is up, then closes |
| `--stay` | With `--run`: leaves the window open when the script is done, to look at what it did |
| `--workspace NAME` | Opens that [workspace](files.md), this time only: the next start opens the one it would have |
| `FILE` | A capture or a CSV to open. Given alone, it goes to the pyscopegui already open, as a double-click does |
| `--help` | Says all this |

A mistake on the command line -- an option it does not know, a script or a workspace that is
not there -- is said before anything opens, and nothing is run. The options are the same as
pycangui's.

## What a script can do

A script run here can do whatever Python can, as you: that is what it is for. Run only
scripts you would run yourself.
