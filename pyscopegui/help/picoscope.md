[&larr; Contents](manual.md)

# PicoScope 2000 series

Pico has made two ranges of scope called the 2000 Series, with a driver each, and the
instrument list has an entry for each driver. The model number alone does not say which a
scope is on: a 2205A is on `ps2000` and a 2205A MSO is on `ps2000a`.

| Choose | For | Models |
|--------|-----|--------|
| **PicoScope 2000 series (ps2000)** | The older two-channel scopes | 2202, 2203, 2204, 2204A, 2205, 2205A |
| **PicoScope 2000 series (ps2000a)** | The newer two-channel scopes | 2206, 2206A, 2206B, 2207, 2207A, 2207B, 2208, 2208A, 2208B |
| | Those with sixteen logic inputs as well | 2205 MSO, 2205A MSO, 2206B MSO, 2207B MSO, 2208B MSO |
| | The four-channel scopes | 2405A, 2406B, 2407B, 2408B |

Choosing the wrong one does no harm: it says that no PicoScope was found.

The single-channel 2104 and 2105 stream in a different way, which pyscopegui does not
support.

Nearly everything on this page is the same for both. Where the newer scopes differ is
gathered under *The newer scopes, on ps2000a*, below.

Once a scope is open pyscopegui knows which model it is, and offers what that model has. On
the older driver:

| Model | Ranges it has | Signal generator |
|-------|---------------|------------------|
| 2204A, 2205A | ±50 mV to ±20 V | Yes |
| 2202 | Every range | No |
| 2203, 2204, 2205 | Every range | Yes |

"Every range" is for the models pyscopegui holds no list of ranges for: ±20 mV to ±20 V are
all offered, and the scope refuses any it does not have, which the Event Log says.

## Scale and probe

A PicoScope has ranges -- ±5 V -- where a bench scope has volts a division. pyscopegui sets
every scope the bench scope's way, so that two of them side by side are set alike, and puts
the PicoScope on the range that holds eight divisions of the scale chosen:

| Scale, with a 1x probe | Range the scope is put on |
|------------------------|---------------------------|
| 5 mV/div | ±20 mV |
| 10 mV/div | ±50 mV |
| 20 mV/div | ±100 mV |
| 50 mV/div | ±200 mV |
| 100 mV/div | ±500 mV |
| 200 mV/div | ±1 V |
| 500 mV/div | ±2 V |
| 1 V/div | ±5 V |
| 2 V/div | ±10 V |
| 5 V/div | ±20 V |

**Probe** is what is on the end of the channel: a voltage probe, as the switch on it says --
1x to 1000x -- or a current probe. The scope cannot tell, so say it here, and what it reads
is multiplied to be what is at the probe's tip. The scales offered have the probe counted:
10 V/div through a 10x probe is the ±5 V range. Through a current probe whose
**Sensitivity** is 100 mV/A, the ±5 V range is 10 A/div, and the channel is in amps: see
[Probes](instruments.md). The channel list on the plot says what the scale came to.

## Before you start

