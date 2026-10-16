[&larr; Contents](manual.md)

# Changes

What each version of pyscopegui added, changed and fixed, newest first. The format is [Keep a
Changelog](https://keepachangelog.com/en/1.1.0/), and versions are numbered as [Semantic
Versioning](https://semver.org/spec/v2.0.0.html) describes. *Unreleased* is what has been done
since the last version, and comes out in the next one.

## [Unreleased]

### Added

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
- **PicoScope 2000 series (ps2000a)**: the newer 2000 Series scopes -- the 2206 to 2208 in
  their A and B forms, the four-channel 2405A to 2408B, and the mixed-signal ones with
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

- The **Instrument traffic** pane comes back as it was left, open or put away, rather than put
  away every time pyscopegui starts. It still records only while it is on screen.
- **Auto Y** is now a choice of three, as Time is: **Auto**, **Range** -- the axis the
  channels are set to -- and **Manual**, which holds the axis where it is. Zooming or dragging
  the voltage axis chooses Manual. Auto Y unticked before comes back as Range.
- A run keeps no more history than half the memory that is free when it starts: where the
  history chosen would take more, it keeps what fits and the Event Log says how much.
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
- The PicoScope is listed as **PicoScope 2000 series (ps2000)**, for every scope on that
  driver and not only the 2204A.

### Fixed

- With **Y** at **Range**, the voltage axis follows a channel's offset: it shows what the
  scope is measuring, -6 V to 4 V for a 1 V offset on ±5 V, and not the range around nought.
- PicoScope 2000 (ps2000): samples the driver handed over in more than one batch at once
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
- **PicoScope 2204A**, and the other scopes on Pico's `ps2000` driver: both channels
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

[Unreleased]: https://github.com/davhodg/pyscopegui/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/davhodg/pyscopegui/releases/tag/v0.1.0
