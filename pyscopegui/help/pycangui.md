[&larr; Contents](manual.md)

# pycangui signals

The signals [pycangui](https://github.com/davhodg/pycangui) decodes from a CAN bus with its
database, as channels here: a controller's speed, current or state beside what the scopes
measure, on the same time axis. A step at each new value, as the bus said it.

## Setting it up

**In pycangui**, turn on *Tools > Settings > Send ticked signals over UDP multicast*, and
tick **UDP out** for each signal to send, in its Signals and Plot pane.

**Here**, choose **pycangui signals** under **Add instrument**, and press **Open**. It listens
for them; there is nothing to connect to, and it does not matter which program was started
first. The [Event Log](event-log.md) says which signals pycangui is sending, and says so
again whenever one is ticked or unticked there -- a run in progress then starts again, with
the channels as they are now.

If nothing comes from pycangui for three seconds, the Event Log says so, and says when its
signals are arriving again.

## The channels

Each signal is a channel, named as pycangui names it, with its message beside it in the
channel list, and in its own unit: a speed in rpm, a temperature in °C. A channel in a unit
other than volts is drawn against [Y2](plot.md), on the right, with a scale of its own.
Where the database gives a signal's limits, **Range** sets the axis to them.

A signal arrives when its frame does, and not at any rate of its own, so it is held at its
last value and read out at the **Sample rate** chosen in the Instrument pane -- 1 kS/s to
begin with, which puts a value within a millisecond of its frame. Everything that works on
an instrument's samples works on these: the [trigger](instruments.md), cursors,
measurements, export and saving. Before a signal's first value there is nothing to show,
and the channel is a gap.

What is shown is a tenth of a second behind, so that the values of one frame, which may
arrive a little apart, are all in their places. Each value is placed at the time pycangui
read its frame, on the clock pyscopegui lines instruments up on, so a signal and a scope's
channel are where they were at the same moment -- to a millisecond or so, as two
instruments are.

## A trigger from the bus

A signal is a channel like any other, so the trigger toolbar can wait on it: a state
changing, a fault bit setting, a speed crossing a level. It sees a change at the rate the
signal arrives, which is right for *start when this happens*, and not for timing a fast
edge -- that is what the scopes are for. Lead the others with it, and every instrument is
shown at the moment it triggered.

## Where the messages go

pycangui sends them as JSON on the multicast group `239.74.163.20`, port 43114: a port of
their own, clear of the CAN frames shared on port 43113. They stay on this computer unless
*Share UDP multicast on the local network* is on in pycangui.
