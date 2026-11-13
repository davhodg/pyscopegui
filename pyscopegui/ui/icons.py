# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""A standard icon beside the word, for the actions that have one.

Beside, never instead: the word stays, and the icon helps somebody who reads
little English find Clear, Save or Stop at a glance. Only actions whose
meaning is the standard one get an icon. A picture made up for Single or
Normal would have to be learnt, which is the opposite of the point, so the run
buttons stay words.

The icons are Microsoft's Fluent UI System Icons (MIT; LICENSES/MIT.txt),
shipped in ``pyscopegui/resources/icons`` under their own file names, so the
same picture is shown on Windows 10, Windows 11, Linux and macOS, and the
same as in pycangui. The system's own are not used: on Linux each desktop
theme names its icons differently and lacks a different third of them.

Each is drawn in the text colour of the moment, so it follows a change of
theme, dark mode and high contrast like the word beside it.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRect, QRectF, QSettings, QSize, Qt
from PySide6.QtGui import (
    QGuiApplication,
    QIcon,
    QIconEngine,
    QImage,
    QPainter,
    QPalette,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMenu, QMessageBox

from pyscopegui import resources

ADD = "add"
BACK = "back"
CALCULATE = "calculate"
CANCEL = "cancel"
CHECK = "check"
CLEAR = "clear"
CLOSE = "close"
CONNECT = "connect"
COPY = "copy"
CUT = "cut"
DELETE = "delete"
DIAGNOSTICS = "diagnostics"
DISCARD = "discard"
DISCONNECT = "disconnect"
EXIT = "exit"
EXPORT = "export"
FOLDER = "folder"
HELP = "help"
HOME = "home"
INFO = "info"
LICENCE = "licence"
MANAGE = "manage"
NEW = "new"
OPEN = "open"
PASTE = "paste"
READ = "read"
REDO = "redo"
RESET = "reset"
RELOAD = "reload"
REMOVE = "remove"
RENAME = "rename"
SAVE = "save"
SAVE_AS = "save as"
SELECT_ALL = "select all"
SETTINGS = "settings"
START = "start"
STOP = "stop"
UNDO = "undo"
UPDATES = "updates"
WRITE = "write"

#: Each of pyscopegui's names for an action, and the file in
#: ``resources/icons`` drawn for it: Fluent's name, at its 20 px size.
FILE: dict[str, str] = {
    ADD: "add_20_regular",
    BACK: "arrow_left_20_regular",
    CALCULATE: "calculator_20_regular",  # a maths channel, worked out from others
    CANCEL: "dismiss_circle_20_regular",
    CHECK: "checkmark_20_regular",
    CLEAR: "eraser_20_regular",  # not a cross: Close and Cancel have those
    CLOSE: "dismiss_20_regular",
    CONNECT: "plug_connected_20_regular",
    COPY: "copy_20_regular",
    CUT: "cut_20_regular",
    DELETE: "delete_20_regular",
    DIAGNOSTICS: "pulse_20_regular",
    DISCARD: "arrow_undo_20_regular",
    DISCONNECT: "plug_disconnected_20_regular",
    EXIT: "door_arrow_right_20_regular",
    EXPORT: "save_20_regular",
    FOLDER: "folder_open_20_regular",
    HELP: "question_circle_20_regular",
    HOME: "home_20_regular",
    INFO: "info_20_regular",
    LICENCE: "certificate_20_regular",
    MANAGE: "wrench_20_regular",  # the gear is Settings
    NEW: "document_add_20_regular",
    OPEN: "folder_open_20_regular",
    PASTE: "clipboard_paste_20_regular",
    READ: "book_open_20_regular",
    REDO: "arrow_redo_20_regular",
    RESET: "arrow_counterclockwise_20_regular",  # back the way it was
    RELOAD: "arrow_sync_20_regular",
    REMOVE: "subtract_20_regular",
    RENAME: "rename_a_20_regular",  # a name in a box: the pencil is Edit
    SAVE: "save_20_regular",
    SAVE_AS: "save_edit_20_regular",
    SELECT_ALL: "select_all_on_20_regular",
    SETTINGS: "settings_20_regular",
    START: "play_20_regular",
    # Solid: an outlined square reads as a tick box.
    STOP: "stop_20_filled",
    UNDO: "arrow_undo_20_regular",
    UPDATES: "arrow_sync_circle_20_regular",
    WRITE: "edit_line_horizontal_3_20_regular",  # writing on lines: the plain pencil is Edit
}


def path(name: str):
    """Where the picture for one of the names above is shipped."""
    return resources.path(f"icons/{FILE[name]}.svg")


#: Where *Tools > Settings > Show icons* is kept: with the computer,
#: like the theme, since it is about who sits at it rather than the work.
SETTING = "icons/shown"
TITLE = "Show icons"
TIP = (
    "A standard icon beside the word on common buttons and menu items:\n"
    "Clear, Save, Stop and the like. The words stay either way. Kept for\n"
    "you on this computer."
)

#: Which icon a button or menu item was given, kept on it so that turning
#: icons off and on again can find it and put it back.
PROPERTY = "pyscopegui_icon"

#: The setting, read once: asked on every button made, it would be read
#: from the disk hundreds of times at startup.
_shown: bool | None = None


def shown() -> bool:
    """Whether icons go beside the words. On unless somebody turned them off."""
    global _shown
    if _shown is None:
        _shown = str(QSettings().value(SETTING, "true")).lower() != "false"
    return _shown


def set_shown(on: bool) -> None:
    """Turn icons on or off, at once, everywhere they were asked for."""
    global _shown
    QSettings().setValue(SETTING, on)
    _shown = on
    for widget in QApplication.allWidgets():
        for thing in (widget, *widget.actions()):
            name = thing.property(PROPERTY)
            if name and on:
                _draw(thing, name)
            elif name:
                thing.setIcon(QIcon())


def beside[Thing](thing: Thing, name: str) -> Thing:
    """Give a button or menu item the icon for ``name``.

    Returns ``thing``, so that it can wrap the line that makes it.
    """
    thing.setProperty(PROPERTY, name)
    if shown():
        _draw(thing, name)
    return thing


def _draw(thing, name: str) -> None:
    thing.setIcon(icon(name))


#: The entries Qt puts in the right-click menu of every text box and number
#: box, by the object name Qt gives each. Qt draws them from the system's own
#: icons -- not these, and not the same on any two systems -- and ignores the
#: icon theme being changed, so they are swapped as each such menu opens.
STANDARD_MENU: dict[str, str] = {
    "edit-undo": UNDO,
    "edit-redo": REDO,
    "edit-cut": CUT,
    "edit-copy": COPY,
    "edit-paste": PASTE,
    "edit-delete": DELETE,
    "select-all": SELECT_ALL,
}


class _StandardMenus(QObject):
    """Puts these icons on Qt's own text menus as they open, or none when off."""

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Show and isinstance(watched, QMenu):
            for action in watched.actions():
                name = STANDARD_MENU.get(action.objectName())
                if name is not None:
                    beside(action, name)
                    if not shown():
                        action.setIcon(QIcon())  # not Qt's, either
        return False


_standard_menus: _StandardMenus | None = None


def on_standard_menus(app: QApplication) -> None:
    """Watch for Qt's own right-click menus, once for the application."""
    global _standard_menus
    if _standard_menus is None:
        _standard_menus = _StandardMenus(app)
        app.installEventFilter(_standard_menus)


_Box = QDialogButtonBox.StandardButton

#: The buttons Qt names itself, in every dialog and message box. A message
#: box's buttons are the same ones under another enum.
STANDARD: dict[QDialogButtonBox.StandardButton, str] = {
    _Box.Ok: CHECK,
    _Box.Yes: CHECK,
    _Box.YesToAll: CHECK,
    _Box.Apply: CHECK,
    _Box.Cancel: CANCEL,
    _Box.No: CANCEL,
    _Box.NoToAll: CANCEL,
    _Box.Abort: CANCEL,
    _Box.Close: CLOSE,
    _Box.Save: SAVE,
    _Box.SaveAll: SAVE,
    _Box.Open: OPEN,
    _Box.Discard: DISCARD,
    _Box.Help: HELP,
    _Box.Reset: RESET,
    _Box.RestoreDefaults: RESET,
    _Box.Retry: RELOAD,
}


def on_buttons[Box: (QDialogButtonBox, QMessageBox)](box: Box) -> Box:
    """Icons beside a dialog's OK, Cancel, Close and the rest.

    Only on those still without one: a button given its own word, and an
    icon for it, keeps that. Returns ``box``, to wrap the line that makes it.
    """
    for button in box.buttons():
        if button.property(PROPERTY) or not button.icon().isNull():
            continue
        name = STANDARD.get(_Box(box.standardButton(button).value))
        if name is not None:
            beside(button, name)
    return box


# --- drawing --------------------------------------------------------------------------
#: One renderer per picture, read from the disk the first time it is drawn.
_RENDERERS: dict[str, QSvgRenderer] = {}

#: Engines handed to Qt, kept here so that Python does not collect one that
#: an icon is still drawing with.
_ENGINES: list[QIconEngine] = []

#: One icon per picture, made the first time it is asked for. A QIcon is
#: shared, not copied, so every button can have the same one; and it is drawn
#: in the palette's colour when painted, so sharing it changes nothing on
#: screen. A new one each time kept a new engine alive for good -- hundreds a
#: window -- and a test run, which makes a window a test, piled them up until
#: each garbage collection took a quarter of a second.
_ICONS: dict[str, QIcon] = {}


def icon(name: str) -> QIcon:
    """The icon for one of the names above, drawn in the text colour."""
    if name not in _ICONS:
        _ICONS[name] = QIcon(_kept(_Engine(name)))
    return _ICONS[name]


def _renderer(name: str) -> QSvgRenderer:
    if name not in _RENDERERS:
        _RENDERERS[name] = QSvgRenderer(str(path(name)))
    return _RENDERERS[name]


class _Engine(QIconEngine):
    """One picture, in the palette's text colour when drawn.

    The files are drawn in one dark grey. The shape is drawn first and then
    filled with the colour the word beside it has, so the file's own colour
    never shows.
    """

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name

    def paint(self, painter, rect: QRect, mode, state) -> None:
        palette = QGuiApplication.palette()
        group = QPalette.Disabled if mode == QIcon.Disabled else QPalette.Active
        ratio = painter.device().devicePixelRatioF() if painter.device() else 1.0
        side = min(rect.width(), rect.height())
        shape = QImage(round(side * ratio), round(side * ratio), QImage.Format_ARGB32_Premultiplied)
        shape.fill(Qt.transparent)
        inner = QPainter(shape)
        _renderer(self.name).render(inner, QRectF(0, 0, shape.width(), shape.height()))
        inner.setCompositionMode(QPainter.CompositionMode_SourceIn)
        inner.fillRect(shape.rect(), palette.color(group, _ink(state)))
        inner.end()
        shape.setDevicePixelRatio(ratio)
        left = rect.x() + (rect.width() - side) // 2
        top = rect.y() + (rect.height() - side) // 2
        painter.drawImage(QRect(left, top, side, side), shape)

    def pixmap(self, size: QSize, mode, state) -> QPixmap:
        out = QPixmap(size)
        out.fill(Qt.transparent)
        painter = QPainter(out)
        self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        return out

    def clone(self) -> QIconEngine:
        return _kept(_Engine(self.name))


def _ink(state) -> QPalette.ColorRole:
    """The colour the word beside it is drawn in.

    Windows 11 fills a pressed toggle with the accent colour and draws its
    word in the window colour to stand out on it; elsewhere a pressed button
    keeps the ordinary button text.
    """
    from pyscopegui.ui import theme  # not at the top: theme is the heavier of the two

    pressed_on_accent = state == QIcon.On and theme.style_name() == theme.STYLE_NAMES["windows11"]
    return QPalette.Window if pressed_on_accent else QPalette.ButtonText


def _kept(engine: QIconEngine) -> QIconEngine:
    _ENGINES.append(engine)
    return engine
