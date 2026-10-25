[&larr; Contents](manual.md)

# About, licences and updates

**Help > Documentation** opens this manual. It ships inside pyscopegui and needs no network;
*Back* and *Contents* get you around it.

**Help > Diagnostics...** opens a report in a window of its own and copies it to the
clipboard, ready to paste into a bug report: the versions, each instrument and its settings,
how many samples each channel has received and holds, and what each plot is showing. Then
what each instrument says of itself -- a PicoScope's library and driver, the rate it gave
and how its stream is keeping up, how a Rigol or a Tektronix is reached and what answered --
the trigger and who finds it, the memory there is for the history, what is decoded and sent
on, any pane put away or out on its own, the last 20 warnings and errors, and what is
running. **Refresh** makes it again as things are now, **Copy** puts it on the clipboard
again, and **Save...** writes it to a text file.

**Help > Check for updates...** asks the question that fits how pyscopegui was installed.
The Windows installer's build asks GitHub whether there is a newer release, and offers to
open the releases page. A pip installation asks PyPI for its newest version, and says the
pip command that updates it. Run from a source folder, it asks about commits instead, since
a release is behind everything pulled since: how many newer commits GitHub has on the branch
this folder is on, and it offers to open the list of them. A branch GitHub does not have is
compared with master.

This is the only time pyscopegui goes online, and only because you asked. Nothing about your
computer is sent, and nothing is downloaded or installed.

**Help > Licences...** shows pyscopegui's own Apache-2.0 licence, the NOTICE attributions
and the third-party notices, all shipped with the application.

**Help > About pyscopegui** shows the version alongside Python, every package pyscopegui
runs on and the platform, in a form you can copy. It also says where it is running from: the
Python it started with, that Python's environment, the folder the pyscopegui package was
loaded from, and how it got there -- pip, an editable install of a source folder, or the
Windows installer. Run from a source checkout, it names the branch or tag and the commit as
well, read from `.git` without running git: between two releases every build calls itself
the same version, so that line is what tells one pull from another.

## If pyscopegui will not start

Started from the source folder, `pyscopegui.cmd` and `pyscopegui.sh` install anything
missing before they start pyscopegui, and a library that is still missing is reported in a
window rather than as nothing happening. The entry made by
*Tools > Settings > Add shortcut to Start menu* (*Add shortcut to applications menu* on
Linux), or by *Add shortcut to desktop* on Windows, starts the launcher too, so starting
from it after a pull does the same. Installed with pip, the same two make a shortcut that
starts pyscopegui with the Python it is installed in. The first start says where they are
in the Event Log, once.

On Linux, a library Qt needs to draw the window is named, with the package it comes in,
before Qt is started: Qt itself says only that it could not load the "xcb" plugin.

`python -m pyscopegui --selftest` imports everything a build is most likely to be missing
and exits with 0 if it is all there, which is how the build checks itself.
