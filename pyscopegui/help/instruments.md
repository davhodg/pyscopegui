[&larr; Contents](manual.md)

# Instrument

## Choosing and running

The toolbar has the list of instruments and one button. The button says what pressing it
will do: **Run** while stopped, **Stop** while running. The instrument cannot be changed
while it is running.

**Run** starts from an empty plot, with time counted from zero. **Stop** keeps what has been
collected on the plot. The status bar says which instrument, its sample rate and how many
seconds are held.

The instrument chosen is remembered.

| Instrument | What it is |
|------------|------------|
| Demo signals | Two analog and four digital channels at 100 kS/s, with no hardware |
| [PicoScope 2204A](picoscope.md) | Pico's two-channel scopes on the `ps2000` driver |

## The Instrument pane

The pane shows what the instrument chosen lets you set, and nothing when it has nothing: the
demo has no settings.

There are two kinds of setting, and the pane says so at the bottom:

- **How the instrument is set up** -- a sample rate, a range. Changing one while the
  instrument is running starts it again, from an empty plot; changed while it is stopped, it
  is used at the next Run.
- **What changes as it runs** -- a signal generator. These take effect without starting
  the instrument again.

A list picks one of several; a tick box is on or off; a number is typed, or stepped with its
arrows, and takes effect when you press Enter or move on, not at every digit.

Settings are remembered for each instrument separately, in [your files](files.md).

## A maker's library

An instrument that needs its maker's library -- a driver, an SDK -- does not come with it.
Install the maker's software and pyscopegui finds the library at run time. If it cannot, the
[Event Log](event-log.md) says which library it looked for and where to get it.

## Demo signals

Something to look at with nothing plugged in: a 50 Hz sine and a slow ramp on the analog
plot, and four logic channels counting in binary, the fastest at 1 kHz.
