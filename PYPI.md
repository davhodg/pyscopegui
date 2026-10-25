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

For a bench with more than one scope: the channels of each, side by side on one plot. pyscopegui reads the scopes live, triggers on any channel, measures between cursors, decodes CAN, UART, SPI and I²C, and keeps the last seconds or minutes of everything to go back over, export to CSV, or save and open again later. Every scope is set up the same way -- volts a division, probe, coupling.

**Works with** the PicoScope 2000 series (including the MSO variants), the Rigol DS1000Z series and the Tektronix TDS/TPS 2000 series, and a built-in demo that needs no hardware.

![pyscopegui with a Rigol and a PicoScope open together: the same 1 kHz sine on a channel of each, drawn on one time axis around each scope's own trigger, with the Instrument pane, the channel list and the Event Log](https://raw.githubusercontent.com/davhodg/pyscopegui/master/pyscopegui/help/main-window.png)

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

Python 3.12 or newer, on Windows or Linux. `python -m pyscopegui` starts it too. On Windows there is also a [standalone installer](https://github.com/davhodg/pyscopegui/releases), which needs no Python.

On Linux, Qt needs a system library to draw the window, and Debian, Ubuntu, Linux Mint and the like often leave it out:

```
sudo apt install libxcb-cursor0
```

## What it does

- **Channels and Plot**: analog channels on one plot and digital channels in lanes under it, on the same time axis. Drag or zoom either and both move.
- **Several instruments at once**, and two of the same kind: **Add instrument** puts each in the Instrument pane with a tab of its own. Each has its own trigger, and is drawn around it; or one **leads**, and the others are shown at about the moment its trigger comes.
- **Triggers**: a scope's own **Stop, Single, Normal and Auto**, and an edge either way, a window, a pulse's width, a runt, a timeout, a logic pattern, or a frame read off a decoded bus, with a holdoff, on the Nth time and after a delay. A PicoScope reading blocks and a Rigol do most in their own hardware.
- **Cursors, Measurements and Data**: what every channel read at one or two cursors; levels, RMS, frequency and duty between them or over what is in view; and the samples themselves, a row for each.
- **Decoding buses**: **CAN**, **UART**, **SPI** and **I²C** read off analog or logic channels, listed in the **Decoded buses** pane.
- **Decoded CAN to pycangui**: frames read off a scope's channel are sent on by UDP multicast to [pycangui](https://github.com/davhodg/pycangui) -- a CAN bus tool, also on [PyPI](https://pypi.org/project/pycangui/) -- and any other program on python-can's UDP multicast bus.
- **Maths channels**: two channels added, taken away, multiplied or divided; or one inverted, squared, scaled, differentiated, integrated or averaged.
- **Probes**: 1x to 1000x, differential, or a current probe read in amps.
- **Python Console**: Python inside the window, with commands to drive the scopes and read their samples, and scripts run from a file.
- **Workspaces**: one for each bench or setup, each with its own instruments, settings and panes, chosen under *File > Workspace*.
- **Export to CSV**, all of it or between the cursors, and **save and open captures**: everything held kept in a file and opened again exactly as it was, beside the live instruments; and CSV files from other tools opened the same way.
- **Deep captures stay quick**: the last ten seconds of every channel are held, or up to ten minutes, and what is drawn is cut down to a lowest and a highest per column of the screen, so a spike narrower than a pixel is still drawn.
- **Panes** that dock, float, detach into windows of their own and pin on top, with the arrangement remembered.
- **Light and dark** themes.

The [manual](https://github.com/davhodg/pyscopegui/blob/master/pyscopegui/help/manual.md) covers each of these, and is also under **Help > Documentation** in the application.

## Instruments

- **Demo signals**: two analog and four digital channels, with no hardware.
- **PicoScope 2000 series**, both ranges of them, and the scope's signal generator. The 2202, 2203, 2204, 2204A, 2205 and 2205A: both channels, streamed continuously at up to 1 MS/s, or read in short blocks at up to 100 MS/s around the scope's own trigger. The 2206 to 2208 in their A and B forms, the four-channel 2405A to 2408B, and the MSO models: two or four channels and an MSO's sixteen logic inputs, streamed at up to 31.25 MS/s, or read in blocks of up to a million samples at the scope's full rate. Pico's library is not included: install the PicoSDK from [picotech.com/downloads](https://www.picotech.com/downloads).
- **Rigol DS1000Z series** (DS1054Z, DS1074Z, DS1104Z, and the Plus, -S and MSO models), over the network or USB: the four analog channels, a sweep at a time around the scope's own trigger, read from its screen or its whole memory, with its own trigger types. Over the network nothing of Rigol's needs installing; USB needs a VISA library, which Rigol's own software installs.
- **Tektronix TDS/TPS 2000 series** (TDS200, TDS1000, TDS2000 and TPS2000 over a serial port; the TDS1000B, TDS2000B and TDS2000C over USB): two or four channels, a sweep at a time around the scope's own trigger, or what is on its screen read off with nothing on the scope changed: suited to taking a capture off the scope rather than watching one live.

## More

- [Source, issues and releases](https://github.com/davhodg/pyscopegui)
- [Standalone Windows installer](https://github.com/davhodg/pyscopegui/releases)
- [Questions and ideas](https://github.com/davhodg/pyscopegui/discussions)
- [Manual](https://github.com/davhodg/pyscopegui/blob/master/pyscopegui/help/manual.md)
- [Changelog](https://github.com/davhodg/pyscopegui/blob/master/pyscopegui/help/changelog.md)

## Safety notice and licence

pyscopegui shows what instruments connected to real equipment measure. A scope's ground clip is connected to the computer's ground unless the scope or its USB connection is isolated, and clipping it to a point that is not at ground can damage the equipment, the scope and the computer. Know what you are connecting to before you connect.

pyscopegui is provided under the Apache License 2.0, without warranty of any kind.