- **Install the PicoSDK**, from [picotech.com/downloads](https://www.picotech.com/downloads).
  pyscopegui uses the `ps2000` library that comes with it, and does not include it.
- **Close PicoScope 7**, Pico's own program, if it is running. Only one program can have
  the scope open.
- **Plug the scope straight into the computer.** Opening it loads its firmware, and the
  scope leaves the USB bus and comes back while that happens. A virtual machine that has
  been handed the scope by its USB address loses it at that moment.

To use a copy of the library somewhere else, set the environment variable
`PYSCOPEGUI_PS2000` to its full path.

## Running it

Choose **PicoScope 2000 series (ps2000)** under **Add instrument**, or **(ps2000a)** for the
newer scopes, and press **Open** in the Instrument pane. Opening takes a few seconds, and
Pico's driver shows a progress window of its own while it does. The
[Event Log](event-log.md) then names the scope and its serial number.

The scope stays open until **Close**, or until pyscopegui is closed. Starting, stopping and
changing a setting are then quick: none of them opens it again. PicoScope 7 cannot use the
scope while pyscopegui has it open.

## Streaming or blocks

**Reading**, in the Instrument pane, chooses between the two ways the scope can be read.
**Sample rate** is for streaming and **Block length** for blocks, and only the one for the
way chosen is shown.

**Streaming** reads continuously -- what Pico calls fast streaming -- every sample from the
moment a run starts, at up to 1 MS/s on each channel, for as long as it runs. The
[trigger](instruments.md) is found by pyscopegui in those samples, and everything either
side of it is kept to go back over.

**Blocks** are for what is too fast to stream. The scope triggers itself and fills its own
memory at up to 100 MS/s, and each block is then drawn in place of the last. The memory is
a few thousand samples, shared between the channels that are on, so a block is a short
stretch of time and there is nothing either side of it to go back over.

| | Streaming | Blocks |
|---|---|---|
| Fastest | 1 MS/s on each channel | Up to 100 MS/s: the scope says what it has, which is less with both channels on |
| How long | As long as it runs | One block: about 8000 samples on a 2204A, between the channels on |
| Trigger | Found by pyscopegui | The scope's own |
| History | Kept, as *Tools > Settings > History* says | None: each block replaces the last |

**Block length** says how long a stretch each block is, and the scope samples as fast as
its memory allows for that length: a shorter block is sampled faster. The
[Event Log](event-log.md) says what it came to -- *Blocks of 3125 samples at 3,125,000 a
second: 1 ms each* -- and the status bar shows the rate. Ask for a block longer than the
scope can take and it takes its longest, and says so.

The trigger toolbar and the four run buttons work as they do when streaming: the source,
edge, level and position are handed to the scope. **Normal** has it wait for a trigger for as
long as it takes; **Auto** has it take the block anyway after a tenth of a second, or twice
the block's length; **Single** takes one block and stops. With no trigger chosen, blocks are
taken one after another.

Two things are different from streaming. The plot shows the whole block, so the box beside
**Time** has no say in how much is drawn. And only a channel of this scope can be the
trigger, since it is the scope that is triggering.

**What the scope waits for itself.** Beyond a rising or a falling edge, a scope does more of
the trigger's [types](instruments.md) in its own hardware, at its full rate. On `ps2000`,
those with Pico's advanced trigger -- the 2202, 2204, 2204A, 2205 and 2205A -- do; the 2203,
2104 and 2105 trigger on an edge only.

| Type | On `ps2000a` | On `ps2000`, with the advanced trigger |
|------|--------------|----------------------------------------|
| Edge | Rising, falling or **Either**, on a channel or a logic input | Rising, falling or **Either** |
| Window | Entering or leaving | Entering or leaving |
| Pulse width | Shorter, longer or between, high or low | Shorter, longer or between, high or low |
| Runt | High or low | -- |
| Logic pattern | Channels and logic inputs together, as soon as they are so | A and B together, as soon as they are so |
| Timeout, Protocol | -- | -- |

What is not in the scope -- a dash -- is greyed out with blocks.

A **holdoff**, and a pattern that has to be **held** for a time, are not offered with blocks
either. What the scope cannot do itself is greyed out on the toolbar and in the details, and
is there again when streaming, where pyscopegui finds it. A pulse's width is timed in the
block's samples, so it is as fine as the block's rate. In **Auto**, a block is called
triggered only when what was waited for is where the trigger is in it: the driver does not
say whether it triggered or gave up waiting.

Every type in the table has been tried on a 2206B and a 2204A, each scope triggering on its
own generator's square wave, except the logic pattern, which has not been tried on either.

**Choose a range the signal fills** for the most dependable trigger. The scope triggers on
its own readings, with a fiftieth of the range to go back past before it triggers again, so
a signal that spans much of the range gives it the most to work with: a 0.3 V signal
triggers cleanly on the ±200 mV range. A trigger level beyond the range is taken as the top
or the bottom of it.

## Settings

In the [Instrument](instruments.md) pane.

| Setting | What it does |
|---------|--------------|
| Reading | Streaming, or blocks: see above |
| Sample rate | When streaming: samples a second on each channel, from 10 kS/s to 1 MS/s |
| Block length | When reading blocks: how long each is, from 1 us to 1 s |
| Scale | Volts a division, with the probe counted: see above |
| Coupling | DC, or AC to remove a steady voltage and look at what is on top of it |
| Probe | What is on the end of the channel: a voltage probe, 1x to 1000x, or a current probe |
| Sensitivity | For a current probe: volts it gives an amp |
| Enabled | Whether the channel is read at all. Something has to be |

Choose the smallest scale the signal fits in. The scope's converter has 8 bits, so a ±1 V
signal at 2 V/div, which is the ±10 V range, is measured in about twenty-six steps and
looks like a staircase; at 200 or 500 mV/div it is smooth. A signal larger than the range
is clipped at the range.

A scale, a probe or the coupling is taken up as the scope runs: reading stops for a moment while it
is set, drawn as a gap in the plot, and what was on the plot is kept. **Reading**, the
sample rate, the block length and **Enabled** change what the samples are, so they start the
run again from an empty plot. None of them opens the scope again.

## Signal generator

The scope's signal generator output is set from the same pane, and changes while the scope
runs. The scope will not take a new output while it is streaming, so reading stops for a
moment while it is set -- a few tens of milliseconds, drawn as a gap in the plot -- and the
scope is not opened again.

| Setting | What it does |
|---------|--------------|
| Output | Off, sine, square or triangle. Off is a steady zero volts |
| Frequency | 1 Hz to 100 kHz. Its arrows go 1, 2, 5, 10, 20, 50 |
| Peak to peak | From the bottom of the wave to the top: 2 V is a wave between -1 V and +1 V |
| Offset | Moves the whole wave up or down, within 2 V of zero |
| Start | `ps2000a` only. **At once**: the wave runs all the time. **On the scope's trigger**: it waits, and puts out its cycles each time the scope triggers -- a stimulus at the moment of the capture |
| Cycles | `ps2000a` only. How many cycles it puts out at each trigger; 0 starts it at the first and leaves it running |

**On the scope's trigger** needs the scope to be triggering itself, which it does when
reading **blocks** with a trigger chosen. Streaming, the trigger is found by pyscopegui in
what has already arrived, too late to tell the generator: the Event Log says it waits for
ever. In **Auto**, a block the scope takes because nothing came does not start it either:
only a real trigger does.

It is off until you choose a waveform, and what was chosen is put back the next time the
scope is run. **The output is a real voltage on the connector**: know what it is connected
to before switching it on.

Connecting the output to channel A is a quick check of the whole chain. A 1000 Hz sine of
2 V peak to peak, at 500 mV/div, should read between -1 V and +1 V with a period of 1 ms.

## What the Event Log may say

- *Pico's ps2000 library was not found* --- install Pico's software, as above.
- *No PicoScope was found* --- it is not plugged in, or another program has it open.
- *Pico's driver failed while opening the scope* --- the scope left the USB bus part way
  through. Unplug it, plug it in again and press Open.
- *The scope would not set channel A to ...* --- this model does not have that range. If
  it was running, it is still reading on the range it had.
- *Both channels are switched off* --- tick **Enabled** for one of them.
- *Samples are arriving at ... a second where ... were expected* --- the computer, or its USB
  connection, is not keeping up with the rate asked for, and the times on the plot are out by
  that ratio. Choose a lower rate.
- *The driver's buffer filled before it was read* --- the computer did not keep up, and
  samples were lost.
- *The driver lost ... samples, which are shown as a gap* --- the same, said for the
  samples it marked as lost. Said once in a while, with how many since the last time.
- *The window fell behind the scope, so ... samples were left out* --- the scope kept up, but
  drawing, measuring and decoding what it sent did not: with a second's worth waiting to be
  taken in, the next is left out and shown as a gap, rather than the window falling further
  and further behind. Said once in a while. A lower rate, fewer channels, or a shorter span on
  the plot gives it less to do.
- *That is the longest block the scope can take* --- the block length asked for is more than
  its memory holds at its slowest. Streaming reads for longer.
- *The PicoScope stopped answering: it may have been unplugged* --- pyscopegui asks the scope
  whether it is still there whenever it has been quiet a while: every 5 seconds while it is
  open and stopped or waiting for a block, and after a second of streaming with nothing
  arriving; never while samples are arriving, which say it is there. Once unplugged it is
  closed, since the driver needs it opened afresh: plug it in again and press **Open**.

## The newer scopes, on ps2000a

Choose **PicoScope 2000 series (ps2000a)**. The library is `ps2000a`, which the same PicoSDK
installs; to use a copy somewhere else, set `PYSCOPEGUI_PS2000A` to its full path.

The scope is asked what it has when it is opened, and that is what the Instrument pane then
offers: the ranges it has, channels C and D on a four-channel scope, and the logic inputs
on a mixed-signal one. Before a scope has been opened the pane offers two channels and the
generator, which every one of them has.

| | Older scopes, on `ps2000` | Newer scopes, on `ps2000a` |
|---|---|---|
| Channels | A and B | A and B; C and D too on a 24xx, off until ticked |
| Logic inputs | None | D0 to D15 on an MSO |
| Streaming | To 1 MS/s on each channel | To 31.25 MS/s: see below |
| Blocks | To 100 MS/s, a few thousand samples | To the scope's fastest -- 500 MS/s or 1 GS/s -- and up to a million samples |
| Trigger for blocks | A or B; either edge, window, pulse width and pattern too, on the models with the advanced trigger | Any channel that is on, or any logic input; window, pulse width, runt and pattern too |
| Signal generator | To 100 kHz | To 1 MHz, and on the scope's trigger |
| Offset | None | On the models that have it |

### Offset

To read a signal that sits away from nought more finely -- one between 3 V and 4 V, say --
give its channel an **Offset**. It is added to the signal before the scope measures it, in
volts at the probe's tip -- amps, through a current probe -- as a bench scope's offset is:
-3.5 V puts that signal in the middle of the range, and a smaller **Scale** then fits it,
measured in finer steps.

The offset is taken off again, so what is read, measured and exported is the signal itself:
3.5 V reads 3.5 V. With **Y** set to **Range**, the plot's axis is the stretch the scope is
measuring, 3 V to 4 V on ±500 mV with -3.5 V of offset; with **Auto**, the axis fits the
signal whatever the offset. Unlike PicoScope's own software, the trace is not drawn moved by
the offset: it stays at its true voltage.

Each range takes only so much offset, and the smaller ranges less: the scope says how much,
and pyscopegui asks it. Ask for more than a range takes and it is given as much as it takes,
the [Event Log](event-log.md) says so, and what is read is still the signal itself -- only
less of it may be in the range. So for 3 V to 4 V, the useful setting is the smallest scale
whose range takes an offset of about 3.5 V.

**Offset** is offered once the scope is open, and only if it has one: not every model does,
and the older scopes on `ps2000` have none at all. It is taken up as the scope runs, and the
channel list says it beside the scale.

### Logic inputs

A mixed-signal scope's sixteen logic inputs are in two ports of eight, and a port is read
whole or not at all. Under **Logic inputs** in the Instrument pane:

| Setting | What it does |
|---------|--------------|
| D0 to D7, D8 to D15 | Whether that port's eight inputs are read. Off to begin with |
| Threshold | The voltage above which an input reads 1, from -5 V to 5 V. One for each port |

1.5 V suits 5 V and 3.3 V logic; half the supply voltage suits anything else. Each input is
then a channel on the plot like any other, drawn as a logic trace, and can be the trigger:
when streaming pyscopegui finds its edge, and when reading blocks the scope does.

A port is held as the scope sends it, its eight inputs together in a byte a sample, and each
input is read out of it only where it is looked at: all sixteen take two bytes a sample.

A threshold is taken up as the scope runs. Switching a port on or off changes what the
channels are, so it starts the run again.

### Streaming faster

**Sample rate** goes on past 1 MS/s: 2, 5, 10, 15.625, 20 and 25 MS/s, and 31.25 MS/s, which
is a sample every 32 ns. Each is a whole number of nanoseconds a sample: 15.625 MS/s is 64 ns. Whether a rate is kept depends on the scope, on USB and on the computer,
and on how much is switched on -- the fastest rates are for one channel. Nothing is hidden
when it is not kept:

- The scope may give the nearest rate it has, which the Event Log says, and time on the
  plot is counted at that.
- If samples arrive slower than asked for, the Event Log says so after five seconds.
- If the driver's buffer fills because it was not read in time, the run stops and says so.

What is kept to go back over is held in memory as the scope sends it, two bytes a sample
for a channel and one for a port of eight logic inputs, and turned into volts only where it
is looked at: at 20 MS/s that is 40 MB for every second of one channel. A run keeps no more of the memory that is free than *Tools > Settings >
Memory* says -- three quarters, to begin with -- so streaming fast keeps a shorter stretch than
*Tools > Settings > History* says, and the Event Log says how long: see
[How much is kept](plot.md).

For a short stretch of something fast, a block is the better tool: it is taken at the
scope's full rate, and nothing has to keep up.

### Blocks

These scopes have far more memory than the older ones -- tens of thousands of samples on the
smallest, tens of millions on the largest -- so a block is not the few thousand samples it
is on a 2204A. pyscopegui reads **up to a million samples a block**, and has the scope
sample as fast as it can for the block length within that: a 1 ms block on a 2206B is
250,000 samples at 250 MS/s with both channels on.

The fastest rate needs the fewest inputs on. A scope that samples at 1 GS/s does so with
one channel; with two it is half that, and the logic inputs count as well.

### What else the Event Log may say

- *Pico's ps2000a library was not found* --- install the PicoSDK, as above.
- *Every channel is switched off* --- tick **Enabled** for a channel, or a port of logic
  inputs.
- *The scope is streaming at ... the nearest it has to the ... asked for* --- the driver
  rounded the rate, and time on the plot is counted at the rate it gave.
- *The driver's buffer filled before it was read, and it has stopped* --- the computer did
  not keep up. Choose a lower rate.
- A message that ends *driver status 0x...* --- the driver refused something. Pico's
  `PicoStatus.h`, in the SDK, lists what each number means; say the number in a bug report.

## Grounds

The scope's two input grounds are joined to each other and, through USB, to the computer's
ground. Clipping a ground lead to a point that is not at ground can damage what is being
measured, the scope and the computer.
