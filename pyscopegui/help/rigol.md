[&larr; Contents](manual.md)

# Rigol DS1000Z

For Rigol's DS1000Z series of four-channel scopes, over the network or USB. The models differ in
bandwidth and in what is added to the four analog channels, which are the same on all of
them and are what pyscopegui reads.

| Models | What they add | In pyscopegui |
|--------|---------------|---------------|
| DS1054Z, DS1074Z, DS1104Z | Nothing: 50, 70 or 100 MHz | The four analog channels |
| DS1074Z Plus, DS1104Z Plus | Logic inputs, with Rigol's probe | The analog channels; the logic inputs are not read yet |
| DS1074Z-S Plus, DS1104Z-S Plus | Logic inputs and a signal generator | The analog channels; neither of the others yet |
| MSO1074Z, MSO1104Z, and the -S of each | Sixteen logic inputs; a signal generator on the -S | The analog channels; neither of the others yet |

The older DS1000E and DS1000D scopes -- the DS1052E -- are a different series with
different commands, and are not supported.

The scope is talked to in plain text, over the network or over USB. **Connection**, in the
Instrument pane, says which.

## Connecting over the network

Nothing needs installing. Plug the scope into the network, and on the scope press **Utility > IO > LAN Conf** to see
the address it was given. Put that in **Address** in the Instrument pane -- `192.168.1.50`
-- and press **Open**. The [Event Log](event-log.md) says which scope answered. The box is
amber while what is typed in it has not been taken up yet: Enter, leaving the box, **Open**
or a run button takes it up.

A scope plugged straight into the computer with one cable works too: leave *Auto IP* on in
the same menu, and both ends give themselves an address starting `169.254`.

## Connecting over USB

USB goes through a *VISA library*, which is the usual way programs talk to bench
instruments and is not part of pyscopegui. Rigol's own software, UltraSigma, installs one;
so do National Instruments' NI-VISA and Keysight's IO Libraries. Any one of them will do.

- Plug the scope's USB **device** port, on its back, into the computer.
- On the scope, **Utility > IO > USB Device** should say **Computer**.
- Choose **USB** for **Connection** and press **Open**. The first Rigol scope the library
  lists is used, and the [Event Log](event-log.md) says which answered.

**USB device** says which scope, and left empty it is the first Rigol found, which with one
scope plugged in is all that is wanted. With more than one, open its list: it shows the
scopes plugged in at that moment, by serial number. A serial number can be typed there too.

The two ways in take the same commands, and everything below is the same for both.

## Sweeps

The scope cannot send samples continuously. It triggers itself and fills its own memory,
and what it took is then read back. So the plot shows one **sweep** at a time, each taking
the place of the last, and there is no history either side of it to go back over.

The trigger toolbar and the four run buttons are handed to the scope. **Normal** waits for a
trigger for as long as it takes. **Auto** waits a little longer than one screen and then
has the scope take the sweep anyway. **Single** takes one sweep and stops. With no trigger
chosen, sweeps are taken one after another.

The trigger's [types](instruments.md) are the scope's own, each tried on a DS1054Z:

| Type | On the scope |
|------|--------------|
| Edge | Rising, falling or **Either** |
| Pulse width | Shorter, longer or between, high or low |
| Runt | High or low: an option on a DS1000Z |
| Window | Entering or leaving: an option on a DS1000Z |
| Timeout | High, low or either for longer than a time: an option on a DS1000Z |
| Logic pattern | Channels together, each at the level, as soon as they are so |
| Logic pattern, held | The scope's Duration trigger: an option on a DS1000Z, and not yet tried on one |
| Protocol | Greyed out |

Each with a **holdoff**, which the scope has too -- all but a timeout, which has none. A
pattern that has to be **held** for 8 ns to 10 s is the scope's own Duration trigger, which
measures how long the pattern lasted once it is over: the sweep is taken around the moment
the pattern ends, having lasted longer than the time, rather than the moment it has lasted
that long, as it is for an instrument that streams. A pattern held for ever does not trigger
it. Runt, window, timeout and duration are among the advanced triggers Rigol sells as an
option for the DS1000Z: a scope without it says so in the [Event Log](event-log.md) when one
is asked for. The **Nth time** and a **delay** are greyed out: the scope has neither.

