<p align="center">
  <img src="https://raw.githubusercontent.com/davhodg/pyscopegui/master/pyscopegui/resources/pyscopegui.png" alt="pyscopegui icon: an analog trace above two logic traces on one time axis" width="128">
</p>

# pyscopegui

[![CI](https://github.com/davhodg/pyscopegui/actions/workflows/ci.yml/badge.svg)](https://github.com/davhodg/pyscopegui/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/davhodg/pyscopegui?include_prereleases)](https://github.com/davhodg/pyscopegui/releases)
[![PyPI](https://img.shields.io/pypi/v/pyscopegui)](https://pypi.org/project/pyscopegui/)
![python](https://img.shields.io/badge/python-3.12+-blue)
![platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey)
![license](https://img.shields.io/badge/license-Apache--2.0-green)

Oscilloscopes and logic analysers in one view: analog and logic channels from separate instruments, on one time axis.

![pyscopegui with a Rigol DS1054Z and a PicoScope 2204A open together: the same 1 kHz sine on a channel of each, drawn on one time axis around each scope's own trigger, with the Instrument pane, the channel list and the Event Log](https://raw.githubusercontent.com/davhodg/pyscopegui/master/pyscopegui/help/main-window.png)

**This is an early version.**

## Install and run

To install it:

```
pip install pyscopegui
```

To run it:

```
pyscopegui
```

To update it:

```
pip install --upgrade pyscopegui
```

Python 3.12 or newer, on Windows or Linux. `python -m pyscopegui` starts it too.

On Linux, Qt needs a system library to draw the window, and Debian, Ubuntu, Linux Mint and the like often leave it out:

```
sudo apt install libxcb-cursor0
```

## What it does

- **Channels and Plot**: analog channels on one plot and digital channels in lanes under it, on the same time axis. Drag or zoom either and both move.
- **Several instruments at once**, and two of the same kind: **Add instrument** puts each in the Instrument pane with a tab of its own, where it is opened and set up. Each has its own trigger, and nought on the time axis is each one's trigger, so two instruments triggered by the same edge line up.
- **Workspaces**: one for each bench or setup -- the scopes at home, the one at work -- each with its own instruments, settings and panes, chosen under *File > Workspace*.
- **The same settings on every scope**: volts a division, probe and coupling, whichever maker's it is.
- **Open and Close**, and a scope's own **Stop, Single, Normal and Auto**, with a trigger on any channel: rising or falling, at a level, placed anywhere in the plot.
- **Export to CSV**: every sample of what the plot shows, with time measured from the trigger.
- **Deep captures stay quick**: what is drawn is cut down to a lowest and a highest per column of the screen, so a spike narrower than a pixel is still drawn.
- **Panes** that dock, float, detach into windows of their own and pin on top, with the arrangement remembered.
- **Light and dark** themes, or whichever the system is set to.

The [manual](https://github.com/davhodg/pyscopegui/blob/master/pyscopegui/help/manual.md) covers each of these, and is also under **Help > Documentation** in the application.

## Instruments

- **Demo signals**: two analog and four digital channels, with no hardware.
- **PicoScope 2000 series** on Pico's `ps2000` driver (2202, 2203, 2204, 2204A, 2205, 2205A): both channels, streamed continuously at up to 1 MS/s, or read in short blocks at up to 100 MS/s around the scope's own trigger, and the scope's signal generator. Pico's library is not included: install the PicoSDK from [picotech.com/downloads](https://www.picotech.com/downloads).
- **Rigol DS1000Z series** (DS1054Z, DS1074Z, DS1104Z, and the Plus, -S and MSO models), over the network or USB: the four analog channels, a sweep at a time around the scope's own trigger, read from its screen or its whole memory. Over the network nothing of Rigol's needs installing; USB needs a VISA library, which Rigol's own software installs.
- **Tektronix TDS/TPS 2000 series** (TDS200, TDS1000, TDS2000 and TPS2000), over a serial port: two or four channels, a sweep at a time around the scope's own trigger, or what is on its screen read off with nothing on the scope changed. For taking a capture off the scope: a serial port is too slow to watch one.

## More

- [Source, issues and releases](https://github.com/davhodg/pyscopegui)
- [Standalone Windows installer](https://github.com/davhodg/pyscopegui/releases)
- [Questions and ideas](https://github.com/davhodg/pyscopegui/discussions)
- [Manual](https://github.com/davhodg/pyscopegui/blob/master/pyscopegui/help/manual.md)
- [Changelog](https://github.com/davhodg/pyscopegui/blob/master/pyscopegui/help/changelog.md)

## Safety notice and licence

pyscopegui shows what instruments connected to real equipment measure. A scope's ground clip is connected to the computer's ground unless the scope or its USB connection is isolated, and clipping it to a point that is not at ground can damage the equipment, the scope and the computer. Know what you are connecting to before you connect.

pyscopegui is provided under the Apache License 2.0, without warranty of any kind.
