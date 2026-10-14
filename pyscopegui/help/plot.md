[&larr; Contents](manual.md)

# Channels and Plot

The list of channels and the plots are one pane, with a splitter between them: the tick that
shows a channel is in the list, so the two are always on screen together. Either side can be
dragged shut.

Analog channels share one plot. Digital channels are stacked in lanes under it, the first at
the top, **on the same time axis**: drag or zoom either plot and both move. With no digital
channel shown, the lower plot is put away.

## Exporting to CSV

**Export CSV...**, above the plot and under *File*, writes what the plot shows to a file a
spreadsheet or a script can read: every sample of the channels that are ticked, in the
stretch of time in view. Not only the few points a plot draws of them: a million samples in
view is a million rows.

- The first column is time in seconds, as the plot's axis has it: from the trigger where
  there is one.
- Each channel is a column, headed with its name and what it is measured in. A logic
  channel is 0 or 1. A gap is `nan`.
- With several instruments open there is a file for each, named for it --
  `capture-Pico.csv`, `capture-Rigol.csv` -- since two instruments' samples are not taken at
  the same moments and cannot share rows.

To write everything that is held and not only what is in view, choose **All** beside
**Time** first. The [Event Log](event-log.md) says how many samples went where.

## Saving a picture

The arrow on the **Export CSV...** button has **Export PNG...**, which is under *File* as
well. It saves a picture of the plot and its channel list as they look at that moment, at
the size they are on the screen: for a report, or to send to somebody. Pressing the button
itself still writes CSV.

## The channel list

A tick shows a channel and unticking hides it; which are hidden is remembered. The name is
in the colour its trace is drawn in. With a [cursor](#cursors) on the plot there is a
column for what each channel read there; with none there is no such column, and the list is
narrower so that the plot has the room.

**Settings** is how the channel is set up, in a line -- *1 V/div, 10x, DC* -- for every
channel of every instrument at once. Click a channel to bring its settings up in the
[Instrument pane](instruments.md), where they are changed.

## Cursors

**Cursors**, above the plot, puts one or two lines down both plots. Drag a line to a moment,
on either plot, and the channel list says what every channel read there.

| Cursors | What the channel list shows |
|---------|-----------------------------|
| None | No readings: the names and settings only, and the most room for the plot |
| 1 | **At cursor**: what each channel read at the cursor |
| 2 | **Cursor 1**, **Cursor 2**, and **2 − 1**: how far the channel moved between them |

Under the box, above the plot, is where each cursor is on the time axis, and with two, the
time between them and the frequency that is one cycle of: two cursors a cycle apart on a
1 kHz signal read *Δ 1 ms, 1 kHz*.

The channel list is fitted to its columns when the number of cursors changes: wider for the
three columns two cursors need, narrower with none. Drag the bar between the list and the
plot to set it as you like after that; a list dragged shut is left shut.

- A reading is **the nearest sample**, as it was measured, and not a value worked out
  between two samples.
- A dash is where nothing is held: before the oldest sample, after the newest, or in a gap.
- A logic channel reads 0 or 1, and has no difference.
- **A cursor stays at its time.** When the plot moves on -- following new samples, or
  dragged somewhere else -- the cursor is left where it was put, and may be out of sight.
  Choosing in the **Cursors** box again brings any that are out of sight back into view.
- With several instruments open, each channel is read at the same place on the plot's time
  axis, which is measured from each instrument's own trigger.

Cursors are most use on a plot that is holding still: stopped, or drawn around a trigger.
How many there are is remembered; where they are is not. **Export PNG** saves them and
their readings, since the picture is of the plot and its channel list together.

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

With [several instruments open](instruments.md), nought on the time axis is each one's own
trigger, and the label beside **Time** says what each is doing.

An instrument that triggers itself sends one capture at a time, and the plot then shows the
whole of each: the box beside **Time** has no say in it, and is greyed out.

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
