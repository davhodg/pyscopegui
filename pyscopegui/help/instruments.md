[&larr; Contents](manual.md)

# Instrument

## Adding, opening and running

**Add instrument**, on the toolbar, lists the kinds of instrument there are. Choosing one
puts it in the Instrument pane, where it gets a tab of its own, and that is where it is
opened, set up and removed. Beside **Add instrument**, in a frame, is everything to do with
triggering: the four run buttons a scope has, and the trigger.

| To | Do this |
|----|---------|
| Add an instrument | **Add instrument**, and pick its kind |
| Choose which one the pane and the trigger are about | Click its tab |
| Connect to it | **Open**, under **Connection** in the pane |
| Let it go, so that another program can have it | **Close**, which is what the same button reads while it is open |
| Take it out of the pane | The cross on its tab, which closes it first |

**Open** is under **Connection**, below whatever says how the instrument is reached -- an
address, a port -- because that is what it uses. It connects and leaves the instrument
stopped: for a scope this is the slow part, done once. While the instrument is open the
button reads **Close**, and a dot on the tab says it is open. Pressing one of the run
buttons opens the instrument chosen for you if it is not open.

Every tab has a cross, the last one's too: with every instrument taken out the pane is
empty, says so, and stays empty the next time pyscopegui starts, until **Add instrument**
puts one back. An instrument's settings are kept when it is removed, and are there again
when one of its kind is added.

Whichever of the four is pressed in is what the instrument is doing:

| Button | What it does |
|--------|--------------|
| **Stop** | Stops reading. What has been collected stays on the plot |
| **Single** | Waits for one trigger, shows what is either side of it, and stops |
| **Normal** | Shows each trigger as it comes, and holds the last one until the next |
| **Auto** | Shows each trigger as it comes, and what there is anyway when none does |

An instrument that is read as it is, with nothing on it changed -- a
[Tektronix](tektronix.md) can be -- has no trigger here to wait for. It has a button of its
own on the toolbar, **Read**, which takes what it shows once; **Auto** keeps reading it,
and **Single** and **Normal** leave it alone.

With no trigger chosen there is nothing to wait for: **Auto** and **Normal** both follow the
newest samples, as a chart recorder does, and **Single** reads one plot's worth and stops.

Going from **Stop** to one of the others starts from an empty plot, with time counted from
zero. Going between **Normal** and **Auto** does not: the run carries on.

The status bar says which instrument, what it is doing, its sample rate and how many seconds
are held. The instruments in the pane, and the one chosen, are remembered.

| Instrument | What it is |
|------------|------------|
| Demo signals | Two analog and four digital channels at 100 kS/s, with no hardware |
| [PicoScope 2000 series (ps2000)](picoscope.md) | Pico's older two-channel scopes: the 2204A and its relatives |
| [PicoScope 2000 series (ps2000a)](picoscope.md) | Pico's newer scopes: two or four channels, and the logic inputs of an MSO |
| [Rigol DS1000Z](rigol.md) | Rigol's DS1000Z and MSO1000Z scopes, over the network or USB |
| [Tektronix TDS and TPS 2000](tektronix.md) | Tektronix's TDS200, TDS1000, TDS2000 and TPS2000 scopes, over a serial port |

## Several instruments at once

Add one instrument and open it, add another and open that too. The channels of all of them
are on the one plot, each named for whose it is: *Pico A*, *Rigol CH1*.

The tab chosen in the Instrument pane -- *Pico*, *Rigol* -- says which instrument the
settings, **Open** and the trigger toolbar are about. The four run buttons are for every
instrument that is open: **Auto** runs them all, **Stop** stops them all, and **Single**
stops once each has its capture.

**Two of the same kind** are added the same way: choose the kind again under **Add
instrument**. The second is numbered -- *Rigol 2* -- and is an instrument in its own right,
with its own settings, its own address or port, and its own trigger. Two scopes of one
model on the bench are two tabs.

**Each instrument keeps time for itself**, and nothing says when one started by another's
clock. What puts them on one time axis is either a trigger on each, or one leading the
others.

With **Lead** at *Each its own*, as it begins, each has a trigger of its own, on a channel
of its own, and nought on the axis is each one's trigger. So they line up as well as their
triggers do:

- Put the same signal on a channel of each, and trigger each on it, at the same level and
  edge. The two then line up to within a sample or so of the slower one.
