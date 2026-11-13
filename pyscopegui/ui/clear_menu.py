# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The right-click of a text pane: the usual Copy and Select All, Save all and Clear all.

The same in the Event Log, the Python Console and Instrument traffic, and the
same as pyflashgui's. *Save all* and *Clear all* rather than *Save* and *Clear*:
Copy acts on what is selected, and these take the whole pane whatever is.

Qt makes Copy and Select All, and gives them the system's own icons, which are
not the ones beside every other word in pyscopegui and stay when *Show icons*
is off. They are given pyscopegui's here, by the name Qt gives each.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFileDialog, QMenu, QPlainTextEdit

from pyscopegui.core.context import Context
from pyscopegui.ui import icons

TITLE = "Clear all"
SAVE_TITLE = "Save all..."
#: Where a pane's text was last saved, so the next is offered there.
TEXT_FOLDER = "text.folder"

#: Qt's own items in a text's menu, by the object name Qt gives each.
QT_ITEMS = {"edit-copy": icons.COPY, "select-all": icons.SELECT_ALL}


def stamped(stem: str, suffix: str, now: datetime | None = None) -> str:
    """A name with the date and time in it, ``event-log_2026-11-13_143012.txt``,
    so that saving again does not offer to overwrite the last. In an order
    that sorts by name alone."""
    return f"{stem}_{(now or datetime.now()):%Y-%m-%d_%H%M%S}{suffix}"


def menu(
    text: QPlainTextEdit,
    ctx: Context | None = None,
    name: str = "",
    clear: Callable[[], None] | None = None,
) -> QMenu:
    """The standard menu for the text, then Save all, and Clear all below a line.
    Made, not shown. Save all is there when ``ctx`` is given, with ``name`` the
    start of the file name offered. ``clear`` is what Clear all does, where the
    pane holds more than its text; the text alone otherwise.

    Save all comes after Select All, Qt's last: the two that take the whole
    pane together, after Copy, which takes what is selected.
    """
    built = text.createStandardContextMenu()
    for action in built.actions():
        if (picture := QT_ITEMS.get(action.objectName())) is not None:
            icons.beside(action, picture)
        elif not action.icon().isNull():
            action.setIcon(QIcon())  # one of Qt's with no picture of ours: the word alone
    if ctx is not None:
        save = icons.beside(built.addAction(SAVE_TITLE), icons.SAVE_AS)
        save.setToolTip("Write everything in this pane to a text file.")
        save.triggered.connect(lambda: ask_save(text, ctx, name))
        save.setEnabled(bool(text.toPlainText()))
    built.addSeparator()
    icons.beside(built.addAction(TITLE, clear or text.clear), icons.CLEAR)
    return built


def ask_save(text: QPlainTextEdit, ctx: Context, name: str) -> None:
    """Ask where, offered where text was saved last, and write the pane there."""
    folder = ctx.settings.get(TEXT_FOLDER)
    start = Path(folder if isinstance(folder, str) else str(ctx.user_dir))
    stem = name.lower().replace(" ", "-") or "pyscopegui"
    chosen, _filter = QFileDialog.getSaveFileName(
        text,
        f"Save {name}" if name else "Save",
        str(start / stamped(stem, ".txt")),
        "Text (*.txt);;All files (*)",
    )
    if chosen:
        ctx.settings.set(TEXT_FOLDER, str(Path(chosen).parent))
        save_text(text, ctx, name, Path(chosen))


def save_text(text: QPlainTextEdit, ctx: Context, name: str, path: Path) -> bool:
    """Write the whole pane to a file as UTF-8, and say where it went. Whether it did."""
    try:
        path.write_text(text.toPlainText() + "\n", encoding="utf-8")
    except OSError as exc:
        ctx.error(f"Could not write {path}: {exc}")
        return False
    ctx.log(f"{name or 'Text'} written to {path}")
    return True


def add(
    text: QPlainTextEdit,
    ctx: Context | None = None,
    name: str = "",
    clear: Callable[[], None] | None = None,
) -> QPlainTextEdit:
    """Give the text pane the menu above on its right-click. What makes that menu
    is kept on the pane as ``clear_menu``, so it can be had without showing it."""

    def show(at: QPoint) -> None:
        shown = text.clear_menu()
        shown.exec(text.viewport().mapToGlobal(at))
        shown.deleteLater()

    text.clear_menu = lambda: menu(text, ctx, name, clear)
    text.setContextMenuPolicy(Qt.CustomContextMenu)
    text.customContextMenuRequested.connect(show)
    return text
