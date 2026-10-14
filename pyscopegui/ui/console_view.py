# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The Python Console pane: a Python prompt with the window and the scopes in it.

Built on the standard library's ``code.InteractiveConsole``, so it behaves as
the ``python`` prompt does: blocks over several lines, ``...`` to carry on,
tracebacks as Python prints them. What is printed is caught by swapping
``sys.stdout`` and ``sys.stderr`` for the length of each statement only.

Code runs on the window's thread, which is what lets it touch the window
without locking. The commands that wait -- for an instrument to open, for a
capture -- keep the window going while they do: see
``pyscopegui.ui.scripting``.

*Run script...* runs a file with the same names.
"""

from __future__ import annotations

import code
import contextlib
import io
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QTextCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pyscopegui.core.context import Context
from pyscopegui.ui import fonts

#: Where the last script was run from, so the next is looked for there.
SCRIPT_FOLDER = "console.folder"

BANNER = """pyscopegui console -- Python {ver}
  add("rigol1000z")          add an instrument      choose(name)  which one the rest are about
  open() / close()           connect, let go        set(key, value) / get(key)  its settings
  run("auto") / stop()       the run buttons        single(timeout=30)  one capture, waited for
  read()                     Read, for a scope read as it is
  trigger("CH1", level=0.5, rising=True, position=0.5)
  channels()                 every channel's name   data("Rigol CH1")  (times, samples)
  export_csv(path) / export_png(path)               wait(seconds)  a script's sleep
  window, ctx, session       the window, settings, every instrument's samples
Type help(single), or dir(), to explore."""


class _Console(code.InteractiveConsole):
    """An interactive console whose errors are shown in it, as Python shows them.

    The standard one hands an error to ``sys.excepthook`` whenever a program
    has replaced it, and pyscopegui has: its hook reports what escapes its own
    code as a bug in pyscopegui. A mistake in what was typed is the typist's,
    and belongs under the line that made it.
    """

    def showtraceback(self) -> None:
        kind, value, tb = sys.exc_info()
        # The first entry is this console's own call into the typed code.
        self.write("".join(traceback.format_exception(kind, value, tb.tb_next if tb else None)))

    def showsyntaxerror(self, filename=None, **_kwargs) -> None:
        kind, value, _tb = sys.exc_info()
        self.write("".join(traceback.format_exception_only(kind, value)))


class _HistoryLineEdit(QLineEdit):
    """A line to type in, with Up and Down going through what was typed before."""

    def __init__(self) -> None:
        super().__init__()
        self.history: list[str] = []
        self._pos = 0
        self._draft = ""

    def remember(self, line: str) -> None:
        if line and (not self.history or self.history[-1] != line):
            self.history.append(line)
        self._pos = len(self.history)
        self._draft = ""

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Up, Qt.Key_Down) and self.history:
            if self._pos == len(self.history):
                self._draft = self.text()
            self._pos += -1 if event.key() == Qt.Key_Up else 1
            self._pos = max(0, min(self._pos, len(self.history)))
            self.setText(self.history[self._pos] if self._pos < len(self.history) else self._draft)
            return
        super().keyPressEvent(event)


class ConsoleView(QWidget):
    def __init__(self, namespace: dict, ctx: Context) -> None:
        super().__init__()
        self.ctx = ctx
        self.namespace = namespace
        self.console = _Console(namespace)
        mono = fonts.mono()

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(mono)
        self.output.setMaximumBlockCount(5000)
        # Short before the line typed in is: in a low pane it is the output that gives way.
        self.output.setMinimumHeight(self.output.fontMetrics().lineSpacing() * 2)
        self.prompt = QLabel(">>>")
        self.prompt.setFont(mono)
        self.input = _HistoryLineEdit()
        self.input.setFont(mono)
        self.input.returnPressed.connect(self._on_enter)
        run_button = QPushButton("Run script...")
        run_button.setToolTip(
            "Run a Python file here, with the same names this console has:\n"
            "add, open, set, run, single, data, export_csv and the rest."
        )
        run_button.clicked.connect(self._run_script_dialog)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.output.clear)

        row = QHBoxLayout()
        row.addWidget(self.prompt)
        row.addWidget(self.input, 1)
        row.addWidget(run_button)
        row.addWidget(clear)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.addWidget(self.output)
        layout.addLayout(row)

        self._write(BANNER.format(ver=sys.version.split()[0]) + "\n")

    # --- running what was typed -------------------------------------------------------------
    def _on_enter(self) -> None:
        line = self.input.text()
        self.input.clear()
        self.input.remember(line)
        self._write(f"{self.prompt.text()} {line}\n")
        more = self._capture(lambda: self.console.push(line))
        self.prompt.setText("..." if more else ">>>")

    def type(self, line: str) -> None:
        """Type a line and press Enter, as somebody would."""
        self.input.setText(line)
        self._on_enter()

    def run_source(self, source: str, filename: str = "<script>") -> None:
        """Run a whole script with the console's names: what *Run script...* does."""
        self._write(f"--- running {filename}\n")

        def go():
            compiled = compile(source, filename, "exec")
            exec(compiled, self.namespace)

        self._capture(go)

    def _capture(self, run):
        buffer = io.StringIO()
        result = None
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            try:
                result = run()
            except SystemExit:
                buffer.write("(SystemExit ignored)\n")
            except Exception:  # the console shows its own; this is for a script
                kind, value, tb = sys.exc_info()
                # The first entries are this pane's own calls into the script.
                while tb is not None and tb.tb_frame.f_code.co_filename == __file__:
                    tb = tb.tb_next
                buffer.write("".join(traceback.format_exception(kind, value, tb)))
        if text := buffer.getvalue():
            self._write(text if text.endswith("\n") else text + "\n")
        return result

    def _run_script_dialog(self) -> None:
        folder = self.ctx.settings.get(SCRIPT_FOLDER)
        start = folder if isinstance(folder, str) else str(self.ctx.user_dir)
        chosen, _filter = QFileDialog.getOpenFileName(
            self, "Run Python script", start, "Python (*.py)"
        )
        if chosen:
            self.ctx.settings.set(SCRIPT_FOLDER, str(Path(chosen).parent))
            self.run_file(chosen)

    def run_file(self, path: str | Path) -> None:
        path = Path(path)
        try:
            self.run_source(path.read_text(encoding="utf-8"), str(path))
        except (OSError, UnicodeDecodeError) as exc:
            self._write(f"cannot read {path}: {exc}\n")

    # --- what it says -----------------------------------------------------------------------
    def _write(self, text: str) -> None:
        self.output.moveCursor(QTextCursor.End)
        self.output.insertPlainText(text)
        self.output.moveCursor(QTextCursor.End)

    def text(self) -> str:
        return self.output.toPlainText()