- Triggered on different signals, each is still drawn around its own trigger, and the
  time between the two is not shown.
- An instrument with no trigger chosen is drawn as its newest samples arrive, beside the
  one that has a trigger, and is not lined up with it at all.

With a signal that repeats, each instrument may be showing a different repeat of it. With
**Single** and something that happens once, they show the same one.

With **Lead** set to one of them, that one's trigger holds the plot, and the others are
shown at the same moment -- what they took then, by the computer's clock, whatever is on
their channels. A CAN frame caught by a logic analyser can be seen on a scope's analog
channel without the scope having a trigger of its own on it. The others' triggers are not
used, and **Single** stops them all once the lead has its capture.

The computer's clock lines them up to a millisecond or a few: when each block of samples
arrived, less the time those samples took, and the soonest of them over the last few
seconds. Plenty for a frame or a burst, not for one edge against another at a microsecond a
division -- for that, put the signal on both, and give each its own trigger. An instrument
that streams is the better lead: one that sends sweeps, over a slow link, is known less
surely.

Closing an instrument leaves its traces on the plot to be looked at. They go when another
instrument is opened or run.

## The trigger

The frame on the toolbar holds the trigger. To the left of its line is what is the same for
every instrument that is open: the four run buttons, and **Position**. To the right is the
trigger of the instrument chosen in the Instrument pane. With several open
it says whose it is -- *Trigger, Rigol* -- and each keeps its own channel, edge and level.
**Position** is the same for all of them, since they share the plot, and so is **Lead**,
there with two or more.

| Setting | What it does |
|---------|--------------|
| Trigger | The channel to trigger on, or **None** for no trigger |
| Type | What to wait for: see below. **Edge** to begin with |
| Edge | For an edge: **Rising**, as the signal goes up through the level, **Falling**, or **Either** |
| Level | The voltage the signal has to cross, drawn as a dashed line on the plot |
| ⋯ | The details of what is waited for, beside a few words saying what they come to |
| Position | Where the trigger sits in the plot: 50% is the middle, with as much before as after |
| Lead | With two or more: *Each its own*, or the instrument whose trigger holds the plot, the others shown at that moment. One that follows has its trigger greyed out, and says *follows* which |

### What to wait for

| Type | Triggers on | Its details |
|------|-------------|-------------|
| **Edge** | The signal crossing the level, up, down or either way | -- |
| **Window** | The signal entering the band between the level and an upper level, or leaving it | The upper level, drawn as a second dashed line; entering or leaving |
| **Pulse width** | The end of a pulse -- high, or low -- shorter than a time, longer, or between two: a glitch, or a pulse gone missing | High or low; shorter, longer or between; the times |
| **Runt** | A pulse that crosses the level but goes back without reaching the upper level: a signal that did not make it | The upper level; high or low |
| **Timeout** | The signal staying high, low, or either, for longer than a time: at that moment, while it still is | Which; the time |
| **Logic pattern** | Logic channels each at the level wanted, together: as soon as they are, or once they have been for a time | Each channel's level -- 0, 1 or either; how long it has to be held |
| **Protocol** | The start of a frame, burst or transfer read off a [decoded bus](decoding.md) that matches | The bus; an ID or address; bytes it contains; its type; all, good only, or only problems |

Every type also has a **holdoff**: after a trigger, none is taken for that long -- for a
burst of edges, say, of which only the first is wanted. A time is typed as it is said: `1 ms`,
`500 us`, `2e-6`. A pattern's channels are chosen in its details, so **Trigger** is not used
for one; an analog channel in a pattern is high above the level.

A **Protocol** trigger waits on a bus that is [decoded](decoding.md) already, chosen in its
details, so **Trigger** and **Level** are not used for one either. What matches:

| Detail | What matches |
|--------|--------------|
| ID / address | A CAN identifier or an I²C address, in hex, `X` for a digit that may be anything: `18FEXX00` matches 18FE0000 to 18FEFF00. Empty for any |
| Data contains | Bytes anywhere in it, in hex, `XX` for one that may be anything: `12 XX 34`. Or text in quotes, for a serial line: `"Error"`. Empty for anything |
| Type | CAN: data or remote frames. I²C: reads, writes, or an address nobody answered |
| Which | All, only what was read cleanly, or only what was not: to catch a stuff error or a NACK the moment it happens |

