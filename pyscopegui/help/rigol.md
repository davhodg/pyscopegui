[&larr; Contents](manual.md)

# Rigol DS1000Z

For Rigol's DS1000Z series of four-channel scopes, over the network. The models differ in
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

Nothing of Rigol's needs installing. The scope is talked to in plain text over the network,
which every one of them can do.

## Connecting

Plug the scope into the network, and on the scope press **Utility > IO > LAN Conf** to see
the address it was given. Put that in **Address** in the Instrument pane -- `192.168.1.50`
-- and press **Open**. The [Event Log](event-log.md) says which scope answered. The box is
amber while what is typed in it has not been taken up yet: Enter, leaving the box, **Open**
or a run button takes it up.

A scope plugged straight into the computer with one cable works too: leave *Auto IP* on in
the same menu, and both ends give themselves an address starting `169.254`.

USB is not supported yet.

## Sweeps

The scope cannot send samples continuously. It triggers itself and fills its own memory,
and what it took is then read back. So the plot shows one **sweep** at a time, each taking
the place of the last, and there is no history either side of it to go back over.

The trigger toolbar and the four run buttons are handed to the scope. **Normal** waits for a
trigger for as long as it takes. **Auto** waits a little longer than one screen and then
has the scope take the sweep anyway. **Single** takes one sweep and stops. With no trigger
chosen, sweeps are taken one after another.

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
| Address | Where the scope is on the network. Taken up at the next **Open** |
| Reading | The screen, or the memory: see above |
| Time | Seconds a division, of the twelve across the screen |
| Acquisition | How each point is made from the samples taken: see below |
| Enabled | Whether the channel is on, and read |
| Scale | Volts a division, of the eight up the screen, with the probe counted |
| Offset | Moves nought volts up or down the screen |
| Coupling | DC, AC or ground |
| 20 MHz limit | Leaves out what is above 20 MHz, which for a slow signal is noise |
| Probe | What the probe divides by: 1x, 10x or 100x |

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
- *The scope stopped answering* --- it was unplugged or switched off, or another program
  sent it something that it is still busy with.
- *This was written for the DS1000Z scopes* --- something else answered. It may work, as
  far as it speaks the same commands.
