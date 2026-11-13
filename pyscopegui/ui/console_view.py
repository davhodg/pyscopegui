# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The Python Console pane: a Python prompt with the window and the scopes in it.

Built on the standard library's ``code.InteractiveConsole``, so it behaves as
the ``python`` prompt does: blocks over several lines, ``...`` to carry on
one, tracebacks as Python prints them. The box typed into takes several lines
as well -- Shift+Enter for another, or several pasted at once -- and Enter then
runs them together, as one block. What is printed is shown as it is printed,
so a script that captures ten times says so one capture at a time. The same
as pyflashgui's console.

Code runs on the window's thread, which is what lets it touch the window
without locking. The commands that wait -- for an instrument to open, for a
capture -- keep the window going while they do: see
``pyscopegui.ui.scripting``. Stop is pressed while they wait, and stops the
script there.

*Run script...* runs a file with the same names.
"""

from __future__ import annotations

import ast
import code
import io
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QTextCursor, QTextOption
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pyscopegui.core.context import Context
from pyscopegui.ui import clear_menu, fonts, icons
from pyscopegui.ui.scripting import ScriptError, Scripting, ScriptStoppedError

#: Where the last script was run from, so the next is looked for there.
SCRIPT_FOLDER = "console.folder"

BANNER = """pyscopegui console -- Python {ver}
  add("rigol1000z")          add an instrument      choose(name)  which one the rest are about
  open() / close()           connect, let go        set(key, value) / get(key)  its settings
  run("auto") / stop()       the run buttons        single(timeout=30)  one capture, waited for
  read()                     Read, for a scope read as it is
  trigger("CH1", level=0.5, rising=True, position=0.5)
  channels()                 every channel's name   data("Rigol CH1")  (times, samples)
  rename("CH1", "5V rail")   a name of its own, shown as 5V rail (CH1); "" puts it back
  axis("CH2", 2)             draw it against Y2, on the right; axis("CH2") says which
  measure("Rigol CH1")       its levels and frequency, between the cursors
  maths("CH1", "-", "CH2")   a maths channel of the chosen instrument;
  maths("CH1", "ddt")        or of one channel: neg abs sq sqrt ddt int,
                             scale (k=, c=, unit=), avg (over=, seconds)
  export_csv(path) / export_png(path)               wait(seconds)  a script's sleep
  window, ctx, session       the window, settings, every instrument's samples
Shift+Enter for another line, or paste several: Enter runs them together.
Type help(single), or dir(), to explore."""

RUN_TIP = (
    "Run a Python file here, with the same names this console has:\n"
    "add, open, set, run, single, data, export_csv and the rest."
)
STOP_TIP = (
    "Stop the script, or what was typed, at the command it is waiting in or\n"
    "the next one it calls. A capture it was waiting for is stopped too."
)
#: The most lines the box typed into grows to before it scrolls.
TALLEST = 10
#: What Tab puts in, and what a line after a colon is indented by.
INDENT = "    "
#: How much the pane keeps, in lines. A script printing in a loop for an
#: hour must not take the memory with it.
MOST_LINES = 5000


def _said(kind, value) -> str | None:
    """How a script's own errors are shown: as a sentence, not a traceback."""
    if issubclass(kind, ScriptStoppedError):
        return "Stopped.\n"
    if issubclass(kind, ScriptError):
        return f"ScriptError: {value}\n"
    return None


def _past_us(tb):
    """A traceback from where the typed code or the script begins: without this
    pane's own calls into it, nor the commands' wrapper."""
    while tb is not None and tb.tb_frame.f_code.co_filename in (__file__, code.__file__):
        tb = tb.tb_next
    return tb


class _Console(code.InteractiveConsole):
    """An interactive console whose errors are shown in it, as Python shows them.

    The standard one hands an error to ``sys.excepthook`` whenever a program
    has replaced it, and pyscopegui has: its hook reports what escapes its own
    code as a bug in pyscopegui. A mistake in what was typed is the typist's,
    and belongs under the line that made it.
    """

    def showtraceback(self) -> None:
        kind, value, tb = sys.exc_info()
        if (said := _said(kind, value)) is not None:
            self.write(said)
            return
        self.write("".join(traceback.format_exception(kind, value, _past_us(tb))))

    def showsyntaxerror(self, filename=None, **_kwargs) -> None:
        kind, value, _tb = sys.exc_info()
        self.write("".join(traceback.format_exception_only(kind, value)))

    def write(self, data: str) -> None:
        sys.stderr.write(data)


