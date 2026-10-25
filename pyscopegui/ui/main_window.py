# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Main window: instrument bar, dockable panes, persistent layout."""

from __future__ import annotations

import time
from collections import deque
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, Signal, Slot
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QFont,
    QKeySequence,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QStatusBar,
    QToolButton,
)

from pyscopegui import APP_NAME, __version__, backends
from pyscopegui.backends.base import Instrument
from pyscopegui.core import capture_file, decoding, memory, shortcut, workspaces
from pyscopegui.core.acquire import AUTO, SINGLE, STOP, Acquisition
from pyscopegui.core.capture import HISTORIES, HISTORY_S, Capture
from pyscopegui.core.context import Context
from pyscopegui.core.events import PROBLEMS, EventLog
from pyscopegui.core.excepthook import ExceptionLogger
from pyscopegui.core.maths import Maths
from pyscopegui.core.session import Session, Unit
from pyscopegui.core.sharing import Sharer
from pyscopegui.ui import column_widths, event_colours, messages, theme
from pyscopegui.ui.console_view import ConsoleView
from pyscopegui.ui.data_view import DataView
from pyscopegui.ui.decoded_view import DecodedView
from pyscopegui.ui.diagnostics import RECENT_PROBLEMS
from pyscopegui.ui.help_menu import HelpMenu
from pyscopegui.ui.import_dialog import ImportDialog
from pyscopegui.ui.instrument_bar import InstrumentBar
from pyscopegui.ui.instrument_view import InstrumentView
from pyscopegui.ui.measurements_view import MeasurementsView
from pyscopegui.ui.panes import PaneKind, Panes
from pyscopegui.ui.scope_view import ScopeView
from pyscopegui.ui.scripting import Scripting
from pyscopegui.ui.scripts_menu import ScriptsMenu
from pyscopegui.ui.traffic_view import TrafficView
from pyscopegui.ui.trigger_bar import TriggerBar
from pyscopegui.ui.workspace_menu import SWITCH_WHILE_OPEN, WorkspaceMenu

# Bumped whenever the set of docks changes. restoreState declines a state
# saved under a different version, so an old layout is replaced by the current
# default instead of being restored with panes missing.
LAYOUT_VERSION = 3

#: Open on a first run. Everything else is one click away in the View menu.
DEFAULT_VISIBLE = ("instrument", "scope", "log", "measurements")

#: How near the bottom of the Event Log still counts as being at the bottom,
#: in scrollbar steps. Exactly at the end is too strict: a line arriving
#: while the last one is part-scrolled would then stop following.
AT_END = 4

#: What the window opens at, and what Reset layout puts it back to. Wide,
#: because a time axis wants every pixel of width there is.
DEFAULT_WIDTH = 1400
DEFAULT_HEIGHT = 900

STATUS_MS = 500

