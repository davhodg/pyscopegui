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
  there is one. It is written to a tenth of the time between two samples, so every sample
  has a time of its own however long the run has been going.
- Each channel is a column, headed with its name and what it is measured in. A logic
  channel is 0 or 1. A gap is `nan`.
- With several instruments open there is a file for each, named for it --
  `capture-Pico.csv`, `capture-Rigol.csv` -- since two instruments' samples are not taken at
  the same moments and cannot share rows.

To write everything that is held and not only what is in view, choose **All** beside
**Time** first. With two [cursors](#cursors), **Export CSV between cursors...** -- on the
button's arrow, and under *File* -- writes only what is between them, wherever the plot has
been moved since. The [Event Log](event-log.md) says how many samples went where.

A large file is written while the instruments go on running, with a bar showing how far it
has got and **Cancel**, which leaves no part-written file behind. Saving a capture is the
same.

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

### Names

**Right-click a channel** in the list and choose **Rename...** to give it a name of its own:
what it is measuring, *5V rail* or *Clock*. It is shown with which channel it is, in
brackets -- *5V rail (CH1)*, or *5V rail (DS1054Z CH1)* with more than one instrument on the
plot -- so the input it is on is never lost. The name is used wherever the channel is: the
plot's list, the cursors, *Measurements*, *Data*, the trigger's **Source**, and the headings
of an [export](#exporting-to-csv).

Leave the name empty to call the channel what its instrument calls it again. Names are kept
with the [workspace](files.md), for each instrument's channels, and in a
[saved capture](captures.md), which opens with them.

### Colours

Each channel is drawn in **the colour its scope draws it in**, so that the plot and the
scope's own screen agree:

| Scope | Channels |
|-------|----------|
| Rigol DS1000Z | CH1 yellow, CH2 cyan, CH3 magenta, CH4 blue |
| Tektronix TDS and TPS 2000 | CH1 yellow, CH2 blue, CH3 magenta, CH4 green |
| PicoScope 2000 series | A blue, B red, C green, D yellow, as Pico's PicoScope software has them |

A channel whose instrument has no colour for it -- the demo's, a logic input -- takes one by
where it is in its own instrument. Either way a channel keeps its colour whatever else is
opened beside it.

**Right-click a channel** in the list to choose another colour: for two scopes of the same
model side by side, say, whose CH1s would otherwise both be yellow. The colour is the same on
every plot and is kept in the [workspace](files.md); *Its own colour*, on the same menu, goes
back to the scope's.

The cursors are orange and violet, which none of the scopes uses for a channel.

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

## Maths channels

**Right-click a channel** in the list and choose **Maths channel...** for a channel worked out
from that one -- and another, where it takes two. Right-click below the channels, on none of
them, and it starts from the instrument's first two analog channels instead, either of which
can be changed in the dialog. Every maths channel's name starts with *Math*: *Math: CH1 −
CH2*.

| Operation | What it is |
|-----------|------------|
| A + B, A − B, A × B, A ÷ B | Two channels, sample by sample. CH1 − CH2 is the voltage across something neither end of which is at ground; CH1 × CH2, with a current probe on one, is power |
| −A | Turned upside down |
| \|A\| | Its size, whichever side of nought |
| A², √A | Squared, or square-rooted: √ of less than nought is a gap |
| k × A + c | Multiplied and offset, and measured in a unit of its own if one is given: a shunt's volts as amps, say |
| dA/dt | How fast it is changing, per second |
| ∫A dt | Added up over time since the run began: charge from a current, say |
| Average | Each sample the mean of a time before it: noise smoothed away |

The rate of change, the integral and the average carry on from one block of samples to the
next, and start afresh at a new run, at each sweep from a scope that sends them, and after a
gap. An average is over a million samples at most.

A maths channel is a channel of its instrument like any other: drawn, read by the cursors,
measured, exported, saved in a capture, and given to the [Python Console](console.md) --
where `maths("CH1", "-", "CH2")` makes one. It is worked out as samples arrive, and from
what is already held as soon as it is made. *Remove this maths channel*, on the same menu,
takes it away. The maths channels of each instrument are kept with the
[workspace](files.md).

Both channels have to be one instrument's and analog: two instruments' samples are not taken
at the same moments, and a logic level is not a number to add. Dividing by nought is a gap.
What it is measured in follows from what it is worked out from: volts plus volts is volts,
volts times volts is V², volts over volts is a plain number, a rate of change is V/s and an
integral V·s.

## Measurements

The **Measurements** pane, from the **View** menu, measures every channel shown on the first
plot: between its two [cursors](#cursors) when there are two, and over what is in view when
there are fewer. The line above the table says which, and how long a stretch that is. The
numbers are measured again a few times a second, and as soon as a cursor is dragged.

| Column | What it is |
|--------|------------|
| Min, Max | The lowest and the highest sample |
| Peak to peak | Max less min |
| Mean | The average: the steady level the signal sits on |
| RMS | The root mean square: for a sine, its peak over the square root of two |
| Frequency, Period | How often it repeats, and how long a repeat is |
| Duty | How much of each repeat it is high |

Frequency is found where the signal rises through the middle of its range. It has to get
clear of a band either side of the middle first, so that noise on a slow edge is not counted
as many edges, and it needs two rising edges at least: with fewer, a dash. For a frequency
that reads right, have several repeats between the cursors, or in view.

A logic channel is 0 or 1, so only its frequency, period and duty cycle are said. Gaps --
samples that were lost -- are left out. In the [Python Console](console.md), `measure()`
gives the same numbers to a script.

Once the instrument has stopped, every number is exact: every sample in the stretch is
measured, once, and the numbers stand until the stretch or what is held changes. While it
runs, a long stretch -- more than 65,536 samples -- is measured from a share of it, so that
measuring takes the same short time however long the stretch, and the line above the table
says *close while it runs*:

- Mean and RMS are of samples spread evenly over the stretch.
- Min and max are the plot's own lowest and highest, where it is showing the same stretch, so
  a spike narrower than the spacing is still caught.
- Frequency, period and duty are of the newest 65,536 samples, or of the spread for a signal
  too slow to rise twice in those.

A channel is measured again only when the stretch has moved: held on a trigger, once for each
trigger shown, and when stopped, once. Samples once held never change, so what arrives after
the stretch changes nothing in it. It is looked at a few times a second, and less often where
measuring takes long, so that it never takes more than a fifth of the time.

## Data

The **Data** pane, from the **View** menu, is the samples themselves, a row for each: the
sample's number, its time on the plot's axis, and what each channel shown read. It is the same
stretch the Measurements pane measures -- between the two [cursors](#cursors) when there are
two, and what is in view when there are fewer -- and the line above the table says which, how
long, and how many samples. The rows at the cursors are tinted their colours.

It is one instrument at a time, chosen above the table: one instrument's channels are read
together, so each row is one moment, where two instruments' samples are taken at moments of
their own. A gap -- a sample that was lost -- is an empty cell.

Select rows and press **Ctrl+C** to copy them, with a heading, a tab between the columns: they
paste into a spreadsheet as they are. For a whole capture, [Export CSV](#exporting-to-csv) is
quicker. A stretch of more than ten million samples is shown as its first ten million: zoom in,
or use the cursors, to see the rest.

## Time

Time is counted from when the instrument was started, in seconds. It comes from the number
of samples and the rate they were taken at, not from when each block of them reached the
computer, so what is drawn does not carry the jitter of the USB or the network.

**Time** chooses which stretch is in view:

- **Follow** keeps the newest samples in view, and the box beside it says how many seconds.
  Its arrows go 1, 2, 5, 10, 20, 50, as a scope's timebase does; any number can be typed.
- **All** shows everything that is held, and keeps it all in view as more arrives. With
  several instruments on the plot that is all of each: the whole of a scope's capture, and
  as much of a stream as is held.
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

**Y** says what the voltage axis shows, as **Time** does for the time axis:

| Y | The axis |
|---|----------|
| **Auto** | Fitted to what is being measured. What it is to start with |
| **Range** | The range the channels are set to, as a scope's screen is: a small signal on a large range is then drawn small |
| **Manual** | Held where it is, until you move it |

Choosing **Manual** keeps the axis exactly as it was. Zooming the plot with the wheel, or
dragging the voltage axis, chooses Manual by itself; so does setting the axis by hand from
the plot's right-click menu, under *Y axis*, which is where to type the limits you want.
Dragging along the time axis leaves Y as it is, and zooming the voltage axis leaves Time.

Manual stays from one run to the next, so a measurement repeated after changing a setting
is drawn where you put it. It goes back to **Auto** when another instrument is added, and
the next time pyscopegui starts, so that new signals are fitted. **Auto** and **Range** are
kept as they are, from one start to the next too.

In **Range**, when the channels shown are on different ranges the axis takes in all of
them, since they share it. An offset moves a channel's range: with a 1 V offset on ±5 V,
what is read is -6 V to 4 V, and that is what the axis shows. What is read is still the
signal itself, offset and all taken off, so a cursor on a 3.5 V signal says 3.5 V.

## How much is kept

The last ten seconds of every channel, to begin with. Past that the oldest are dropped.
*Tools > Settings > History* chooses how much: from one second to ten minutes. A change
starts the instrument again.

It is all held in memory, so a long history at a high rate is a great deal of it: four bytes
a sample for an analog channel and one for a digital one. A PicoScope's channels are held as
the scope sends them, two bytes a sample, and its logic inputs eight to a byte. Ten seconds of
two channels at 1 MS/s is about 80 MB, or 40 MB from a PicoScope; ten minutes of them is
about 4.8 GB, or 2.4 GB. Each channel's samples are held round in a ring, the newest over the
oldest, so nothing is copied about as they arrive and none of the memory is spare. The [Event Log](event-log.md)
says how much the history chosen comes to each time the instrument is run.

A run takes no more than a share of the memory that is free when it starts, leaving the rest
for drawing, measuring and everything else on the computer: three quarters, to begin with,
and *Tools > Settings > Memory* chooses a quarter, a half or nine tenths instead. A change
starts the instrument again. Where the history chosen would take more, the run keeps as much
as fits and the Event Log says how much that is: "Keeping the last 2.5 s of each channel, not
10 s". History itself is left as it was, for the next run. Only where not even a tenth of a
second fits is the instrument not started. On macOS, which does not say how much is free, the
history is always what was chosen.

The right of the status bar says how much the histories take and how much is free now --
*Memory: 577 MB held, 9.4 GB free* -- and, held over, what a run started now may take.
Pressed, it is the same Memory menu.

**Clear history** throws away what is held and counts time from zero again. The status bar
says how many seconds are held.

Starting a run -- from **Stop** to one of the other three, or a change to what the samples
are -- starts from an empty plot.

## Many samples in few pixels

A plot a thousand pixels wide cannot show a million samples, so each column of the screen is
drawn as a line from the lowest sample it holds to the highest. A spike narrower than a
column is therefore still drawn, where taking every thousandth sample would lose it. Zoom in
far enough and each sample is drawn as it is.

The lowest and highest of every 256 samples are also kept as they arrive, so a span of
seconds at megasamples a second -- tens of millions of samples in view -- is drawn from those
and the few samples at each column's edges, rather than from every sample in it each time the
plot is drawn. What is drawn is the same either way.

A signal much faster than the stretch of time in view fills in as a solid band between its
lowest and highest levels. That is the signal, not a fault: zoom in to see its shape.

## Gaps

Samples an instrument could not deliver in time are drawn as a gap, and the
[Event Log](event-log.md) says how many. The samples after a gap keep their place in time.
