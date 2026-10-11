# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Main window: instrument bar, dockable panes, persistent layout."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl, Slot
from PySide6.QtGui import (
    QAction,
    QActionGroup,
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
from pyscopegui.core.acquire import AUTO, STOP, Acquisition
from pyscopegui.core.capture import HISTORIES, HISTORY_S, Capture
from pyscopegui.core.context import Context
from pyscopegui.core.events import PROBLEMS, EventLog
from pyscopegui.core.excepthook import ExceptionLogger
from pyscopegui.ui import event_colours, theme
from pyscopegui.ui.help_menu import HelpMenu
from pyscopegui.ui.instrument_bar import InstrumentBar
from pyscopegui.ui.instrument_view import InstrumentView
from pyscopegui.ui.panes import PaneKind, Panes
from pyscopegui.ui.scope_view import ScopeView
from pyscopegui.ui.trigger_bar import TriggerBar

# Bumped whenever the set of docks changes. restoreState declines a state
# saved under a different version, so an old layout is replaced by the current
# default instead of being restored with panes missing.
LAYOUT_VERSION = 3

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

HISTORY_KEY = "capture.history_s"
HISTORY_TIP = (
    "How much of each channel is kept, for the plot to go back over. Past it the\n"
    "oldest samples are dropped. It is all held in memory: four bytes a sample\n"
    "for an analog channel and one for a digital one, and half as much again,\n"
    "so ten minutes of two channels at 1 MS/s is about 7 GB.\n"
    "A change starts the instrument again."
)


def short_time(seconds: float) -> str:
    """600 -> "10 min", 0.001 -> "1 ms": a length of time as it is said."""
    for unit, size in (("min", 60.0), ("s", 1.0), ("ms", 1e-3)):
        if seconds >= size:
            return f"{seconds / size:.3g} {unit}"
    return f"{seconds * 1e6:.3g} us" if seconds > 0 else "0 s"


def short_bytes(count: int) -> str:
    for unit, size in (("GB", 1e9), ("MB", 1e6)):
        if count >= size:
            return f"{count / size:.3g} {unit}"
    return f"{count / 1e3:.3g} kB"


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
        self.capture = Capture(history_s=self._saved_history(), parent=self)
        self.capture.gap.connect(self._on_gap)
        #: Stop, Single, Normal or Auto, and the trigger they wait for.
        self.acquisition = Acquisition(self.capture, parent=self)
        self.acquisition.single_done.connect(self._on_single_done)
        self.acquisition.changed.connect(self._tell_trigger)
        self.acquisition.longest_window = self._longest_window
        #: Whichever back end was last opened, kept until another is chosen.
        self.instrument: Instrument | None = None
        self._instrument_name = ""
        #: True while a run is stopped only to be started again, so that the
        #: buttons do not show a stop nobody asked for.
        self._restarting = False

        self.instrument_bar = InstrumentBar(self.ctx)
        self.addToolBar(self.instrument_bar)
        self.instrument_bar.open_requested.connect(self.open_instrument)
        self.instrument_bar.close_requested.connect(self.close_instrument)
        self.instrument_bar.mode_requested.connect(self.set_mode)
        self.trigger_bar = TriggerBar(self.acquisition, self.ctx)
        self.addToolBar(self.trigger_bar)
        self.capture.channels_changed.connect(self._show_trigger_sources)

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
        self.history_menu = self._history_menu()
        settings_menu.addMenu(self.history_menu)
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
    def _have(self, name: str) -> bool:
        """Make the instrument called this, if it is not the one there is. False if it cannot be."""
        if self.instrument is not None and name == self._instrument_name:
            return True
        self._drop_instrument()
        try:
            instrument = backends.create(name, self, self.ctx.settings.get(f"instrument.{name}"))
        except Exception as exc:
            # Not ImportError alone: a maker's library that is installed
            # and will not load fails however it likes.
            self.events.error(
                f"{backends.title(name)} could not be started: {type(exc).__name__}: {exc}"
            )
            return False
        instrument.block.connect(self._on_block)
        instrument.opened_changed.connect(self._on_opened)
        instrument.state_changed.connect(self._on_state)
        instrument.error.connect(self.events.error)
        instrument.note.connect(self.events.information)
        instrument.warning.connect(self.events.warning)
        self.instrument, self._instrument_name = instrument, name
        # Its channels, empty, in place of whatever the one before left: to
        # be looked at, and to choose a trigger from, before anything is run.
        self._make_records()
        return True

    @Slot(str)
    def open_instrument(self, name: str = "") -> None:
        """Connect to the instrument called this, or the one chosen, and leave it stopped."""
        if not self._have(name or self.instrument_bar.current()):
            self.instrument_bar.set_open(False)
            return
        # Now, and not when it says so: a scope takes seconds to open, and
        # the button has to offer Close for all of them.
        self.instrument_bar.set_open(True)
        self.instrument.open()

    @Slot()
    def close_instrument(self) -> None:
        """Stop, and let go of the instrument. What is on the plot stays."""
        self._show_mode(STOP)
        if self.instrument is not None:
            self.instrument.close()
        self.instrument_bar.set_open(self.instrument is not None and self.instrument.is_open)

    @Slot(str)
    def set_mode(self, mode: str) -> None:
        """Stop, or run as Single, Normal or Auto: opening the instrument if it is not open."""
        if mode == STOP:
            self._show_mode(STOP)
            if self.instrument is not None and self.instrument.running:
                self.instrument.stop()
            return
        if not self._have(self.instrument_bar.current()):
            self._show_mode(STOP)
            return
        if not self.instrument.running:
            # Before it starts, so that an instrument that triggers itself is
            # told from the first whether to wait for ever or not.
            self.acquisition.set_mode(mode)
            if not self._begin():
                self._show_mode(STOP)
                return
        self.instrument_bar.set_open(True)
        self._show_mode(mode)

    def run(self, name: str = "") -> None:
        """Choose the instrument called this and run it as Auto, from an empty plot."""
        box = self.instrument_bar.instrument
        if name and name != self.instrument_bar.current():
            self.close_instrument()
            box.setCurrentIndex(box.findData(name))
        self.set_mode(STOP)
        self.set_mode(AUTO)

    def stop(self) -> None:
        self.set_mode(STOP)

    def _show_mode(self, mode: str) -> None:
        self.acquisition.set_mode(mode)
        self.instrument_bar.set_mode(mode)
        if hasattr(self, "status"):
            self._update_status()

    def _make_records(self) -> bool:
        """Empty records for the instrument's channels. False, and said, if there is no room."""
        try:
            self.capture.set_channels(
                self.instrument.channels(),
                self.instrument.rate,
                # One sweep at a time, whatever its length turns out to be.
                capacity=1 if self.instrument.sweeps else None,
            )
        except MemoryError:
            self.events.error(
                f"There is not enough memory to keep {short_time(self.capture.history_s)} of "
                f"every channel at {short_rate(self.instrument.rate)}. Choose a shorter "
                "history under Tools > Settings > History, or a lower sample rate."
            )
            return False
        return True

    def _begin(self) -> bool:
        """Start a run, from an empty plot with time counted from zero. False if it could not."""
        if not self._make_records():
            return False
        if not self.instrument.sweeps:
            self.events.information(
                f"Keeping the last {short_time(self.capture.history_s)} of each channel: up to "
                f"{short_bytes(self.capture.memory_bytes())} of memory at this rate."
            )
        self.acquisition.reset()
        self._tell_trigger()
        self.instrument.start()
        return True

    def _tell_trigger(self) -> None:
        """Tell the instrument what is being waited for, in case it triggers itself."""
        if self.instrument is None:
            return
        acquisition = self.acquisition
        self.instrument.set_trigger(
            acquisition.source,
            acquisition.level,
            acquisition.rising,
            acquisition.position,
            # Normal and Single wait for a trigger however long it takes.
            auto=acquisition.mode == AUTO,
        )

    def _restart(self, change=None) -> None:
        """Stop the run, make a change that needs it stopped, and run again as it was."""
        mode = self.acquisition.mode
        self._restarting = True
        try:
            self.instrument.stop()
            if change is not None:
                change()
            started = self._begin()
        finally:
            self._restarting = False
        self._show_mode(mode if started else STOP)

    def _longest_window(self) -> float:
        """The longest stretch of time any plot shows, which is what Single waits for."""
        views = (self.panes.view(name) for name in self.panes.instances("scope"))
        return max((view.window_s.value() for view in views if view is not None), default=0.0)

    @Slot(object)
    def _on_block(self, block) -> None:
        self.capture.add(block)
        self.acquisition.examine(block)

    @Slot()
    def _on_single_done(self) -> None:
        self.set_mode(STOP)

    def _show_trigger_sources(self) -> None:
        self.trigger_bar.set_channels([r.channel for r in self.capture.records.values()])

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

        One that is live is taken up as the instrument runs, and what is on
        the plot is kept. Anything else changes what the samples are -- how
        many a second, of which channels -- so a run in progress is stopped
        and started again from an empty plot. Either way the instrument stays
        open, which is what makes it quick.
        """
        name = self.instrument_bar.current()
        options = self._options(name)
        options[key] = value
        self.ctx.settings.set(f"instrument.{name}", options)
        if self.instrument is None or name != self._instrument_name:
            return
        if not live and self.instrument.running:
            self._restart(lambda: self.instrument.set(key, value))
            return
        self.instrument.set(key, value)
        if live:
            # The same channels, on a new range: named for it, with what is held kept.
            self.capture.update_channels(self.instrument.channels())

    def _drop_instrument(self) -> None:
        if self.instrument is not None:
            self.instrument.close()
            self.instrument.deleteLater()
        self.instrument, self._instrument_name = None, ""

    @Slot(bool)
    def _on_opened(self, is_open: bool) -> None:
        if self.sender() is not self.instrument:
            return
        self.instrument_bar.set_open(is_open)
        if is_open:
            # Now that it knows which model it is: the ranges that one has.
            self.instrument_view.show_settings(
                self.instrument.settings_offered(), self._options(self._instrument_name)
            )
        else:
            self._show_mode(STOP)
        self._update_status()

    @Slot(bool)
    def _on_state(self, running: bool) -> None:
        # A scope says it has stopped from its own thread, so the word can
        # arrive after it has been replaced: only the one there is now counts.
        if self.sender() is not self.instrument:
            return
        title = backends.title(self._instrument_name)
        if running:
            count = len(self.instrument.channels())
            if self.instrument.sweeps:
                # The rate is the instrument's to choose, and it says what it chose.
                self.events.information(f"{title}: running, {count} channels in blocks.")
            else:
                rate = short_rate(self.instrument.rate)
                self.events.information(f"{title}: running, {count} channels at {rate}.")
        else:
            self.events.information(f"{title}: stopped.")
            if not self._restarting:
                # It stopped by itself -- a scope unplugged -- or was told to.
                self._show_mode(STOP)
        self._update_status()

    @Slot(int)
    def _on_gap(self, missing: int) -> None:
        self.events.warning(
            f"{missing} samples did not arrive in time and are shown as a gap. "
            "The samples after them keep their place in time."
        )

    def _update_status(self) -> None:
        if self.instrument is None:
            self.status.setText("No instrument open: choose one and press Open, or Auto to run it.")
            return
        held = (self.capture.newest() or 0.0) - (self.capture.oldest() or 0.0)
        if self.instrument.running:
            doing = f"running ({self.acquisition.mode})"
        else:
            doing = "open, stopped" if self.instrument.is_open else "closed"
        self.status.setText(
            f"{backends.title(self._instrument_name)}: {doing}, "
            f"{short_rate(self.instrument.rate)}, {short_time(held)} held"
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
                lambda name: ScopeView(
                    self.capture, self.ctx, key=name, acquisition=self.acquisition
                ),
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
                "No hardware? Press Auto on Demo signals and there will be something to look at."
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
        self.help_menu.shutdown()
        self.exceptions.remove()
        super().closeEvent(event)

    # --- how much is kept ----------------------------------------------------------------
    def _saved_history(self) -> float:
        """The history chosen, or the default for anything that is not one of the choices."""
        saved = self.ctx.settings.get(HISTORY_KEY, HISTORY_S)
        return float(saved) if saved in HISTORIES else HISTORY_S

    def _history_menu(self) -> QMenu:
        """*Tools > Settings > History*: how long a stretch of each channel is kept."""
        menu = QMenu("History", self)
        menu.setToolTipsVisible(True)
        menu.menuAction().setToolTip(HISTORY_TIP)
        group = QActionGroup(menu)
        group.setExclusive(True)
        for seconds in HISTORIES:
            action = QAction(short_time(seconds), menu, checkable=True)
            action.setChecked(seconds == self.capture.history_s)
            action.setToolTip(HISTORY_TIP)
            action.triggered.connect(lambda _on=False, s=seconds: self.set_history(s))
            group.addAction(action)
            menu.addAction(action)
        return menu

    def set_history(self, seconds: float) -> None:
        """Keep this much of each channel from now on.

        The records are made at the size they will need, so an instrument
        that is running is started again, as for any change to how it is set up.
        """
        if seconds == self.capture.history_s:
            return
        self.capture.history_s = seconds
        self.ctx.settings.set(HISTORY_KEY, seconds)
        if self.instrument is not None and self.instrument.running:
            self._restart()

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