The plot shows the whole sweep, so the box beside **Time** has no say in how much is drawn:
**Time** in the Instrument pane does that, as the knob on the scope would.

**Reading** chooses how much of each sweep is read.

| | Screen | Memory |
|---|---|---|
| Points | The 1200 the scope draws | Every sample it took: thousands to millions |
| How quick | About two sweeps a second | Seconds for each: about ten for six million points |
| For | Looking, as you would at the scope | **Single**, then zooming in |

How deep the memory is, is left as it is set on the scope: *Acquire > Mem Depth*.

The scope says *Can Operate Now!* and beeps after every piece of its memory that is read,
which is dozens of times a sweep. So pyscopegui turns the scope's beeper off while it reads
the memory, and puts it back as it was when the run stops: one beep as a run starts and one
as it stops is what is left. If pyscopegui is ended in the
middle of a run, turn it back on at the scope: *Utility > Sound*.

## Settings

| Setting | What it is |
|---------|------------|
| Connection | Network, or USB. Set while the scope is closed |
| Address | For the network: where the scope is. Set while the scope is closed |
| USB device | For USB: which scope, where there are several. Set while the scope is closed |
| Reading | The screen, or the memory: see above |
| Time | Seconds a division, of the twelve across the screen |
| Acquisition | How each point is made from the samples taken: see below |
| Enabled | Whether the channel is on, and read |
| Scale | Volts a division, of the eight up the screen, with the probe counted |
| Offset | Moves nought volts up or down the screen |
| Coupling | DC, AC or ground |
| 20 MHz limit | Leaves out what is above 20 MHz, which for a slow signal is noise |
| Probe | What is on the end of the channel: a voltage probe, 1x to 1000x, or a current probe. See [Probes](instruments.md) |
| Sensitivity | For a current probe: volts it gives an amp. The channel is then in amps |

**Reading** and **Enabled** start the run again. The rest are taken up between two sweeps.

**Acquisition** is the scope's own *Acquire > Mode*:

| Acquisition | What it does |
|-------------|--------------|
| Normal | One sample for each point |
| High resolution | Averages the samples either side of each point: quieter, and slower to follow an edge |
| Peak detect | Keeps the lowest and the highest, so that nothing narrow is missed |

The scope's averaging mode is not offered. It averages over several triggers, and each
sweep here is one trigger.

A trace that looks noisy beside another scope's is often only showing more: the whole of
the memory at full bandwidth has noise in it that a slower scope never sees. The 20 MHz
limit and High resolution are the two things that take it out.

pyscopegui sets the scope up from this pane when a run starts, so the knobs on the scope
are overridden for these settings. Everything else -- memory depth, and a signal generator
if the scope has one -- stays as the scope has it.

## When it does not work

- *No address to connect to* --- **Address** in the Instrument pane is empty.
- *No scope answered at ...* --- the address is wrong, the scope is off or on another
  network, or something between the two blocks port 5555.
- *No VISA library was found for USB* --- USB needs one installed: see above. The network
  needs none.
- *No scope of Rigol's was found on USB* --- the message lists what the library can see.
  The cable is in the scope's USB host port on the front, which is for memory sticks, or
  **Utility > IO > USB Device** is set to a printer.
- *The scope stopped answering* --- it was unplugged or switched off, or another program
  sent it something that it is still busy with.
- *The Rigol stopped answering and has been closed* --- while it was stopped. pyscopegui
  asks a stopped scope who it is every 5 seconds, so that one switched off or unplugged is
  noticed then rather than at the next Run; running, every look at its trigger says it is
  there. Press **Open** once it is back.
- *This was written for the DS1000Z scopes* --- something else answered. It may work, as
  far as it speaks the same commands.