#: In QSettings, not settings.json: whether this person has been told, on
#: this machine, where a shortcut is made.
SHORTCUT_TOLD_KEY = "shortcut/told"
HISTORY_KEY = "capture.history_s"
#: The share of what is free a run's history may take: Tools > Settings > Memory.
MEMORY_KEY = "capture.memory_share"
#: Where the last capture was opened from or saved to.
CAPTURE_FOLDER = "capture.folder"
#: The instruments in the Instrument pane, by name, and the one chosen.
ADDED_KEY = "instruments.added"
CHOSEN_KEY = "instrument.name"
#: The model each instrument said it was when it was last opened, by name: what its
#: tab and its channels are called, before it is opened again.
MODELS_KEY = "instruments.model"
WIDTHS_TIP = "How wide the columns of the lists are, and whether they can be dragged."
#: In QSettings: whether decoded CAN frames sent by UDP multicast reach the
#: local network. The computer's, not the workspace's: it is about where this
#: computer is, and the same as pycangui's.
UDP_NETWORK_KEY = "udp/local_network"
#: How long after the lead has its Single capture the others are stopped, in
#: milliseconds: for what they took at the same moment to arrive.
FOLLOWERS_LAG_MS = 500
UDP_NETWORK_TIP = (
    "Off, decoded CAN frames sent on by UDP multicast stay on this computer:\n"
    "pycangui and other programs on it hear them, and nothing goes out on a\n"
    "network. On, they reach the local network too, and no further: every\n"
    "computer on it that has joined the group hears them. Use it on a network\n"
    "you trust."
)
WIDTHS_AUTO_TIP = (
    "Every column is as wide as what is in it. Nothing to set, and nothing\n"
    "can be dragged: a long name takes the room it needs."
)
WIDTHS_MANUAL_TIP = (
    "A column fits what is in it up to a limit, and can be dragged to any\n"
    "width, which is remembered. Double-click a column's edge to have it\n"
    "fit its contents again."
)
HISTORY_TIP = (
    "How much of each channel is kept, for the plot to go back over. Past it the\n"
    "oldest samples are dropped. It is all held in memory: four bytes a sample\n"
    "for an analog channel -- two from a PicoScope -- and one for a digital one,\n"
    "so ten minutes of two channels at 1 MS/s is about 4.8 GB, or 2.4 GB from a\n"
    "PicoScope. Tools > Settings > Memory says how much\n"
    "of it a run may take. A change starts the instrument again."
)
MEMORY_TIP = (
    "How much of the memory that is free when a run starts its history may take.\n"
    "The rest is for drawing, measuring and saving it, and for everything else on\n"
    "the computer. Where History would take more, the run keeps as much as fits,\n"
    "and the Event Log says how much. A change starts the instrument again."
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


def window_title() -> str:
    """The workspace is named only when it is not the one everybody has.

    Somebody with a single bench should not be able to tell from the window
    that workspaces were built, and a title bar reading "default" would be the
    one place that gave it away.
    """
    name = workspaces.active()
    return f"{APP_NAME} {__version__}" + ("" if name == workspaces.DEFAULT else f" - {name}")


class MainWindow(QMainWindow):
    #: Open this workspace instead. Emitted rather than acted on, because a
    #: switch is a full reload and the window that asks is the one that goes:
    #: something outside it has to close it and open the next.
    reopen_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(window_title())
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
        #: The last warnings and errors, for Help > Diagnostics: (time, level, text).
        self.recent_problems: deque[tuple[str, str, str]] = deque(maxlen=RECENT_PROBLEMS)
        self.events.posted.connect(self._on_event)

        self.ctx = Context(events=self.events)
        #: Started with pythonw, which has no console, so a traceback from a
        #: Qt slot would otherwise go nowhere at all -- see the module.
        self.exceptions = ExceptionLogger(self.events.post)
        self.exceptions.install()

        # --- the instruments, and what they have sent --------------------------
        #: Every instrument added, each with what it has sent and the
        #: trigger it waits for. The one chosen in the Instrument pane is the
        #: one that pane, Open and the trigger toolbar are about; Stop,
        #: Single, Normal and Auto are for all that are open.
        self.session = Session(history_s=self._saved_history(), parent=self)
        #: How much of what is free a run's history may take.
        self.memory_share = self._saved_share()
        #: Sends decoded CAN frames on, to pycangui and any other python-can program.
        self.sharer = Sharer(
            lambda said, problem: (self.events.warning if problem else self.events.information)(
                said
            )
        )
        #: The instruments in the Instrument pane, by name, in the order they
        #: were added; and the one chosen, or "" when the pane has none.
        self._added, self._chosen = self._saved_instruments()

        self.instrument_bar = InstrumentBar(self.ctx)
        self.addToolBar(self.instrument_bar)
        self.instrument_bar.add_requested.connect(self.add_instrument)
        self.instrument_bar.mode_requested.connect(self.set_mode)
        self.instrument_bar.read_requested.connect(self.read_once)
        self.trigger_bar = TriggerBar(
            self.session, self.ctx, modes=tuple(self.instrument_bar.modes.values())
        )
        self.addToolBar(self.trigger_bar)
        self.session.channels_changed.connect(self._show_trigger_sources)

        # --- panes -----------------------------------------------------------
        self.panes = Panes(self, self.ctx)
        self._register_panes()
        # The first of each kind is named after its kind, which is the name
        # every saved layout and setting knows it by.
        self.instrument_view = self.panes.view(self.panes.add("instrument"))
        self.instrument_view.changed.connect(self._on_setting)
        self.instrument_view.instrument_chosen.connect(self.choose)
        self.instrument_view.instrument_removed.connect(self.remove_instrument)
        self.instrument_view.open_requested.connect(self.open_instrument)
        self.instrument_view.close_requested.connect(self.close_instrument)
        self._on_chosen()
        self.scope = self.panes.view(self.panes.add("scope"))
        self.panes.add("log")
        #: Every command and answer, kept only while it is on screen.
        self.traffic = self.panes.view(self.panes.add("traffic"))
        #: Python, with the window and a few commands to drive the scopes.
        self.console = self.panes.view(self.panes.add("console"))
        #: Each channel's levels and frequency, between the cursors.
        self.measurements = self.panes.view(self.panes.add("measurements"))
        #: The samples themselves, a row for each.
        self.data = self.panes.view(self.panes.add("data"))
        #: What has been read off the channels decoded as buses.
        self.decoded = self.panes.view(self.panes.add("decoded"))
        self.panes.pane_shown.connect(self._on_pane_shown)
        self._arrange_default()

        self.setStatusBar(QStatusBar())
        self.status = QLabel()
        self.statusBar().addWidget(self.status, 1)
        # What the histories take and what is free: pressed, it is the Memory menu.
        self.memory_button = QToolButton(autoRaise=True)
        self.memory_button.setPopupMode(QToolButton.InstantPopup)
        self.statusBar().addPermanentWidget(self.memory_button)
        self._status_timer = QTimer(self, interval=STATUS_MS, timeout=self._update_status)
        self._status_timer.start()
        self._update_status()

        # --- menus & layout persistence --------------------------------------
        file_menu = self.menuBar().addMenu("&File")
        open_action = file_menu.addAction("Open capture...", self.ask_open_capture)
        open_action.setToolTip(
            "Open a capture saved here, or a CSV -- Export CSV's, or any other --\n"
            "and show it beside the instruments, as one of them."
        )
        save_action = file_menu.addAction("Save capture...", self.ask_save_capture)
        save_action.setToolTip(
            "Save everything held, of every instrument on the first plot, to open again\n"
            "later exactly as it is: one file for each instrument."
        )
        file_menu.addSeparator()
        export_action = file_menu.addAction("Export CSV...", lambda: self.scope.ask_export())
        export_action.setToolTip(
            "Write what the first plot shows as CSV: one file for each instrument."
        )
        between_action = file_menu.addAction(
            "Export CSV between cursors...", lambda: self.scope.ask_export(between_cursors=True)
        )
        between_action.setToolTip(
            "Write what is between the first plot's two cursors as CSV: one file for each\n"
            "instrument. With two cursors chosen."
        )
        file_menu.aboutToShow.connect(
            lambda: between_action.setEnabled(self.scope.cursor_count() == 2)
        )
        picture_action = file_menu.addAction("Export PNG...", lambda: self.scope.ask_picture())
        picture_action.setToolTip("Save a picture of the first plot, as it looks now.")
        file_menu.setToolTipsVisible(True)
        file_menu.addSeparator()
        quit_action = file_menu.addAction("Exit", self.close)
        quit_action.setMenuRole(QAction.QuitRole)
        quit_action.setShortcut(QKeySequence.Quit)
        #: A script run in the console, and the last few that were.
        self.scripts_menu = ScriptsMenu(self, self.ctx)
        self.scripts_menu.install(file_menu, before=quit_action)
        self.scripts_menu.run_wanted.connect(self.run_script_in_console)
        # The console's own Run script... button is remembered too.
        self.console.ran.connect(self.scripts_menu.remember)
        #: One workspace per bench or setup: new, save as, switch to and manage.
        self.workspace_menu = WorkspaceMenu(self, self.ctx)
        self.workspace_menu.install(file_menu, before=quit_action)
        self.workspace_menu.switch_requested.connect(self._switch_workspace)

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
        self.memory_menu = self._memory_menu()
        settings_menu.addMenu(self.memory_menu)
        self.memory_button.setMenu(self.memory_menu)
        self.widths_menu = self._widths_menu()
        settings_menu.addMenu(self.widths_menu)
        self.udp_network_action = settings_menu.addAction(
            "Share UDP multicast on the local network"
        )
        self.udp_network_action.setCheckable(True)
        self.udp_network_action.setToolTip(UDP_NETWORK_TIP)
        on = QSettings().value(UDP_NETWORK_KEY, False, type=bool)
        self.udp_network_action.setChecked(on)
        self.sharer.set_local_network(on)
        self.udp_network_action.toggled.connect(self._share_on_network)
        # For a source folder and for pip: the installer makes its own entries.
        self.shortcut_action = self.desktop_action = None
        if shortcut.start() is not None:
            settings_menu.addSeparator()
            for place in shortcut.places():
                name = shortcut.place_name(place)
                action = settings_menu.addAction(
                    f"Add shortcut to {name}", lambda place=place: self._add_shortcut(place)
                )
                action.setToolTip(
                    f"Start {APP_NAME} from the {name}. From a source folder the entry\n"
                    "starts the launcher, so after a pull it still picks up new\n"
                    "libraries, as double-clicking the launcher does. Replaces one\n"
                    "made before."
                )
                if place == shortcut.ON_DESKTOP:
                    self.desktop_action = action
                else:
                    self.shortcut_action = action

        self.help_menu = HelpMenu(self)

        self._say_how_to_add_a_shortcut()
        self._restore_layout()
        self.panes.restore_state()
        # As it was left: recording while it is on screen, and not otherwise.
        self.traffic.listen(self.panes.on_screen("traffic"))

    # --- the instruments ---------------------------------------------------------------
    def _unit(self, name: str) -> Unit:
        """The unit for the instrument called this, made and wired up if it is new."""
        new = name not in self.session.units
        unit = self.session.unit(name, self._short(name))
        if new:
            unit.capture.gap.connect(self._on_gap)
            unit.capture.decoded.connect(self._on_decoded)
            unit.acquisition.single_done.connect(lambda u=unit: self._on_single_done(u))
            unit.acquisition.changed.connect(lambda u=unit: self._tell_trigger(u))
            unit.acquisition.longest_window = self._longest_window
            self.trigger_bar.prime(unit)
            # Its maths channels, as they were: made once its channels are there.
            saved = self.ctx.settings.get(f"maths.{name}")
            found = [Maths.from_saved(s) for s in saved] if isinstance(saved, list) else []
            unit.capture.set_maths([m for m in found if m is not None])
            # And the buses it had decoded.
            saved = self.ctx.settings.get(f"{decoding.SAVED_KEY}.{name}")
            setups = [decoding.from_saved(s) for s in saved] if isinstance(saved, list) else []
            unit.capture.set_decodings([s for s in setups if s is not None])
            # Those that were paused, still paused.
            paused = self.ctx.settings.get(f"{decoding.PAUSED_KEY}.{name}")
            for each in unit.capture.decodings:
                each.pause(isinstance(paused, list) and each.key in paused)
        return unit

    def _short(self, name: str) -> str:
        """A word for an instrument: the model it was when last opened, or its kind's."""
        models = self.ctx.settings.get(MODELS_KEY)
        model = models.get(name) if isinstance(models, dict) else None
        return backends.short(name, model if isinstance(model, str) else "")

    def _saved_instruments(self) -> tuple[list[str], str]:
        """The instruments that were in the pane last time, and the one chosen.

        Anything saved that is not an instrument there is now is left out.
        With nothing saved there is the one chosen before there was a list, or
        the demo; a pane every instrument was taken out of is empty again.
        """
        saved = self.ctx.settings.get(ADDED_KEY)
        added: list[str] = []
        for name in saved if isinstance(saved, list) else []:
            if backends.known(name) and name not in added:
                added.append(name)
        chosen = self.ctx.settings.get(CHOSEN_KEY)
        if not added and saved != []:
            added = [chosen if backends.known(chosen) else backends.DEFAULT]
        return added, chosen if chosen in added else (added[0] if added else "")

    def _save_instruments(self) -> None:
        self.ctx.settings.set(ADDED_KEY, list(self._added))
        self.ctx.settings.set(CHOSEN_KEY, self._chosen)

    @property
    def added(self) -> list[str]:
        """The instruments in the Instrument pane, by name."""
        return list(self._added)

    @property
    def chosen(self) -> str:
        """The name of the instrument chosen in the Instrument pane: "" when it has none."""
        return self._chosen

    @property
    def unit(self) -> Unit | None:
        """The instrument chosen in the Instrument pane: None when it has none."""
        return self._unit(self._chosen) if self._chosen else None

    @Slot(str)
    def add_instrument(self, kind: str) -> str:
        """Put one more instrument of this kind in the Instrument pane, and choose it.

        It is not opened: how it is reached may have to be said first.
        """
        if kind not in backends.BACKENDS:
            return ""
        name = backends.another(kind, self._added)
        self._added.append(name)
        self.choose(name)
        self.panes.show("instrument")
        return name

    @Slot(str)
    def remove_instrument(self, name: str = "") -> None:
        """Close the instrument called this, or the one chosen, and take it out of the pane.

        Its settings stay saved, for when one of its kind is added again. The
        last one can go too, and the pane is empty until another is added.
        """
        name = name or self._chosen
        if name not in self._added:
            return
        unit = self.session.units.get(name)
        if unit is not None:
            unit.acquisition.set_mode(STOP)
            self._drop_unit(unit)
            unit.capture.set_channels([], 1.0)
            self.session.forget(name)
        at = self._added.index(name)
        self._added.remove(name)
        if self._chosen == name:
            # The one beside it: after it, or before it if it was the last.
            self._chosen = self._added[min(at, len(self._added) - 1)] if self._added else ""
            self._save_instruments()
            self._on_chosen()
        else:
            self._save_instruments()
            self._show_open()
        self._settle_mode()

    @Slot(str)
    def choose(self, name: str) -> None:
        """Choose the instrument called this, as pressing its tab does. One that
        is not in the pane yet, and is of a kind there is, is put there."""
        if name not in self._added:
            if not backends.known(name):
                return
            self._added.append(name)
        if name != self._chosen or name not in self.instrument_view.listed():
            self._chosen = name
            self._save_instruments()
            self._on_chosen()

    @property
    def instrument(self) -> Instrument | None:
        return unit.instrument if (unit := self.unit) is not None else None

    @property
    def capture(self) -> Capture:
        return self.unit.capture

    @property
    def acquisition(self) -> Acquisition:
        return self.unit.acquisition

    def _in_use(self) -> list[Unit]:
        """The units with an instrument behind them."""
        return [unit for unit in self.session.units.values() if unit.instrument is not None]

    def _have(self, name: str) -> bool:
        """Make the instrument called this, if there is not one. False if it cannot be."""
        unit = self._unit(name)
        if unit.instrument is not None:
            return True
        try:
            instrument = backends.create(name, self, self.ctx.settings.get(f"instrument.{name}"))
        except Exception as exc:
            # Not ImportError alone: a maker's library that is installed
            # and will not load fails however it likes.
            self.events.error(
                f"{backends.title(name)} could not be started: {type(exc).__name__}: {exc}"
            )
            return False
        # An instrument says things from its own thread, so the word can
        # arrive after it has been replaced: each is told which it came from.
        instrument.block.connect(lambda block, u=unit: self._on_block(u, block))
        instrument.opened_changed.connect(
            lambda on, u=unit, i=instrument: self._on_opened(u, i, on)
        )
        instrument.state_changed.connect(lambda on, u=unit, i=instrument: self._on_state(u, i, on))
        instrument.error.connect(self.events.error)
        instrument.note.connect(self.events.information)
        instrument.warning.connect(self.events.warning)
        instrument.activity.connect(lambda text, u=unit: self._on_activity(u, text))
        unit.instrument = instrument
        # Its channels, empty: to be looked at, and to choose a trigger
        # from, before anything is run.
        self._make_records(unit)
        return True

    def _forget_closed(self, keep: Unit) -> None:
        """Let go of what is left of instruments that have been closed.

        A closed instrument's traces stay on the plot to be looked at, until
        another is opened or run: then they would be beside something they
        have nothing to do with.
        """
        for unit in self.session.units.values():
            if unit is keep or unit.wanted_open or unit.running:
                continue
            self._drop_unit(unit)
            if unit.capture.records:
                unit.capture.set_channels([], 1.0)
                unit.acquisition.reset()

    @Slot(str)
    def open_instrument(self, name: str = "") -> None:
        """Connect to the instrument called this, or the one chosen, and leave it stopped."""
        # An address typed and not yet finished with is the one meant.
        self.instrument_view.commit()
        name = name or self._chosen
        if not name:
            return
        unit = self._unit(name)
        self._forget_closed(unit)
        if not self._have(name):
            self._show_open()
            return
        # Now, and not when it says so: a scope takes seconds to open, and
        # the button has to offer Close for all of them.
        unit.wanted_open = True
        self._show_open()
        unit.instrument.open()

    @Slot()
    def close_instrument(self) -> None:
        """Stop, and let go of the instrument chosen. What is on the plot stays."""
        unit = self.unit
        if unit is None:
            return
        unit.acquisition.set_mode(STOP)
        if unit.instrument is not None:
            unit.instrument.close()
        unit.wanted_open = unit.is_open
        self._settle_mode()
        self._show_open()

    def _show_open(self) -> None:
        """Say in the Instrument pane which instruments there are, which are
        open, and whether the one chosen is."""
        unit = self.unit
        self.instrument_view.set_open(unit is not None and (unit.wanted_open or unit.is_open))
        units = self.session.units
        self.instrument_view.set_instruments(
            [
                (
                    name,
                    units[name].short if name in units else self._short(name),
                    self._described(name),
                    name in units and (units[name].wanted_open or units[name].is_open),
                )
                for name in self._added
            ],
            self._chosen,
        )
        self._show_reading()

    def _described(self, name: str) -> str:
        """What an instrument is, in full, for its tab's tip. A capture file's tab
        says only File, so which file is said here."""
        title = backends.title(name)
        if backends.kind(name) == "file":
            path = self._options(name).get("path")
            if isinstance(path, str) and path:
                return f"{title}: {Path(path).name}\n{Path(path).parent}"
        return title

    @staticmethod
    def _as_is(unit: Unit | None) -> bool:
        """Whether an instrument is read as it is: no trigger of ours, only what it shows."""
        return unit is not None and unit.instrument is not None and unit.instrument.reads_as_is

    def _takes(self, unit: Unit, mode: str) -> bool:
        """Whether a run button means anything to an instrument. Single and Normal
        wait for a trigger, and one read as it is has none here to wait for."""
        return mode == AUTO or not self._as_is(unit)

    def _show_reading(self) -> None:
        """Offer what there is for an instrument read as it is: Read, and no trigger."""
        chosen = self.unit
        as_is = self._as_is(chosen)
        self.instrument_bar.set_reads(as_is, busy=as_is and chosen.running)
        # Single and Normal are for whatever a run button would run.
        ran = [unit for unit in self._in_use() if unit is chosen or unit.wanted_open]
        self.instrument_bar.set_triggered(not ran or not all(self._as_is(u) for u in ran))
        self.trigger_bar.show_usable()

    def run_script_in_console(self, path: str) -> None:
        """File > Run script... and Recent scripts: in the console, shown, so
        that what the script prints is there to be read."""
        self.panes.show("console")
        self.console.run_file(path)

    # --- captures in files -------------------------------------------------------------------
    def ask_open_capture(self) -> None:
        """Ask which files, and for a CSV how it is laid out, and open each."""
        folder = self.ctx.settings.get(CAPTURE_FOLDER)
        chosen, _filter = QFileDialog.getOpenFileNames(
            self,
            "Open capture",
            folder if isinstance(folder, str) else "",
            "Captures (*.npz *.csv *.txt);;pyscopegui captures (*.npz);;CSV (*.csv *.txt);;"
            "All files (*)",
        )
        for text in chosen:
            path = Path(text)
            self.ctx.settings.set(CAPTURE_FOLDER, str(path.parent))
            if capture_file.is_own(path):
                self.open_capture(path)
                continue
            dialog = ImportDialog(path, self)
            if dialog.exec() == QDialog.Accepted:
                self.open_capture(path, dialog.layout())

    def open_capture(self, path: Path, layout=None) -> str:
        """Open a capture file as an instrument of its own, and put it on the plot.
        Its name, in the Instrument pane."""
        name = backends.another("file", self._added)
        options = {"path": str(path)}
        if layout is not None:
            options["csv"] = layout.as_options()
        self.ctx.settings.set(f"instrument.{name}", options)
        self.choose(name)
        self.open_instrument()
        if self.unit.is_open:
            self.read_once()
        return name

    def ask_save_capture(self) -> None:
        folder = self.ctx.settings.get(CAPTURE_FOLDER)
        start = str(Path(folder) / "capture.npz") if isinstance(folder, str) else "capture.npz"
        chosen, _filter = QFileDialog.getSaveFileName(
            self, "Save capture", start, "pyscopegui captures (*.npz)"
        )
        if chosen:
            self.ctx.settings.set(CAPTURE_FOLDER, str(Path(chosen).parent))
            self.scope.save_captures(Path(chosen))

    @Slot()
    def read_once(self) -> None:
        """Read what the instrument chosen shows, once, and leave the others as they are."""
        self.instrument_view.commit()
        unit = self.unit
        if unit is None:
            return
        self._forget_closed(unit)
        if not self._have(unit.name):
            self._show_open()
            return
        unit.wanted_open = True
        if unit.instrument.running:
            unit.instrument.stop()
        unit.acquisition.set_mode(SINGLE)
        if not self._begin(unit):
            unit.acquisition.set_mode(STOP)
        self._show_open()
        self._update_status()

    @Slot(str)
    def set_mode(self, mode: str) -> None:
        """Stop, or run as Single, Normal or Auto: every instrument that is open, and the
        one chosen, which is opened if it is not."""
        if mode == STOP:
            self._show_mode(STOP)
            for unit in self._in_use():
                if unit.instrument.running:
                    unit.instrument.stop()
            return
        self.instrument_view.commit()
        chosen = self.unit
        if chosen is None:
            # Nothing in the pane, so nothing open to run either.
            self._settle_mode()
            return
        self._forget_closed(chosen)
        if not self._have(chosen.name):
            self._settle_mode()
            return
        if self._takes(chosen, mode):
            chosen.wanted_open = True
        for unit in self._in_use():
            if not (unit is chosen or unit.wanted_open) or not self._takes(unit, mode):
                continue
            # Before it starts, so that an instrument that triggers itself is
            # told from the first whether to wait for ever or not.
            unit.acquisition.set_mode(mode)
            if not unit.instrument.running and not self._begin(unit):
                unit.acquisition.set_mode(STOP)
        self._show_open()
        if any(unit.running for unit in self._in_use()):
            self._show_mode(mode)
        else:
            self._show_mode(STOP)

    def run(self, name: str = "") -> None:
        """Choose the instrument called this and run it as Auto, from an empty plot."""
        if name and name != self._chosen:
            self.close_instrument()
            self.choose(name)
        self.set_mode(STOP)
        self.set_mode(AUTO)

    def stop(self) -> None:
        self.set_mode(STOP)

    def _show_mode(self, mode: str) -> None:
        """Press in the button for what is being done. Stop is said to every instrument."""
        if mode == STOP:
            for unit in self.session.units.values():
                unit.acquisition.set_mode(STOP)
        self.instrument_bar.set_mode(mode)
        if hasattr(self, "status"):
            self._update_status()

    def _settle_mode(self) -> None:
        """Show Stop once nothing is running any more."""
        if not any(unit.running or unit.restarting for unit in self._in_use()):
            self._show_mode(STOP)

    def _make_records(self, unit: Unit) -> bool:
        """Empty records for an instrument's channels. False, and said, if there is no room."""
        instrument = unit.instrument
        try:
            unit.capture.set_channels(
                instrument.channels(),
                instrument.rate,
                # One sweep at a time, whatever its length turns out to be.
                capacity=1 if instrument.sweeps else None,
                # No more of the history than there is memory for.
                room=lambda: memory.room(self.memory_share),
            )
        except MemoryError:
            self.events.error(
                f"There is not enough memory to keep every channel at "
                f"{short_rate(instrument.rate)}, even for a moment. Choose a lower sample "
                "rate, or fewer channels, or close other programs."
            )
            return False
        return True

    def _begin(self, unit: Unit) -> bool:
        """Start a run, from an empty plot with time counted from zero. False if it could not."""
        if not self._make_records(unit):
            return False
        unit.clock.reset()
        if not unit.instrument.sweeps:
            capture = unit.capture
            held, wanted = capture.held_s(), capture.history_s
            if held < wanted * 0.999:
                self.events.warning(
                    f"Keeping the last {short_time(held)} of each channel, not "
                    f"{short_time(wanted)}: at {short_rate(unit.instrument.rate)} that is all "
                    f"there is memory for ({short_bytes(capture.memory_bytes())}, "
                    f"{self.memory_share:.0%} of what was free: Tools > Settings > Memory). "
                    "A lower sample rate, or fewer channels, keeps more."
                )
            else:
                self.events.information(
                    f"Keeping the last {short_time(held)} of each channel: up to "
                    f"{short_bytes(capture.memory_bytes())} of memory at this rate."
                )
        unit.acquisition.reset()
        self._tell_trigger(unit)
        unit.instrument.start()
        return True

    def _tell_trigger(self, unit: Unit) -> None:
        """Tell an instrument what is being waited for, in case it triggers itself."""
        if unit.instrument is None:
            return
        acquisition = unit.acquisition
        unit.instrument.set_trigger(
            acquisition.source,
            acquisition.level,
            acquisition.rising,
            acquisition.position,
            # Normal and Single wait for a trigger however long it takes.
            auto=acquisition.mode == AUTO,
            condition=acquisition.condition,
        )

    def _restart(self, unit: Unit, change=None) -> None:
        """Stop a run, make a change that needs it stopped, and run again as it was."""
        unit.restarting = True
        try:
            unit.instrument.stop()
            if change is not None:
                change()
            started = self._begin(unit)
        finally:
            unit.restarting = False
        if not started:
            unit.acquisition.set_mode(STOP)
            self._settle_mode()

    def _longest_window(self) -> float:
        """The longest stretch of time any plot shows, which is what Single waits for."""
        views = (self.panes.view(name) for name in self.panes.instances("scope"))
        return max((view.window_s.value() for view in views if view is not None), default=0.0)

    def _on_block(self, unit: Unit, block) -> None:
        unit.clock.saw(block)
        unit.capture.add(block)
        unit.acquisition.examine(block)

    def _on_activity(self, unit: Unit, text: str) -> None:
        """An instrument says what it is busy with: shown, so that a slow one is not
        taken for one that has stopped."""
        unit.doing = text
        self._update_status()

    def _on_single_done(self, unit: Unit) -> None:
        """One instrument has its capture: it stops, and the others go on waiting
        for theirs. With a lead, its capture is everyone's: the others stop
        too, once what they took at the same moment has had time to arrive,
        and their own triggers are not waited for."""
        lead = self.session.lead
        if lead is not None and lead in self.session.units and unit.name != lead:
            return  # it follows the lead, and stops when the lead does
        unit.acquisition.set_mode(STOP)
        if unit.running:
            unit.instrument.stop()
        if lead == unit.name:
            QTimer.singleShot(FOLLOWERS_LAG_MS, self._stop_followers)
        self._settle_mode()

    def _stop_followers(self) -> None:
        """Stop the instruments following the lead, which has its Single capture."""
        for unit in self._in_use():
            if unit.name != self.session.lead:
                unit.acquisition.set_mode(STOP)
                if unit.running:
                    unit.instrument.stop()
        self._settle_mode()

    def _show_trigger_sources(self) -> None:
        self.trigger_bar.show_leads()
        for unit in self.session.units.values():
            self.trigger_bar.set_channels(unit)

    def _options(self, name: str) -> dict:
        """What is saved for this instrument. Empty for anything that is not a dictionary."""
        saved = self.ctx.settings.get(f"instrument.{name}")
        return dict(saved) if isinstance(saved, dict) else {}

    def _on_chosen(self) -> None:
        """Another instrument was chosen: the pane, the trigger and Open are about it now."""
        self._show_settings()
        self.trigger_bar.bind(self.unit)
        self._show_open()
        if hasattr(self, "status"):
            self._update_status()

    def offered(self, name: str) -> tuple:
        """What can be set on this instrument, as it is with what is chosen:
        the ranges its model has, in amps on a channel with a current probe."""
        unit = self._unit(name)
        # Once open, it knows which model it is: the ranges that one has.
        settings = unit.instrument.settings_offered() if unit.is_open else backends.settings(name)
        return backends.fitted(name, settings, self._options(name))

    def _show_settings(self) -> None:
        """Fill the Instrument pane for whichever instrument is chosen."""
        name = self._chosen
        if not name:
            self.instrument_view.show_none()
            return
        try:
            settings = self.offered(name)
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
        name = self._chosen
        if not name:
            return
        options = self._options(name)
        before = self._offered_quietly(name)
        options[key] = value
        self.ctx.settings.set(f"instrument.{name}", options)
        if self._offered_quietly(name) != before:
            # A probe changed what a channel is measured in, or what its
            # scales are: the pane says so. Its controls go once this is done.
            self._show_settings()
        unit = self._unit(name)
        instrument = unit.instrument
        if instrument is None:
            return
        was_as_is = self._as_is(unit)
        if not live and instrument.running:
            self._restart(unit, lambda: instrument.set(key, value))
        else:
            instrument.set(key, value)
            if live:
                # The same channels, on a new range: named for it, with what is held kept.
                unit.capture.update_channels(instrument.channels())
        if self._as_is(unit) and not was_as_is:
            self._show_whole_snapshots()
        # How it is read may be what changed, and with it what the toolbar offers.
        self._show_reading()

    def _offered_quietly(self, name: str) -> tuple:
        """What offered says, or nothing where that fails: _show_settings says why."""
        try:
            return self.offered(name)
        except Exception:
            return ()

    def _show_whole_snapshots(self) -> None:
        """Have every plot show all it holds, for an instrument read as it is.

        Done once, when it is set to be read that way or is opened so: what it
        sends is a snapshot of its screen, and Follow's stretch of time around
        the trigger can cut it short. What is chosen after that is left alone.
        """
        for name in self.panes.instances("scope"):
            if (view := self.panes.view(name)) is not None:
                view.show_all()

    def _drop_unit(self, unit: Unit) -> None:
        if unit.instrument is not None:
            unit.instrument.close()
            unit.instrument.deleteLater()
        unit.instrument, unit.wanted_open = None, False

    def _on_opened(self, unit: Unit, instrument: Instrument, is_open: bool) -> None:
        if unit.instrument is not instrument:
            return
        unit.wanted_open = is_open
        if not is_open:
            unit.acquisition.set_mode(STOP)
            self._settle_mode()
        else:
            self._name_for_model(unit, instrument.model)
            if unit is self.unit:
                self._show_settings()
            if self._as_is(unit):
                self._show_whole_snapshots()
        self._show_open()
        self._update_status()

    def _name_for_model(self, unit: Unit, model: str) -> None:
        """Call an instrument by the model it says it is, and its channels with it,
        and remember the model for the next time it is started."""
        if not model:
            return
        models = self.ctx.settings.get(MODELS_KEY)
        models = dict(models) if isinstance(models, dict) else {}
        if models.get(unit.name) != model:
            models[unit.name] = model
            self.ctx.settings.set(MODELS_KEY, models)
        short = backends.short(unit.name, model)
        if short != unit.short:
            unit.short = short
            self.session.channels_changed.emit()

    def _on_state(self, unit: Unit, instrument: Instrument, running: bool) -> None:
        if unit.instrument is not instrument:
            return
        title = backends.title(unit.name)
        # A file is put on the plot whole, and that is all: its "running" and
        # "stopped" are a moment apart and say nothing. Opening it is said.
        quiet = backends.kind(unit.name) == "file"
        if running and quiet:
            pass
        elif running:
            count = len(instrument.channels())
            channels = f"{count} channel" if count == 1 else f"{count} channels"
            if instrument.sweeps:
                # The rate is the instrument's to choose, and it says what it chose.
                self.events.information(f"{title}: running, {channels} in blocks.")
            else:
                rate = short_rate(instrument.rate)
                self.events.information(f"{title}: running, {channels} at {rate}.")
        else:
            unit.doing = ""
            if not quiet:
                self.events.information(f"{title}: stopped.")
            if not unit.restarting:
                # It stopped by itself -- a scope unplugged -- or was told to.
                unit.acquisition.set_mode(STOP)
                self._settle_mode()
        self._show_reading()
        self._update_status()

    @Slot(int)
    def _on_gap(self, missing: int) -> None:
        self.events.warning(
            f"{missing} samples did not arrive in time and are shown as a gap. "
            "The samples after them keep their place in time."
        )

    def _update_status(self) -> None:
        self._update_memory()
        units = self._in_use()
        if not self._added:
            self.status.setText(
                "No instrument: Add instrument, on the toolbar, puts one in the pane."
            )
            return
        if not units:
            self.status.setText(
                "No instrument open: press Open in the Instrument pane, or Auto to run it."
            )
            return
        said = []
        for unit in units:
            capture, instrument = unit.capture, unit.instrument
            held = (capture.newest() or 0.0) - (capture.oldest() or 0.0)
            if instrument.running:
                doing = f"running ({unit.acquisition.mode})"
                if unit.doing:
                    doing += f", {unit.doing}"
            else:
                doing = "open, stopped" if instrument.is_open else "closed"
            title = backends.title(unit.name) if len(units) == 1 else unit.short
            said.append(f"{title}: {doing}, {short_rate(instrument.rate)}, {short_time(held)} held")
        self.status.setText("    |    ".join(said))

    def _update_memory(self) -> None:
        """What the histories take, set aside as each run started, and what is free now."""
        held = sum(unit.capture.memory_bytes() for unit in self.session.units.values())
        free, whole = memory.available(), memory.total()
        text = f"Memory: {short_bytes(held)} held"
        tip = [f"The channels' histories take {short_bytes(held)}, set aside as each run started."]
        if free is not None:
            text += f", {short_bytes(free)} free"
            tip.append(
                f"{short_bytes(free)} is free now"
                + (f", of {short_bytes(whole)} in all." if whole else ".")
            )
            tip.append(
                f"A run started now may take {self.memory_share:.0%} of that: "
                f"{short_bytes(int(free * self.memory_share))}."
            )
        else:
            tip.append("This computer does not say how much is free: a run keeps all of History.")
        tip.append("Pressed: how much of what is free a run may take.")
        self.memory_button.setText(text)
        self.memory_button.setToolTip("\n".join(tip))

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
                self._make_scope,
                several=True,
            )
        )
        self.panes.register(
            PaneKind("log", "Event Log", Qt.BottomDockWidgetArea, lambda _name: self.log)
        )
        # Those not in the default arrangement open floating the first time:
        # in front of the window, still part of it, rather than as one more
        # tab behind the Event Log. Where they go after that is up to whoever
        # moves them, and the saved layout keeps it.
        self.panes.register(
            PaneKind(
                "traffic",
                "Instrument traffic",
                Qt.BottomDockWidgetArea,
                lambda _n: TrafficView(),
                floating_first=True,
            )
        )
        self.panes.register(
            PaneKind(
                "measurements",
                "Measurements",
                Qt.BottomDockWidgetArea,
                lambda _n: MeasurementsView(self.scope),
            )
        )
        self.panes.register(
            PaneKind(
                "data",
                "Data",
                Qt.BottomDockWidgetArea,
                lambda _n: DataView(self.scope),
                floating_first=True,
            )
        )
        self.panes.register(
            PaneKind(
                "decoded",
                "Decoded buses",
                Qt.BottomDockWidgetArea,
                lambda _n: DecodedView(self.scope),
                floating_first=True,
            )
        )
        self.panes.register(
            PaneKind(
                "console",
                "Python Console",
                Qt.BottomDockWidgetArea,
                lambda _n: ConsoleView(Scripting(self).names(), self.ctx),
                floating_first=True,
            )
        )

    def _on_pane_shown(self, name: str, on: bool) -> None:
        if name == "traffic":
            self.traffic.listen(on)

    def _make_scope(self, name: str) -> ScopeView:
        view = ScopeView(self.session, self.ctx, key=name)
        view.channel_picked.connect(self._on_channel_picked)
        # What a bus reads, in front of whoever has just asked for it decoded.
        view.decoding_started.connect(lambda: self.panes.show("decoded"))
        return view

    def _on_channel_picked(self, instrument: str, group: str) -> None:
        """A channel was clicked on a plot: show its settings, to be changed."""
        self.choose(instrument)
        self.instrument_view.select_group(group)
        self.panes.show("instrument")

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
                f"Additional {kind.title}", lambda k=kind.name: self.panes.another(k)
            )
            action.setToolTip(
                f"Another {kind.title} pane, with settings of its own: one that was\n"
                "put away comes back first, and a new one opens only once they are all\n"
                "on screen. A new one opens in a window of its own; drag it into the\n"
                "main window to dock it, or onto another pane to tab the two together."
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

            +------------+-------------------------+
            | Instrument |    Channels and Plot    |
            +------------+-------------------------+
            | Event Log  |      Measurements       |
            +------------+-------------------------+

        The plot gets most of the room; the settings are a narrow column
        beside it. Under them, the log is the thing you glance at rather than
        work in, and the measurements -- a column for each reading -- have
        two thirds of the width.
        """
        instrument, scope, log, measurements = (self.panes.docks[n] for n in DEFAULT_VISIBLE)
        self.addDockWidget(Qt.TopDockWidgetArea, instrument)
        self.splitDockWidget(instrument, log, Qt.Vertical)
        self.splitDockWidget(instrument, scope, Qt.Horizontal)
        self.splitDockWidget(log, measurements, Qt.Horizontal)
        # Behind the Event Log, put away until they are asked for.
        self.tabifyDockWidget(log, self.panes.docks["traffic"])
        self.tabifyDockWidget(log, self.panes.docks["console"])
        self.tabifyDockWidget(log, self.panes.docks["data"])
        self.tabifyDockWidget(log, self.panes.docks["decoded"])
        for name, dock in self.panes.docks.items():
            dock.setFloating(False)
            dock.setVisible(name in DEFAULT_VISIBLE)
        # The inner divisions first, and the outer through a dock that sits
        # directly in it: an outer call re-divides what an inner one settled.
        self.resizeDocks([instrument, scope], [1, 5], Qt.Horizontal)
        self.resizeDocks([log, measurements], [1, 2], Qt.Horizontal)
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

    # --- decoded CAN, sent on --------------------------------------------------------------
    def _on_decoded(self, decoding, frames, received: int) -> None:
        """Frames decoded as a block arrived: sent on, where they are asked to be."""
        share = getattr(decoding.setup, "share", "")
        if not share:
            return
        # The computer's time, when each started: as long ago as it is
        # before the newest sample received.
        now = time.time()
        timed = [(f, now - (received - f.start) / decoding.rate) for f in frames]
        self.sharer.send(share, timed)

    def _share_on_network(self, on: bool) -> None:
        QSettings().setValue(UDP_NETWORK_KEY, on)
        self.sharer.set_local_network(on)
        where = "the local network" if on else "this computer only"
        self.events.information(f"Decoded CAN frames sent by UDP multicast reach {where}.")

    def closeEvent(self, event) -> None:
        QSettings().setValue("geometry", self.saveGeometry())
        self.sharer.close()
        # Saved before they are closed: closing one puts its pane away, and
        # what is saved should be how things were left.
        self.save_arrangement()
        # Parentless windows of their own, so they would keep the application
        # running after the main window had gone.
        self.panes.close_detached()
        self._status_timer.stop()
        for unit in self.session.units.values():
            self._drop_unit(unit)
        self.traffic.listen(False)
        self.help_menu.shutdown()
        self.exceptions.remove()
        super().closeEvent(event)

    # --- how much is kept ----------------------------------------------------------------
    def _saved_history(self) -> float:
        """The history chosen, or the default for anything that is not one of the choices."""
        saved = self.ctx.settings.get(HISTORY_KEY, HISTORY_S)
        return float(saved) if saved in HISTORIES else HISTORY_S

    def _saved_share(self) -> float:
        """The share of what is free chosen, or the default for anything else."""
        saved = self.ctx.settings.get(MEMORY_KEY, memory.SHARE)
        return float(saved) if saved in memory.SHARES else memory.SHARE

    def _memory_menu(self) -> QMenu:
        """*Tools > Settings > Memory*: how much of what is free a run's history may take."""
        menu = QMenu("Memory", self)
        menu.setToolTipsVisible(True)
        menu.menuAction().setToolTip(MEMORY_TIP)
        group = QActionGroup(menu)
        group.setExclusive(True)
        for share in memory.SHARES:
            action = QAction(f"{share:.0%} of what is free", menu, checkable=True)
            action.setChecked(share == self.memory_share)
            action.setToolTip(MEMORY_TIP)
            action.triggered.connect(lambda _on=False, s=share: self.set_memory_share(s))
            group.addAction(action)
            menu.addAction(action)
        return menu

    def set_memory_share(self, share: float) -> None:
        """Let a run's history take this share of what is free, from now on: an
        instrument that is running is started again, to be made at that size."""
        if share == self.memory_share:
            return
        self.memory_share = share
        self.ctx.settings.set(MEMORY_KEY, share)
        self._update_memory()
        for unit in self._in_use():
            if unit.running:
                self._restart(unit)

    def _widths_menu(self) -> QMenu:
        """*Tools > Settings > Column widths*: fitted, or fitted until dragged."""
        menu = QMenu("Column widths", self)
        menu.setToolTipsVisible(True)
        menu.menuAction().setToolTip(WIDTHS_TIP)
        group = QActionGroup(menu)
        group.setExclusive(True)
        current = column_widths.mode(self.ctx.settings)
        for wanted, label, tip in (
            (column_widths.AUTO, "Automatic", WIDTHS_AUTO_TIP),
            (column_widths.MANUAL, "Manual", WIDTHS_MANUAL_TIP),
        ):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(wanted == current)
            action.setData(wanted)
            action.setToolTip(tip)
            action.triggered.connect(
                lambda _=False, w=wanted: column_widths.set_mode(self.ctx.settings, w)
            )
            group.addAction(action)
        return menu

    def _history_menu(self) -> QMenu:
        """*Tools > Settings > History*: how long a stretch of each channel is kept."""
        menu = QMenu("History", self)
        menu.setToolTipsVisible(True)
        menu.menuAction().setToolTip(HISTORY_TIP)
        group = QActionGroup(menu)
        group.setExclusive(True)
        for seconds in HISTORIES:
            action = QAction(short_time(seconds), menu, checkable=True)
            action.setChecked(seconds == self.session.history_s)
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
        if seconds == self.session.history_s:
            return
        self.session.set_history(seconds)
        self.ctx.settings.set(HISTORY_KEY, seconds)
        for unit in self._in_use():
            if unit.running:
                self._restart(unit)

    # --- settings ------------------------------------------------------------------------
    def _add_shortcut(self, place: str = shortcut.IN_MENU) -> None:
        """Tools > Settings > Add shortcut to Start menu, or to desktop."""
        name = shortcut.place_name(place)
        try:
            path = shortcut.create(place=place)
        except OSError as exc:
            self.events.warning(f"Could not add {APP_NAME} to the {name}: {exc}")
            return
        self.events.information(f"Added {APP_NAME} to the {name}: {path}")

    def _say_how_to_add_a_shortcut(self) -> None:
        """Once for each person on a machine, for a source folder or pip: the
        launcher no longer asks, and pip never did, so say where it is done.
        Not where there is one already, nor for the installer, which made its own."""
        if shortcut.start() is None or QSettings().value(SHORTCUT_TOLD_KEY) is not None:
            return
        QSettings().setValue(SHORTCUT_TOLD_KEY, True)
        if shortcut.made():
            return
        names = " or the ".join(shortcut.place_name(place) for place in shortcut.places())
        self.events.information(
            f"To start {APP_NAME} from the {names}: Tools > Settings > Add shortcut. "
            "This is said once."
        )

    # --- workspaces ----------------------------------------------------------------------
    def _switch_workspace(self, name: str) -> None:
        """Open another workspace, once it is agreed that what is open here is closed.

        A workspace holds which instruments there are and how each is
        reached, so opening one closes this one's instruments. Worth a
        question, and only when there is something open to lose.
        """
        if name == self.ctx.workspace or not workspaces.exists(name):
            return
        open_now = [unit for unit in self._in_use() if unit.wanted_open or unit.is_open]
        if open_now:
            what = (
                f"{backends.title(open_now[0].name)} is"
                if len(open_now) == 1
                else f"{len(open_now)} instruments are"
            )
            answer = messages.question(
                self,
                "Close what is open, and open another workspace?",
                SWITCH_WHILE_OPEN.format(
                    what=what, them="it" if len(open_now) == 1 else "them", name=name
                ),
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if answer != QMessageBox.Yes:
                return
        self.reopen_requested.emit(name)

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
            self.recent_problems.append((f"{datetime.now():%H:%M:%S}", level, message))
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
