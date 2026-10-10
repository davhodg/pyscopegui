[&larr; Contents](manual.md)

# PicoScope 2204A

For the two-channel PicoScope 2000 Series scopes that use Pico's older `ps2000` driver: the
2202, 2203, 2204, 2204A, 2205 and 2205A. It has been tried on a 2204A. The newer models --
the B models and the MSOs -- use a different driver, `ps2000a`, and are not supported yet.

## Before you start

- **Install Pico's software.** The PicoSDK or PicoScope 7, from
  [picotech.com/downloads](https://www.picotech.com/downloads). pyscopegui uses the
  `ps2000` library that comes with either, and does not include it.
- **Close PicoScope 7.** Only one program can have the scope open.
- **Plug the scope straight into the computer.** Opening it loads its firmware, and the
  scope leaves the USB bus and comes back while that happens. A virtual machine that has
  been handed the scope by its USB address loses it at that moment.

To use a copy of the library somewhere else, set the environment variable
`PYSCOPEGUI_PS2000` to its full path.

## Running it

Choose **PicoScope 2204A (ps2000)** and press **Run**. Opening takes a few seconds, and
Pico's driver shows a progress window of its own while it does. The
[Event Log](event-log.md) then names the scope and its serial number.

The scope is read continuously -- what Pico calls fast streaming -- with no trigger: every
sample from the moment it starts, on both channels at once.

## Settings

In the [Instrument](instruments.md) pane.

| Setting | What it does |
|---------|--------------|
| Sample rate | Samples a second on each channel, from 10 kS/s to 1 MS/s |
| Range | The most the input can measure, either side of zero: ±50 mV to ±20 V |
| Coupling | DC, or AC to remove a steady voltage and look at what is on top of it |
| Enabled (channel B) | Whether channel B is read at all |

Choose the smallest range the signal fits in. The scope's converter has 8 bits, so a ±1 V
signal on the ±10 V range is measured in about twenty-six steps and looks like a staircase;
on ±1 V or ±2 V it is smooth. A signal larger than the range is clipped at the range.

Changing any of these starts the scope again, which is its few seconds of opening each time.

## Signal generator

The scope's signal generator output is set from the same pane, and changes at once without
starting the scope again.

| Setting | What it does |
|---------|--------------|
| Output | Off, sine, square or triangle. Off is a steady zero volts |
| Frequency | 1 Hz to 100 kHz |
| Peak to peak | From the bottom of the wave to the top: 2 V is a wave between -1 V and +1 V |
| Offset | Moves the whole wave up or down, within 2 V of zero |

It is off until you choose a waveform, and what was chosen is put back the next time the
scope is run. **The output is a real voltage on the connector**: know what it is connected
to before switching it on.

Connecting the output to channel A is a quick check of the whole chain. A 1000 Hz sine of
2 V peak to peak, on the ±2 V range, should read between -1 V and +1 V with a period of 1 ms.

## What the Event Log may say

- *Pico's ps2000 library was not found* --- install Pico's software, as above.
- *No PicoScope was found* --- it is not plugged in, or another program has it open.
- *Pico's driver failed while opening the scope* --- the scope left the USB bus part way
  through. Unplug it, plug it in again and press Run.
- *The scope would not set channel A to ...* --- this model does not have that range.
- *The scope is delivering ... samples a second where ... were asked for* --- it cannot keep
  to that rate, and the times on the plot are out by that ratio. Choose a lower rate.
- *The driver's buffer filled before it was read* --- the computer did not keep up, and
  samples were lost.

## Grounds

The scope's two input grounds are joined to each other and, through USB, to the computer's
ground. Clipping a ground lead to a point that is not at ground can damage what is being
measured, the scope and the computer.
