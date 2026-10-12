[&larr; Contents](manual.md)

# PicoScope 2000 series

For the two-channel PicoScope 2000 Series scopes that use Pico's older `ps2000` driver: the
2202, 2203, 2204, 2204A, 2205 and 2205A.

The rest of the 2000 Series use a different driver, `ps2000a`, and are **not supported
yet**. The model number alone does not say which: a 2205A is on `ps2000` and a 2205A MSO is
not.

| Not supported yet | Models |
|-------------------|--------|
| 2-channel | 2206, 2206A, 2206B, 2207, 2207A, 2207B, 2208, 2208A, 2208B |
| 2-channel with logic inputs | 2205 MSO, 2205A MSO, 2206B MSO, 2207B MSO, 2208B MSO |
| 4-channel | 2405A, 2406B, 2407B, 2408B |

The single-channel 2104 and 2105 are on the `ps2000` driver but cannot stream as this back
end needs, and are not supported either.

Once a scope is open pyscopegui knows which model it is, and offers what that model has:

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

**Probe** is what the probe divides by, as the switch on it says: 1x, 10x or 100x. The scope
cannot tell, so say it here, and voltages are multiplied by it to be what is at the probe's
tip. The scale has the probe counted: 10 V/div through a 10x probe is the ±5 V range. A
scale the scope cannot reach through the probe chosen is the nearest it can, and the
channel list on the plot says what that came to.

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

Choose **PicoScope 2000 series (ps2000)** and press **Open**. Opening takes a few seconds, and
Pico's driver shows a progress window of its own while it does. The
[Event Log](event-log.md) then names the scope and its serial number.

The scope stays open until **Close**, or until pyscopegui is closed. Starting, stopping and
changing a setting are then quick: none of them opens it again. PicoScope 7 cannot use the
scope while pyscopegui has it open.

## Streaming or blocks

**Reading**, in the Instrument pane, chooses between the two ways the scope can be read.
**Sample rate** is for streaming and **Block length** for blocks, and whichever has no say
is greyed out.

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
**Time** has no say in how much is drawn. And only channel A or B can be the trigger, since
it is the scope that is triggering.

## Settings

In the [Instrument](instruments.md) pane.

| Setting | What it does |
|---------|--------------|
| Reading | Streaming, or blocks: see above |
| Sample rate | When streaming: samples a second on each channel, from 10 kS/s to 1 MS/s |
| Block length | When reading blocks: how long each is, from 1 us to 1 s |
| Scale | Volts a division, with the probe counted: see above |
| Coupling | DC, or AC to remove a steady voltage and look at what is on top of it |
| Probe | What the probe divides by: 1x, 10x or 100x |
| Enabled | Whether the channel is read at all. One of the two has to be |

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
- *The scope is delivering ... samples a second where ... were asked for* --- it cannot keep
  to that rate, and the times on the plot are out by that ratio. Choose a lower rate.
- *The driver's buffer filled before it was read* --- the computer did not keep up, and
  samples were lost.
- *That is the longest block the scope can take* --- the block length asked for is more than
  its memory holds at its slowest. Streaming reads for longer.
- *The scope stopped answering* --- while a block was being waited for. It may have been
  unplugged.

## Grounds

The scope's two input grounds are joined to each other and, through USB, to the computer's
ground. Clipping a ground lead to a point that is not at ground can damage what is being
measured, the scope and the computer.
