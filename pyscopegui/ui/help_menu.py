# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Help: what this is, and what it is running on."""

from __future__ import annotations

import platform
import sys
from importlib.metadata import PackageNotFoundError, version

from PySide6.QtCore import QObject, Qt, qVersion
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QVBoxLayout,
)

from pyscopegui import APP_NAME, __version__
from pyscopegui.core import paths
from pyscopegui.ui import fonts

PROJECT_PAGE = "https://github.com/davhodg/pyscopegui"
#: The packages worth naming in a bug report, in the order they are listed.
PACKAGES = ("PySide6-Essentials", "pyqtgraph", "numpy")


def _label_width(names) -> int:
    return max(len(name) for name in names) + 2


def environment_report() -> str:
    """Versions and folders, as text to paste into a report."""
    rows = [
        (APP_NAME, __version__ + (" (installed build)" if getattr(sys, "frozen", False) else "")),
        ("Python", platform.python_version()),
        ("Qt", qVersion()),
    ]
    for name in PACKAGES:
        try:
            rows.append((name, version(name)))
        except PackageNotFoundError:
            rows.append((name, "not installed"))
    rows.append(("System", platform.platform()))
    rows.append(("Settings", str(paths.user_dir())))
    width = _label_width(name for name, _ in rows)
    return "\n".join(f"{name:<{width}}{value}" for name, value in rows)


class AboutDialog(QDialog):
    """Version and environment, selectable so it can be pasted into a report."""

    def __init__(self, parent: QMainWindow | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        heading = QLabel(
            f"<h3>{APP_NAME} {__version__}</h3>"
            "<p>Oscilloscopes and logic analysers in one time-aligned view.</p>"
        )
        heading.setTextFormat(Qt.RichText)
        self.details = QPlainTextEdit(environment_report())
        self.details.setReadOnly(True)
        self.details.setFont(fonts.mono())
        self.details.setLineWrapMode(QPlainTextEdit.NoWrap)
        metrics = self.details.fontMetrics()
        text = self.details.toPlainText().splitlines()
        self.details.setMinimumWidth(max(metrics.horizontalAdvance(line) for line in text) + 40)
        self.details.setMinimumHeight(metrics.lineSpacing() * (len(text) + 2))
        link = QLabel(
            f'<p>Apache License 2.0 &middot; <a href="{PROJECT_PAGE}">{PROJECT_PAGE}</a></p>'
        )
        link.setOpenExternalLinks(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        for widget in (heading, self.details, link, buttons):
            layout.addWidget(widget)


class HelpMenu(QObject):
    def __init__(self, window: QMainWindow) -> None:
        super().__init__(window)
        self._window = window
        menu = window.menuBar().addMenu("&Help")
        menu.addAction(f"About {APP_NAME}", self._show_about)

    def _show_about(self) -> None:
        AboutDialog(self._window).exec()
