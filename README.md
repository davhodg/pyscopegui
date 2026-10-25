<p align="center">
  <img src="pyscopegui/resources/pyscopegui.png" alt="pyscopegui icon: an analog trace above two logic traces on one time axis" width="128">
</p>

# pyscopegui

[![CI](https://github.com/davhodg/pyscopegui/actions/workflows/ci.yml/badge.svg)](https://github.com/davhodg/pyscopegui/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/davhodg/pyscopegui?include_prereleases)](https://github.com/davhodg/pyscopegui/releases)
[![PyPI](https://img.shields.io/pypi/v/pyscopegui)](https://pypi.org/project/pyscopegui/)
![python](https://img.shields.io/badge/python-3.12+-blue)
![platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey)
![license](https://img.shields.io/badge/license-Apache--2.0-green)

Oscilloscopes and logic analysers in one view: analog and logic channels from separate instruments, on one time axis. Apache-2.0.

![pyscopegui with a Rigol and a PicoScope open together: the same 1 kHz sine on a channel of each, drawn on one time axis around each scope's own trigger, with the Instrument pane, the channel list and the Event Log](pyscopegui/help/main-window.png)

**This is an early version.** The window, the panes, the build and the installer are in place, with a built-in demo that needs no hardware and back ends for both ranges of the PicoScope 2000 series, the Rigol DS1000Z series and the Tektronix TDS/TPS 2000 series.

## What it does

- **Channels and Plot**: analog channels on one plot and digital channels in lanes under it, on the same time axis. Drag or zoom either and both move. **Y** fits the voltage axis to the signal, shows the range the channels are set to as a scope's screen does, or holds it where you put it.
- **Deep captures stay quick**: the last ten seconds of every channel are held, or up to ten minutes if you ask, and what is drawn is cut down to a lowest and a highest per column of the screen, so a spike narrower than a pixel is still drawn.
- **Cursors and measurements**: one or two cursors, with what every channel read at each beside its name; the **Measurements** pane -- levels, peak to peak, RMS, frequency, period, duty -- between the cursors or over what is in view; and the **Data** pane, the samples themselves, a row for each, to copy into a spreadsheet.
- **Triggers** on any channel: a scope's own **Stop, Single, Normal and Auto**, and an edge rising, falling or either way, a window, a pulse's width, a runt, a timeout, a logic pattern, or a frame read off a decoded bus, each with a holdoff. A PicoScope on the `ps2000a` driver and a Rigol do most of them in their own hardware, at their full rate.
- **Several instruments at once**, and two of the same kind: **Add instrument** puts each in the Instrument pane with a tab of its own, where it is opened and set up. Each has its own trigger, so two instruments triggered by the same edge line up; or one **leads**, and the others are shown at the moment its trigger comes, by the computer's clock.
- **Decoding buses**: right-click a channel, analog or logic, and decode it as **CAN**, **UART**, **SPI** or **I²C**. The **Decoded buses** pane lists every frame, character and transfer, problems and all, and each bus can be paused, removed and added there.
- **Decoded CAN to pycangui**: frames read off a scope's channel are sent on by UDP multicast to [pycangui](https://github.com/davhodg/pycangui) -- a CAN bus tool, on [PyPI](https://pypi.org/project/pycangui/) too -- and any other program on python-can's UDP multicast bus, which take them as they would from a CAN adapter. On this computer only, or across the local network if you choose.
- **Maths channels**: two channels added, taken away, multiplied or divided; or one inverted, made positive, squared, square-rooted, scaled and offset, differentiated, integrated or averaged. Drawn, measured, triggered on and decoded like any other.
- **Probes**: 1x to 1000x, a differential probe's ratio, or a current probe read in amps, with the scale, the offset, the cursors and the measurements all in its units.
- **Python Console**: Python inside the window, with commands to drive the scopes, read their samples and make maths channels, and *File > Run script...* for a script kept in a file.
- **Workspaces**: one for each bench or setup, each with its own instruments, settings and panes, chosen under *File > Workspace*.
- **Export to CSV**: every sample of what the plot shows, with time measured from the trigger, one file for each instrument.
- **Save and open captures**: everything held kept in a file and opened again exactly as it was, beside the live instruments; and CSV files -- pyscopegui's own, or another tool's, with lines to skip and columns to choose -- opened the same way.
- **Instrument** pane: the settings of whichever instrument is chosen, built from what its back end says it has. A scope's channels are set one at a time, and how every channel is set is read beside its name in the plot's list: click one there to change it.
- **The same settings on every scope**: volts a division, probe, coupling and offset, whichever maker's it is.
- **Panes** that dock, float, detach into windows of their own and pin on top, with the arrangement remembered. More than one plot can be open at once.
- **Event Log**: everything the application has to say, with warnings and errors in their own colours; and **Instrument traffic**, every command sent to an instrument and every answer, while it is open.
- **Light and dark** themes, or whichever the system is set to.

Full details are in [the manual](pyscopegui/help/manual.md), which is also under **Help > Documentation** in the application. What each version added, changed and fixed is in [the changelog](pyscopegui/help/changelog.md), which is part of the manual too.

## Instruments

- **Demo signals**: two analog and four digital channels, with no hardware.
- **PicoScope 2000 series**, both ranges of them. On Pico's `ps2000` driver (2202, 2203, 2204, 2204A, 2205, 2205A): both channels, streamed continuously at up to 1 MS/s, or read in short blocks at up to 100 MS/s around the scope's own trigger. On the `ps2000a` driver (2206 to 2208 in their A and B forms, the four-channel 2405A to 2408B, and the MSO models): two or four channels and an MSO's sixteen logic inputs, streamed at up to 31.25 MS/s, or read in blocks of up to a million samples at the scope's full rate.
- **Rigol DS1000Z series** (DS1054Z, DS1074Z, DS1104Z, and the Plus, -S and MSO models), over the network or USB: the four analog channels, a sweep at a time around the scope's own trigger, read from its screen or its whole memory, with its own trigger types: either edge, pulse width, runt, window, timeout and pattern. The logic inputs and signal generator that some models have are not used yet. Over the network nothing of Rigol's needs installing; USB needs a VISA library, which Rigol's own software installs.
- **Tektronix TDS/TPS 2000 series** (TDS200, TDS1000, TDS2000 and TPS2000 over a serial port; the TDS1000B, TDS2000B and TDS2000C over USB): two or four channels, a sweep at a time around the scope's own trigger, or what is on its screen read off with nothing on the scope changed. For taking a capture off the scope rather than watching one: neither link is quick.

Pico's library is not bundled. Install the PicoSDK from [picotech.com/downloads](https://www.picotech.com/downloads). If Pico's own PicoScope 7 is running, close it first, since only one program can have the scope open.

The **Instrument** pane sets the scope up: sample rate, and each channel's scale in volts a division, probe, coupling and whether it is read at all. The scope is opened once and kept open, so starting, stopping and changing a setting are quick.

The pane also drives the scope's **signal generator** output: off, sine, square or triangle, with frequency, peak-to-peak amplitude and offset. It is off until you choose a waveform, and changes take effect while the scope runs, with a short gap in the plot while it is set.

## Installing

There are three options:

1. **With pip** -- from [PyPI](https://pypi.org/project/pyscopegui/), into whichever Python environment you choose. Python 3.12 or newer is needed.

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

   It is an ordinary Python package with an ordinary entry point, so the choice of environment is yours.

2. **The Windows installer** -- `pyscopegui-<version>-setup.exe` from the [releases page](https://github.com/davhodg/pyscopegui/releases). Nothing else is needed: **not even Python.** It installs a self-contained application, offers a desktop shortcut, and uninstalls cleanly.

   It asks first who it is for: **everybody who uses the computer**, which needs administrator rights, or **only you**, which does not.

3. **From a Git clone** -- clone the repository, then double-click `pyscopegui.cmd` (Windows) or run `./pyscopegui.sh` (Linux). This is the way to have the latest changes before they are released, or to contribute. Python 3.12 or newer must be on the PATH.

   For a shortcut, *Tools > Settings > Add shortcut to Start menu* (the applications menu on Linux) and, on Windows, *Add shortcut to desktop*. The entry starts the launcher, so a start from it after a pull still picks up new libraries. A pip installation has the same two, and its shortcut starts the Python it is installed in.

   The first run sets itself up: it creates a *virtual environment* -- a folder called `.venv` holding its own copy of Python and only the libraries pyscopegui needs, so nothing else on the machine is touched -- and downloads a couple of hundred megabytes into it. That takes a few minutes once; every later start is immediate, and deleting `.venv` undoes the whole thing. If `uv` is installed it is used instead of pip.

   **On Windows** the launcher makes `.venv` from Python 3.15, 3.14, 3.13 or 3.12 when the `py` launcher has one of them, newest first, even if a newer Python -- a preview, say -- is the one on the PATH: those are the versions every library pyscopegui runs on has a ready-made download for.

   **If the Python `.venv` was made with is uninstalled** -- or replaced by a newer version -- the launcher says so, and offers to delete `.venv` and set it up again with the Python installed now. Workspaces and settings are not in `.venv`, and are kept. A setup that fails does not leave a half-made `.venv` behind.

**On Linux**, however pyscopegui is installed, Qt needs a system library to draw the window, and Debian, Ubuntu, Linux Mint and the like often leave it out:

```
sudo apt install libxcb-cursor0
```

pyscopegui names any that are missing as it starts.

**Where your own files are kept** is the same whichever way it was installed: `%APPDATA%\pyscopegui` on Windows and `~/.config/pyscopegui` on Linux. Upgrading and uninstalling leave that folder alone.

## Uninstalling

- **The Windows installer:** *Settings > Apps* (or *Add or remove programs*), or *Uninstall pyscopegui* in its Start menu folder. It takes away its shortcuts too.
- **pip:** `pip uninstall pyscopegui`, and any shortcut *Tools > Settings* added, as for a clone.
- **A Git clone:** delete the folder. If *Tools > Settings* was used to add a shortcut, take that away as well: the shortcuts are `%APPDATA%\Microsoft\Windows\Start Menu\Programs\pyscopegui.lnk` and `pyscopegui.lnk` on the desktop (on Linux, `~/.local/share/applications/pyscopegui.desktop`).

Your own files -- settings and the pane arrangement -- are never removed by uninstalling. To remove them too, delete the folder named above under *Where your own files are kept*.

## Supported systems

**Windows and Linux**, on **Python 3.12 or newer**. The CI workflow runs the tests on both on every push. The installer is for Windows only.

## Built with

pyscopegui is Apache-2.0 and is a pure-Python application on top of these packages, each used unmodified under its own licence. The LGPL components stay separate, replaceable packages, as the LGPL requires.

| Package | Used for | Licence |
|---------|----------|---------|
| [Python](https://www.python.org) | Runtime | PSF-2.0 |
| [PySide6-Essentials](https://www.qt.io/qt-for-python) | GUI toolkit (Qt for Python) | LGPL-3.0 (used under LGPL) |
| [shiboken6](https://www.qt.io/qt-for-python) | Qt binding runtime used by PySide6 | LGPL-3.0 (used under LGPL) |
| [pyqtgraph](https://www.pyqtgraph.org) | Plotting | MIT |
| [numpy](https://numpy.org) | Sample arrays | BSD-3-Clause (with 0BSD / MIT / Zlib / CC0 parts) |
| [pyvisa](https://github.com/pyvisa/pyvisa) | A scope on USB, through an installed VISA library | MIT |
| [pyserial](https://github.com/pyserial/pyserial) | Serial port, for the Tektronix scopes | BSD-3-Clause |
| [python-can](https://github.com/hardbyte/python-can) | Decoded CAN frames sent on by UDP multicast, to pycangui and others | LGPL-3.0 (used under LGPL) |
| [msgpack](https://github.com/msgpack/msgpack-python) | Packing those frames, on Windows, as python-can's UDP multicast bus does | Apache-2.0 |

Only LGPL Qt modules are used (QtCore, QtGui, QtWidgets). pyscopegui depends on **PySide6-Essentials** rather than the full PySide6, so the GPL-only add-on modules (Qt Charts, Qt Data Visualization and the rest) are never installed.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md): setting up, running the tests, and building the Windows installer. Everyone taking part is asked to follow the [code of conduct](CODE_OF_CONDUCT.md), and security problems go through [SECURITY.md](SECURITY.md).

## Safety notice

pyscopegui shows what instruments connected to real equipment measure. A scope's ground clip is connected to the computer's ground unless the scope or its USB connection is isolated, and clipping it to a point that is not at ground can damage the equipment, the scope and the computer. Know what you are connecting to before you connect.

## Licence

pyscopegui is free software, provided under the Apache License 2.0, without warranty of any kind; see [LICENSE](LICENSE) and [NOTICE](NOTICE).

Development has made use of Anthropic's Claude.
