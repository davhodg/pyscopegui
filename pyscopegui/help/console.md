[&larr; Contents](manual.md)

# Python Console

The **Python Console** pane is a Python prompt with pyscopegui in it: the window, every
instrument, and a few commands that do what the window's own buttons do. For a measurement
done over and over -- set something, capture, read a number, write it down -- typed once
rather than clicked twenty times.

Open it from the **View** menu. It opens behind the [Event Log](event-log.md). It behaves
as the `python` prompt does: Up and Down go through what was typed, a block carries on with
`...`, and a mistake is shown as Python shows it. **Run script...** runs a `.py` file with the
same names.

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
| `data("Rigol CH1")` | A channel's times and samples, all that is held of it, as numpy arrays |
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

## What a script can do

A script run here can do whatever Python can, as you: that is what it is for. Run only
scripts you would run yourself.
