# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""One offscreen QApplication for the whole test session, and a drain between
tests.

The drain matters more than it looks. Windows and instruments are created per
test and talk to each other through Qt signals and timers. If a queued signal
is still in the event queue when the test ends and its target is garbage
collected, Qt delivers it to a dead C++ object and the interpreter dies with
an access violation somewhere in a later test.

Draining the queue while everything is still alive, then collecting garbage
before the next test starts, keeps that from happening.
"""

import gc
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox


@pytest.fixture(scope="session", autouse=True)
def _isolate_settings(tmp_path_factory):
    """Keep QSettings in a temporary file rather than the registry.

    MainWindow saves its geometry in closeEvent, so without this a test run
    leaves settings behind, and the next run restores from the last one.
    """
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(
        QSettings.IniFormat, QSettings.UserScope, str(tmp_path_factory.mktemp("settings"))
    )


@pytest.fixture(autouse=True)
def _own_user_folder(tmp_path, monkeypatch):
    """Settings and layout in a folder of the test's own, never in yours."""
    monkeypatch.setenv("PYSCOPEGUI_HOME", str(tmp_path / "home"))


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _no_unanswered_dialogs(monkeypatch):
    """A modal dialog nobody answered blocks forever.

    Offscreen or not, ``exec`` runs its own event loop and waits, so a test
    that reaches an unexpected dialog does not fail -- it hangs. This turns
    that into an ordinary failure naming the dialog. A test that means to
    answer one patches ``exec`` itself, and its patch replaces this one.
    """

    def refuse(self, *_args, **_kwargs):
        raise AssertionError(
            f"a modal {type(self).__name__} opened that no test answered: {self.windowTitle()!r}"
        )

    for widget in (QDialog, QMessageBox):
        monkeypatch.setattr(widget, "exec", refuse)


@pytest.fixture(autouse=True)
def _drain_qt_events():
    yield
    # Fixtures tear down after this point, so deliver what is already queued
    # first, then let go of anything unreferenced before the next test.
    instance = QCoreApplication.instance()
    if instance is not None:
        for _ in range(3):
            instance.processEvents()
    gc.collect()
    if instance is not None:
        instance.processEvents()


@pytest.fixture
def window(app):
    """A main window, closed again afterwards so that nothing of it outlives the test."""
    from pyscopegui.ui.main_window import MainWindow

    made = MainWindow()
    made.show()
    yield made
    made.close()
    made.deleteLater()
