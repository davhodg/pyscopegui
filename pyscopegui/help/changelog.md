[&larr; Contents](manual.md)

# Changes

What each version of pyscopegui added, changed and fixed, newest first. The format is [Keep a
Changelog](https://keepachangelog.com/en/1.1.0/), and versions are numbered as [Semantic
Versioning](https://semver.org/spec/v2.0.0.html) describes. *Unreleased* is what has been done
since the last version, and comes out in the next one.

## [Unreleased]

Nothing has been released yet. This is what the first version will have.

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
  streamed at up to 1 MS/s, with range, coupling and sample rate, either channel switched
  off, and the scope's signal generator.
- PicoScope **blocks**: short captures at up to 100 MS/s around the scope's own trigger, for
  what is too fast to stream.
- The PicoScope's settings follow the model that is plugged in: the ranges a 2204A or 2205A
  has, and no signal generator for a 2202.
- **Rigol DS1000Z series**, over the network: the four analog channels,
  a sweep at a time around the scope's own trigger, from its screen or its whole memory.
- **Several instruments open at once**, on one time axis: each with a trigger of its own,
  and drawn around it.
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
