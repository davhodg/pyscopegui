# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Main window: instrument bar, dockable panes, persistent layout."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl, Slot
from PySide6.QtGui import (
    QAction,
    QDesktopServices,
    QFont,
    QKeySequence,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QStatusBar,
)

from pyscopegui import APP_NAME, __version__, backends
from pyscopegui.backends.base import Instrument
from pyscopegui.core import shortcut
from pyscopegui.core.capture import Capture
from pyscopegui.core.context import Context
from pyscopegui.core.events import PROBLEMS, EventLog
from pyscopegui.core.excepthook import ExceptionLogger
from pyscopegui.ui import event_colours, theme
from pyscopegui.ui.help_menu import HelpMenu
from pyscopegui.ui.instrument_bar import InstrumentBar
from pyscopegui.ui.instrument_view import InstrumentView
from pyscopegui.ui.panes import PaneKind, Panes
from pyscopegui.ui.scope_view import ScopeView

# Bumped whenever the set of docks changes. restoreState declines a state
# saved under a different version, so an old layout is replaced by the current
# default instead of being restored with panes missing.
LAYOUT_VERSION = 2

#: Open on a first run. Everything else is one click away in the View menu.
DEFAULT_VISIBLE = ("instrument", "scope", "log")

#: How near the bottom of the Event Log still counts as being at the bottom,
#: in scrollbar steps. Exactly at the end is too strict: a line arriving
#: while the last one is part-scrolled would then stop following.
AT_END = 4

#: What the window opens at, and what Reset layout puts it back to. Wide,
#: because a time axis wants every pixel of width there is.
DEFAULT_WIDTH = 1400
DEFAULT_HEIGHT = 900

STATUS_MS = 500


