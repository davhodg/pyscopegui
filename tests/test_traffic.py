# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Everything said to an instrument and back, kept only while somebody is looking."""

import ctypes

import pytest

from pyscopegui.core import traffic as module
from pyscopegui.core.traffic import CALL, RECEIVED, SENT, Note, traffic


@pytest.fixture(autouse=True)
def quiet():
    """Nothing left over from another test, and nothing kept after this one."""
    traffic.listen(False)
    traffic.take()
    yield
    traffic.listen(False)
    traffic.take()


class FakeLink:
    def __init__(self):
        self.heard = []
        self.port = "COM9"

    def write(self, command):
        self.heard.append(command)

    def ask(self, command, wait=None):
        self.heard.append(command)
        if command == "BAD?":
            raise OSError("silence")
        return "1\n" if command == "*OPC?" else "x" * 500

    def answer(self, command, wait=None):
        return "TEKTRONIX,TPS 2014"

    def ask_bytes(self, command):
        self.heard.append(command)
        return bytes(2500)


def texts():
    return [(note.direction, note.text) for note in traffic.take()]


# --- the recorder ------------------------------------------------------------------------------
def test_nothing_is_kept_while_nobody_is_looking():
    traffic.note("Rigol", SENT, "*IDN?")
    assert traffic.take() == []


def test_what_is_noted_is_taken_once():
    traffic.listen(True)
    traffic.note("Rigol", SENT, "*IDN?")
    traffic.note("Rigol", RECEIVED, "RIGOL", took=0.01)
    taken = traffic.take()
    assert [(n.who, n.direction, n.text, n.took) for n in taken] == [
        ("Rigol", SENT, "*IDN?", None),
        ("Rigol", RECEIVED, "RIGOL", 0.01),
    ]
    assert traffic.take() == []


def test_a_pane_left_paused_keeps_only_the_newest(monkeypatch):
    monkeypatch.setattr(module, "MOST", 3)
    fresh = module.Traffic()
    fresh.listen(True)
    for number in range(5):
        fresh.note("Pico", CALL, str(number))
    assert [note.text for note in fresh.take()] == ["2", "3", "4"]


# --- a connection, wrapped ---------------------------------------------------------------------
def test_a_command_and_its_answer_are_noted_with_how_long_it_took():
    traffic.listen(True)
    link = module.traced(FakeLink(), "Tektronix COM9")
    link.write("HEADER OFF")
    assert link.ask("*OPC?") == "1\n"
    taken = traffic.take()
    assert [(n.direction, n.text) for n in taken] == [
        (SENT, "HEADER OFF"),
        (SENT, "*OPC?"),
        (RECEIVED, "1\\n"),
    ]
    assert taken[2].took is not None and taken[2].took >= 0
    assert link.port == "COM9", "and the rest is the connection's own"


def test_a_waveform_is_how_many_bytes_and_a_long_answer_is_cut_short():
    traffic.listen(True)
    link = module.traced(FakeLink(), "Rigol")
    link.ask_bytes("CURVE?")
    link.ask("LONG?")
    said = texts()
    assert said[1] == (RECEIVED, "2,500 bytes")
    assert said[3][1].endswith("(500 characters)") and len(said[3][1]) < 260


def test_an_answer_that_never_came_is_noted_and_still_raised():
    traffic.listen(True)
    link = module.traced(FakeLink(), "Rigol")
    with pytest.raises(OSError):
        link.ask("BAD?")
    assert texts()[-1] == (RECEIVED, "no answer: silence")


def test_an_answer_read_by_itself_is_noted():
    traffic.listen(True)
    link = module.traced(FakeLink(), "Tektronix COM9")
    link.write("*IDN?")
    assert link.answer("*IDN?", wait=60) == "TEKTRONIX,TPS 2014"
    assert texts() == [(SENT, "*IDN?"), (RECEIVED, "TEKTRONIX,TPS 2014")]


def test_with_nobody_looking_the_connection_is_used_as_it_is():
    raw = FakeLink()
    link = module.traced(raw, "Rigol")
    link.write("*RST")
    assert raw.heard == ["*RST"] and traffic.take() == []


# --- a library, wrapped ------------------------------------------------------------------------
class FakeLibrary:
    def ps2000_set_channel(self, handle, channel, enabled, dc, code):
        return 1

    def ps2000_get_values(self, handle, a, b, c, d, overflow, samples):
        return samples

    def ps2000_broken(self):
        raise OSError("gone")


def test_each_call_is_noted_with_what_it_was_given_and_what_it_returned():
    traffic.listen(True)
    library = module.traced_library(FakeLibrary(), "PicoScope")
    library.ps2000_set_channel(1, 0, True, True, 8)
    buffer = (ctypes.c_int16 * 16)()
    overflow = ctypes.c_int16(0)
    library.ps2000_get_values(1, buffer, None, None, None, ctypes.byref(overflow), 16)
    assert texts() == [
        (CALL, "ps2000_set_channel(1, 0, True, True, 8) -> 1"),
        (CALL, "ps2000_get_values(1, buffer[16], NULL, NULL, NULL, &out, 16) -> 16"),
    ]


