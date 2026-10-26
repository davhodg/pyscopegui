# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Entry point: `python -m pyscopegui`, or the `pyscopegui` command pip installs."""

import importlib
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from pyscopegui import APP_NAME

#: Imported by ``--selftest``. These are the modules a packaged build is most
#: likely to be missing, because they are loaded by name at run time and so no
#: static analysis can see them.
SELFTEST_MODULES = (
    "pyqtgraph",
    "numpy",
    "pyscopegui.ui.main_window",
    # Opening a double-clicked capture in the window already open.
    "pyscopegui.ui.handoff",
)


def selftest() -> int:
    """Import everything a build could plausibly be missing. Exit code only:
    a windowed build has nowhere to print to."""
    failures = []
    for name in SELFTEST_MODULES:
        try:
            importlib.import_module(name)
        except Exception as exc:
            failures.append(f"{name}: {exc}")
    # Every back end's module, asked for the way the instrument list asks.
    try:
        from pyscopegui import backends

        for name, backend in backends.BACKENDS.items():
            try:
                getattr(importlib.import_module(backend.module), backend.cls)
            except Exception as exc:
                failures.append(f"back end {name}: {exc}")
    except Exception as exc:
        failures.append(f"pyscopegui.backends: {exc}")

    try:
        from pyscopegui import resources

        if not resources.path("pyscopegui.ico").is_file():
            failures.append("pyscopegui/resources/pyscopegui.ico: not shipped with this build")
    except Exception as exc:
        failures.append(f"pyscopegui.resources: {exc}")

    # The manual is package data, so it is exactly the kind of file a build
    # drops silently. Every page, by name: a manual that still opens is the
    # worst way for a missing page to be found.
    try:
        from pyscopegui.help import missing_images, missing_pages

        for page in missing_pages():
            failures.append(f"pyscopegui/help/{page}: not shipped with this build")
        for image in missing_images():
            failures.append(f"pyscopegui/help/{image}: shown in the manual but not shipped")
    except Exception as exc:
        failures.append(f"pyscopegui.help: {exc}")

    # Help > Licences reads these at run time from beside the executable. A
    # build that ships them where it cannot see them would show empty tabs.
    try:
        from pyscopegui.ui.help_menu import missing_licence_files

        failures += [
            f"{name}: not found beside the application"
            for name in missing_licence_files(getattr(sys, "frozen", False))
        ]
    except Exception as exc:
        failures.append(f"pyscopegui.ui.help_menu: {exc}")

    if failures:
        sys.stderr.write("selftest failures:" + "".join(f"\n  {f}" for f in failures) + "\n")
        return 1
    return 0


#: Who Windows thinks the windows belong to. Without one, a pyscopegui started
#: from source is grouped under pythonw.exe and the taskbar shows Python's
#: icon whatever the window says -- the window icon only reaches the title bar.
APP_USER_MODEL_ID = "davhodg.pyscopegui"


def set_icon(app) -> None:
    """The application icon, before any window exists.

    The .ico rather than the PNG: it holds each size drawn for that size, and
    Qt picks the nearest one.
    """
    from PySide6.QtGui import QIcon

    from pyscopegui import resources

    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except (AttributeError, OSError):  # an unusual shell: the title bar still has it
            pass
    app.setWindowIcon(QIcon(str(resources.path("pyscopegui.ico"))))


#: The libraries Qt's X11 plugin needs that Debian, Ubuntu and Linux Mint can
#: leave out, each with the package it comes in. Without one, Qt stops with
#: "could not load the Qt platform plugin xcb" and does not say which.
XCB_LIBRARIES = (
    ("libxcb-cursor.so.0", "libxcb-cursor0"),
    ("libxcb-icccm.so.4", "libxcb-icccm4"),
    ("libxcb-image.so.0", "libxcb-image0"),
    ("libxcb-keysyms.so.1", "libxcb-keysyms1"),
    ("libxcb-render-util.so.0", "libxcb-render-util0"),
    ("libxkbcommon-x11.so.0", "libxkbcommon-x11-0"),
)


