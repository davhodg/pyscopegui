[&larr; Contents](manual.md)

# Tektronix TDS and TPS 2000

For Tektronix's TDS200, TDS1000, TDS2000 and TPS2000 series scopes, over a serial port or
USB. They are one family with one set of commands, and differ in bandwidth, in how many
channels they have, and in what they are plugged in by.

| Models | Channels | Plugged in by |
|--------|----------|---------------|
| TDS1001B, TDS1002B, TDS1012B, TDS2002B, TDS2004B, TDS2012B, TDS2014B, TDS2022B, TDS2024B, and the TDS2000C | Two, or four where the number ends in 4 | USB, on the back |
| TPS2012, TPS2014, TPS2024 | Two or four, likewise | A serial port of its own, on the side |
| TDS1002, TDS1012, TDS2002, TDS2012, TDS2014, TDS2022, TDS2024 | Two or four, likewise | A serial port on the TDS2CMA or TDS2CM module |
| TDS210, TDS220, TDS224 | Two or four, likewise | A serial port on the TDS2CM or TDS2CMA module |

Over a serial port nothing of Tektronix's needs installing. USB needs a VISA library:
Tektronix's own TekVISA, or National Instruments' or Keysight's -- whichever is there.

## Connecting

**Connection**, at the top of the Instrument pane, says which: **Serial port** to begin
with, or **USB**. What is not for the one chosen is greyed out.

### On USB

- **A cable** from the USB port on the back of the scope -- the square one -- to the
  computer. Where the scope offers that port for a computer or for a printer, it has to be
  set for a computer.
- **A VISA library** on the computer: TekVISA, NI-VISA or Keysight's.
- **In the Instrument pane**, set **Connection** to **USB**. **USB device** lists the
  Tektronix scopes plugged in at that moment; left empty, the first one found is used, and
  a serial number can be typed to choose between two. Then press **Open**. The
  [Event Log](event-log.md) says which device it opened.

### On a serial port

- **A cable.** The scope's serial port to the computer's, or to a USB serial adapter. Two
  computers' worth of port are being joined, so it is a *null modem* cable that is wanted,
  with all its wires if hard flagging is to be used.
- **On the scope**, press **Utility > Options > RS232 Setup**. Set the speed to the
  fastest there is, 19200, and flagging to **Hard**. Parity **None** and an end of line of
  **LF** are what pyscopegui starts with.
- **In the Instrument pane**, choose the port from the list in **Port**, which shows the
  serial ports there are at that moment -- `COM3` on Windows, `/dev/ttyUSB0` on Linux; a
  name can be typed too -- and set **Speed**, **Flow control**, **Parity** and **End of
  line** to what the scope has. Then press **Open**.

The [Event Log](event-log.md) says which scope answered, and how many channels it has. The
Instrument pane then offers that many.

## It is slow

A waveform is 2500 points, and a serial port is slow: a little over a second a channel at
19200 baud, about three at 9600, and most of a minute at 300. So on a serial port this is for
taking a capture off the scope and onto the computer -- to look at closely, or to
[export as CSV](plot.md) -- and not for watching a signal move. On USB a waveform takes a
moment, and the scope itself is what is slow: the set-up below, and its own sweeps.

Setting the scope up takes a while too: it takes up to a second over each setting, and a
first run with four channels sends about thirty, which can be half a minute. They are sent
one at a time, each once the scope has done the one before, so the status bar and the plot
can say how far it has got -- *setting up the scope (7 of 31)*, *waiting for a sweep*,
*reading CH2 (2 of 4)* -- and the [Event Log](event-log.md) says how long the set-up took.
After that only what changes is sent. **Stop** or **Close** part way through a set-up stops
it after the setting in hand.

A scope that is closed part way through a set-up, by something other than **Close** --
pyscopegui itself closed, or a cable pulled -- may still be busy with what it was sent the
next time it is opened. It answers nothing until it has done, so opening waits up to a
minute for it to say who it is, and the Event Log says it is waiting.

## Two ways of reading

**Reading**, in the Instrument pane, chooses between them.

**Set it up, and take sweeps.** The scope is put as the pane says -- timebase, channels,
trigger -- and takes one sweep after another, each read as it is taken. The trigger toolbar
and the four run buttons are handed to the scope. **Normal** waits for a trigger for as
long as it takes; **Auto** lets the scope give up waiting, as its own Auto does;
**Single** takes one sweep and stops.

