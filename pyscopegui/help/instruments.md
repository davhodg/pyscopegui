[&larr; Contents](manual.md)

# Instrument

## Choosing, opening and running

The toolbar has the list of instruments, **Open**, and the four buttons a scope has.

**Open** connects to the instrument chosen and leaves it stopped. For a scope this is the
slow part, done once. The button then reads **Close**, which stops the instrument and lets
it go, so that another program can have it. Pressing one of the run buttons opens it for
you if it is not open.

Whichever of the four is pressed in is what the instrument is doing:

| Button | What it does |
|--------|--------------|
| **Stop** | Stops reading. What has been collected stays on the plot |
| **Single** | Waits for one trigger, shows what is either side of it, and stops |
| **Normal** | Shows each trigger as it comes, and holds the last one until the next |
| **Auto** | Shows each trigger as it comes, and what there is anyway when none does |

With no trigger chosen there is nothing to wait for: **Auto** and **Normal** both follow the
newest samples, as a chart recorder does, and **Single** reads one plot's worth and stops.

Going from **Stop** to one of the others starts from an empty plot, with time counted from
zero. Going between **Normal** and **Auto** does not: the run carries on.

The status bar says which instrument, what it is doing, its sample rate and how many seconds
are held. The instrument chosen is remembered.

| Instrument | What it is |
|------------|------------|
| Demo signals | Two analog and four digital channels at 100 kS/s, with no hardware |
| [PicoScope 2204A](picoscope.md) | Pico's two-channel scopes on the `ps2000` driver |
| [Rigol DS1000Z](rigol.md) | Rigol's DS1000Z and MSO1000Z scopes, over the network |

## Several instruments at once

Open one instrument, choose another in the list, and open that too. The list says which
are open. The channels of all of them are on the one plot, each named for whose it is:
*Pico A*, *Rigol CH1*.

The list chooses which instrument **Open**, the Instrument pane and the trigger toolbar are
about. The four run buttons are for every instrument that is open: **Auto** runs them all,
**Stop** stops them all, and **Single** stops once each has its capture.

**Each instrument keeps time for itself**, and nothing says when one started by another's
clock. What puts them on one time axis is the trigger: each has a trigger of its own, on a
channel of its own, and nought on the axis is each one's trigger. So they line up as well
as their triggers do:

- Put the same signal on a channel of each, and trigger each on it, at the same level and
  edge. The two then line up to within a sample or so of the slower one.
- Triggered on different signals, each is still drawn around its own trigger, and the
  time between the two is not shown.
- An instrument with no trigger chosen is drawn as its newest samples arrive, beside the
  one that has a trigger, and is not lined up with it at all.

With a signal that repeats, each instrument may be showing a different repeat of it. With
**Single** and something that happens once, they show the same one.

Closing an instrument leaves its traces on the plot to be looked at. They go when another
instrument is opened or run.

## The trigger

The second toolbar is the trigger of the instrument chosen in the list. With several open
it says whose it is -- *Trigger, Rigol* -- and each keeps its own channel, edge and level.
**Position** is the same for all of them, since they share the plot.

| Setting | What it does |
|---------|--------------|
| Trigger | The channel to trigger on, or **None** for no trigger |
| Edge | **Rising**, as the signal goes up through the level, or **Falling** |
| Level | The voltage the signal has to cross, drawn as a dashed line on the plot |
| Position | Where the trigger sits in the plot: 50% is the middle, with as much before as after |

A digital channel has only one level, between its 0 and its 1, so the level box is not
offered for one.

An instrument that sends short captures taken around a trigger of its own -- a
[PicoScope reading blocks](picoscope.md), or a [Rigol](rigol.md) -- is handed these
settings and does the triggering. For everything else the trigger is found by pyscopegui, in the samples as they
arrive, and not by the instrument. So it is the same for every instrument, the samples either side of a trigger are
all still there to go back over, and it finds nothing the instrument cannot stream: on a
PicoScope 2204A, nothing faster than 1 MS/s shows.

A signal has to go back past the level by a fiftieth of the channel's range before it can
trigger again, so that the noise on a slow edge does not trigger a dozen times on the way
through.

What the plot does with a trigger is in [Channels and Plot](plot.md). The trigger's settings
are remembered.

## The Instrument pane

The pane shows what the instrument chosen lets you set, and nothing when it has nothing: the
demo has no settings.

A scope's channels all have the same settings, so they are shown one channel at a time,
under a row of tabs: **1 2 3 4**. How every channel is set can be read at once in the
[plot's channel list](plot.md), and clicking a channel there brings its settings up here,
whichever instrument it belongs to.

Every scope is set the same way, whoever made it: **Scale** in volts a division, **Probe**
for what the probe divides by, and **Coupling**.

There are two kinds of setting, and a setting's tip says which it is:

- **What the samples are** -- how many a second, of which channels. Changing one while the
  instrument is running starts the run again, from an empty plot; changed while it is
  stopped, it is used the next time it is run.
- **What changes as it runs** -- a scale, a signal generator. These take effect with what is
  on the plot kept.

Neither closes the instrument, so neither costs the time it took to open.

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