The trigger is at the start of what matched, so the plot shows what led up to it and what
followed.

A digital channel has only one level, between its 0 and its 1, so the level box is not
offered for one.

An instrument that sends short captures taken around a trigger of its own -- a
[PicoScope reading blocks](picoscope.md), or a [Rigol](rigol.md) -- is handed these
settings and does the triggering. What it cannot wait for itself is greyed out: an older
PicoScope does a rising or a falling edge, and a newer PicoScope and a Rigol most of the
types -- what [each](picoscope.md) [does](rigol.md). For everything else the trigger is found by pyscopegui, in the samples as they
arrive, and not by the instrument. So it is the same for every instrument, the samples either side of a trigger are
all still there to go back over, and it finds nothing the instrument cannot stream: on a
PicoScope 2204A, nothing faster than 1 MS/s shows.

A signal has to go back past the level by a fiftieth of the channel's range before it can
trigger again, so that the noise on a slow edge does not trigger a dozen times on the way
through.

What the plot does with a trigger is in [Channels and Plot](plot.md). The trigger's settings
are remembered.

## The Instrument pane

Across the top is a tab for each instrument. Under it, **Connection** has whatever says how
the instrument chosen is reached, and **Open**; the rest is what that instrument lets you
set, which for the demo is nothing.

A scope's channels all have the same settings, so they are shown one channel at a time,
under a row of tabs: **1 2 3 4**. How every channel is set can be read at once in the
[plot's channel list](plot.md), and clicking a channel there brings its settings up here,
whichever instrument it belongs to.

Every scope is set the same way, whoever made it: **Scale** in volts a division, **Probe**
for what is on the end of the channel, and **Coupling**.

### Probes

**Probe** is the same list on every scope:

| Probe | What it is |
|-------|------------|
| 1x, 10x, 20x, 50x, 100x, 500x, 1000x | A voltage probe, as its switch or label says. A differential probe is one of these too: 20x, 50x, 500x |
| Current probe | A clamp or other current probe, which gives so many volts an amp |

A voltage probe divides: through 10x, a tenth of what is at its tip reaches the scope, and
what is read is multiplied back. The scale has the probe counted -- 10 V/div through a 10x
probe -- so the channel says what is at the probe's tip. A Rigol is told the probe, and does
that itself. A Tektronix is told it too, where it has that ratio; the older ones have only
1x, 10x, 100x and 1000x, so for 20x, 50x or 500x it is told 1x and pyscopegui does the
multiplying. A PicoScope has no probe setting, and pyscopegui always does it.

A **Current probe** brings a second setting, **Sensitivity**: how many volts the probe gives
for an amp, as its switch or label says. A clamp's 100 mV/A is 0.1 V/A. The channel is
then in amps, on every scope the same way: its **Scale** is in A/div, its **Offset** and the
trigger level are in amps, and every sample read is too -- so the plot, the
cursors, the [measurements](plot.md) and a maths channel all say amps. A current probe's
volts times another channel's are watts: see *Maths channels* in [the plot](plot.md). The
scope itself is told the probe is 1x and set in the volts the probe gives, so its own screen
shows volts.

A scale saved through one probe and shown through another is the nearest there is.

There are two kinds of setting, and a setting's tip says which it is:

- **What the samples are** -- how many a second, of which channels. Changing one while the
  instrument is running starts the run again, from an empty plot; changed while it is
  stopped, it is used the next time it is run.
- **What changes as it runs** -- a scale, a signal generator. These take effect with what is
  on the plot kept.

Neither closes the instrument, so neither costs the time it took to open.

What says how an instrument is reached -- a network address, a serial port -- is used to
open it, so those are greyed out while it is open: close it to change them.

A list picks one of several; a tick box is on or off; a number is typed, or stepped with its
arrows, and takes effect when you press Enter or move on, not at every digit.

Settings are remembered for each instrument separately, in [your files](files.md).

## A maker's library

An instrument that needs its maker's library -- a driver, an SDK -- does not come with it:
install it from the maker. If it is missing, the [Event Log](event-log.md) says which
library was looked for and where to get it.

## Demo signals

Something to look at with nothing plugged in: a 50 Hz sine and a slow ramp on the analog
plot, and four logic channels counting in binary, the fastest at 1 kHz.