class _Shown(io.TextIOBase):
    """Printed text, into the pane as it is printed."""

    def __init__(self, view: ConsoleView) -> None:
        super().__init__()
        self._view = view

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        self._view.write(text)
        return len(text)


class _Typed(QPlainTextEdit):
    """What is typed: a line, or several, with Up and Down going through what
    was typed before.

    Enter is the end of it, and says so with ``entered``; Shift+Enter is
    another line, indented as the one before and further after a colon. One
    line tall until there is more, so that it looks like the prompt it mostly is.
    """

    entered = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.history: list[str] = []
        self._pos = 0
        self._draft = ""
        self.setWordWrapMode(QTextOption.NoWrap)
        self.setTabChangesFocus(False)
        self.textChanged.connect(self._fit)
        self._fit()

    # Named as QLineEdit's are, which is what this was and what its callers use.
    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str) -> None:
        self.setPlainText(text)
        self.moveCursor(QTextCursor.End)

    def _fit(self) -> None:
        lines = min(max(self.document().blockCount(), 1), TALLEST)
        margins = self.contentsMargins()
        frame = 2 * int(self.document().documentMargin()) + margins.top() + margins.bottom()
        self.setFixedHeight(self.fontMetrics().lineSpacing() * lines + frame)

    def _new_line(self) -> None:
        """Another line, indented as this one, and further after a colon."""
        line = self.textCursor().block().text()
        indent = line[: len(line) - len(line.lstrip())]
        if line.rstrip().endswith(":"):
            indent += INDENT
        self.insertPlainText("\n" + indent)

    def remember(self, typed: str) -> None:
        if typed and (not self.history or self.history[-1] != typed):
            self.history.append(typed)
        self._pos = len(self.history)
        self._draft = ""

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                self._new_line()
            else:
                self.entered.emit()
            return
        if event.key() == Qt.Key_Tab:
            self.insertPlainText(INDENT)
            return
        cursor = self.textCursor()
        # Within what is typed, Up and Down move between its lines; only from
        # the first line, or the last, do they go through what came before.
        on_edge = (event.key() == Qt.Key_Up and cursor.blockNumber() == 0) or (
            event.key() == Qt.Key_Down and cursor.blockNumber() == self.document().blockCount() - 1
        )
        if event.key() in (Qt.Key_Up, Qt.Key_Down) and self.history and on_edge:
            if self._pos == len(self.history):
                self._draft = self.text()
            self._pos += -1 if event.key() == Qt.Key_Up else 1
            self._pos = max(0, min(self._pos, len(self.history)))
            self.setText(self.history[self._pos] if self._pos < len(self.history) else self._draft)
            return
        super().keyPressEvent(event)