While it takes sweeps the scope is stopping after each one, so its own screen holds still
while a sweep is read and moves on only when the next is taken. That is the scope waiting
to be read, not a fault. When the run is stopped, or the scope closed, it is put back to
acquiring as it was found.

**What it shows, as it is.** Nothing on the scope is changed, and nothing is asked of it
but what is on its screen. This is the one for fetching something that was captured at the
bench: stop the scope on what you want, press **Read** here, and it is on the plot. The
channels read are the ones ticked **Enabled** here that are also on the scope's screen;
their scale, their timebase and their trigger are the scope's own.

What is read is a snapshot of the screen, so the plot's **Time** is set to **All** when the
scope is set to be read this way, or is opened already set so: **Follow**, with another
instrument on the plot beside it, would show only a stretch of the snapshot around its
trigger. It is done that once, and what you choose after that is left as it is.

**Read** is on the toolbar, beside **Add instrument**, while the scope is read this way. It takes what
the screen shows once and stops. **Auto** reads the screen over and over, which follows a
scope that is running without touching it. There is no trigger here to wait for -- the
scope triggers on whatever it was set to at the bench -- so the trigger's **Source**,
**Edge** and **Level** are greyed out, no level is drawn on the plot, and **Single** and
**Normal** are greyed out too unless another instrument is open for them to run.

Either way the plot shows the whole sweep, with nought on the time axis at the scope's
trigger.

## Settings

| Setting | What it is |
|---------|------------|
| Connection | Serial port, or USB. Set while the scope is closed |
| USB device | On USB: which scope, where there are several. Set while the scope is closed |
| Port | On a serial port: the port the scope is on. Set while the scope is closed |
| Speed | On a serial port: the baud rate, as the scope is set. Set while the scope is closed |
| Flow control | On a serial port: hard flagging, or none, as the scope is set. Set while the scope is closed |
| Parity | On a serial port: none, even or odd, as the scope is set. Set while the scope is closed |
| End of line | On a serial port: what the scope ends each answer with -- LF, CR, CR/LF or LF/CR -- as it is set. Set while the scope is closed |
| Reading | Set up from here, or read as it is: see above |
| Time | Seconds a division, of the ten across the screen |
| Acquisition | Sample, peak detect, or an average of several sweeps |
| Averages | How many sweeps go into each average: 4, 16, 64 or 128 |
| Enabled | Whether the channel is read, and when setting up, whether it is on |
| Scale | Volts a division, of the eight up the screen, with the probe counted |
| Offset | Moves nought volts up or down the screen |
| Coupling | DC, AC or ground |
| 20 MHz limit | Leaves out what is above 20 MHz, which for a slow signal is noise |
| Probe | What is on the end of the channel: a voltage probe, 1x to 1000x, or a current probe. See [Probes](instruments.md) |
| Sensitivity | For a current probe: volts it gives an amp. The channel is then in amps |

Everything from **Time** down is used when the scope is set up from here, and greyed out
when it is read as it is. **Reading** and **Enabled** start the run again; the rest are
taken up between two sweeps.

Soft flagging is not offered. A waveform is sent as bytes, any of which soft flagging
would take for one of its own.

## When it does not work

- *No port to open* --- **Port** in the Instrument pane is empty, with **Connection** at
  Serial port.
- *No VISA library was found for USB* --- there is none on the computer: install TekVISA,
  NI-VISA or Keysight's.
- *No scope of Tektronix's was found on USB* --- the Event Log says what the VISA library
  does list. Check the cable, that the scope is on, and that its USB port is set for a
  computer.
- *The serial port ... could not be opened* --- the name is wrong, or another program has
  the port.
- *Setting ... to ...: the scope did not answer* --- it was being set up, and did not say
  it had done that setting within fifteen seconds. It may have been unplugged.
- *The scope did not answer ...* --- the cable is not a null modem one, or the speed, flow
  control, parity or end of line here is not what the scope has. With hard flagging and a cable that lacks
  those wires, nothing is ever sent: try **None**, on the scope and here.
- *What answered ... is not this scope* --- something else is on that port.
- *None of the channels ticked here is on the scope's screen* --- reading it as it is, with
  a channel ticked that the scope is not showing.
