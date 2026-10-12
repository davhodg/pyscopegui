[&larr; Contents](manual.md)

# Tektronix TDS and TPS 2000

For Tektronix's TDS200, TDS1000, TDS2000 and TPS2000 series scopes, over a serial port.
They are one family with one set of commands, and differ in bandwidth, in how many channels
they have, and in what they are plugged in by.

| Models | Channels | Serial port |
|--------|----------|-------------|
| TPS2012, TPS2014, TPS2024 | Two, or four where the number ends in 4 | Its own, on the side |
| TDS1002, TDS1012, TDS2002, TDS2012, TDS2014, TDS2022, TDS2024 | Two or four, likewise | On the TDS2CMA or TDS2CM module |
| TDS210, TDS220, TDS224 | Two or four, likewise | On the TDS2CM or TDS2CMA module |

The later scopes with a USB port in place of a serial one -- the TDS1000B, TDS2000B and
TDS2000C -- take the same commands, but USB is not supported yet.

Nothing of Tektronix's needs installing.

## Connecting

- **A cable.** The scope's serial port to the computer's, or to a USB serial adapter. Two
  computers' worth of port are being joined, so it is a *null modem* cable that is wanted,
  with all its wires if hard flagging is to be used.
- **On the scope**, press **Utility > Options > RS232 Setup**. Set the speed to the
  fastest there is, 19200, and flagging to **Hard**. Leave the end of line at LF.
- **In the Instrument pane**, put the port's name in **Port** -- `COM3` on Windows, as
  Device Manager lists it under *Ports*, or `/dev/ttyUSB0` on Linux -- and set **Speed** and
  **Flow control** to what the scope has. Then press **Open**.

The [Event Log](event-log.md) says which scope answered, and how many channels it has. The
Instrument pane then offers that many.

## It is slow

A waveform is 2500 points, and a serial port is slow: a little over a second a channel at
19200 baud, about three at 9600, and most of a minute at 300. So this is for taking a
capture off the scope and onto the computer -- to look at closely, or to
[export as CSV](plot.md) -- and not for watching a signal move.

## Two ways of reading

**Reading**, in the Instrument pane, chooses between them.

**Set it up, and take sweeps.** The scope is put as the pane says -- timebase, channels,
trigger -- and takes one sweep after another, each read as it is taken. The trigger toolbar
and the four run buttons are handed to the scope. **Normal** waits for a trigger for as
long as it takes; **Auto** lets the scope give up waiting, as its own Auto does;
**Single** takes one sweep and stops.

**What it shows, as it is.** Nothing on the scope is changed, and nothing is asked of it
but what is on its screen. This is the one for fetching something that was captured at the
bench: stop the scope on what you want, press **Single** here, and it is on the plot. The
channels read are the ones ticked **Enabled** here that are also on the scope's screen;
their scale, their timebase and their trigger are the scope's own. Left on **Auto**, it
reads the screen over and over, which follows a scope that is running without touching it.

Either way the plot shows the whole sweep, with nought on the time axis at the scope's
trigger.

## Settings

| Setting | What it is |
|---------|------------|
| Port | The serial port the scope is on. Taken up at the next **Open** |
| Speed | The baud rate, as the scope is set. Taken up at the next **Open** |
| Flow control | Hard flagging, or none, as the scope is set. Taken up at the next **Open** |
| Reading | Set up from here, or read as it is: see above |
| Time | Seconds a division, of the ten across the screen |
| Acquisition | Sample, peak detect, or an average of several sweeps |
| Averages | How many sweeps go into each average: 4, 16, 64 or 128 |
| Enabled | Whether the channel is read, and when setting up, whether it is on |
| Scale | Volts a division, of the eight up the screen, with the probe counted |
| Offset | Moves nought volts up or down the screen |
| Coupling | DC, AC or ground |
| 20 MHz limit | Leaves out what is above 20 MHz, which for a slow signal is noise |
| Probe | What the probe divides by: 1x, 10x, 100x or 1000x |

Everything from **Time** down is used when the scope is set up from here, and greyed out
when it is read as it is. **Reading** and **Enabled** start the run again; the rest are
taken up between two sweeps.

Soft flagging is not offered. A waveform is sent as bytes, any of which soft flagging
would take for one of its own.

## When it does not work

- *No port to open* --- **Port** in the Instrument pane is empty.
- *The serial port ... could not be opened* --- the name is wrong, or another program has
  the port.
- *The scope did not answer ...* --- the cable is not a null modem one, or the speed or
  flow control here is not what the scope has. With hard flagging and a cable that lacks
  those wires, nothing is ever sent: try **None**, on the scope and here.
- *What answered ... is not this scope* --- something else is on that port.
- *None of the channels ticked here is on the scope's screen* --- reading it as it is, with
  a channel ticked that the scope is not showing.
