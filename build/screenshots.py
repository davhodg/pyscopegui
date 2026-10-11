# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Take a screenshot of the window on its demo instrument.

    python build/screenshots.py

Opens pyscopegui on the demo instrument for a few seconds, with temporary
settings of its own so that nothing of yours is read or changed, and writes
``build/work/demo-window.png``. Leave the window alone while it runs.

Not the picture the README shows: that one, ``pyscopegui/help/main-window.png``,
is of two real scopes and was taken by hand. This is for seeing how the
window looks after a change, and is not kept.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
OUTPUT = PROJECT / "build" / "work" / "demo-window.png"
#: A window that fits a README column without being shrunk past reading.
SIZE = (1200, 760)
#: Long enough for the plot to have filled and the list to show values.
RUN_MS = 2500


def main() -> int:
    # Before pyscopegui is imported: where it keeps things is read as it starts.
    os.environ["PYSCOPEGUI_HOME"] = tempfile.mkdtemp(prefix="pyscopegui-shot-")
    sys.path.insert(0, str(PROJECT))

    from PySide6.QtCore import QSettings, QTimer
    from PySide6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(
        QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp(prefix="pyscopegui-shot-")
    )
    app = QApplication(sys.argv)

    from pyscopegui.__main__ import set_icon
    from pyscopegui.ui import theme
    from pyscopegui.ui.main_window import MainWindow

    set_icon(app)
    # The same picture whatever this computer is set to.
    theme.apply(theme.LIGHT)
    window = MainWindow()
    window.resize(*SIZE)
    window.show()
    window.set_mode("auto")
    # Triggered on the sine, so the picture shows the trigger and stands still.
    source = window.trigger_bar.source
    source.setCurrentIndex(source.findData("A"))
    source.activated.emit(source.currentIndex())

    def take() -> None:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        window.grab().save(str(OUTPUT))
        window.close()
        app.quit()

    QTimer.singleShot(RUN_MS, take)
    app.exec()
    print(f"wrote {OUTPUT.relative_to(PROJECT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
