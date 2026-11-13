# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Clear on the right-click of a text pane, under the usual Copy and Select All.

As in pycangui: the Event Log, the Python Console and Instrument traffic all
have it, so that what a pane's Clear button does can be done where the text is.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QMenu, QPlainTextEdit

from pyscopegui.ui import icons


def menu(text: QPlainTextEdit, clear: Callable[[], None] | None = None) -> QMenu:
    """The standard menu for the text, with Clear at the bottom: ``clear`` where
    the pane holds more than its text, or the text alone. Built apart from being shown."""
    built = text.createStandardContextMenu()
    built.addSeparator()
    icons.beside(built.addAction("Clear", clear or text.clear), icons.CLEAR)
    return built


def add(text: QPlainTextEdit, clear: Callable[[], None] | None = None) -> QPlainTextEdit:
    """Give the text pane the menu above on its right-click. What makes that menu
    is kept on the pane as ``clear_menu``, so it can be had without showing it."""

    def show(at: QPoint) -> None:
        shown = text.clear_menu()
        shown.exec(text.viewport().mapToGlobal(at))
        shown.deleteLater()

    text.clear_menu = lambda: menu(text, clear)
    text.setContextMenuPolicy(Qt.CustomContextMenu)
    text.customContextMenuRequested.connect(show)
    return text