def short_rate(rate: float) -> str:
    """100000 -> "100 kS/s": a sample rate as it is said."""
    for unit, size in (("MS/s", 1e6), ("kS/s", 1e3)):
        if rate >= size:
            return f"{rate / size:g} {unit}"
    return f"{rate:g} S/s"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)
        self.setDockNestingEnabled(True)  # full grid layouts, not just the four edges

        # --- log pane first: everything else reports into it -----------------
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        # Everything is kept, however long the session: the line that matters
        # is often the first of a thousand. Clear, on the right-click, empties it.
        self.log.setMaximumBlockCount(0)
        self.log.setContextMenuPolicy(Qt.CustomContextMenu)
        self.log.customContextMenuRequested.connect(self._log_menu)
        #: Every line said to the user arrives here with a level, and this is
        #: the only thing that writes to the pane. Warnings and errors open it
        #: if it has been closed; notes do not.
        self.events = EventLog()
        self._surfacing = False
        self.events.posted.connect(self._on_event)

        self.ctx = Context(events=self.events)
        #: Started with pythonw, which has no console, so a traceback from a
        #: Qt slot would otherwise go nowhere at all -- see the module.
        self.exceptions = ExceptionLogger(self.events.post)
        self.exceptions.install()

        # --- the instrument, and what it has sent ------------------------------
        self.capture = Capture(parent=self)
        self.capture.gap.connect(self._on_gap)
        #: Whichever back end was last run, kept so that Run again reuses it.
        self.instrument: Instrument | None = None
        self._instrument_name = ""

        self.instrument_bar = InstrumentBar(self.ctx)
        self.addToolBar(self.instrument_bar)
        self.instrument_bar.run_requested.connect(self.run)
        self.instrument_bar.stop_requested.connect(self.stop)

        # --- panes -----------------------------------------------------------
        self.panes = Panes(self, self.ctx)
        self._register_panes()
        # The first of each kind is named after its kind, which is the name
        # every saved layout and setting knows it by.
        self.instrument_view = self.panes.view(self.panes.add("instrument"))
        self.instrument_view.changed.connect(self._on_setting)
        self.instrument_bar.instrument.currentIndexChanged.connect(lambda _i: self._show_settings())
        self._show_settings()
        self.scope = self.panes.view(self.panes.add("scope"))
        self.panes.add("log")
        self._arrange_default()

        self.setStatusBar(QStatusBar())
        self.status = QLabel()
        self.statusBar().addWidget(self.status, 1)
        self._status_timer = QTimer(self, interval=STATUS_MS, timeout=self._update_status)
        self._status_timer.start()
        self._update_status()

        # --- menus & layout persistence --------------------------------------
        file_menu = self.menuBar().addMenu("&File")
        quit_action = file_menu.addAction("Exit", self.close)
        quit_action.setMenuRole(QAction.QuitRole)
        quit_action.setShortcut(QKeySequence.Quit)

        self.view_menu = self.menuBar().addMenu("&View")
        self.view_menu.setToolTipsVisible(True)
        self._view_actions: dict[str, QAction] = {}
        self.reset_layout_action = QAction("Reset layout", self)
        self.reset_layout_action.setToolTip(
            "Put the panes back where they start, in a window the size it opens at."
        )
        self.reset_layout_action.triggered.connect(self._reset_layout)
        # Built as it opens: which panes there are changes while the window is up.
        self.view_menu.aboutToShow.connect(self._build_view_menu)
        self._build_view_menu()

        tools_menu = self.menuBar().addMenu("&Tools")
        tools_menu.setToolTipsVisible(True)
        self.settings_menu = settings_menu = QMenu("Settings", tools_menu)
        settings_menu.setToolTipsVisible(True)
        tools_menu.addMenu(settings_menu)
        self.theme_menu = theme.menu(self)
        settings_menu.addMenu(self.theme_menu)
        if shortcut.launcher() is not None:
            # Only for a source folder: the installer makes its own entry.
            settings_menu.addSeparator()
            self.shortcut_action = settings_menu.addAction(
                f"Add shortcut to {shortcut.menu_name()}", self._add_shortcut
            )
        folder = tools_menu.addAction("Open settings folder", self._open_settings_folder)
        folder.setToolTip("Where settings.json and the pane arrangement are kept.")

        self.help_menu = HelpMenu(self)

        self._restore_layout()
        self.panes.restore_state()

    # --- the instrument ----------------------------------------------------------------
    @Slot(str)
    def run(self, name: str) -> None:
        """Start reading the instrument called this, from an empty plot."""
        self.stop()
        if self.instrument is None or name != self._instrument_name:
            self._drop_instrument()
            try:
                options = self.ctx.settings.get(f"instrument.{name}")
                instrument = backends.create(name, self, options)
            except Exception as exc:
                # Not ImportError alone: a maker's library that is installed
                # and will not load fails however it likes.
                self.events.error(
                    f"{backends.title(name)} could not be started: {type(exc).__name__}: {exc}"
                )
                self.instrument_bar.set_running(False)
                return
            instrument.block.connect(self.capture.add)
            instrument.state_changed.connect(self._on_state)
            instrument.error.connect(self.events.error)
            instrument.note.connect(self.events.information)
            instrument.warning.connect(self.events.warning)
            self.instrument, self._instrument_name = instrument, name
        self.capture.set_channels(self.instrument.channels(), self.instrument.rate)
        self.instrument.start()
        # Now, and not when it says so: a scope takes seconds to open, and
        # the button has to offer Stop for all of them.
        self.instrument_bar.set_running(self.instrument.running)

    @Slot()
    def stop(self) -> None:
        if self.instrument is not None and self.instrument.running:
            self.instrument.stop()

    def _options(self, name: str) -> dict:
        """What is saved for this instrument. Empty for anything that is not a dictionary."""
        saved = self.ctx.settings.get(f"instrument.{name}")
        return dict(saved) if isinstance(saved, dict) else {}

    def _show_settings(self) -> None:
        """Fill the Instrument pane for whichever instrument is chosen."""
        name = self.instrument_bar.current()
        try:
            settings = backends.settings(name)
        except Exception as exc:
            self.events.error(
                f"{backends.title(name)}: its settings could not be read: "
                f"{type(exc).__name__}: {exc}"
            )
            settings = ()
        self.instrument_view.show_settings(settings, self._options(name))

    @Slot(str, object, bool)
    def _on_setting(self, key: str, value: object, live: bool) -> None:
        """Save a setting, and have the instrument take it up.

        One that is live is handed to the instrument as it runs. Anything else
        is part of how it was set up, so the instrument is made again with it:
        started again if it was running, and otherwise at the next Run.
        """
        name = self.instrument_bar.current()
        options = self._options(name)
        options[key] = value
        self.ctx.settings.set(f"instrument.{name}", options)
        if self.instrument is None or name != self._instrument_name:
            return
        if live:
            self.instrument.set(key, value)
            return
        was_running = self.instrument.running
        self._drop_instrument()
        if was_running:
            self.run(name)

    def _drop_instrument(self) -> None:
        if self.instrument is not None:
            self.instrument.stop()
            self.instrument.deleteLater()
        self.instrument, self._instrument_name = None, ""

    @Slot(bool)
    def _on_state(self, running: bool) -> None:
        # A scope says it has stopped from its own thread, so the word can
        # arrive after it has been replaced: one made again for a changed
        # setting would otherwise be shown as stopped by the one before it.
        if self.sender() is not self.instrument:
            return
        self.instrument_bar.set_running(running)
        title = backends.title(self._instrument_name)
        if running:
            count = len(self.instrument.channels())
            rate = short_rate(self.instrument.rate)
            self.events.information(f"{title}: running, {count} channels at {rate}.")
        else:
            self.events.information(f"{title}: stopped.")
        self._update_status()

    @Slot(int)
    def _on_gap(self, missing: int) -> None:
        self.events.warning(
            f"{missing} samples did not arrive in time and are shown as a gap. "
            "The samples after them keep their place in time."
        )

    def _update_status(self) -> None:
        if self.instrument is None:
            self.status.setText("No instrument running: choose one and press Run.")
            return
        held = (self.capture.newest() or 0.0) - (self.capture.oldest() or 0.0)
        self.status.setText(
            f"{backends.title(self._instrument_name)}: "
            f"{'running' if self.instrument.running else 'stopped'}, "
            f"{short_rate(self.instrument.rate)}, {held:.1f} s held"
        )

    # --- panes ---------------------------------------------------------------------------
    def _register_panes(self) -> None:
        """Every sort of pane, in the order the View menu lists them."""
        self.panes.register(
            PaneKind("instrument", "Instrument", Qt.LeftDockWidgetArea, lambda _n: InstrumentView())
        )
        self.panes.register(
            PaneKind(
                "scope",
                "Channels and Plot",
                Qt.TopDockWidgetArea,
                lambda name: ScopeView(self.capture, self.ctx, key=name),
                several=True,
            )
        )
        self.panes.register(
            PaneKind("log", "Event Log", Qt.BottomDockWidgetArea, lambda _name: self.log)
        )

    def _view_order(self) -> list[str]:
        """The panes in the order they were registered, extras after the first of a kind."""
        order = []
        for kind in self.panes.kinds:
            order.extend(name for name in self.panes.instances(kind) if name in self.panes.docks)
        order.extend(name for name in self.panes.names() if name not in order)
        return order

    def _pane_action(self, name: str) -> QAction:
        """A pane's entry in the View menu: ticked while it is on screen, anywhere."""
        action = QAction(self.panes.docks[name].windowTitle(), self.view_menu)
        action.setCheckable(True)
        action.setChecked(self.panes.on_screen(name))
        action.triggered.connect(lambda _checked=False, n=name: self._view_picked(n))
        self._view_actions[name] = action
        return action

    def _view_picked(self, name: str) -> None:
        """Show a pane, bring its window to the front, or put a docked one away."""
        dock = self.panes.docks.get(name)
        if dock is None:
            return
        if name in self.panes.detached or not self.panes.on_screen(name):
            self.panes.show(name)
        else:
            dock.hide()

    def _build_view_menu(self) -> None:
        """Every pane, and the things you can do to the set of them."""
        self.view_menu.clear()
        self._view_actions = {}
        for name in self._view_order():
            self.view_menu.addAction(self._pane_action(name))
        self.view_menu.addSeparator()

        standard = self.view_menu.addMenu("Standard panes")
        standard.setToolTipsVisible(True)
        for kind in self.panes.kinds.values():
            if not kind.several or kind.named:
                continue
            action = standard.addAction(
                f"Additional {kind.title}", lambda k=kind.name: self.panes.add(k, floating=True)
            )
            action.setToolTip(
                f"Open another {kind.title} pane, with settings of its own.\n"
                "It opens in a window of its own; drag it into the main window\n"
                "to dock it, or onto another pane to tab the two together."
            )

        rename = self.view_menu.addMenu("Rename pane")
        for name in self.panes.names():
            rename.addAction(
                self.panes.docks[name].windowTitle(), lambda n=name: self._rename_pane(n)
            )

        extras = self.panes.extras()
        remove = self.view_menu.addMenu("Remove pane")
        remove.setEnabled(bool(extras))
        remove.setToolTipsVisible(True)
        for name in extras:
            action = remove.addAction(
                self.panes.docks[name].windowTitle(), lambda n=name: self.panes.remove(n)
            )
            action.setToolTip("Close this pane for good. Closing its window only puts it away.")

        self.view_menu.addSeparator()
        self.view_menu.addAction("Dock all panes", self.panes.dock_all)
        self.view_menu.addAction(self.reset_layout_action)

    def _rename_pane(self, name: str) -> None:
        dock = self.panes.docks.get(name)
        if dock is None:
            return
        title, chose = QInputDialog.getText(
            self,
            "Rename pane",
            f"A name for it, or nothing for {self.panes.default_title(name)}:",
            text=dock.windowTitle(),
        )
        if chose:
            self.panes.rename(name, title)

    def _arrange_default(self) -> None:
        """The layout a first run opens with, and what Reset layout goes back to.

            +------------+-------------------+
            | Instrument | Channels and Plot |
            +------------+-------------------+
            |           Event Log            |
            +--------------------------------+

        The plot gets most of the room; the settings are a narrow column
        beside it, and the log is the thing you glance at rather than work in.
        """
        instrument, scope, log = (self.panes.docks[n] for n in DEFAULT_VISIBLE)
        self.addDockWidget(Qt.TopDockWidgetArea, instrument)
        self.splitDockWidget(instrument, log, Qt.Vertical)
        self.splitDockWidget(instrument, scope, Qt.Horizontal)
        for name, dock in self.panes.docks.items():
            dock.setFloating(False)
            dock.setVisible(name in DEFAULT_VISIBLE)
        # The inner division first, and the outer through a dock that sits
        # directly in it: an outer call re-divides what an inner one settled.
        self.resizeDocks([instrument, scope], [1, 5], Qt.Horizontal)
        self.resizeDocks([log, scope], [1, 4], Qt.Vertical)

    def _restore_layout(self) -> None:
        # Where the window sits stays in QSettings: that belongs to this desk
        # and these monitors.
        if (geo := QSettings().value("geometry")) is not None:
            self.restoreGeometry(geo)
        self.panes.restore_instances()
        state = self.ctx.layout.get("window")
        # restoreState declines a layout saved under an older LAYOUT_VERSION,
        # which leaves the default in place -- the same as never having run.
        restored = state is not None and self.restoreState(state, LAYOUT_VERSION)
        if restored:
            self.panes.note_placed()
        elif state is not None:
            # Said rather than silently starting from the default: somebody
            # who had arranged the panes deserves to know why they moved.
            self.events.information(
                "The saved pane arrangement is from a version with a different set "
                "of panes, so this window opens with the default one."
            )
            self.panes.forget_arrangement()
        else:
            self.events.information(
                "No hardware? Press Run on Demo signals and there will be something to look at."
            )
        self.panes.restore_view_states()

    def _reset_layout(self) -> None:
        """Put the panes back where they start, in a window the size it opens at."""
        self.showNormal()  # maximised or full screen, resizing does nothing
        screen = self.screen() or QApplication.primaryScreen()
        available = screen.availableGeometry()
        self.resize(min(DEFAULT_WIDTH, available.width()), min(DEFAULT_HEIGHT, available.height()))
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())
        self._arrange_default()

    def save_arrangement(self) -> None:
        self.ctx.layout.set("window", bytes(self.saveState(LAYOUT_VERSION)))
        self.panes.save_view_states()
        self.panes.save()

    def closeEvent(self, event) -> None:
        QSettings().setValue("geometry", self.saveGeometry())
        # Saved before they are closed: closing one puts its pane away, and
        # what is saved should be how things were left.
        self.save_arrangement()
        # Parentless windows of their own, so they would keep the application
        # running after the main window had gone.
        self.panes.close_detached()
        self._status_timer.stop()
        self._drop_instrument()
        self.exceptions.remove()
        super().closeEvent(event)

    # --- settings ------------------------------------------------------------------------
    def _add_shortcut(self) -> None:
        try:
            path = shortcut.create()
        except OSError as exc:
            self.events.warning(f"Could not add {APP_NAME} to the {shortcut.menu_name()}: {exc}")
            return
        self.events.information(f"Added {APP_NAME} to the {shortcut.menu_name()}: {path}")

    def _open_settings_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ctx.user_dir)))

    # --- the Event Log -------------------------------------------------------------------
    @Slot(str, str)
    def _on_event(self, message: str, level: str) -> None:
        """The only thing that writes to the Event Log pane.

        Written through a cursor rather than appendPlainText so the line can
        carry a format, and as text rather than as HTML so that a traceback
        keeps its indentation.

        The view is only dragged to the bottom if it was already there:
        somebody scrolled up reading should not be pulled away by the next line.
        """
        bar = self.log.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - AT_END
        cursor = QTextCursor(self.log.document())
        cursor.movePosition(QTextCursor.End)
        if not self.log.document().isEmpty():
            cursor.insertBlock()
        shape = QTextCharFormat()
        dark = event_colours.dark_behind(self.log.palette())
        if (colour := event_colours.colour_for(level, dark)) is not None:
            shape.setForeground(colour)
        if event_colours.bold_for(level):
            shape.setFontWeight(QFont.Bold)
        cursor.insertText(message, shape)
        self.log.viewport().update()
        if at_end:
            bar.setValue(bar.maximum())
        if level in PROBLEMS:
            self._surface_log()

    def _log_menu(self, at) -> None:
        menu = self.log.createStandardContextMenu()
        menu.addSeparator()
        menu.addAction("Clear", self.log.clear)
        menu.exec(self.log.viewport().mapToGlobal(at))
        menu.deleteLater()

    def _surface_log(self) -> None:
        """Open the Event Log, because something in it needs reading.

        Deferred by a turn of the event loop: a problem raised while the
        window is still being built would otherwise be undone by the saved
        layout, and a burst of them should cost one show rather than twenty.
        """
        if self._surfacing:
            return
        self._surfacing = True
        QTimer.singleShot(0, self._show_log)

    def _show_log(self) -> None:
        self._surfacing = False
        panes = getattr(self, "panes", None)
        dock = None if panes is None else panes.docks.get("log")
        if dock is None or "log" in panes.detached:
            return  # too early to have a pane, or it has a window of its own
        if not dock.isVisible():
            dock.show()
        dock.raise_()  # it may be docked but tabbed behind another pane
