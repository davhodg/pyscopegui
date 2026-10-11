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

It has been tried on a DS1054Z, with voltages, timing and the place of the trigger checked
against the scope's own 1 kHz probe-compensation output. The other models take the same
commands, and have not been tried.

The older DS1000E and DS1000D scopes -- the DS1052E -- are a different series with
different commands, and are not supported.

Nothing of Rigol's needs installing. The scope is talked to in plain text over the network,
which every one of them can do.

## Connecting

Plug the scope into the network, and on the scope press **Utility > IO > LAN Conf** to see
the address it was given. Put that in **Address** in the Instrument pane -- `192.168.1.50`
-- and press **Open**. The [Event Log](event-log.md) says which scope answered.

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

## Settings

| Setting | What it is |
|---------|------------|
| Address | Where the scope is on the network. Taken up at the next **Open** |
| Reading | The screen, or the memory: see above |
| Time | Seconds a division, of the twelve across the screen |
| Enabled | Whether the channel is on, and read |
| Scale | Volts a division, of the eight up the screen, with the probe counted |
| Offset | Moves nought volts up or down the screen |
| Coupling | DC, AC or ground |
| Probe | What the probe divides by: 1x, 10x or 100x |

**Reading** and **Enabled** start the run again. The rest are taken up between two sweeps.

pyscopegui sets the scope up from this pane when a run starts, so the knobs on the scope
are overridden for these settings. Everything else -- memory depth, bandwidth limit,
averaging, and a signal generator if the scope has one -- stays as the scope has it.

## When it does not work

- *No address to connect to* --- **Address** in the Instrument pane is empty.
- *No scope answered at ...* --- the address is wrong, the scope is off or on another
  network, or something between the two blocks port 5555.
- *The scope stopped answering* --- it was unplugged or switched off, or another program
  sent it something that it is still busy with.
- *This was written for the DS1000Z scopes* --- something else answered. It may work, as
  far as it speaks the same commands.
