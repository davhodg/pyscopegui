# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Light, dark, or whatever the operating system is set to.

Qt follows the system's choice by itself; this only adds a way to override it,
under *Tools > Settings > Theme*. The choice is kept per person on this machine, in
``QSettings`` beside the window's position, rather than in the workspace: a
workspace handed to somebody else should not change their colours.

Applied through Qt's own colour scheme rather than a palette of pyscopegui's, so
anything that reads the palette -- the Event Log's colours among them --
follows the change as it happens.

**Not every native style can be dark.** Windows 11's can; the one Qt uses on
Windows 10 (``windowsvista``) draws light whatever is asked for -- which is why
pyscopegui stayed light on a Windows 10 set to dark, and why choosing Dark there
did nothing. So where the native style cannot draw dark, Qt's own Fusion style
is used for both, from the start. Switching to it only when dark was chosen
would change the controls' sizes as well as their colours on every switch, and
the whole window would reflow; with one style, light and dark are colours only.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QApplication, QMenu, QWidget

SETTING = "appearance/theme"
SYSTEM, LIGHT, DARK = "system", "light", "dark"
#: In the order the menu offers them.
CHOICES = ((SYSTEM, "Match the system"), (LIGHT, "Light"), (DARK, "Dark"))
#: Native styles that stay light whatever the colour scheme says.
LIGHT_ONLY = {"windowsvista", "windows"}
#: Qt's own style, which draws dark as well as light on every platform.
FUSION = "Fusion"
#: Qt's names for its styles, as the menu and the diagnostics say them.
STYLE_NAMES = {
    "windows11": "Windows 11",
    "windowsvista": "Windows Vista",  # Qt's native one up to Windows 10
    "windows": "Windows",
    "fusion": "Fusion",
    "macos": "macOS",
}
STYLE_TIP = (
    "The look Qt draws pyscopegui in. Windows 11 and macOS have their own, light and dark. "
    "Qt's style for Windows 10 and earlier has no dark version, so Fusion is used there "
    "for both. On Linux it is Fusion, or the desktop's own Qt style where it sets one."
)
TITLE = "Theme"
TIP = "Light, dark, or whichever the operating system is set to. Kept for you on this computer."


def chosen(settings: QSettings | None = None) -> str:
    """The choice remembered, or the system's when there is none or it is not one we know."""
    value = str((settings or QSettings()).value(SETTING, SYSTEM) or SYSTEM)
    return value if value in dict(CHOICES) else SYSTEM


def apply(choice: str, app: QApplication | None = None) -> None:
    """Ask Qt for this colour scheme, or give the choice back to the system,
    in a style that can draw both."""
    app = app or QApplication.instance()
    if app is None:
        return
    if app.style().name().lower() in LIGHT_ONLY:
        app.setStyle(FUSION)
    hints = app.styleHints()
    if choice == LIGHT:
        hints.setColorScheme(Qt.ColorScheme.Light)
    elif choice == DARK:
        hints.setColorScheme(Qt.ColorScheme.Dark)
    else:
        hints.unsetColorScheme()


def style_name(app: QApplication | None = None) -> str:
    """The style pyscopegui is drawn in, as a person would say it."""
    app = app or QApplication.instance()
    if app is None:
        return ""
    name = app.style().name()
    return STYLE_NAMES.get(name.lower(), name)


def describe(settings: QSettings | None = None, app: QApplication | None = None) -> str:
    """The choice, and for *Match the system* what the system gave."""
    choice = chosen(settings)
    label = dict(CHOICES)[choice]
    app = app or QApplication.instance()
    if choice != SYSTEM or app is None:
        return label
    scheme = app.styleHints().colorScheme()
    got = {Qt.ColorScheme.Dark: "dark", Qt.ColorScheme.Light: "light"}.get(scheme)
    return f"{label} ({got})" if got else label


def choose(choice: str, settings: QSettings | None = None, app: QApplication | None = None) -> None:
    """Remember a choice and apply it straight away."""
    (settings or QSettings()).setValue(SETTING, choice)
    apply(choice, app)


def menu(parent: QWidget, settings: QSettings | None = None) -> QMenu:
    """*Tools > Settings > Theme*: the three choices, the current one ticked,
    and the style in use greyed out below them.

    A greyed entry is skipped by the keyboard and by most screen readers, so
    the menu's own tooltip says the style as well.
    """
    out = QMenu(TITLE, parent)
    out.setToolTipsVisible(True)
    group = QActionGroup(out)
    group.setExclusive(True)
    current = chosen(settings)
    for value, label in CHOICES:
        action = QAction(label, out, checkable=True)
        action.setData(value)
        action.setChecked(value == current)
        action.triggered.connect(lambda _=False, v=value: choose(v, settings))
        group.addAction(action)
        out.addAction(action)
    out.addSeparator()
    style = QAction(out, enabled=False)
    style.setToolTip(STYLE_TIP)
    out.addAction(style)
    out.style_action = style

    def show_style() -> None:
        name = style_name()
        style.setText(f"Style: {name}")
        out.menuAction().setToolTip(f"{TIP} Drawn in Qt's {name} style." if name else TIP)

    show_style()
    out.aboutToShow.connect(show_style)
    return out