def test_a_call_that_fails_is_noted_and_still_raised():
    traffic.listen(True)
    library = module.traced_library(FakeLibrary(), "PicoScope")
    with pytest.raises(OSError):
        library.ps2000_broken()
    assert texts() == [(CALL, "ps2000_broken() failed: gone")]


def test_with_nobody_looking_a_call_is_the_librarys_own():
    raw = FakeLibrary()
    library = module.traced_library(raw, "PicoScope")
    assert library.ps2000_set_channel == raw.ps2000_set_channel


# --- the instruments' own connections ----------------------------------------------------------
def test_the_tektronix_is_heard_through_its_serial_port(monkeypatch):
    from tests.test_tektronix2000 import FakePort, tek

    port = FakePort()
    monkeypatch.setattr(tek, "open_port", lambda *_a, **_k: port)
    traffic.listen(True)
    scope = tek.Scope(tek.Settings({"port": "COM9"}))
    scope.open()
    said = traffic.take()
    assert {note.who for note in said} == {"Tektronix COM9"}
    assert (SENT, "*IDN?") in [(n.direction, n.text) for n in said]
    assert any(n.direction == RECEIVED and "TPS 2014" in n.text for n in said)
    scope.close()


def test_the_picoscope_is_heard_through_its_library():
    from pyscopegui.backends import picoscope2000 as pico
    from tests.test_picoscope2000 import FakeLibrary as FakePico

    traffic.listen(True)
    reading = pico.Stream(FakePico(), pico.Settings())
    reading.open()
    said = traffic.take()
    assert said[0].who == "PicoScope" and said[0].text == "ps2000_open_unit() -> 1"


# --- the pane ----------------------------------------------------------------------------------
def pane(window):
    return window.traffic


def test_the_pane_starts_put_away_and_keeps_nothing(window):
    assert not window.panes.on_screen("traffic") and not traffic.on


def test_opening_the_pane_starts_recording_and_putting_it_away_stops_it(window, app):
    window.panes.show("traffic")
    app.processEvents()
    assert traffic.on
    window.panes.docks["traffic"].close()
    app.processEvents()
    assert not traffic.on


def test_lines_are_shown_with_which_way_and_how_long(window, app):
    view = pane(window)
    view.listen(True)
    traffic.note("Tektronix COM7", SENT, "*OPC?")
    traffic.note("Tektronix COM7", RECEIVED, "1", took=0.815)
    view._take()
    lines = view.shown_text().splitlines()
    assert lines[0].endswith("Tektronix COM7         -> *OPC?")
    assert lines[1].endswith("<- 1   (815 ms)")
    view.listen(False)


def test_the_same_line_running_is_counted_on_one_line(window):
    view = pane(window)
    view.listen(True)
    for _ in range(37):
        traffic.note("PicoScope", CALL, "ps2000_ready(1) -> 1", took=0.0)
    traffic.note("PicoScope", CALL, "ps2000_get_values(...) -> 16", took=0.0)
    view._take()
    lines = view.shown_text().splitlines()
    assert len(lines) == 2 and lines[0].endswith("x37")
    view.listen(False)


def test_one_instrument_can_be_shown_by_itself(window):
    view = pane(window)
    view.listen(True)
    traffic.note("Rigol 192.168.1.13", SENT, "*IDN?")
    traffic.note("Tektronix COM7", SENT, "*IDN?")
    view._take()
    view.who.setCurrentText("Tektronix COM7")
    assert [line.split()[1] for line in view.shown_text().splitlines()] == ["Tektronix"]
    view.who.setCurrentText("Every instrument")
    assert len(view.shown_text().splitlines()) == 2
    view.listen(False)


def test_paused_nothing_is_added_and_nothing_is_lost(window):
    view = pane(window)
    view.listen(True)
    view.pause.setChecked(True)
    traffic.note("Rigol", SENT, "*IDN?")
    view._take()
    assert view.shown_text() == ""
    view.pause.setChecked(False)
    assert "*IDN?" in view.shown_text()
    view.listen(False)


def test_clear_and_save(window, tmp_path):
    view = pane(window)
    view.listen(True)
    traffic.note("Rigol", SENT, "*IDN?")
    view._take()
    view.save(tmp_path / "traffic.txt")
    assert "*IDN?" in (tmp_path / "traffic.txt").read_text(encoding="utf-8")
    view.clear()
    assert view.shown_text() == ""
    view.listen(False)


def test_left_open_it_is_put_away_again_the_next_time(window, app):
    from pyscopegui.ui.main_window import MainWindow

    window.panes.show("traffic")
    app.processEvents()
    window.save_arrangement()
    window.close()
    again = MainWindow()
    again.show()
    app.processEvents()
    try:
        assert not again.panes.on_screen("traffic") and not traffic.on
    finally:
        again.close()
        again.deleteLater()


def test_closing_the_window_stops_recording(app):
    from pyscopegui.ui.main_window import MainWindow

    made = MainWindow()
    made.show()
    made.panes.show("traffic")
    app.processEvents()
    assert traffic.on
    made.close()
    made.deleteLater()
    assert not traffic.on


def test_a_note_is_a_line_of_its_own_text():
    from pyscopegui.ui.traffic_view import Entry

    entry = Entry(Note(0.0, "Rigol", SENT, "*IDN?"))
    assert entry.text().endswith("Rigol                  -> *IDN?")
