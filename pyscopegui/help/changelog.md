[&larr; Contents](manual.md)

# Changes

What each version of pyscopegui added, changed and fixed, newest first. The format is [Keep a
Changelog](https://keepachangelog.com/en/1.1.0/), and versions are numbered as [Semantic
Versioning](https://semver.org/spec/v2.0.0.html) describes. *Unreleased* is what has been done
since the last version, and comes out in the next one.

## [Unreleased]

### Added

- **Copy PNG**, beside *Export PNG* on the plot and under *File*: the same picture, on the
  clipboard.
- **Copy CSV** and **Copy CSV between cursors**, beside *Export CSV*: what it writes, headed,
  on the clipboard, a tab between the columns to paste straight into a spreadsheet.
- The Data pane's table has a right-click menu: *Copy*, *Copy without headings* to add rows
  to a sheet that already has them, and *Select all*.

### Changed

- A Rigol or Tektronix **read as it is** says so plainly: the Instrument pane's Channel box
  shows *Configured on scope* rather than empty tabs, and the channel list's Settings column
  *N/A*.
- The **Decoded buses** pane lists what was read in view on the plot, or between the two
  cursors, as the Data pane does, rather than everything held: zoom in on a moment to see what
  was read there.

### Fixed

- A **parallel bus** clocked at a megahertz could not be kept up with: its words are now put
  into transfers, and drawn as channels, about three times faster.
- What a bus read is kept for as long as its samples, as the manual says, and not only the
  last 100,000: about 1.6 s of an ADC clocked at 1 MHz. A parallel bus's words are kept as
  compactly as the samples, so ten seconds of that ADC is some 130 MB rather than over a
  gigabyte.

## [0.3.1] - 2026-11-08

### Added

- **Tools > Reset**, as in pycangui: *Reset layout* (also under *View*), *Forget remembered
  folders* for the file dialogs, and *Reset everything...*, which offers a new workspace
  rather than undoing anything in place.

- **Parallel buses**, under *Decode as*: several lines read as one word -- a mixed-signal
  scope's D0 to D15, say -- on a clock's rising or falling edges or both, or where the lines
  settle without one, with an enable to mark each transfer. A **multiplex** line can say
  which of two channels each word is from, as an AD9238 sends both its channels on one bus.
  The words can be drawn as channels on the plot, in volts across a full scale, to be
  measured, triggered on and made into maths channels; a protocol trigger can wait for words.

- **The Qt style in use** is shown greyed out at the bottom of *Tools > Settings > Theme*
  and in its tooltip, and *Help > Diagnostics* gives it with the theme -- and, for *Match
  the system*, whether the system gave light or dark.
- **Time on Event Log lines**, under *Tools > Settings*: the time of day in front of each
  line, to the second, kept when it is copied. Off to begin with, and kept with this
  computer rather than the workspace, as the theme is.
- **Python 3.15**: tested on Windows and Linux, and listed on PyPI. Windows Server 2022 is
  tested too, for Windows 10.

### Changed

- **UDP multicast is off, this computer only, or the local network**, in *Tools > Settings
  > UDP multicast*, as in pycangui: one setting for the CAN sent on and pycangui's signals
  received, in place of *Share UDP multicast on the local network*, whose choice is kept.
  *Off* sends nothing and greys *Send the frames on to pycangui*, keeping the group;
  *This computer only* also drops signals sent from another computer. A page of its own in
  the manual.

### Fixed

- **A Tektronix starts a run in a second or so** rather than fifteen: it is asked how it is
  set, ten questions to a line, and sent only what it has otherwise, rather than every
  setting one at a time with each asked back. Its waveforms are described in a line each
  too.
- **A Tektronix changed while it waits for a sweep** -- Auto to Normal, say -- is no longer
  closed as not answering: the sweep waited for is given up first, since the scope does not
  say it has done a setting until a sweep it is taking is in.
- **A Tektronix read as it is, running at the bench,** is stopped while its channels are
  read, so that they are all of the one sweep, and set running again.
- **A Rigol or a Tektronix just talked to is not asked who it is**: looking at how it is
  set, reading its settings and writing them count as hearing from it, so the check that it
  is still there waits until it has been quiet a while.

## [0.3.0] - 2026-11-01

### Added

- **A Rigol read as it is**, set up and triggered at the bench: *Control > As it is, set up
  on the scope* changes nothing on it, and **Read** takes what it shows -- its screen, or
  every point in its memory -- of the channels it is showing, in the units it has for each,
  as a Tektronix can be read. A running scope is stopped only while its memory is read, and
  set running again.
- **pycangui signals**, under *Add instrument*: the signals pycangui decodes from a CAN bus
  and sends over UDP multicast, a channel each, in their own units, each value placed at
  the time of its frame on the clock the instruments are lined up by. A step at each new
  value, read out at a steady rate, so a signal can be triggered on, measured and exported
  like any channel (#1).
- **A second voltage axis, Y2**, on the right of the plot, with a scale of its own: a
  channel in amps, or a maths channel in a unit of its own, goes on it by itself, and
  **Plot on Y2** in the channel list puts any channel there, kept with the workspace. **Y**
  fits or ranges each axis to its own channels; `axis("CH2", 2)` does the same from the
  Python Console. Built so that more axes can follow (#8).
- **`pyscopegui --run script.py`** runs a script as pyscopegui starts, with what the Python
  Console has, then closes with the script's exit code: 0, `sys.exit(n)`'s `n`, or 1 for an
  exception. `--stay` leaves the window open afterwards, and `--workspace NAME` opens a
  workspace for that run only. The same options as pycangui's.
- **A channel can be given a name of its own**: right-click it in the list for
  **Rename...**. It is shown with which channel it is, *5V rail (CH1)*, on the plot, the
  cursors, Measurements, Data, the trigger's Source and the headings of an export, and is
  kept with the workspace and in a saved capture. `rename("CH1", "5V rail")` does the same
  from the Python Console or a script.
- **Double-click a capture to open it**: captures are saved as `.pyscp`, a name of
  pyscopegui's own, and the installer offers to make pyscopegui what opens them, as *Tools >
  Settings > Open captures with pyscopegui* does however it was installed. On Windows it is
  offered under *Open with* for a `.npz`, as captures were saved before, which still open. A
  capture double-clicked while pyscopegui is open goes to that window. It opens showing
  what was shown: every channel is saved, and each is ticked, or not, and on Y1 or Y2, as
  it was on the plot.

- **Whether a scope has the pane's settings**, for a Rigol or a Tektronix set up from here:
  opened, it is asked how it is set, and what it has otherwise is amber in the pane, with
  what it has in the tip. **Read** takes the scope's settings into the pane and **Write**
  sends it the pane's. A setting changed in the pane is amber until the scope has it --
  asked back once it is sent -- and one it would not take is said in the Event Log. One
  that took over a second is said too, and Help > Diagnostics has the last and the slowest.
  A PicoScope's change made as it runs is amber until it is taken up (#6).

### Changed

- **Every run sends a Rigol or a Tektronix the whole of the pane's setup**, rather than
  only what changed in the pane since the last: a knob turned at the bench while it was
  stopped is set back.
- **A Tektronix read as it is** reads the channels its screen shows, switched on and off at
  the scope: **Enabled** is not asked, and a channel switched on there is in the next reading.
- **Y** at **Auto** fits the axis again only when a trace goes past it, or comes to take
  less than half of it, rather than every time the plot is drawn: a steady signal leaves
  the axis still, and the plot is drawn in about a tenth less time.
- **Y** held at **Manual** goes back to **Auto** when another instrument is added, and the
  next time pyscopegui starts, so that new signals are fitted rather than held where the
  last ones were zoomed to. From one run to the next it stays where it was put, and Auto
  and Range are remembered as before.

- **A pulse width's times are a Min and a Max**: *Longer than* uses the Min, *Shorter
  than* the Max, and *Between* both, each greyed out where it is not used, rather than one
  box whose meaning changed with the choice. A *Shorter than* saved before keeps the Max it
  had, which may need setting again.
- **The Instrument pane takes less room**: what goes together shares a line -- how a
  scope is read and its sample rate or block length, its time a division and how it
  acquires, a signal generator's wave and frequency, peak to peak (*Pk-pk*) and offset,
  and start and cycles, and a Tektronix's port and speed, and parity and end of line.
- **Trigger Nth time** is what the count of times is called in the trigger's details,
  rather than *Trigger on time*.

### Fixed

- **A Rigol waits for a logic pattern that has to be held**: the scope says its Duration
  trigger back as *DUR*, which was taken to mean it did not have the option, and the run
  stopped with that said.

## [0.2.0] - 2026-10-25

### Added

- **Trigger on the Nth time** a trigger is met, and **a delay** after it, for every trigger
  type, in its details: counted from the first time after the holdoff, so that each burst
  triggers on its Nth edge, pulse or frame. The toolbar says so: *3rd time, +1 ms*.
- **A Rigol waits for a logic pattern that has to be held** itself, as its own Duration
  trigger, one of its advanced triggers: for 8 ns to 10 s, triggering as the pattern ends.
- **Export CSV between cursors...**, with two cursors: every sample between them, wherever
  the plot has been moved since. On the export button's arrow and under *File*.
- **A progress bar for a large save or export**, with **Cancel**: the file is written while
  the instruments go on running, and a cancelled one leaves nothing part-written behind.
- **A PicoScope that is unplugged is noticed**: asked whether it is still there when it has
  been quiet a while -- never while samples are arriving -- and closed, with the Event Log
  saying so, rather than seeming to take settings it never gets.
- **A Rigol or Tektronix switched off or unplugged while stopped is noticed** too: asked
  who it is every 5 seconds while it is stopped, and closed if it does not answer. Running,
  it is never asked: every look at its trigger or its sweep already says it is there.
- **A PicoScope 2202 to 2205A triggers on more than an edge itself**, reading blocks: **Either**
  edge, **Window**, **Pulse width** and a **Logic pattern** of A and B, on the models with
  Pico's advanced trigger (2202, 2204, 2204A, 2205, 2205A).
- **The signal generator on the scope's trigger**, on a PicoScope 2206 to 2408B or MSO: **Start** at
  once, or on the scope's trigger, with a number of **Cycles** each time, or running on from
  it.
- **More maths**: of one channel, **−A**, **|A|**, **A²**, **√A**, **k × A + c** in a unit of
  its own, **dA/dt**, **∫A dt** and an **average** over a time, beside the four of two
  channels. Every maths channel is named *Math: ...*; right-click below the channels for one.
- The **Decoded buses** pane lists each bus with a tick to pause it, and **Add...** and
  **Remove** buttons; it opens by itself when a channel is decoded.
- The **Measurements** pane is in the default arrangement, beside the Event Log, and the
  other panes open floating the first time, in front of the window.
- **A Rigol triggers on more than an edge itself**: **Either** edge, **Pulse width**,
  **Runt**, **Window**, **Timeout** and **Logic pattern**, with a holdoff, as the scope's
  own trigger types. A trigger level past what the scope takes is the nearest it does.
- **A PicoScope 2206 to 2408B or MSO triggers on more than an edge itself**, reading blocks: **Either**
  edge, **Window**, **Pulse width**, **Runt** and **Logic pattern**, in its own hardware at
  its full rate. What a scope that sends sweeps cannot wait for itself is greyed out.
- **One instrument leading the others**: **Lead** on the trigger toolbar, with two or more
  open. Its trigger holds the plot, and the others are shown at the same moment by the
  computer's clock, to a millisecond or a few; **Single** stops them all once it has its
  capture.
- **Triggers beyond an edge**: a *Type* on the trigger toolbar -- **Window**, **Pulse width**,
  **Runt**, **Timeout** and **Logic pattern** -- with an edge **Either** way, a holdoff for
  every type, and the details under the button beside it. Found in what is streamed.
- **Protocol triggers**: wait for a frame, burst or transfer read off a decoded bus -- by
  its ID or address, bytes it contains, its type, or a problem with it.
- **Decoding buses**: right-click a channel and choose *Decode as* -- **CAN** (from a logic
  input, CAN_H, CAN_L, or a maths channel of the two), a **UART** serial line, **SPI** or
  **I²C** -- and the **Decoded buses** pane lists everything read off them, problems and all.
  The demo has a CAN bus to try it on.
- Decoded CAN frames **sent on to pycangui** by UDP multicast, to the group it offers as
  *pyscopegui*, 239.74.163.10. They stay on this computer unless *Tools > Settings > Share
  UDP multicast on the local network* is ticked. python-can is now a dependency.
- **Tektronix over USB**, for the TDS1000B, TDS2000B and TDS2000C: **Connection** is
  Serial port or USB, through a VISA library, with the same commands either way. The
  VISA link is now shared with the Rigol's.
- **Data** pane: the samples themselves, a row for each, for one instrument -- between the
  cursors or what is in view, the cursors' rows tinted, and Ctrl+C copies rows for a spreadsheet.
- *Tools > Settings > Column widths*, as in pycangui: **Automatic**, every column as wide
  as what is in it, or **Manual**, fitted until dragged and the dragged width remembered.
- **Current probes** on every scope: a **Sensitivity** in volts an amp, and the channel in
  amps -- its scale, offset, trigger level and samples. And more voltage probes: 1x, 10x,
  20x, 50x, 100x, 500x and 1000x, for differential probes among others.
- **Maths channels**: two channels of one instrument added, taken away, multiplied or
  divided, sample by sample, and kept as a channel like any other.
- **Measurements** pane: each channel's min, max, peak to peak, mean, RMS, frequency, period
  and duty cycle, between the cursors or over what is in view.
- *File > Run script...* and *File > Recent scripts*, the last five run in the workspace.
- **Reference traces**: a capture opened from a file drawn faded, behind the instruments'
  own, to compare them with.
- **Save capture** and **Open capture**, under *File*: everything held, kept in a file to
  open again exactly as it was; and a CSV -- Export CSV's, or another's, with lines to skip
  and columns to choose -- opened beside the instruments as one of them.
- **Python Console**, under *View*: a Python prompt with commands to drive the scopes --
  `add`, `open`, `set`, `run`, `single`, `data`, `export_csv` and the rest -- and *Run
  script...* for a file of them.
- **PicoScope 2206 to 2408B, and MSOs**: the 2000 Series scopes beyond the 2205A --
  the 2206 to 2208 in their A and B forms, the four-channel 2405A to 2408B, and the mixed-signal ones with
  their sixteen logic inputs -- streamed at up to 31.25 MS/s, or read in blocks of up to a
  million samples -- with an **offset** on each channel where the scope has one.
- **Channel colours** as each scope draws its channels, kept by a channel whatever else is
  open, and chosen by right-clicking it in the channel list.
- **Instrument traffic**, under *View*: every command sent to an instrument, every answer
  and how long it took, and every call into a maker's library, kept only while the pane is
  open.
- **Workspaces**, under *File > Workspace*: one for each bench or setup, each with its own
  instruments, settings and panes. There is one called `default`, and what was kept before
  is moved into it. *File > Workspace > Open folder* takes the place of *Tools > Open
  settings folder*.
- **Export CSV**: every sample of what a plot shows, with time as the plot's axis has it,
  and a file for each instrument.
- **Cursors** on the plot, one or two: the channel list reads every channel at each, to the
  nearest sample, and two give the time and the change between them.
- **Export PNG**, under the arrow on the plot's Export button and under *File*: a picture
  of the plot and its channel list.
- **Read**, for a Tektronix read as it is: one reading of what its screen shows. The
  trigger, **Single** and **Normal** are greyed out for it, since its trigger is its own.
- *Tools > Settings > Add shortcut to desktop* on Windows; both shortcuts for a pip
  installation too.
- Rigol over **USB**, through an installed VISA library, as well as over the network.
- Rigol: a **20 MHz limit** for each channel, and the scope's **acquisition mode** --
  normal, high resolution or peak detect.
- **Tektronix TDS200, TDS1000, TDS2000 and TPS2000** scopes, over a serial port: a sweep at
  a time, or what is on the scope's screen read off with nothing on it changed. A set-up is
  sent a setting at a time, with how far it has got shown, and opening waits for a scope
  that is still busy with one. Read as it is, the plot shows the whole of what is read.

### Changed

- **Help > Diagnostics** opens in a window of its own, with **Refresh**, **Copy** and
  **Save...**, rather than in the Event Log, and says more: what each instrument says of
  itself -- a PicoScope's library, driver and how its stream is keeping up, how a Rigol or a
  Tektronix is reached -- the trigger and who finds it, memory, what is decoded and sent on,
  panes put away, the last 20 warnings and errors, and the threads running.
- **A more compact Instrument pane**: what has no say is not shown until it has -- a block's
  length while streaming, a generator's details while it is off -- in place of being greyed
  out; a logic port's threshold is on its line, a channel's offset beside its scale, its
  20 MHz limit beside its coupling and a current probe's volts an amp beside the probe,
  its **Enabled** beside the channels' tabs, and **Open** on a line of its own under the
  instruments' tabs, which keep their line to themselves.
- The **Instrument traffic** pane comes back as it was left, open or put away, rather than put
  away every time pyscopegui starts. It still records only while it is on screen.
- **Auto Y** is now a choice of three, as Time is: **Auto**, **Range** -- the axis the
  channels are set to -- and **Manual**, which holds the axis where it is. Zooming or dragging
  the voltage axis chooses Manual. Auto Y unticked before comes back as Range.
- A run keeps no more history than a share of the memory that is free when it starts --
  half, unless *Tools > Settings > Memory* says a quarter, three quarters or nine tenths:
  where the history chosen would take more, it keeps what fits and the Event Log says how
  much. The status bar says what the histories take and what is free, and pressed, offers
  the same choice.
- A PicoScope's channels are held as the scope sends them, two bytes a sample rather than
  four, and turned into volts only where they are looked at: twice the history in the same
  memory, and no time spent on every sample as it arrives. A mixed-signal scope's logic
  inputs are held as the scope sends them too, eight to a byte, and read out only where they
  are looked at: all sixteen take two bytes a sample rather than sixteen.
- The last instrument can be taken out of the Instrument pane too: the pane then says there
  is none, and stays empty the next time until one is added.
- **Add instrument** takes the place of the list of instruments on the toolbar. Each
  instrument added has a tab in the Instrument pane, where **Open** now is, under
  **Connection**; the cross on a tab removes it.
- **Two instruments of the same kind** can be in use at once, each with its own settings.
- The channel list's **Value** column, which said what each channel read now, is gone: with
  no cursor the list has names and settings only, and the plot has the room.
- The launchers no longer ask about a Start menu entry: the first start says in the Event
  Log where a shortcut is made.
- The Rigol is listed as **Rigol DS1000Z series**: how it is connected is a setting, not
  part of its name.
- The PicoScopes are listed by the models they cover, as the scope itself says:
  **PicoScope 2202 to 2205A**, and **PicoScope 2206 to 2408B, and MSOs**. Where there is
  room only for a word -- a tab, a channel's name, an export's file -- an instrument is
  called by the model it says it is once opened, *2206B* or *DS1054Z*, remembered for the
  next start, and by its kind until then, *ps2000* or *ps2000a*; the tab's or the channel's
  tip says which in full.
- **Measurements** are exact once the instrument stops, and are worked out again only when
  the stretch measured moves -- held on a trigger, once a trigger; while it runs, a long
  stretch is measured from a share of it and said to be close, so that measuring a span of seconds at megasamples a second takes no longer than
  a short one. Edges are found only where the signal gets clear of the band, and a long
  stretch is measured a piece at a time, in no more memory than a piece.
- **A window that falls behind a fast PicoScope stays a second behind at most**: what it has
  not yet taken in is left out and shown as a gap, and the Event Log says so, rather than its
  falling further behind and its memory growing. A PicoScope 2206 to 2408B or MSO has room in
  its driver for a second between two reads, not a quarter, for a computer that is busy for a
  moment.
- A run may take **three quarters** of the memory that is free when it starts, unless
  *Tools > Settings > Memory* says otherwise, rather than half.
- A **200x** voltage probe, as some differential probes are: a Rigol is told it, and for any
  other scope pyscopegui does the multiplying.
- A PicoScope 2206 to 2408B or MSO streams at **15.625 and 25 MS/s** too: a sample every 64 ns, and 40 ns.
- **Captures are saved as they are held**: a PicoScope's channels as the scope's own counts,
  a third smaller than volts, and every logic input a bit a sample, a tenth the size or less.
  A mixed-signal scope's inputs open again packed in their ports. A capture saved before
  still opens; one from a newer pyscopegui says so.
- **A third less memory for the same history**, or half as much history again in the same:
  each channel's samples are held round in a ring, the newest over the oldest, where before
  half as much again was kept spare to copy them back into. Taking them in is quicker too.
- **A long span is drawn in a fraction of the time**: the lowest and highest of every 256
  samples are kept as they arrive, and a span of seconds at megasamples a second is drawn
  from those -- 10 s at 10 MS/s in a twentieth of the time it took -- looking just the same.
- **Triggers are found in a fraction of the time**: only where the signal gets clear of
  the margin either side of the level is anything worked out, and a PicoScope's samples are
  compared as the scope sent them, the level turned into the scope's own count once. Every
  trigger type is found exactly where it was before.

### Fixed

- The instruments' tabs are seen again on starting: they were restored but drawn no height,
  so only adding another instrument brought them back. *Help > Diagnostics* names every
  instrument in the pane, those whose tab has not been chosen since starting too.
- A Rigol waiting for a held logic pattern is told how long it is held: its Duration trigger
  kept its own 1 µs, whatever was asked for.
- **Additional Channels and Plot** brings back a plot that was put away before it opens a
  new one: each one closed and asked for again was one more, out of sight, until something
  showed them all at once.
- In **Normal**, a span as long as the history -- 10 s of a 1 kHz signal, say -- drew once
  and then went blank: the trigger it needed, half the span back, had been forgotten.
- A PicoScope 2206 to 2408B or MSO had its samples checked against the rate asked for, not the
  nearest one the scope gave, so a rate it rounds -- 20 MS/s, say -- could be said to be
  arriving slowly.
- The launchers notice a `.venv` whose Python has been uninstalled or replaced, and offer
  to make it again: before, Windows opened nothing and Linux took it for a first run. On
  Windows, `.venv` is made from Python 3.15, 3.14, 3.13 or 3.12, newest first, through the
  `py` launcher when one is installed, and a setup that fails no longer leaves a half-made
  `.venv` behind. CI tests on Windows with Python 3.15 too.
- With **Y** at **Range**, the voltage axis follows a channel's offset: it shows what the
  scope is measuring, -6 V to 4 V for a 1 V offset on ±5 V, and not the range around nought.
- PicoScope 2202 to 2205A: samples the driver handed over in more than one batch at once
  were partly dropped, without a word, and the time of everything after them was out;
  and samples the driver lost were drawn as a gap the Event Log said nothing about.
- *Help > Licences* said the third-party file held the full text of every licence. It is a
  list of the packages a build was made with, and now says so.

## [0.1.0] - 2026-10-11

The first version.

### Added

- **Channels and Plot**: analog channels on one plot and logic channels in lanes under it,
  on one time axis. Follow, All or Manual for time; Auto Y, or the axis as the channels'
  range.
- Deep captures are drawn as a lowest and a highest per column of the screen, so a spike
  narrower than a pixel is still drawn.
- **Open** and **Close** for the instrument, and a scope's own **Stop**, **Single**,
  **Normal** and **Auto**.
- A **trigger** on any channel -- rising or falling, at a level, anywhere in the plot --
  found in the samples as they arrive, so it is the same for every instrument.
- **Instrument** pane: the settings of whichever instrument is chosen, built from what its
  back end says it has.
- **PicoScope 2000 series**, the scopes on Pico's `ps2000` driver: both channels
  streamed at up to 1 MS/s, with scale, probe, coupling and sample rate, either channel switched
  off, and the scope's signal generator.
- PicoScope **blocks**: short captures at up to 100 MS/s around the scope's own trigger, for
  what is too fast to stream.
- The PicoScope's settings follow the model that is plugged in: the ranges a 2204A or 2205A
  has, and no signal generator for a 2202.
- **Rigol DS1000Z series**, over the network: the four analog channels,
  a sweep at a time around the scope's own trigger, from its screen or its whole memory.
- **Several instruments open at once**, on one time axis: each with a trigger of its own,
  and drawn around it.
- A PicoScope channel is set by **volts a division and probe**, as a bench scope is, and
  the scope is put on the range that holds it.
- How each channel is set is read beside it in the plot's channel list, and channels are
  set one at a time in the Instrument pane: click one in the list to bring it up. With
  several instruments in use the pane has a tab for each.
- *Tools > Settings > History*: how much of each channel is kept, from a second to ten
  minutes.
- **Demo signals**: two analog and four digital channels, with no hardware.
- Panes that dock, float, detach into windows of their own and pin on top, with the
  arrangement remembered, and more than one plot at once.
- **Event Log**, with warnings and errors in their own colours.
- Light and dark themes, or whichever the system is set to.
- **Help**: this manual, a diagnostics report, a check for updates, the licences and About.
- Installing with pip, from a source folder with a launcher that sets itself up, or with a
  Windows installer.

[Unreleased]: https://github.com/davhodg/pyscopegui/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/davhodg/pyscopegui/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/davhodg/pyscopegui/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/davhodg/pyscopegui/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/davhodg/pyscopegui/releases/tag/v0.1.0
