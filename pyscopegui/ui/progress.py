# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Writing a large file without the window standing still.

The writing is done on a thread of its own, and a progress bar shows how far
it has got, with Cancel. The window goes on drawing what arrives meanwhile;
the bar only appears when the writing takes long enough to want one.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QEventLoop, Qt, QThread, Signal
from PySide6.QtWidgets import QProgressDialog, QWidget

#: How long the writing goes on before the bar appears, in milliseconds.
SHOWN_AFTER_MS = 500
#: The bar's steps, from nothing to done.
STEPS = 1000


class CancelledError(Exception):
    """Cancel was pressed: what was being written is not finished."""


class _Job(QThread):
    moved = Signal(int)

    def __init__(self, job: Callable[[Callable[[int], None]], Any], total: int) -> None:
        super().__init__()
        self._job = job
        self._total = max(1, total)
        self.cancelled = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None

    def _progress(self, done: int) -> None:
        if self.cancelled.is_set():
            raise CancelledError
        self.moved.emit(min(STEPS, done * STEPS // self._total))

    def run(self) -> None:
        try:
            self.result = self._job(self._progress)
        except BaseException as exc:  # handed to the GUI thread, which raises it
            self.error = exc


def with_progress(
    parent: QWidget | None,
    title: str,
    total: int,
    job: Callable[[Callable[[int], None]], Any],
) -> Any:
    """Run ``job`` on a thread of its own while a progress bar says how far it
    has got, and give back what it returns, or raise what it raised: CancelledError
    when Cancel was pressed.

    ``job`` is handed something to call with how much of ``total`` it has
    done; it must touch nothing the GUI thread may change while it runs.
    """
    worker = _Job(job, total)
    dialog = QProgressDialog(title, "Cancel", 0, STEPS, parent)
    dialog.setWindowTitle(title)
    dialog.setWindowModality(Qt.WindowModal)
    dialog.setMinimumDuration(SHOWN_AFTER_MS)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)
    dialog.setValue(0)
    dialog.canceled.connect(worker.cancelled.set)
    worker.moved.connect(dialog.setValue)
    waiting = QEventLoop()
    worker.finished.connect(waiting.quit)
    worker.start()
    if not worker.isFinished():
        waiting.exec()
    worker.wait()
    dialog.close()
    dialog.deleteLater()
    if worker.error is not None:
        raise worker.error
    return worker.result
