# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The Tektronix TDS and TPS 2000 back end, against a stand-in on a pretend serial port."""

import time

import numpy as np
import pytest

from pyscopegui import backends
from pyscopegui.backends import tektronix2000 as tek
from pyscopegui.ui.scope_view import FREE, TRIGGERED


class FakePort:
    """Enough of a TPS2014 on a serial port: it remembers what it was sent and answers queries."""

    def __init__(self, identity="TEKTRONIX,TPS 2014,0,CF:91.1CT FV:v10.21") -> None:
        self.identity = identity
        #: Everything it was sent, in order, a command at a time.
        self.heard: list[str] = []
        #: What was last set: "CH1:SCALE" -> "1".
        self.state: dict[str, str] = {"ACQUIRE:STOPAFTER": "RUNSTOP"}
        #: Whether a sweep it is asked for has been taken by the time it is asked.
        self.takes_sweeps = True
        #: Running free, as a scope on the bench is, until it is told otherwise.
        self.acquiring = True
        #: What is waiting to be read.
        self._out = bytearray()
        self.timeout = 3.0
        self.baudrate = 9600
        #: What it ends each answer with, as its RS232 menu is set.
        self.eol = b"\n"
        self.closed = False
        #: When set, it has stopped answering.
        self.dead = False

    # --- the port ------------------------------------------------------------------------
    def write(self, data: bytes) -> int:
        for line in data.decode("ascii").split("\n"):
            if line.strip():
                self._hear(line.strip())
        return len(data)

    def readline(self) -> bytes:
        end = self._out.find(b"\n")
        if end < 0:
            taken, self._out = bytes(self._out), bytearray()
            return taken
        taken, self._out = bytes(self._out[: end + 1]), self._out[end + 1 :]
        return taken

    def read_until(self, expected: bytes = b"\n") -> bytes:
        end = self._out.find(expected)
        if end < 0:
            taken, self._out = bytes(self._out), bytearray()
            return taken
        stop = end + len(expected)
        taken, self._out = bytes(self._out[:stop]), self._out[stop:]
        return taken

    def read(self, count: int) -> bytes:
        taken, self._out = bytes(self._out[:count]), self._out[count:]
        return taken

    def reset_input_buffer(self) -> None:
        self._out = bytearray()

    def close(self) -> None:
        self.closed = True

    # --- the scope -----------------------------------------------------------------------
    def sent(self, command: str) -> int:
        return self.heard.count(command)

    def _say(self, text: str) -> None:
        if not self.dead:
            self._out += text.encode("ascii") + self.eol

    def _hear(self, command: str) -> None:
        self.heard.append(command)
        what, _, to = command.partition(" ")
        if what == "*IDN?":
            self._say(self.identity)
        elif what == "*OPC?":
            self._say("1")
        elif what == "ACQUIRE:STATE?":
            single = self.state.get("ACQUIRE:STOPAFTER") == "SEQUENCE"
            if self.acquiring and self.takes_sweeps and single:
                self.acquiring = False  # it has taken its one sweep, and stopped
            self._say("1" if self.acquiring else "0")
        elif what.startswith("SELECT:") and what.endswith("?"):
            self._say("1" if self.state.get(what[:-1], "OFF") == "ON" else "0")
        elif what == "WFMPRE:XINCR?":
            self._say(f"{self._time_div() * tek.ACROSS / tek.POINTS:.6E}")
        elif what == "WFMPRE:XZERO?":
            position = float(self.state.get("HORIZONTAL:MAIN:POSITION", "0"))
            self._say(f"{position - self._time_div() * tek.ACROSS / 2:.6E}")
        elif what == "WFMPRE:PT_OFF?":
            self._say("0")
        elif what == "WFMPRE:YMULT?":
            self._say(f"{self._scale() / 25:.6E}")
        elif what == "WFMPRE:YOFF?":
            # Where nought volts is, in counts: the trace's position in divisions.
            self._say(f"{float(self.state.get(self._source() + ':POSITION', '0')) * 25:.6E}")
        elif what == "CURVE?":
            if not self.dead:
                data = self.waveform().tobytes()
                self._out += b"#4%04d" % len(data) + data + self.eol
        elif what == "*ESR?":
            self._say("0")
        elif what.endswith("?") and what[:-1] in self.state:
            # Whatever it was last set to, asked for back.
            self._say(self.state[what[:-1]])
        elif what == "ACQUIRE:STATE" and to == "RUN":
            self.acquiring = True
        elif to:
            self.state[what] = to

    def _source(self) -> str:
        return self.state.get("DATA:SOURCE", "CH1")

    def _time_div(self) -> float:
        return float(self.state.get("HORIZONTAL:MAIN:SCALE", "0.001"))

    def _scale(self) -> float:
        return float(self.state.get(self._source() + ":SCALE", "1"))

    def waveform(self) -> np.ndarray:
        """A ramp from four divisions below the middle to four above."""
        return (np.arange(tek.POINTS) * 200 // tek.POINTS - 100).astype(np.int8)


@pytest.fixture
def port(monkeypatch):
    fake = FakePort()
    monkeypatch.setattr(tek, "open_port", lambda *_port: fake)
    return fake


def opened(port, **options) -> tek.Scope:
    scope = tek.Scope(tek.Settings({"port": "COM9", **options}))
    scope.open()
    return scope


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_a_stopped_scope_is_asked_who_it_is_now_and_then_and_one_gone_is_an_error(port):
    clock = Clock()
    scope = tek.Scope(tek.Settings({"port": "COM9"}), clock=clock)
    scope.open()
    asked = port.sent("*IDN?")
    clock.now = tek.CHECK_S - 0.1
    scope.check_there()
    assert port.sent("*IDN?") == asked, "not before it has been stopped a while"
    clock.now = tek.CHECK_S
    scope.check_there()
    scope.check_there()
    assert port.sent("*IDN?") == asked + 1, "once in a while, not every look"
    scope.running = True
    clock.now = 10 * tek.CHECK_S
    scope.check_there()
    assert port.sent("*IDN?") == asked + 1, "running, every look at its sweep says it is there"
    scope.running = False
    port.dead = True
    with pytest.raises(tek.ScopeError, match="stopped answering and has been closed"):
        scope.check_there()


def sweep_of(scope: tek.Scope, tries: int = 20):
    for _ in range(tries):
        if (block := scope.poll()) is not None:
            return block
    raise AssertionError("no sweep came")


# --- settings -------------------------------------------------------------------------------
def test_settings_from_nothing_are_the_defaults():
    for odd in (None, "x", {"time_div": "fast", "scale_1": None, "baud": "quick", "probe_1": "x"}):
        settings = tek.Settings(odd)
        assert settings.keys() == ["CH1"] and settings.time_div == 1e-3
        assert (settings.baud, settings.hard_flow, settings.as_is) == (9600, True, False)
        assert settings.scale["CH1"] == 1.0 and settings.probe["CH1"].ratio == 10
        assert settings.acquire == tek.SAMPLE and settings.averages == 16


def test_the_timebase_goes_one_two_and_a_half_five():
    assert tek.TIMES[:4] == (5e-9, 1e-8, 2.5e-8, 5e-8) and tek.TIMES[-1] == 50
    assert tek.Settings({"time_div": 2e-3}).time_div == 2.5e-3


def test_every_setting_has_a_group_and_the_keys_are_all_different():
    keys = [setting.key for setting in tek.SETTINGS]
    assert len(set(keys)) == len(keys)
    assert all(setting.group for setting in tek.SETTINGS)


@pytest.mark.parametrize(
    ("model", "channels"),
    [
        ("TPS 2014", 4),
        ("TPS 2024", 4),
        ("TPS 2012", 2),
        ("TDS 224", 4),
        ("TDS 210", 2),
        ("TDS 1002", 2),
        ("TDS 2012B", 2),
        ("TDS 2004B", 4),
        ("TDS 1001B", 2),
        ("something else", 2),
    ],
)
def test_how_many_channels_is_in_the_models_number(model, channels):
    assert tek.channels_of(model) == channels


def test_a_two_channel_scope_is_offered_two():
    keys = {setting.key for setting in tek.make_settings(2)}
    assert "scale_2" in keys and "scale_3" not in keys
    assert tek.Settings({"enabled_3": True}).keys(2) == ["CH1"]


def test_the_setup_puts_a_trace_in_divisions_and_the_trigger_where_asked():
    settings = tek.Settings(
        {"time_div": 1e-3, "enabled_2": True, "scale_2": 0.5, "offset_2": -1.0, "limit_2": True}
    )
    wanted = tek.setup(settings, tek.Trigger("CH2", 0.5, False, 0.25, auto=False))
    assert wanted["CH2:POSITION"] == "-2", "a volt down at half a volt a division"
    assert wanted["CH2:BANDWIDTH"] == "ON" and wanted["CH1:BANDWIDTH"] == "OFF"
    assert (
        wanted["TRIGGER:MAIN:EDGE:SOURCE"] == "CH2" and wanted["TRIGGER:MAIN:EDGE:SLOPE"] == "FALL"
    )
    assert wanted["TRIGGER:MAIN:LEVEL"] == "0.5" and wanted["TRIGGER:MAIN:MODE"] == "NORMAL"
    # A quarter of the way across ten divisions: the middle is two and a half after it.
    assert float(wanted["HORIZONTAL:MAIN:POSITION"]) == pytest.approx(0.0025)
    assert wanted["SELECT:CH3"] == "OFF" and "CH3:SCALE" not in wanted


def test_auto_and_no_trigger_let_the_scope_give_up_waiting_itself():
    settings = tek.Settings()
    assert tek.setup(settings, tek.Trigger("CH1", auto=True))["TRIGGER:MAIN:MODE"] == "AUTO"
    assert tek.setup(settings, tek.Trigger(None, auto=False))["TRIGGER:MAIN:MODE"] == "AUTO"


def test_averaging_says_how_many():
    wanted = tek.setup(tek.Settings({"acquire": tek.AVERAGE, "averages": 64}), tek.Trigger())
    assert wanted["ACQUIRE:MODE"] == "AVERAGE" and wanted["ACQUIRE:NUMAVG"] == "64"
    assert "ACQUIRE:NUMAVG" not in tek.setup(tek.Settings(), tek.Trigger())


# --- the scope ------------------------------------------------------------------------------
def test_no_port_is_said_in_words():
    with pytest.raises(tek.ScopeError, match="Instrument pane"):
        tek.Scope(tek.Settings()).open()


def test_a_port_that_will_not_open_is_said_in_words(monkeypatch):
    def refuse(*_port):
        raise OSError("could not open port 'COM9'")

    monkeypatch.setattr(tek, "open_port", refuse)
    with pytest.raises(tek.ScopeError, match="COM9 could not be opened"):
        tek.Scope(tek.Settings({"port": "COM9"})).open()


def test_no_pyserial_says_what_to_install(monkeypatch):
    def missing(*_port):
        raise ImportError("No module named 'serial'")

    monkeypatch.setattr(tek, "open_port", missing)
    with pytest.raises(tek.ScopeError, match="pip install pyserial"):
        tek.Scope(tek.Settings({"port": "COM9"})).open()


def test_a_scope_that_does_not_answer_says_what_to_check(port):
    port.dead = True
    with pytest.raises(tek.ScopeError, match="RS232 Setup"):
        opened(port)


def test_opening_says_which_scope_it_is_and_how_many_channels(port):
    scope = opened(port)
    assert (scope.model, scope.channels) == ("TPS 2014", 4)
    assert scope.notes == [("TEKTRONIX TPS 2014: 4 channels.", False)]
    assert port.heard[0] == "HEADER OFF", "so that answers come with nothing in front"
    scope.close()
    assert port.closed


def test_something_else_on_the_port_is_refused(port):
    port.identity = "RIGOL TECHNOLOGIES,DS1054Z,DS1ZA0,00.04"
    with pytest.raises(tek.ScopeError, match="not this scope"):
        opened(port)


def test_another_tektronix_is_warned_of(port):
    port.identity = "TEKTRONIX,MSO 4104,0,CF:91.1CT FV:v2.0"
    scope = opened(port)
    assert any(is_warning and "TPS2000" in text for text, is_warning in scope.notes)


def test_a_sweep_is_the_screen_in_volts_with_the_trigger_in_the_middle(port):
    scope = opened(port, time_div=1e-3, scale_1=0.5)
    scope.start(scope.settings, tek.Trigger("CH1", 0.0, True, 0.5, auto=False))
    block = sweep_of(scope)
    assert block.sweep and len(block) == 2500
    assert block.rate == pytest.approx(250_000)
    assert (block.trigger, block.triggered) == (1250, True)
    samples = block.data["CH1"]
    assert samples.dtype == np.float32
    # Twenty-five counts a division, a hundred up and down from the middle.
    assert samples[0] == pytest.approx(-2.0) and samples[-1] == pytest.approx(1.98, abs=0.02)
    assert port.state["CH1:SCALE"] == "0.5" and port.state["HORIZONTAL:MAIN:SCALE"] == "0.001"
    assert port.state["ACQUIRE:STOPAFTER"] == "SEQUENCE"
    assert port.sent("ACQUIRE:STATE RUN") == 2, "armed again for the next"
    scope.close()


def test_the_trigger_is_where_the_position_put_it(port):
    scope = opened(port)
    scope.start(scope.settings, tek.Trigger("CH1", 0.0, True, 0.25, auto=False))
    assert sweep_of(scope).trigger == 625
    scope.close()


def test_the_offset_is_taken_off_again(port):
    scope = opened(port, scale_1=1.0, offset_1=2.0)
    scope.start(scope.settings, tek.Trigger())
    assert sweep_of(scope).data["CH1"][0] == pytest.approx(-6.0)
    scope.close()


def test_every_channel_that_is_on_is_read_and_the_others_are_not(port):
    scope = opened(port, enabled_1=True, enabled_3=True)
    scope.start(scope.settings, tek.Trigger())
    assert list(sweep_of(scope).data) == ["CH1", "CH3"]
    assert port.state["SELECT:CH2"] == "OFF" and port.state["SELECT:CH3"] == "ON"
    scope.close()


def test_a_sweep_not_taken_yet_is_waited_for(port):
    port.takes_sweeps = False
    scope = opened(port)
    scope.start(scope.settings, tek.Trigger("CH1", auto=False))
    assert scope.poll() is None and scope.poll() is None
    assert port.sent("CURVE?") == 0
    port.takes_sweeps = True
    assert len(sweep_of(scope)) == 2500
    scope.close()


def test_auto_says_whether_the_signal_was_there_to_trigger_on(port):
    scope = opened(port)
    scope.start(scope.settings, tek.Trigger("CH1", 0.0, True, auto=True))
    assert sweep_of(scope).triggered, "the ramp goes up through nought at the trigger"
    scope.wanted_trigger = tek.Trigger("CH1", 3.9, True, auto=True)
    assert scope.poll() is None
    block = sweep_of(scope)
    assert block.trigger == 1250 and not block.triggered, "nowhere near that level there"
    scope.close()


def test_with_no_trigger_chosen_the_sweep_has_none(port):
    scope = opened(port)
    scope.start(scope.settings, tek.Trigger(None))
    assert sweep_of(scope).trigger is None
    scope.close()


def test_a_change_as_it_runs_sends_only_what_changed(port):
    scope = opened(port)
    scope.start(scope.settings, tek.Trigger())
    sweep_of(scope)
    before = len(port.heard)
    scope.wanted = tek.Settings({"port": "COM9", "scale_1": 2.0})
    assert scope.poll() is None
    sent = [command for command in port.heard[before:] if command.startswith("CH")]
    assert sent == ["CH1:SCALE 2"]
    assert sweep_of(scope).data["CH1"][0] == pytest.approx(-8.0)
    scope.close()


def test_a_scope_that_goes_away_is_said_in_words(port):
    scope = opened(port)
    scope.start(scope.settings, tek.Trigger())
    port.dead = True
    with pytest.raises(tek.ScopeError, match="did not answer"):
        sweep_of(scope)
    scope.close()


# --- the port, as the scope has it ---------------------------------------------------------
def test_parity_and_the_end_of_line_are_as_the_scopes_menu_names_them():
    settings = tek.Settings({"parity": "Even", "eol": "CR/LF"})
    assert (settings.parity, settings.eol) == ("E", b"\r\n")
    for odd in (None, "x", 3):
        plain = tek.Settings({"parity": odd, "eol": odd})
        assert (plain.parity, plain.eol) == ("N", b"\n")


def test_the_port_is_opened_as_the_settings_say(monkeypatch):
    asked = []

    def note(*port):
        asked.append(port)
        raise OSError("that is all this test wants")

    monkeypatch.setattr(tek, "open_port", note)
    settings = tek.Settings({"port": "COM6", "baud": 19200, "flow": "none", "parity": "Odd"})
    with pytest.raises(tek.ScopeError):
        tek.Scope(settings).open()
    assert asked == [("COM6", 19200, False, "O")]


@pytest.mark.parametrize("name", list(tek.ENDS))
def test_an_answer_is_read_to_whatever_the_scope_ends_it_with(port, name):
    port.eol = tek.ENDS[name]
    scope = opened(port, eol=name)
    assert scope.model == "TPS 2014"
    scope.start(scope.settings, tek.Trigger("CH1", auto=False))
    block = sweep_of(scope)
    assert len(block) == 2500 and block.trigger == 1250
    assert sweep_of(scope).data["CH1"][0] == pytest.approx(-4.0), "and the one after it"
    scope.close()


def test_the_wrong_end_of_line_says_what_to_check(port):
    port.eol = b"\r"
    with pytest.raises(tek.ScopeError, match="end of line"):
        opened(port, eol="LF")


# --- as it is -------------------------------------------------------------------------------
def test_read_as_it_is_nothing_on_the_scope_is_changed(port):
    port.state.update({"SELECT:CH1": "ON", "CH1:SCALE": "0.2", "HORIZONTAL:MAIN:SCALE": "0.0025"})
    scope = opened(port, read="asis")
    before = dict(port.state)
    scope.start(scope.settings, tek.Trigger("CH1", 1.0))
    block = sweep_of(scope)
    changed = {k: v for k, v in port.state.items() if before.get(k) != v}
    assert set(changed) <= {"DATA:ENCDG", "DATA:WIDTH", "DATA:START", "DATA:STOP", "DATA:SOURCE"}
    assert port.sent("ACQUIRE:STATE RUN") == 0, "and it is not made to take anything"
    # At the scope's own scale and timebase, and its own trigger.
    assert block.rate == pytest.approx(100_000)
    assert block.data["CH1"][0] == pytest.approx(-0.8)
    assert (block.trigger, block.triggered) == (1250, True)
    scope.close()


def test_read_as_it_is_the_channels_are_the_ones_the_scope_shows(port):
    port.state.update({"SELECT:CH1": "OFF", "SELECT:CH3": "ON"})
    scope = opened(port, read="asis")  # CH1 ticked here, and not shown there
    assert scope.shown == ["CH3"] and scope.view_changed
    scope.start(scope.settings, tek.Trigger())
    assert list(sweep_of(scope).data) == ["CH3"]
    scope.close()


def test_read_as_it_is_a_channel_switched_on_at_the_bench_is_read_with_the_rest(
    as_is_window, port, app
):
    window = as_is_window
    port.state["SELECT:CH3"] = "ON"
    window.instrument_bar.read.click()
    wait_for(app, lambda: "CH3" in window.capture.records and not window.unit.running)
    wait_for(app, lambda: window.capture.records["CH3"].count > 0)
    assert set(window.capture.records) == {"CH1", "CH2", "CH3"}


def test_read_as_it_is_with_nothing_on_the_screen_says_so(port):
    scope = opened(port, read="asis")
    scope.start(scope.settings, tek.Trigger())
    with pytest.raises(tek.ScopeError, match="nothing to read"):
        scope.poll()
    scope.close()


# --- the instrument, and in the window ------------------------------------------------------
def wait_for(app, done, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not done() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert done(), "timed out"


def test_the_channels_say_how_each_is_set(app):
    instrument = backends.create("tektronix2000", None, {"limit_1": True, "offset_1": 1.0})
    assert [(c.name, c.detail, c.group) for c in instrument.channels()] == [
        ("CH1", "1 V/div, 10x, DC, 20 MHz, offset 1 V", "Channel 1")
    ]
    as_is = backends.create("tektronix2000", None, {"read": "asis"})
    assert as_is.channels() == [], "the ones the scope is showing, once it is open"


@pytest.fixture
def scope_window(window, port, monkeypatch):
    monkeypatch.setattr(tek, "POLL_S", 0.01)
    window.ctx.settings.set("instrument.tektronix2000", {"port": "COM9", "enabled_2": True})
    window.choose("tektronix2000")
    yield window
    window.close_instrument()


def test_the_window_shows_a_sweep_around_the_scopes_trigger(scope_window, port, app):
    window = scope_window
    assert window.instrument_view.controls["port"].currentText() == "COM9"
    window.instrument_view.open.click()
    wait_for(app, lambda: window.instrument.is_open)
    assert "TPS 2014" in window.log.toPlainText()
    box = window.trigger_bar.source
    box.setCurrentIndex(box.findData("CH2"))
    box.activated.emit(box.currentIndex())
    window.set_mode("normal")
    wait_for(app, lambda: window.acquisition.sweep is not None)
    assert set(window.capture.records) == {"CH1", "CH2"}
    window.scope.redraw()
    low, high = window.scope.analog.getViewBox().viewRange()[0]
    assert low == pytest.approx(-0.005, rel=1e-3) and high == pytest.approx(0.005, rel=1e-3)
    # What it shows, and what the scope is at meanwhile: it is slow, and says so.
    assert window.scope.state.text().startswith(TRIGGERED)
    assert port.state["TRIGGER:MAIN:EDGE:SOURCE"] == "CH2"


def test_auto_with_nothing_to_trigger_on_says_so(scope_window, port, app):
    window = scope_window
    window.instrument_view.open.click()
    box = window.trigger_bar.source
    box.setCurrentIndex(box.findData("CH1"))
    box.activated.emit(box.currentIndex())
    window.trigger_bar.level.setValue(3.9)
    window.set_mode("auto")
    wait_for(app, lambda: window.acquisition.sweep is not None)
    window.scope.redraw()
    assert window.scope.state.text().startswith(FREE)


def test_single_takes_one_sweep_and_stops(scope_window, app):
    window = scope_window
    window.instrument_bar.modes["single"].click()
    wait_for(app, lambda: window.acquisition.sweep is not None)
    wait_for(app, lambda: not window.instrument.running)
    assert window.instrument_bar.mode() == "stop" and window.instrument.is_open


def test_a_two_channel_scope_is_offered_two_once_it_is_open(scope_window, port, app):
    window = scope_window
    port.identity = "TEKTRONIX,TPS 2012,0,CF:91.1CT FV:v10.21"
    assert "scale_4" in window.instrument_view.controls, "before it is known which it is"
    window.instrument_view.open.click()
    wait_for(app, lambda: window.instrument.is_open)
    assert "scale_4" not in window.instrument_view.controls
    assert "scale_2" in window.instrument_view.controls


def test_what_only_matters_when_setting_up_is_greyed_out_as_it_is(scope_window, app):
    view = scope_window.instrument_view
    assert view.controls["scale_1"].isEnabled() and view.controls["time_div"].isEnabled()
    box = view.controls["read"]
    box.setCurrentIndex(box.findData("asis"))
    box.activated.emit(box.currentIndex())
    assert not view.controls["scale_1"].isEnabled()
    assert not view.controls["time_div"].isEnabled()
    assert not view.controls["enabled_1"].isEnabled(), "the scope's own switches say which"


def test_no_port_says_so_and_goes_back_to_closed(window, app):
    window.choose("tektronix2000")
    window.instrument_view.open.click()
    wait_for(app, lambda: "No port to open" in window.log.toPlainText())
    wait_for(app, lambda: window.instrument_view.open.text() == "Open")
    assert not window.instrument.is_open


# --- choosing the port --------------------------------------------------------------------------
def test_the_ports_there_are_now_are_listed_by_name(monkeypatch):
    from serial.tools import list_ports

    class Port:
        def __init__(self, device, description):
            self.device, self.description = device, description

    monkeypatch.setattr(
        list_ports,
        "comports",
        lambda: [Port("COM6", "USB Serial Port (COM6)"), Port("COM1", "n/a"), Port("COM3", "")],
    )
    assert tek.serial_ports() == [
        ("COM1", "COM1"),
        ("COM3", "COM3"),
        ("COM6", "COM6   USB Serial Port (COM6)"),
    ]


def test_the_port_box_is_a_list_with_a_hint_when_empty(window, app):
    window.choose("tektronix2000")
    picker = window.instrument_view.controls["port"]
    assert picker.lineEdit().placeholderText() == "Choose a port"
    picker.fill()  # whatever ports this machine has, after the empty choice
    assert picker.itemData(0) == "" and picker.itemText(0) == "Choose a port"
    picker.setEditText("COM7")
    window.instrument_view.commit()
    assert window.ctx.settings.get("instrument.tektronix2000")["port"] == "COM7"


# --- saying what it is at, since all of it is slow ----------------------------------------------
def test_setting_up_sends_a_setting_once_the_scope_has_done_the_one_before(port):
    """Sent all at once they queue in the scope, which then answers nothing for half a minute."""
    waited = []
    real = port.read_until

    def note(expected=b"\n"):
        waited.append(port.timeout)
        return real(expected)

    port.read_until = note
    scope = opened(port, enabled_2=True)
    waited.clear()
    del port.heard[:]
    scope.start(scope.settings, tek.Trigger("CH1", auto=False))
    changed = list(tek.setup(scope.settings, scope.trigger, 4).items())
    sent = port.heard[: 2 * len(changed)]
    assert sent[0::2] == [f"{what} {to}" for what, to in changed]
    assert sent[1::2] == ["*OPC?"] * len(changed), "each one waited for"
    assert waited[: len(changed)] == [tek.SETTING_S] * len(changed)
    assert port.timeout == 3.0, "and the ordinary wait is put back"
    assert any("Setting the scope up" in text for text, _warning in scope.notes)
    assert any(text.startswith("Set up in") for text, _warning in scope.notes)
    scope.close()


def test_a_setting_the_scope_does_not_finish_is_named(port):
    scope = opened(port)
    real = port._hear

    def stuck(command):
        real(command)
        if command.startswith("CH1:SCALE"):
            port.dead = True

    port._hear = stuck
    with pytest.raises(tek.ScopeError, match=r"Setting CH1:SCALE to .*did not answer"):
        scope.start(scope.settings, tek.Trigger())


def test_a_set_up_gives_way_to_a_stop_asked_for_meanwhile(port):
    scope = opened(port, enabled_2=True)
    asked = []
    scope.interrupted = lambda: len(asked) > 0
    real = port._hear

    def stop_after_three(command):
        real(command)
        if command == "*OPC?" and port.sent("*OPC?") == 3:
            asked.append("stop")

    port._hear = stop_after_three
    scope.start(scope.settings, tek.Trigger())
    assert port.sent("*OPC?") == 3, "and nothing more of it sent"
    assert "ACQUIRE:STOPAFTER SEQUENCE" not in port.heard, "nor a sweep asked for"
    scope.close()


def test_a_scope_still_busy_when_it_is_opened_is_waited_for(port):
    """What happens when it is opened again before it has done a set-up it was sent."""
    real = port._hear
    waited = []

    def busy(command):
        real(command)
        if command == "*IDN?":
            # It says nothing until it is through what it had: the answer is there
            # for the long wait, and not the first.
            answer, port._out = bytes(port._out), bytearray()
            later = port.read_until

            def read_until(expected=b"\n"):
                waited.append(port.timeout)
                if port.timeout >= tek.BUSY_S:
                    port._out += answer
                    port.read_until = later
                return later(expected)

            port.read_until = read_until

    port._hear = busy
    said = []
    scope = tek.Scope(tek.Settings({"port": "COM9"}))
    scope.doing = said.append
    scope.open()
    assert scope.model == "TPS 2014"
    assert waited == [tek.ANSWER_S, tek.BUSY_S]
    assert "waiting for the scope, which may still be busy" in said
    assert any("did not answer at once" in text for text, _warning in scope.notes)
    scope.close()


def test_an_answer_left_over_from_before_is_not_taken_for_who_it_is(port):
    port._out += b"1\n"  # the end of a set-up it was sent before it was closed
    real = port.reset_input_buffer
    port.reset_input_buffer = lambda: None  # arrived after the port was cleared
    scope = opened(port)
    assert scope.model == "TPS 2014"
    port.reset_input_buffer = real
    scope.close()


def test_a_scope_that_stays_busy_says_it_may_be(port):
    port.dead = True
    with pytest.raises(tek.ScopeError, match="still be busy"):
        opened(port)


def test_the_scope_says_what_it_is_busy_with(port):
    said = []
    scope = opened(port, enabled_2=True)
    scope.doing = said.append
    scope.start(scope.settings, tek.Trigger())
    count = len(tek.setup(scope.settings, scope.trigger, 4))
    assert said == [
        *(f"setting up the scope ({n} of {count})" for n in range(1, count + 1)),
        "waiting for a sweep",
    ]
    del said[:]
    sweep_of(scope)
    assert said == ["reading CH1 (1 of 2)", "reading CH2 (2 of 2)", "waiting for a sweep"]
    scope.stop()
    assert said[-1] == "", "and nothing, once it has stopped"
    scope.close()


def test_one_channel_is_read_without_being_counted(port):
    said = []
    scope = opened(port)
    scope.doing = said.append
    scope.start(scope.settings, tek.Trigger())
    sweep_of(scope)
    assert "reading CH1" in said
    scope.close()


def test_the_window_says_what_a_slow_scope_is_at(scope_window, port, app):
    window = scope_window
    port.takes_sweeps = False  # so that it stays waiting, to be looked at
    window.set_mode("normal")
    wait_for(app, lambda: window.unit.doing == "waiting for a sweep")
    assert "waiting for a sweep" in window.status.text()
    window.scope.redraw()
    assert "waiting for a sweep" in window.scope.state.text().lower()
    assert "Setting the scope up" in window.log.toPlainText()
    window.set_mode("stop")
    wait_for(app, lambda: window.unit.doing == "")
    assert "waiting for a sweep" not in window.status.text()


# --- leaving the scope as it was found ---------------------------------------------------------
def test_the_scope_is_put_back_to_running_when_the_run_stops(port):
    """Left to stop after each sweep, it sits with a still screen and looks hung."""
    scope = opened(port)
    scope.start(scope.settings, tek.Trigger())
    sweep_of(scope)
    assert port.state["ACQUIRE:STOPAFTER"] == "SEQUENCE"
    scope.stop()
    assert port.state["ACQUIRE:STOPAFTER"] == "RUNSTOP"
    assert port.heard[-2:] == ["ACQUIRE:STOPAFTER RUNSTOP", "ACQUIRE:STATE RUN"]
    scope.close()


def test_a_scope_that_was_stopped_is_left_stopped(port):
    port.acquiring = False
    scope = opened(port)
    scope.start(scope.settings, tek.Trigger())
    sweep_of(scope)
    scope.stop()
    assert port.heard[-1] == "ACQUIRE:STOPAFTER RUNSTOP", "and not set running, which it was not"
    scope.close()


def test_closing_in_the_middle_of_a_run_puts_it_back_too(port):
    scope = opened(port)
    scope.start(scope.settings, tek.Trigger())
    scope.close()
    assert port.state["ACQUIRE:STOPAFTER"] == "RUNSTOP" and port.closed


def test_how_it_was_is_asked_once_and_kept_across_a_change(port):
    scope = opened(port)
    scope.start(scope.settings, tek.Trigger())
    sweep_of(scope)
    scope.wanted = tek.Settings({"port": "COM9", "scale_1": 2.0})
    scope.poll()
    assert port.sent("ACQUIRE:STOPAFTER?") == 1
    scope.stop()
    assert port.state["ACQUIRE:STOPAFTER"] == "RUNSTOP"
    scope.close()


def test_read_as_it_is_there_is_nothing_to_put_back(port):
    port.state["SELECT:CH1"] = "ON"
    scope = opened(port, read="asis")
    scope.start(scope.settings, tek.Trigger())
    sweep_of(scope)
    scope.stop()
    assert not any(command.startswith("ACQUIRE") for command in port.heard)
    scope.close()


# --- read as it is: no trigger of ours, and a button to read it with ---------------------------
@pytest.fixture
def as_is_window(scope_window, port, app):
    window = scope_window
    port.state.update({"SELECT:CH1": "ON", "SELECT:CH2": "ON"})
    window.instrument_view.open.click()
    wait_for(app, lambda: window.instrument.is_open)
    window._on_setting("read", "asis", False)
    return window


def test_read_is_offered_only_for_a_scope_read_as_it_is(scope_window, app):
    window = scope_window
    assert not window.instrument_bar.reads(), "nothing is known of it before it is opened"
    window.instrument_view.open.click()
    wait_for(app, lambda: window.instrument.is_open)
    assert not window.instrument_bar.reads(), "which is set up from here, and takes sweeps"
    window._on_setting("read", "asis", False)
    assert window.instrument.reads_as_is and window.instrument_bar.reads()
    window._on_setting("read", "set", False)
    assert not window.instrument_bar.reads()


def test_read_as_it_is_the_trigger_is_the_scopes_and_cannot_be_set_here(as_is_window):
    window = as_is_window
    bar = window.trigger_bar
    assert not bar.source.isEnabled() and not bar.edge.isEnabled() and not bar.level.isEnabled()
    assert "set on the instrument itself" in bar.source.toolTip()
    modes = window.instrument_bar.modes
    assert not modes["single"].isEnabled() and not modes["normal"].isEnabled()
    assert modes["auto"].isEnabled() and modes["stop"].isEnabled()
    assert "Read takes what it shows once" in modes["single"].toolTip()
    window._on_setting("read", "set", False)
    assert bar.source.isEnabled() and modes["single"].isEnabled()
    assert "Read takes" not in modes["single"].toolTip()


def test_read_takes_what_the_scope_shows_once_and_stops(as_is_window, port, app):
    window = as_is_window
    window.instrument_bar.read.click()
    assert not window.instrument_bar.read.isEnabled(), "while it is reading"
    wait_for(app, lambda: window.acquisition.sweep is not None and not window.unit.running)
    assert set(window.capture.records) == {"CH1", "CH2"}
    assert port.sent("CURVE?") == 2, "each channel once, and not again"
    assert not any(command.startswith("ACQUIRE") for command in port.heard)
    assert window.instrument_bar.mode() == "stop" and window.instrument_bar.read.isEnabled()
    assert window.instrument.is_open, "read, and still open for the next"


def test_read_again_reads_again(as_is_window, port, app):
    window = as_is_window
    for reads in (1, 2):
        window.instrument_bar.read.click()
        wait_for(app, lambda r=reads: not window.unit.running and port.sent("CURVE?") == 2 * r)


def test_auto_keeps_reading_a_scope_that_is_read_as_it_is(as_is_window, port, app):
    window = as_is_window
    window.set_mode("auto")
    wait_for(app, lambda: port.sent("CURVE?") >= 4)
    assert window.unit.running and window.instrument_bar.mode() == "auto"
    window.set_mode("stop")
    assert not window.unit.running


def test_single_is_not_for_a_scope_read_as_it_is_and_does_not_run_it(as_is_window, port):
    window = as_is_window
    window.set_mode("single")
    assert not window.unit.running and window.instrument_bar.mode() == "stop"
    assert port.sent("CURVE?") == 0


def test_read_as_it_is_no_level_is_drawn_for_a_trigger_that_is_not_ours(as_is_window, app):
    window = as_is_window
    window.acquisition.set_trigger(source="CH1")
    window.instrument_bar.read.click()
    wait_for(app, lambda: window.acquisition.sweep is not None and not window.unit.running)
    window.scope.redraw()
    assert not window.scope.level_line.isVisible()


# --- a snapshot is shown whole -----------------------------------------------------------------
def demo_beside(window):
    """The demo run and stopped, with what it sent still on the plot, as a
    default workspace would have it beside the scope."""
    window.choose("demo")
    window.set_mode("auto")
    window.instrument._started -= 1.0
    window.instrument._tick()
    window.set_mode("stop")
    window.choose("tektronix2000")


def read_once(window, app):
    window.instrument_bar.read.click()
    wait_for(app, lambda: window.acquisition.sweep is not None and not window.unit.running)
    window.scope.redraw()
    return window.scope.analog.getViewBox().viewRange()[0]


@pytest.fixture
def slow_screen(port):
    """Five seconds of screen, which is far more than Follow's stretch."""
    port.state.update({"SELECT:CH1": "ON", "SELECT:CH2": "ON", "HORIZONTAL:MAIN:SCALE": "0.5"})
    return port


def test_choosing_to_read_as_it_is_shows_all_of_what_is_read(scope_window, slow_screen, app):
    window = scope_window
    demo_beside(window)
    window.instrument_view.open.click()
    wait_for(app, lambda: window.instrument.is_open)
    assert window.scope.time.currentText() == "Follow"
    window._on_setting("read", "asis", False)
    assert window.scope.time.currentText() == "All"
    low, high = read_once(window, app)
    assert low <= -2.5 and high >= 2.5, "the whole five seconds, beside the demo"


def test_all_beside_another_instrument_is_all_of_both(scope_window, slow_screen, app):
    """It used to be the same as Follow whenever two instruments shared the plot."""
    window = scope_window
    demo_beside(window)
    window.instrument_view.open.click()
    wait_for(app, lambda: window.instrument.is_open)
    window._on_setting("read", "asis", False)
    window.scope.time.setCurrentText("Follow")
    low, high = read_once(window, app)
    assert high - low == pytest.approx(window.scope.window_s.value()), "Follow is its stretch"
    window.scope.time.setCurrentText("All")
    window.scope.redraw()
    low, high = window.scope.analog.getViewBox().viewRange()[0]
    assert low <= -2.5 and high >= 2.5


def test_it_is_done_once_and_a_choice_made_after_is_left_alone(scope_window, slow_screen, app):
    window = scope_window
    window.instrument_view.open.click()
    wait_for(app, lambda: window.instrument.is_open)
    window._on_setting("read", "asis", False)
    window.scope.time.setCurrentText("Follow")
    read_once(window, app)
    read_once(window, app)
    assert window.scope.time.currentText() == "Follow"
    window._on_setting("enabled_2", False, False)  # any other setting
    assert window.scope.time.currentText() == "Follow"


def test_a_scope_opened_already_set_to_be_read_as_it_is_shows_all(window, port, app, monkeypatch):
    monkeypatch.setattr(tek, "POLL_S", 0.01)
    window.ctx.settings.set("instrument.tektronix2000", {"port": "COM9", "read": "asis"})
    window.choose("tektronix2000")
    assert window.scope.time.currentText() == "Follow"
    window.instrument_view.open.click()
    wait_for(app, lambda: window.instrument.is_open)
    assert window.scope.time.currentText() == "All"
    window.close_instrument()


def test_a_scope_set_up_from_here_leaves_the_plot_as_it_is(scope_window, port, app):
    window = scope_window
    window.instrument_view.open.click()
    wait_for(app, lambda: window.instrument.is_open)
    window._on_setting("time_div", 0.001, False)
    assert window.scope.time.currentText() == "Follow"


# --- over USB ---------------------------------------------------------------------------------
class FakeInstrument:
    """A scope as a VISA library hands it over: the stand-in above, without the serial port."""

    def __init__(self, port: FakePort) -> None:
        self._port = port
        self.timeout = None
        self.write_termination = None
        self.read_termination = "\n"
        self.closed = False
        self.cleared = 0

    def write(self, command: str) -> None:
        self._port.write(command.encode("ascii") + b"\n")

    def read_raw(self) -> bytes:
        if self.read_termination is not None:
            raise AssertionError("a read would stop at the first new line in a waveform")
        taken = self._port.read(len(self._port._out))
        if not taken:
            raise OSError("VI_ERROR_TMO (-1073807339): Timeout expired before operation completed.")
        return taken

    def query(self, command: str) -> str:
        self.write(command)
        return self.read_raw().decode()

    def clear(self) -> None:
        self.cleared += 1
        self._port.reset_input_buffer()

    def close(self) -> None:
        self.closed = True


class FakeVisa:
    def __init__(self, port, listed=("USB0::0x0699::0x036A::C010001::INSTR",)) -> None:
        self.listed = listed
        self.instrument = FakeInstrument(port)
        self.opened: list[str] = []
        self.closed = False

    def list_resources(self, _query: str):
        return self.listed

    def open_resource(self, name: str):
        self.opened.append(name)
        return self.instrument

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def usb(monkeypatch):
    """A TDS 2024B on USB: the stand-in scope, through a stand-in VISA library."""
    from pyscopegui.backends import visa

    library = FakeVisa(FakePort("TEKTRONIX,TDS 2024B,C010001,CF:91.1CT FV:v22.11"))
    monkeypatch.setattr(visa, "open_visa", lambda: library)
    return library


def over_usb(**options) -> tek.Scope:
    scope = tek.Scope(tek.Settings({"connection": "usb", **options}))
    scope.open()
    return scope


def test_usb_is_chosen_in_the_settings_and_needs_no_port():
    settings = tek.Settings({"connection": "usb", "usb": " C010001 "})
    assert settings.usb and settings.usb_device == "C010001"
    assert not tek.Settings().usb, "a serial port, unless it is said"
    needs = {setting.key: setting.needs for setting in tek.SETTINGS}
    assert needs["usb"] == ("connection", "usb")
    for serial_only in ("port", "baud", "flow", "parity", "eol"):
        assert needs[serial_only] == ("connection", "serial"), serial_only
    assert tek.SETTINGS[0].key == "connection", "how it is plugged in comes first"


def test_a_scope_on_usb_is_opened_and_named(usb):
    scope = over_usb()
    assert (scope.model, scope.channels) == ("TDS 2024B", 4)
    assert usb.opened == ["USB0::0x0699::0x036A::C010001::INSTR"]
    assert usb.instrument.cleared == 1, "anything left over from before thrown away"
    assert ("On USB: USB0::0x0699::0x036A::C010001::INSTR.", False) in scope.notes
    assert not any(warned for _said, warned in scope.notes), "a TDS2000B is one of the family"
    scope.close()
    assert usb.instrument.closed and usb.closed


def test_a_sweep_over_usb_is_the_same_sweep(usb):
    scope = over_usb(time_div=1e-3, scale_1=0.5)
    scope.start(scope.settings, tek.Trigger("CH1", 0.0, True, 0.5, auto=False))
    block = sweep_of(scope)
    assert len(block) == tek.POINTS and block.rate == pytest.approx(tek.POINTS / 1e-2)
    assert block.data["CH1"][0] == pytest.approx(-2.0)
    port = usb.instrument._port
    assert port.state["CH1:SCALE"] == "0.5" and port.sent("*OPC?") > 0, "set up a setting at a time"
    scope.close()


def test_the_first_tektronix_is_found_among_what_is_plugged_in(usb):
    usb.listed = ("USB0::0x1AB1::0x04CE::DS1ZA1::INSTR", "USB0::1689::874::C010002::0::INSTR")
    over_usb().close()
    assert usb.opened == ["USB0::1689::874::C010002::0::INSTR"], "in decimal too"
    usb.opened.clear()
    over_usb(usb="c010002").close()
    assert usb.opened == ["USB0::1689::874::C010002::0::INSTR"], "by its serial number"


def test_no_tektronix_on_usb_says_what_was_found_and_what_to_check(usb):
    usb.listed = ("USB0::0x1AB1::0x04CE::DS1ZA1::INSTR",)
    with pytest.raises(
        tek.ScopeError, match=r"No scope of Tektronix's.*lists USB0::0x1AB1.*printer"
    ):
        over_usb()
    assert usb.closed, "and the library is let go of"


def test_no_visa_library_says_where_one_comes_from(monkeypatch):
    from pyscopegui.backends import visa

    def none():
        raise OSError("Could not locate a VISA implementation")

    monkeypatch.setattr(visa, "open_visa", none)
    with pytest.raises(tek.ScopeError, match=r"No VISA library was found.*TekVISA"):
        over_usb()
    assert tek.usb_scopes() == [], "and the list of what is plugged in is empty, not an error"


def test_a_scope_unplugged_from_usb_is_said_in_words(usb):
    scope = over_usb()
    scope.start(scope.settings, tek.Trigger())
    usb.instrument._port.dead = True
    with pytest.raises(tek.ScopeError, match="on USB"):
        sweep_of(scope)
    scope.close()


def test_the_window_greys_out_the_serial_settings_for_usb(window):
    window.choose("tektronix2000")
    controls = window.instrument_view.controls
    assert controls["port"].isEnabled() and not controls["usb"].isEnabled()
    connection = controls["connection"]
    connection.setCurrentIndex(connection.findData("usb"))
    connection.activated.emit(connection.currentIndex())
    assert controls["usb"].isEnabled()
    for serial_only in ("port", "baud", "flow", "parity", "eol"):
        assert not controls[serial_only].isEnabled(), serial_only
