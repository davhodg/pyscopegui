# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Take the screenshot the README shows.

    python build/screenshots.py

Opens pyscopegui on the demo instrument for a few seconds, with temporary
settings of its own so that nothing of yours is read or changed, and writes
``pyscopegui/help/main-window.png``. Leave the window alone while it runs.

In the manual's folder because the README and the manual show the same file,
so there is one copy of it and it ships with the manual.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
OUTPUT = PROJECT / "pyscopegui" / "help" / "main-window.png"
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
    window.instrument_bar.run.setChecked(True)

    def take() -> None:
        window.grab().save(str(OUTPUT))
        window.close()
        app.quit()

    QTimer.singleShot(RUN_MS, take)
    app.exec()
    print(f"wrote {OUTPUT.relative_to(PROJECT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
