[&larr; Contents](manual.md)

# Channels and Plot

The list of channels and the plots are one pane, with a splitter between them: the tick that
shows a channel is in the list, so the two are always on screen together. Either side can be
dragged shut.

Analog channels share one plot. Digital channels are stacked in lanes under it, the first at
the top, **on the same time axis**: drag or zoom either plot and both move. With no digital
channel shown, the lower plot is put away.

## The channel list

A tick shows a channel and unticking hides it; which are hidden is remembered. The name is
in the colour its trace is drawn in, and **Value** is what the channel reads now, a few times
a second.

## Time

Time is counted from when the instrument was started, in seconds. It comes from the number
of samples and the rate they were taken at, not from when each block of them reached the
computer, so what is drawn does not carry the jitter of the USB or the network.

**Time** chooses which stretch is in view:

- **Follow** keeps the newest samples in view, and the box beside it says how many seconds.
  Its arrows go 1, 2, 5, 10, 20, 50, as a scope's timebase does; any number can be typed.
- **All** shows everything that is held, and keeps it all in view as more arrives.
- **Manual** stays where you put it. Dragging or zooming a plot chooses it for you.

Wheel to zoom, drag to move, and right-click a plot for the rest.

## With a trigger

With a [trigger](instruments.md) chosen, time is measured **from the trigger**: nought is the
trigger, and it stays in the same place on the screen while each new one is drawn over the
last, so a repeating signal stands still. A dashed line down the plots marks it, and a dashed
line across the analog plot marks the level.

The box beside **Time** is then the stretch drawn around each trigger, and **Position** in
the trigger toolbar says how much of it is before the trigger. Each plot has its own, so one
plot can show a whole burst and another the few milliseconds around the same edge.

Beside the time controls the plot says what it is doing: *Triggered*; *Waiting for trigger*,
with what was last drawn left on screen; *Auto*, when no trigger has come and it is showing
what there is; or *Stopped*.

An instrument that triggers itself sends one capture at a time, and the plot then shows the
whole of each: the box beside **Time** has no say in it.

Dragging or zooming still chooses **Manual**, and the plot stays where you put it, measured
from the trigger. Choosing a trigger, or going back to none, puts it back to **Follow**.

## Voltage

**Auto Y** fits the voltage axis to what is being measured, and is on to start with.
Unticked, the axis is the range the channels are set to, as a scope's screen is: a small
signal on a large range is then drawn small. When the channels shown are on different ranges
the axis takes the largest, since they share it.

## How much is kept

The last ten seconds of every channel, to begin with. Past that the oldest are dropped.
*Tools > Settings > History* chooses how much: from one second to ten minutes. A change
starts the instrument again.

It is all held in memory, so a long history at a high rate is a great deal of it: four bytes
a sample for an analog channel and one for a digital one, and half as much again. Ten seconds
of two channels at 1 MS/s is about 120 MB; ten minutes of them is about 7 GB. The
[Event Log](event-log.md) says how much the history chosen comes to each time the instrument
is run, and if there is not room for it the instrument is not started.

**Clear history** throws away what is held and counts time from zero again. The status bar
says how many seconds are held.

Starting a run -- from **Stop** to one of the other three, or a change to what the samples
are -- starts from an empty plot.

## Many samples in few pixels

A plot a thousand pixels wide cannot show a million samples, so each column of the screen is
drawn as a line from the lowest sample it holds to the highest. A spike narrower than a
column is therefore still drawn, where taking every thousandth sample would lose it. Zoom in
far enough and each sample is drawn as it is.

A signal much faster than the stretch of time in view fills in as a solid band between its
lowest and highest levels. That is the signal, not a fault: zoom in to see its shape.

## Gaps

Samples an instrument could not deliver in time are drawn as a gap, and the
[Event Log](event-log.md) says how many. The samples after a gap keep their place in time.