class ConsoleView(QWidget):
    #: A file was run, by the button here or from the File menu: its path.
    ran = Signal(str)

    def __init__(self, namespace: dict, ctx: Context, scripting: Scripting | None = None) -> None:
        super().__init__()
        self.ctx = ctx
        self.namespace = namespace
        #: Whose commands the names are: what Stop tells to stop.
        self.scripting = scripting
        self.console = _Console(namespace)
        #: True while what was typed, or a script, is running. Nothing else is
        #: taken until it has finished, and the window will not close under it.
        self.running = False
        mono = fonts.mono()

        self.output = clear_menu.add(QPlainTextEdit(), ctx, "Console output")
        self.output.setReadOnly(True)
        self.output.setFont(mono)
        self.output.setMaximumBlockCount(MOST_LINES)
        self.output.setAccessibleName("Console output")
        # Short before the box typed in is: in a low pane it is the output that gives way.
        self.output.setMinimumHeight(self.output.fontMetrics().lineSpacing() * 2)
        self.prompt = QLabel(">>>")
        self.prompt.setFont(mono)
        self.prompt.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.input = _Typed()
        self.input.setFont(mono)
        self.input.setAccessibleName("Python")
        self.input.entered.connect(self._on_enter)
        self.run_button = icons.beside(QPushButton("Run script..."), icons.START)
        self.run_button.setToolTip(RUN_TIP)
        self.run_button.clicked.connect(self._run_script_dialog)
        self.stop_button = icons.beside(QPushButton("Stop"), icons.STOP)
        self.stop_button.setToolTip(STOP_TIP)
        self.stop_button.clicked.connect(self.stop)
        # No Clear button, as in pyflashgui: it is rarely wanted, and Clear all
        # is on the output's right-click.

        row = QHBoxLayout()
        row.addWidget(self.prompt, 0, Qt.AlignTop)
        row.addWidget(self.input, 1)
        row.addWidget(self.run_button, 0, Qt.AlignTop)
        row.addWidget(self.stop_button, 0, Qt.AlignTop)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.addWidget(self.output)
        layout.addLayout(row)

        self.write(BANNER.format(ver=sys.version.split()[0]) + "\n")
        self._enable()

    # --- running what was typed -------------------------------------------------------------
    def _on_enter(self) -> None:
        typed = self.input.text()
        self.input.clear()
        self.input.remember(typed)
        if "\n" not in typed:
            self.write(f"{self.prompt.text()} {typed}\n")
            more = self._run(lambda: self.console.push(typed))
            self.prompt.setText("..." if more else ">>>")
            return
        lines = typed.split("\n")
        first = self.prompt.text()
        self.write(
            "".join(f"{first if i == 0 else '...'} {line}\n" for i, line in enumerate(lines))
        )
        # What was begun a line at a time and finished with these.
        source = "\n".join([*self.console.buffer, *lines])
        self.console.resetbuffer()
        self._run(lambda: self._run_block(source))
        self.prompt.setText(">>>")

    def _run_block(self, source: str) -> None:
        """Several lines run as one, each value shown as the prompt shows it.

        Compiled as the prompt compiles one statement, but with all of them:
        "a = 2", "a * 3" shows 6, as typing them one at a time would.
        """
        try:
            tree = ast.parse(source, "<console>")
            compiled = compile(ast.Interactive(body=tree.body), "<console>", "single")
        except (SyntaxError, ValueError, OverflowError):
            self.console.showsyntaxerror("<console>")
            return
        self.console.runcode(compiled)

    def type(self, typed: str) -> None:
        """Type a line, or several, and press Enter, as somebody would."""
        self.input.setText(typed)
        self._on_enter()

    def run_source(self, source: str, filename: str = "<script>") -> None:
        """Run a whole script with the console's names: what *Run script...* does."""
        self.write(f"--- running {filename}\n")

        def go() -> None:
            try:
                exec(compile(source, filename, "exec"), self.namespace)
            except SystemExit:
                print("(the script called exit, which here ends the script and nothing more)")
            except Exception:
                kind, value, tb = sys.exc_info()
                if (said := _said(kind, value)) is not None:
                    sys.stderr.write(said)
                else:
                    sys.stderr.write("".join(traceback.format_exception(kind, value, _past_us(tb))))

        if self._run(go) is not False:
            self.write(f"--- {filename} has finished\n")

    def _run(self, work):
        """Run ``work`` with what it prints shown here, one at a time. False
        where something else was running, and this was not."""
        if self.running:
            return False
        self.running = True
        if self.scripting is not None:
            self.scripting.started()
        self._enable()
        shown = _Shown(self)
        try:
            with redirect_stdout(shown), redirect_stderr(shown):
                return work()
        finally:
            self.running = False
            self._enable()
            self.input.setFocus()

    def stop(self) -> None:
        """Stop what is running, at the command it is in or the next it calls."""
        if self.running and self.scripting is not None:
            self.scripting.halt()

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
        if self.running:
            self.ctx.warn(
                f"{path.name} was not run: the Python Console is still running something."
            )
            return
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self.write(f"cannot read {path}: {exc}\n")
            return
        # Before it runs: a script that fails is still the one to run again.
        self.ran.emit(str(path))
        self.run_source(source, str(path))

    def _enable(self) -> None:
        self.input.setEnabled(not self.running)
        self.run_button.setEnabled(not self.running)
        self.stop_button.setEnabled(self.running)

    # --- what it says -----------------------------------------------------------------------
    def write(self, text: str) -> None:
        self.output.moveCursor(QTextCursor.End)
        self.output.insertPlainText(text)
        self.output.moveCursor(QTextCursor.End)

    def text(self) -> str:
        return self.output.toPlainText()