def uses_xcb(environ=None) -> bool:
    """Whether Qt will draw through X11 here, where XCB_LIBRARIES are needed."""
    if not sys.platform.startswith("linux"):
        return False
    environ = os.environ if environ is None else environ
    chosen = environ.get("QT_QPA_PLATFORM", "")
    if chosen:
        return chosen.startswith("xcb")
    return environ.get("XDG_SESSION_TYPE") != "wayland"


def missing_xcb_packages(load=None) -> list[str]:
    """The packages to install for the XCB_LIBRARIES that cannot be loaded."""
    if load is None:
        import ctypes

        load = ctypes.CDLL
    missing = []
    for library, package in XCB_LIBRARIES:
        try:
            load(library)
        except OSError:
            missing.append(package)
    return missing


def files_given(arguments: list[str]) -> list[Path]:
    """The files pyscopegui was started with -- a capture double-clicked in the
    file manager -- from what is left once Qt has taken its own arguments."""
    return [Path(arg).resolve() for arg in arguments[1:] if arg and not arg.startswith("-")]


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if uses_xcb() and (missing := missing_xcb_packages()):
        sys.stderr.write(
            "Qt needs libraries this system does not have to draw the window. On Debian,\n"
            "Ubuntu and Linux Mint:\n\n"
            f"    sudo apt install {' '.join(missing)}\n"
        )
        return 1
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)  # QSettings uses these two for the registry/ini path
    set_icon(app)
    # Before anything is drawn, so the window opens in the colours chosen.
    from pyscopegui.ui import theme

    theme.apply(theme.chosen())

    # Before the libraries: a capture double-clicked while pyscopegui is open
    # goes to that one, and this one has nothing more to do.
    from pyscopegui.ui import handoff

    files = files_given(app.arguments())
    if files and handoff.hand_over(files):
        return 0
    listener = handoff.Listener(parent=app)
    listener.waiting += files

    # Imported here rather than at the top of the file so that a library
    # which is not installed becomes a dialog. Started from pyscopegui.cmd
    # there is no console -- it runs pythonw -- so an ImportError on the way
    # up is a window that never appears and not one word about why.
    try:
        from pyscopegui.ui.main_window import MainWindow
        from pyscopegui.ui.windows import Windows
    except Exception as exc:
        # Not ImportError alone: a library that is installed and will not
        # load fails however it likes.
        from pyscopegui.ui import messages

        messages.critical(None, f"{APP_NAME} cannot start", why_it_cannot_start(exc))
        sys.stderr and sys.stderr.write(why_it_cannot_start(exc) + "\n")
        return 1

    # Held by Windows rather than a local, because switching workspace
    # replaces the window rather than reconfiguring it.
    windows = Windows(MainWindow)
    windows.open()
    # The window of the moment: switching workspace replaces it.
    listener.deliver(lambda paths: windows.window and windows.window.open_files(paths))
    finished = app.exec()
    listener.close()
    return finished


def why_it_cannot_start(failed: BaseException) -> str:
    """What to tell somebody whose libraries would not load, and what to do.

    Two different faults. A library that is not there is put right by
    installing it. One that is there and will not load is usually two
    libraries that no longer agree, and installing again changes nothing: it
    wants the name of the file that failed, so that the pair can be found.
    """
    if isinstance(failed, ModuleNotFoundError):
        return (
            f"A library {APP_NAME} needs is missing:\n\n    {failed}\n\n"
            "Start it with pyscopegui.cmd (or pyscopegui.sh), which installs "
            "anything missing before starting, or install it with pip."
        )
    import traceback

    where = traceback.extract_tb(failed.__traceback__)
    place = f"\n    in {where[-1].filename}, line {where[-1].lineno}" if where else ""
    return (
        f"A library {APP_NAME} needs is installed but would not load:\n\n"
        f"    {type(failed).__name__}: {failed}{place}\n\n"
        "This is usually two libraries that no longer agree, after a new release "
        "of one of them. Upgrading the one named above, or going back a version "
        "of the one it was loading, normally puts it right; in a source folder, "
        "deleting .venv and starting the launcher installs them all again."
    )


if __name__ == "__main__":
    sys.exit(main())
