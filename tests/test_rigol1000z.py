# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The Rigol DS1000Z back end, against a stand-in scope answering on a real socket."""

import socketserver
import threading
import time

import numpy as np
import pytest

from pyscopegui.backends import rigol1000z as rigol
from pyscopegui.backends.base import Block
from pyscopegui.ui.scope_view import FREE, TRIGGERED


class FakeScope(socketserver.ThreadingTCPServer):
    """Enough of a DS1054Z to be talked to: it remembers what it was sent and answers queries."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.identity = "RIGOL TECHNOLOGIES,DS1054Z,DS1ZA000000001,00.04.04.SP3"
        #: Everything it was sent, in order.
        self.heard: list[str] = []
        #: What was last set: ":CHAN1:SCAL" -> "1".
        self.state: dict[str, str] = {}
        self.status = "STOP"
        #: Whether a trigger comes by itself once it is armed.
        self.triggers = True
        #: How often it has beeped at being read.
        self.beeps = 0
        #: How often setting one end of what is to be read moved the other.
        self.moved = 0
        #: How many points its memory holds.
        self.depth = 600_000
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def address(self) -> str:
        return f"127.0.0.1:{self.server_address[1]}"

    def sent(self, command: str) -> int:
        return self.heard.count(command)

    def answer(self, command: str) -> bytes | None:
        self.heard.append(command)
        what, _, to = command.partition(" ")
        if what == "*IDN?":
            return self.identity.encode() + b"\n"
        if what == "*OPC?":
            return b"1\n"
        if what == ":SING":
            self.status = "STOP" if self.triggers else "WAIT"
        elif what == ":TFOR":
            self.status = "STOP"
        elif what == ":STOP":
            self.status = "STOP"
        elif what == ":TRIG:STAT?":
            return self.status.encode() + b"\n"
        elif what == ":SYST:BEEP?":
            return b"0\n" if self.state.get(":SYST:BEEP") == "OFF" else b"1\n"
        elif what == ":WAV:PRE?":
            return self._preamble().encode() + b"\n"
        elif what == ":WAV:DATA?":
            if self._raw() and self.state.get(":SYST:BEEP", "1") != "OFF":
                self.beeps += 1  # "Can Operate Now!", after each piece of its memory
            data = self._data()
            return b"#9%09d" % len(data) + data + b"\n"
        elif to:
            self.state[what] = to
            # As the real one does: an end set past the other moves that one too.
            first, last = (int(self.state.get(f":WAV:{end}", 1)) for end in ("STAR", "STOP"))
            if what in (":WAV:STAR", ":WAV:STOP") and first > last:
                self.moved += 1
                self.state[":WAV:STOP" if what == ":WAV:STAR" else ":WAV:STAR"] = to
        return None

    def _raw(self) -> bool:
        return self.state.get(":WAV:MODE") == "RAW"

    def _points(self) -> int:
        return self.depth if self._raw() else rigol.SCREEN_POINTS

    def _preamble(self) -> str:
        time_div = float(self.state.get(":TIM:MAIN:SCAL", "0.001"))
        offset = float(self.state.get(":TIM:MAIN:OFFS", "0"))
        points = self._points()
        span = rigol.ACROSS * time_div
        scale = float(self.state.get(f":{self._source()}:SCAL", "1"))
        volts_offset = float(self.state.get(f":{self._source()}:OFFS", "0"))
        y_step = scale / 25
        return (
            f"0,{2 if self._raw() else 0},{points},1,{span / points:e},{offset - span / 2:e},0,"
            f"{y_step:e},{round(volts_offset / y_step)},127"
        )

    def _source(self) -> str:
        return self.state.get(":WAV:SOUR", "CHAN1")

    def _data(self) -> bytes:
        points = self._points()
        # The real one keeps to these for its screen too, whatever they were left at.
        first = min(int(self.state.get(":WAV:STAR", 1)), points)
        last = min(int(self.state.get(":WAV:STOP", points)), points)
        # A ramp from the bottom of the screen to the top, the same on every channel.
        ramp = (np.arange(first - 1, last) * 200 // points + 27).astype(np.uint8)
        return ramp.tobytes()


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        for line in self.rfile:
            answer = self.server.answer(line.decode().strip())
            if answer is not None:
                self.wfile.write(answer)
                self.wfile.flush()


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(rigol, "SETTLE_S", 0.0)
    monkeypatch.setattr(rigol, "AUTO_S", 0.0)
    monkeypatch.setattr(rigol, "QUIET_S", 0.0)
    scope = FakeScope()
    yield scope
    scope.shutdown()
    scope.server_close()


def opened(fake, **options) -> rigol.Scope:
    scope = rigol.Scope(rigol.Settings({"address": fake.address, **options}))
    scope.open()
    return scope


def sweep_of(scope: rigol.Scope, seconds: float = 3.0) -> Block:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if (block := scope.poll()) is not None:
            return block
        time.sleep(0.002)
    raise AssertionError("no sweep came")


# --- settings -------------------------------------------------------------------------------
def test_settings_from_nothing_are_the_defaults():
    for odd in (None, "x", {"time_div": "fast", "scale_1": None, "coupling_2": 3, "probe_1": "x"}):
        settings = rigol.Settings(odd)
        assert settings.keys() == ["CH1"] and settings.time_div == 1e-3
        assert settings.scale["CH1"] == 1.0 and settings.probe["CH1"] == 10
        assert settings.coupling["CH2"] == "DC" and not settings.memory


def test_an_address_may_carry_a_port():
    assert (rigol.Settings({"address": " 10.0.0.7 "}).host, rigol.Settings().port) == (
        "10.0.0.7",
        5555,
    )
    with_port = rigol.Settings({"address": "scope.lan:5025"})
    assert (with_port.host, with_port.port) == ("scope.lan", 5025)


def test_a_scale_that_is_not_one_of_the_scopes_is_the_nearest_that_is():
    assert rigol.Settings({"scale_1": 0.3}).scale["CH1"] == 0.2
    assert rigol.Settings({"time_div": 3e-6}).time_div == 2e-6


def test_every_setting_has_a_group_and_the_keys_are_all_different():
    keys = [setting.key for setting in rigol.SETTINGS]
    assert len(set(keys)) == len(keys)
    assert all(setting.group for setting in rigol.SETTINGS)


def test_the_setup_has_the_trigger_where_the_toolbar_put_it():
    settings = rigol.Settings({"time_div": 1e-3, "enabled_2": True})
    wanted = rigol.setup(settings, rigol.Trigger("CH2", 0.5, False, 0.25))
    assert wanted[":TRIG:EDG:SOUR"] == "CHAN2" and wanted[":TRIG:EDG:SLOP"] == "NEG"
    assert wanted[":TRIG:EDG:LEV"] == "0.5"
    # A quarter of the way across twelve divisions: the middle is three after it.
    assert float(wanted[":TIM:MAIN:OFFS"]) == pytest.approx(0.003)
    assert wanted[":CHAN3:DISP"] == "OFF" and ":CHAN3:SCAL" not in wanted


def test_a_trigger_on_a_channel_that_is_off_is_left_alone():
    wanted = rigol.setup(rigol.Settings(), rigol.Trigger("CH3"))
    assert ":TRIG:EDG:SOUR" not in wanted


def test_a_bandwidth_limit_and_an_acquisition_mode_are_set_with_the_rest():
    settings = rigol.Settings({"limit_1": True, "acquire": "HRES", "enabled_2": True})
    wanted = rigol.setup(settings, rigol.Trigger())
    assert wanted[":CHAN1:BWL"] == "20M" and wanted[":CHAN2:BWL"] == "OFF"
    assert wanted[":ACQ:TYPE"] == "HRES"
    assert ":CHAN3:BWL" not in wanted, "nothing is set on a channel that is off"


def test_an_acquisition_mode_the_scope_has_not_got_is_normal():
    for odd in ("AVER", "fast", None, 3):
        assert rigol.Settings({"acquire": odd}).acquire == "NORM"
    assert rigol.Settings({"limit_1": "yes"}).limit["CH1"] is False


def test_a_limit_is_said_beside_the_channel(app):
    from pyscopegui import backends

    instrument = backends.create("rigol1000z", None, {"limit_1": True})
    assert instrument.channels()[0].detail == "1 V/div, 10x, DC, 20 MHz"


# --- the scope ------------------------------------------------------------------------------
def test_no_address_is_said_in_words():
    with pytest.raises(rigol.ScopeError, match="Instrument pane"):
        rigol.Scope(rigol.Settings()).open()


def test_nothing_listening_is_said_in_words(fake, monkeypatch):
    monkeypatch.setattr(rigol, "CONNECT_S", 0.5)
    address = fake.address
    fake.shutdown()
    fake.server_close()
    with pytest.raises(rigol.ScopeError, match="No scope answered"):
        rigol.Scope(rigol.Settings({"address": address})).open()


def test_opening_says_which_scope_it_is(fake):
    scope = opened(fake)
    assert scope.model == "DS1054Z"
    assert scope.notes == [
        ("RIGOL TECHNOLOGIES DS1054Z, serial DS1ZA000000001, firmware 00.04.04.SP3.", False)
    ]
    scope.close()


def test_another_makers_scope_is_warned_of(fake):
    fake.identity = "KEYSIGHT,DSOX1204G,CN0,1.0"
    scope = opened(fake)
    assert any(is_warning and "DS1000Z" in text for text, is_warning in scope.notes)
    scope.close()


def test_a_sweep_is_the_screen_in_volts_with_the_trigger_in_the_middle(fake):
    scope = opened(fake, time_div=1e-3, scale_1=0.5)
    scope.start(scope.settings, rigol.Trigger("CH1", 0.0, True, 0.5, auto=False))
    block = sweep_of(scope)
    assert block.sweep and len(block) == 1200
    assert block.rate == pytest.approx(100_000)
    assert (block.trigger, block.triggered) == (600, True)
    samples = block.data["CH1"]
    assert samples.dtype == np.float32
    # Twenty-five counts a division, a hundred up and down from the middle.
    assert samples[0] == pytest.approx(-2.0) and samples[-1] == pytest.approx(1.98, abs=0.02)
    assert fake.state[":CHAN1:SCAL"] == "0.5" and fake.state[":TIM:MAIN:SCAL"] == "0.001"
    scope._link.ask("*OPC?")  # so that everything before it has been heard
    assert fake.sent(":SING") == 2, "armed again for the next"
    scope.close()


def test_the_trigger_is_where_the_position_put_it(fake):
    scope = opened(fake)
    scope.start(scope.settings, rigol.Trigger("CH1", 0.0, True, 0.25, auto=False))
    assert sweep_of(scope).trigger == 300
    scope.close()


def test_the_offset_is_taken_off_again(fake):
    scope = opened(fake, scale_1=1.0, offset_1=2.0)
    scope.start(scope.settings, rigol.Trigger())
    assert sweep_of(scope).data["CH1"][0] == pytest.approx(-6.0)
    scope.close()


def test_every_channel_that_is_on_is_read_and_the_others_are_not(fake):
    scope = opened(fake, enabled_1=True, enabled_3=True)
    scope.start(scope.settings, rigol.Trigger())
    assert list(sweep_of(scope).data) == ["CH1", "CH3"]
    assert fake.state[":CHAN2:DISP"] == "OFF" and fake.state[":CHAN3:DISP"] == "ON"
    scope.close()


def test_with_no_trigger_chosen_the_sweep_has_none(fake):
    fake.triggers = False
    scope = opened(fake)
    scope.start(scope.settings, rigol.Trigger(None))
    block = sweep_of(scope)
    assert block.trigger is None and fake.sent(":TFOR") == 1
    scope.close()


def test_auto_makes_it_trigger_and_says_it_was_not(fake):
    fake.triggers = False
    scope = opened(fake, time_div=1e-6)
    scope.start(scope.settings, rigol.Trigger("CH1", auto=True))
    block = sweep_of(scope)
    assert block.trigger == 600 and not block.triggered
    scope.close()


def test_normal_waits_for_as_long_as_it_takes(fake):
    fake.triggers = False
    scope = opened(fake, time_div=1e-6)
    scope.start(scope.settings, rigol.Trigger("CH1", auto=False))
    for _ in range(20):
        assert scope.poll() is None
    assert fake.sent(":TFOR") == 0
    fake.status = "STOP"
    assert sweep_of(scope).triggered
    scope.close()


def test_the_memory_is_read_a_piece_at_a_time(fake):
    scope = opened(fake, read="memory")
    scope.start(scope.settings, rigol.Trigger("CH1", auto=False))
    block = sweep_of(scope)
    assert len(block) == 600_000 and block.trigger == 300_000
    assert block.rate == pytest.approx(50e6)
    assert fake.sent(":WAV:DATA?") == 3
    assert fake.sent(":WAV:STAR 250001") == 1 and fake.sent(":WAV:STOP 600000") == 1
    assert np.all(np.diff(block.data["CH1"]) >= 0), "the pieces in order"
    sweep_of(scope)
    assert fake.moved == 0, "asked for in an order the scope has nothing to put right"
    scope.close()


def test_the_screen_is_read_whole_after_the_memory_was(fake):
    scope = opened(fake, read="memory")
    scope.start(scope.settings, rigol.Trigger())
    sweep_of(scope)
    scope.wanted = rigol.Settings({"address": fake.address})
    assert scope.poll() is None
    assert len(sweep_of(scope)) == 1200
    scope.close()


def test_the_beeper_is_off_while_the_memory_is_read_and_put_back_after(fake):
    scope = opened(fake, read="memory")
    scope.start(scope.settings, rigol.Trigger())
    sweep_of(scope)
    sweep_of(scope)
    assert fake.beeps == 0 and fake.state[":SYST:BEEP"] == "OFF"
    scope.stop()
    scope._link.ask("*OPC?")
    assert fake.state[":SYST:BEEP"] == "ON"
    scope.close()


def test_a_beeper_that_was_off_is_left_off(fake):
    fake.state[":SYST:BEEP"] = "OFF"
    scope = opened(fake, read="memory")
    scope.start(scope.settings, rigol.Trigger())
    sweep_of(scope)
    scope.stop()
    scope._link.ask("*OPC?")
    assert fake.sent(":SYST:BEEP ON") == 0
    scope.close()


def test_the_screen_is_read_without_touching_the_beeper(fake):
    scope = opened(fake)
    scope.start(scope.settings, rigol.Trigger())
    sweep_of(scope)
    assert fake.sent(":SYST:BEEP?") == 0
    scope.close()


def test_a_long_read_is_given_up_when_something_else_is_asked(fake):
    scope = opened(fake, read="memory")
    scope.interrupted = lambda: True
    scope.start(scope.settings, rigol.Trigger())
    assert scope.poll() is None
    assert fake.sent(":WAV:DATA?") == 0
    scope.close()


def test_a_change_as_it_runs_sends_only_what_changed(fake):
    scope = opened(fake)
    scope.start(scope.settings, rigol.Trigger())
    sweep_of(scope)
    before = len(fake.heard)
    scope.wanted = rigol.Settings({"address": fake.address, "scale_1": 2.0})
    assert scope.poll() is None
    sent = [command for command in fake.heard[before:] if command.startswith(":CHAN")]
    assert sent == [":CHAN1:SCAL 2"]
    assert sweep_of(scope).data["CH1"][0] == pytest.approx(-8.0)
    scope.close()


def test_a_scope_that_has_stopped_with_nothing_to_show_yet_is_asked_again(fake):
    scope = opened(fake)
    scope.start(scope.settings, rigol.Trigger("CH1", auto=False))
    real = fake._preamble
    fake._preamble = lambda: "0,0,0,1,0.000000,0.000000,0,0.000000,0,0"
    assert scope.poll() is None
    fake._preamble = real
    assert len(sweep_of(scope)) == 1200
    scope._link.ask("*OPC?")
    assert fake.sent(":SING") == 2, "not armed again for having been early"
    scope.close()


def test_a_limit_changed_as_it_runs_is_sent_by_itself(fake):
    scope = opened(fake)
    scope.start(scope.settings, rigol.Trigger())
    sweep_of(scope)
    assert fake.state[":CHAN1:BWL"] == "OFF" and fake.state[":ACQ:TYPE"] == "NORM"
    before = len(fake.heard)
    scope.wanted = rigol.Settings({"address": fake.address, "limit_1": True, "acquire": "PEAK"})
    assert scope.poll() is None
    scope._link.ask("*OPC?")
    sent = [c for c in fake.heard[before:] if c.startswith((":CHAN", ":ACQ"))]
    assert sent == [":CHAN1:BWL 20M", ":ACQ:TYPE PEAK"]
    scope.close()


def test_stopping_does_not_leave_it_waiting(fake):
    fake.triggers = False
    scope = opened(fake)
    scope.start(scope.settings, rigol.Trigger("CH1", auto=False))
    scope.stop()
    scope.close()
    time.sleep(0.05)
    assert fake.heard[-1] == ":STOP"


def test_a_scope_that_goes_away_is_said_in_words(fake):
    scope = opened(fake)
    scope.start(scope.settings, rigol.Trigger())
    fake.answer = lambda command: None
    scope._link._socket.settimeout(0.2)
    with pytest.raises(rigol.ScopeError):
        sweep_of(scope)
    scope.close()


# --- over USB ---------------------------------------------------------------------------------
class FakeInstrument:
    """A scope as a VISA library hands it over: the stand-in above, without the socket."""

    def __init__(self, scope, pieces=1) -> None:
        self._scope = scope
        #: How many pieces a block is handed over in.
        self._pieces = pieces
        self._waiting = b""
        self.timeout = None
        self.write_termination = None
        self.read_termination = "\n"
        self.closed = False

    def write(self, command: str) -> None:
        self._waiting = self._scope.answer(command) or b""

    def query(self, command: str) -> str:
        self.write(command)
        return self.read_raw().decode()

    def read_raw(self) -> bytes:
        if self.read_termination is not None:
            raise AssertionError("a read would stop at the first new line in a waveform")
        size = len(self._waiting)
        if self._pieces > 1 and self._waiting[:1] == b"#" and size > 100:
            # A block, handed over a part at a time; a line of text comes whole.
            size = size // self._pieces
            self._pieces -= 1
        taken, self._waiting = self._waiting[:size], self._waiting[size:]
        return taken

    def close(self) -> None:
        self.closed = True


class FakeVisa:
    def __init__(self, scope, listed=("USB0::0x1AB1::0x04CE::DS1ZA000000001::INSTR",)) -> None:
        self.listed = listed
        self.instrument = FakeInstrument(scope)
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
def visa(fake, monkeypatch):
    library = FakeVisa(fake)
    monkeypatch.setattr(rigol, "open_visa", lambda: library)
    return library


def over_usb(**options) -> rigol.Scope:
    scope = rigol.Scope(rigol.Settings({"connection": "usb", **options}))
    scope.open()
    return scope


def test_usb_is_chosen_in_the_settings_and_needs_no_address():
    settings = rigol.Settings({"connection": "usb", "usb": " DS1ZA7 "})
    assert settings.usb and settings.usb_device == "DS1ZA7"
    assert not rigol.Settings().usb, "the network, unless it is said"
    needs = {setting.key: setting.needs for setting in rigol.SETTINGS}
    assert needs["address"] == ("connection", "lan") and needs["usb"] == ("connection", "usb")


def test_the_first_of_rigols_is_found_among_what_is_plugged_in():
    listed = (
        "USB0::0x0957::0x1796::MY1::INSTR",
        "USB0::0x1AB1::0x04CE::DS1ZA111::INSTR",
        "USB0::0x1ab1::0x04CE::DS1ZA222::INSTR",
    )
    assert rigol.find_usb(listed, "") == listed[1]
    assert rigol.find_usb(listed, "ds1za222") == listed[2], "by its serial number, in any case"
    assert rigol.find_usb(listed, "DS1ZA999") is None
    assert rigol.find_usb(("USB0::6833::1230::DS1ZA1::0::INSTR",), "") is not None, "in decimal too"
    assert rigol.find_usb(listed[:1], "") is None, "somebody else's instrument is not a guess"


def test_a_scope_on_usb_is_opened_and_named(visa):
    scope = over_usb()
    assert scope.model == "DS1054Z"
    assert visa.opened == ["USB0::0x1AB1::0x04CE::DS1ZA000000001::INSTR"]
    assert visa.instrument.read_termination is None and visa.instrument.write_termination == "\n"
    scope.close()
    assert visa.instrument.closed and visa.closed


def test_a_sweep_over_usb_is_the_same_sweep(visa):
    scope = over_usb(time_div=1e-3, scale_1=0.5)
    scope.start(scope.settings, rigol.Trigger("CH1", 0.0, True, 0.5, auto=False))
    block = sweep_of(scope)
    assert len(block) == 1200 and block.rate == pytest.approx(100_000)
    assert (block.trigger, block.triggered) == (600, True)
    assert block.data["CH1"][0] == pytest.approx(-2.0)
    scope.close()


def test_a_block_that_arrives_in_pieces_is_put_together(visa):
    scope = over_usb()
    scope.start(scope.settings, rigol.Trigger())
    visa.instrument._pieces = 3
    block = sweep_of(scope)
    assert visa.instrument._pieces < 3, "it was handed over a part at a time"
    assert len(block) == 1200 and np.all(np.diff(block.data["CH1"]) >= 0)
    scope.close()


def test_the_memory_is_read_over_usb_too(visa):
    scope = over_usb(read="memory")
    scope.start(scope.settings, rigol.Trigger("CH1", auto=False))
    assert len(sweep_of(scope)) == 600_000
    scope.close()


def test_no_scope_on_usb_says_what_was_found(visa):
    visa.listed = ("USB0::0x0957::0x1796::MY1::INSTR",)
    with pytest.raises(rigol.ScopeError, match="lists USB0::0x0957"):
        over_usb()
    assert visa.closed, "and the library is let go of"
    visa.listed = ()
    with pytest.raises(rigol.ScopeError, match="lists nothing"):
        over_usb()
    with pytest.raises(rigol.ScopeError, match="matching 'DS1ZA9'"):
        over_usb(usb="DS1ZA9")


def test_no_visa_library_says_where_one_comes_from(monkeypatch):
    def none():
        raise OSError("Could not locate a VISA implementation")

    monkeypatch.setattr(rigol, "open_visa", none)
    with pytest.raises(rigol.ScopeError, match="No VISA library was found"):
        over_usb()


def test_no_pyvisa_says_what_to_install(monkeypatch):
    def missing():
        raise ImportError("No module named 'pyvisa'")

    monkeypatch.setattr(rigol, "open_visa", missing)
    with pytest.raises(rigol.ScopeError, match="pip install pyvisa"):
        over_usb()


def test_a_scope_unplugged_from_usb_is_said_in_words(visa):
    scope = over_usb()
    scope.start(scope.settings, rigol.Trigger())

    def gone(_command):
        raise OSError("VI_ERROR_TMO")

    visa.instrument.query = gone
    with pytest.raises(rigol.ScopeError, match="on USB"):
        sweep_of(scope)
    scope.close()


def test_the_window_greys_out_the_address_for_usb_and_opens_the_scope(window, visa, app):
    box = window.instrument_bar.instrument
    box.setCurrentIndex(box.findData("rigol1000z"))
    controls = window.instrument_view.controls
    assert controls["address"].isEnabled() and not controls["usb"].isEnabled()
    connection = controls["connection"]
    connection.setCurrentIndex(connection.findData("usb"))
    connection.activated.emit(connection.currentIndex())
    assert not controls["address"].isEnabled() and controls["usb"].isEnabled()
    window.instrument_bar.open.click()
    wait_for(app, lambda: window.instrument.is_open)
    assert "DS1054Z" in window.log.toPlainText()
    window.close_instrument()


# --- in the window --------------------------------------------------------------------------
def wait_for(app, done, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not done() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert done(), "timed out"


@pytest.fixture
def scope_window(window, fake):
    window.ctx.settings.set("instrument.rigol1000z", {"address": fake.address, "enabled_2": True})
    box = window.instrument_bar.instrument
    box.setCurrentIndex(box.findData("rigol1000z"))
    yield window
    window.close_instrument()


def test_the_window_shows_a_sweep_around_the_scopes_trigger(scope_window, fake, app):
    window = scope_window
    assert window.instrument_view.controls["address"].text() == fake.address
    window.instrument_bar.open.click()
    wait_for(app, lambda: window.instrument.is_open)
    assert "DS1054Z" in window.log.toPlainText()
    box = window.trigger_bar.source
    box.setCurrentIndex(box.findData("CH2"))
    box.activated.emit(box.currentIndex())
    window.set_mode("normal")
    wait_for(app, lambda: window.acquisition.sweep is not None)
    assert set(window.capture.records) == {"CH1", "CH2"}
    window.scope.redraw()
    low, high = window.scope.analog.getViewBox().viewRange()[0]
    assert low == pytest.approx(-0.006, rel=1e-3) and high == pytest.approx(0.006, rel=1e-3)
    assert window.scope.state.text() == TRIGGERED
    assert fake.state[":TRIG:EDG:SOUR"] == "CHAN2"


def test_auto_with_nothing_to_trigger_on_says_so(scope_window, fake, app):
    window = scope_window
    fake.triggers = False
    window.instrument_bar.open.click()
    box = window.trigger_bar.source
    box.setCurrentIndex(box.findData("CH1"))
    box.activated.emit(box.currentIndex())
    window.set_mode("auto")
    wait_for(app, lambda: window.acquisition.sweep is not None)
    window.scope.redraw()
    assert window.scope.state.text() == FREE


def test_single_takes_one_sweep_and_stops(scope_window, fake, app):
    window = scope_window
    window.instrument_bar.modes["single"].click()
    wait_for(app, lambda: window.acquisition.sweep is not None)
    wait_for(app, lambda: not window.instrument.running)
    assert window.instrument_bar.mode() == "stop" and window.instrument.is_open


def test_no_address_says_so_and_goes_back_to_closed(window, app):
    box = window.instrument_bar.instrument
    box.setCurrentIndex(box.findData("rigol1000z"))
    window.instrument_bar.open.click()
    wait_for(app, lambda: "No address" in window.log.toPlainText())
    wait_for(app, lambda: window.instrument_bar.instrument.isEnabled())
    assert not window.instrument.is_open


def test_an_address_typed_in_is_saved(window, app):
    box = window.instrument_bar.instrument
    box.setCurrentIndex(box.findData("rigol1000z"))
    line = window.instrument_view.controls["address"]
    line.setText(" 192.168.1.50 ")
    line.editingFinished.emit()
    assert window.ctx.settings.get("instrument.rigol1000z")["address"] == "192.168.1.50"


def test_an_address_typed_and_not_finished_with_is_amber_and_open_takes_it_up(window, fake, app):
    from pyscopegui.ui.instrument_view import PENDING

    box = window.instrument_bar.instrument
    box.setCurrentIndex(box.findData("rigol1000z"))
    line = window.instrument_view.controls["address"]
    line.setText(fake.address)
    assert line.styleSheet() == PENDING
    assert "address" not in (window.ctx.settings.get("instrument.rigol1000z") or {})
    window.instrument_bar.open.click()
    assert line.styleSheet() == ""
    wait_for(app, lambda: window.instrument.is_open)
    assert window.ctx.settings.get("instrument.rigol1000z")["address"] == fake.address
    window.close_instrument()


def test_typing_back_what_was_there_is_not_waiting(window, app):
    from pyscopegui.ui.instrument_view import PENDING

    box = window.instrument_bar.instrument
    box.setCurrentIndex(box.findData("rigol1000z"))
    line = window.instrument_view.controls["address"]
    line.setText("10.0.0.1")
    assert line.styleSheet() == PENDING
    line.setText("")
    assert line.styleSheet() == ""
