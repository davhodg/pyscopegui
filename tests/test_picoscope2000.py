# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The PicoScope back end, against a stand-in for Pico's library.

Neither the library nor a scope is on a test machine. The stand-in answers
the calls the way Pico's programmer's guide says the driver does, and hands
its samples over through the same C callback, so what is checked is
everything on pyscopegui's side of that boundary. What the real driver does
is checked with a scope on the desk.
"""

import ctypes
from pathlib import Path

import numpy as np
import pytest

from pyscopegui import backends
from pyscopegui.backends import picoscope2000 as pico


class FakeLibrary:
    """Pico's ps2000 library, as far as the back end uses it."""

    def __init__(self, handle=1, info=None):
        self.handle = handle
        self.info = {pico.INFO_VARIANT: b"2204A", pico.INFO_SERIAL: b"AB123/456"} | (info or {})
        self.calls = []
        #: What each poll hands over next: (A's samples, B's samples) in counts.
        self.waiting = []
        self.refused_ranges = set()
        self.streams = True
        self.generates = True
        self.overrun = False

    def ps2000_open_unit(self):
        self.calls.append(("open",))
        return self.handle

    def ps2000_get_unit_info(self, handle, text, length, line):
        value = self.info.get(line, b"")
        text.value = value[: length - 1]
        return len(value)

    def ps2000_set_channel(self, handle, channel, enabled, dc, code):
        self.calls.append(("channel", channel, bool(enabled), bool(dc), code))
        return 0 if code in self.refused_ranges else 1

    def ps2000_set_trigger(self, handle, source, threshold, direction, delay, auto_ms):
        self.calls.append(("trigger", source))
        return 1

    def ps2000_run_streaming_ns(self, handle, interval, units, most, auto_stop, per, overview):
        self.calls.append(("stream", interval, units, most, auto_stop, per, overview))
        return 1 if self.streams else 0

    def ps2000_get_streaming_last_values(self, handle, callback):
        if not self.waiting:
            return 0
        a, b = self.waiting.pop(0)
        count = len(a if a is not None else b)
        kept = []  # the arrays, alive for as long as the callback runs

        def pointer(samples):
            if samples is None:
                return ctypes.POINTER(ctypes.c_int16)()  # a channel that is off
            kept.append(np.asarray(samples, dtype=np.int16))
            return kept[-1].ctypes.data_as(ctypes.POINTER(ctypes.c_int16))

        buffers = (ctypes.POINTER(ctypes.c_int16) * 4)(
            pointer(a), pointer(a), pointer(b), pointer(b)
        )
        callback(buffers, 0, 0, 0, 0, count)
        return 1

    def ps2000_overview_buffer_status(self, handle, overrun):
        overrun._obj.value = int(self.overrun)
        return 0

    def ps2000_set_sig_gen_built_in(
        self, handle, offset, pk_to_pk, wave, start, stop, increment, dwell, sweep, sweeps
    ):
        self.calls.append(("generator", offset, pk_to_pk, wave, start, stop))
        return 1 if self.generates else 0

    def ps2000_stop(self, handle):
        self.calls.append(("stop",))
        return 1

    def ps2000_close_unit(self, handle):
        self.calls.append(("close",))
        return 1


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def stream(library, options=None, clock=None):
    return pico.Stream(library, pico.Settings(options), clock or Clock())


# --- settings --------------------------------------------------------------------------------
def test_the_defaults_are_two_channels_at_five_volts():
    settings = pico.Settings()
    assert settings.keys() == ["A", "B"]
    assert settings.ranges == {"A": "5V", "B": "5V"}
    assert settings.dc == {"A": True, "B": True}
    assert settings.rate == pico.DEFAULT_RATE


def test_the_rate_is_the_one_a_whole_number_of_nanoseconds_gives():
    """300 kS/s is not a whole number of nanoseconds a sample, and time on
    the plot has to come from the interval the scope was really given."""
    settings = pico.Settings({"rate": 300_000})
    assert settings.interval_ns == 3333
    assert settings.rate == pytest.approx(1e9 / 3333)


@pytest.mark.parametrize("options", [None, [], "fast", {"rate": "fast"}, {"rate": 0}])
def test_settings_nobody_can_read_are_the_defaults(options):
    settings = pico.Settings(options)
    assert settings.rate == pico.DEFAULT_RATE


def test_a_range_nobody_has_heard_of_is_the_default():
    assert pico.Settings({"range_a": "3V", "range_b": "200mV"}).ranges == {"A": "5V", "B": "200mV"}


def test_channel_b_can_be_switched_off():
    assert pico.Settings({"enabled_b": False}).keys() == ["A"]


# --- opening ---------------------------------------------------------------------------------
def test_opening_sets_both_channels_and_starts_fast_streaming():
    library = FakeLibrary()
    opened = stream(library, {"range_a": "1V", "coupling_b": "AC"})
    opened.open()
    assert library.calls == [
        ("open",),
        ("channel", pico.CHANNEL_A, True, True, 6),
        ("channel", pico.CHANNEL_B, True, False, 8),
        ("generator", 0, 0, pico.WAVES["off"], 1000.0, 1000.0),
        ("trigger", pico.NO_TRIGGER),
        ("stream", 2000, pico.TIME_UNITS_NS, pico.DRIVER_SAMPLES, 0, 1, pico.OVERVIEW_SAMPLES),
    ]
    assert opened.notes == [("PicoScope 2204A, AB123/456.", False)]


def test_no_scope_found_says_what_to_check():
    with pytest.raises(pico.ScopeError, match="plugged in"):
        stream(FakeLibrary(handle=0)).open()


def test_a_scope_that_will_not_open_says_why():
    library = FakeLibrary(handle=-1, info={pico.INFO_ERROR: b"4"})
    with pytest.raises(pico.ScopeError, match="firmware"):
        stream(library).open()


def test_a_driver_that_fails_inside_opening_is_said_and_not_raised_as_it_is():
    """What ps2000_open_unit did when the scope left the bus under it."""
    library = FakeLibrary()

    def fails():
        raise OSError("[WinError -529697949] Windows Error 0xe06d7363")

    library.ps2000_open_unit = fails
    with pytest.raises(pico.ScopeError, match="drops off USB"):
        stream(library).open()


def test_a_range_the_model_does_not_have_is_said():
    library = FakeLibrary()
    library.refused_ranges = {1}
    with pytest.raises(pico.ScopeError, match="channel A to ±20mV"):
        stream(library, {"range_a": "20mV"}).open()


def test_a_rate_the_scope_refuses_is_said():
    library = FakeLibrary()
    library.streams = False
    with pytest.raises(pico.ScopeError, match="lower rate"):
        stream(library).open()


def test_closing_stops_and_lets_go_and_does_nothing_if_it_never_opened():
    library = FakeLibrary()
    never = stream(library)
    never.close()
    assert library.calls == []
    opened = stream(library)
    opened.open()
    opened.close()
    assert library.calls[-2:] == [("stop",), ("close",)]


# --- reading ---------------------------------------------------------------------------------
def test_counts_become_volts_at_the_range_each_channel_is_on():
    library = FakeLibrary()
    reading = stream(library, {"range_a": "5V", "range_b": "200mV"})
    reading.open()
    library.waiting.append(([pico.MAX_VALUE, 0, -pico.MAX_VALUE], [pico.MAX_VALUE, 0, 0]))
    block = reading.poll()
    assert block.first == 0 and block.rate == pico.DEFAULT_RATE
    assert block.data["A"].dtype == np.float32
    assert block.data["A"].tolist() == pytest.approx([5.0, 0.0, -5.0])
    assert block.data["B"].tolist() == pytest.approx([0.2, 0.0, 0.0])


def test_blocks_are_numbered_from_the_samples_before_them():
    library = FakeLibrary()
    reading = stream(library)
    reading.open()
    library.waiting += [([1] * 700, [2] * 700), ([3] * 50, [4] * 50)]
    first, second = reading.poll(), reading.poll()
    assert (first.first, len(first)) == (0, 700)
    assert (second.first, len(second)) == (700, 50)


def test_nothing_waiting_is_no_block():
    reading = stream(FakeLibrary())
    reading.open()
    assert reading.poll() is None


def test_a_sample_the_driver_lost_is_a_gap_and_not_minus_full_scale():
    library = FakeLibrary()
    reading = stream(library)
    reading.open()
    library.waiting.append(([100, pico.LOST_DATA, 100], [0, 0, 0]))
    samples = reading.poll().data["A"]
    assert np.isnan(samples[1]) and not np.isnan(samples[[0, 2]]).any()


def test_a_channel_that_is_off_sends_nothing():
    library = FakeLibrary()
    reading = stream(library, {"enabled_b": False})
    reading.open()
    library.waiting.append(([1, 2, 3], None))
    assert set(reading.poll().data) == {"A"}


def test_the_samples_are_copied_out_of_the_drivers_buffer():
    """The driver reuses its buffers as soon as the callback returns."""
    library = FakeLibrary()
    reading = stream(library)
    reading.open()
    theirs = np.array([1000, 2000], dtype=np.int16)
    library.waiting.append((theirs, theirs))
    block = reading.poll()
    theirs[:] = 0
    assert block.data["A"][0] != 0


def test_a_full_driver_buffer_is_a_warning():
    library = FakeLibrary()
    reading = stream(library)
    reading.open()
    reading.notes.clear()
    library.overrun = True
    library.waiting.append(([1], [1]))
    reading.poll()
    assert reading.notes and reading.notes[0][1] is True
    assert "samples were lost" in reading.notes[0][0]


def test_samples_arriving_at_half_the_rate_asked_for_are_said_once():
    """What a scope sharing its streaming rate between two channels would do."""
    library, clock = FakeLibrary(), Clock()
    reading = stream(library, clock=clock)
    reading.open()
    reading.notes.clear()
    clock.now = pico.CHECK_AFTER_S + 1
    library.waiting += [([0] * 1_500_000, [0] * 1_500_000), ([0], [0])]
    reading.poll()
    reading.poll()
    warnings = [text for text, is_warning in reading.notes if is_warning]
    assert len(warnings) == 1
    assert "250,000 samples a second where 500,000 were asked for" in warnings[0]


def test_samples_arriving_at_the_rate_asked_for_say_nothing():
    library, clock = FakeLibrary(), Clock()
    reading = stream(library, clock=clock)
    reading.open()
    reading.notes.clear()
    clock.now = 6.0
    library.waiting.append(([0] * 3_000_000, [0] * 3_000_000))
    reading.poll()
    assert reading.notes == []


# --- the signal generator ----------------------------------------------------------------------
def test_the_generator_is_off_unless_asked_for():
    assert pico.Settings().generator[0] == "off"
    assert pico.Settings({"gen_wave": "sawtooth"}).generator[0] == "off"


def test_generator_settings_are_kept_to_what_the_output_can_do():
    settings = pico.Settings(
        {"gen_wave": "sine", "gen_frequency": 5e6, "gen_amplitude": 9, "gen_offset": -7}
    )
    assert settings.generator == ("sine", pico.GENERATOR_HZ, 4.0, -2.0)
    assert pico.Settings({"gen_frequency": "fast"}).generator[1] == 1000.0


def test_a_generator_asked_for_is_set_as_the_scope_opens_in_microvolts():
    library = FakeLibrary()
    opened = stream(
        library,
        {"gen_wave": "square", "gen_frequency": 250, "gen_amplitude": 1.5, "gen_offset": 0.25},
    )
    opened.open()
    assert ("generator", 250_000, 1_500_000, pico.WAVES["square"], 250.0, 250.0) in library.calls
    assert ("Signal generator: square, 250 Hz, 1.5 V peak to peak, 0.25 V offset.", False) in (
        opened.notes
    )


def test_a_generator_change_while_running_is_made_between_two_polls():
    library = FakeLibrary()
    reading = stream(library)
    reading.open()
    library.calls.clear()
    reading.notes.clear()
    reading.wanted_generator = ("sine", 1000.0, 2.0, 0.0)
    reading.poll()
    reading.poll()
    assert library.calls == [("generator", 0, 2_000_000, pico.WAVES["sine"], 1000.0, 1000.0)]
    reading.wanted_generator = ("off", 1000.0, 2.0, 0.0)
    reading.poll()
    assert library.calls[-1] == ("generator", 0, 0, pico.WAVES["off"], 1000.0, 1000.0)
    assert [text for text, _ in reading.notes][-1] == "Signal generator: off."


def test_a_scope_with_no_generator_warns_only_when_one_is_asked_for():
    library = FakeLibrary()
    library.generates = False
    quiet = stream(library)
    quiet.open()
    assert not any(is_warning for _text, is_warning in quiet.notes)
    asked = stream(library, {"gen_wave": "sine"})
    asked.open()
    assert any("would not set its signal generator" in text for text, _ in asked.notes)


def test_the_running_instrument_passes_a_generator_setting_to_its_thread(app, monkeypatch):
    library = FakeLibrary()
    monkeypatch.setattr(pico, "load_library", lambda: library)
    instrument = backends.create("picoscope2000")
    states = []
    instrument.state_changed.connect(states.append)
    instrument.start()
    run_for(app, instrument, lambda: states == [True])
    instrument.set("gen_wave", "triangle")
    wanted = ("generator", 0, 2_000_000, pico.WAVES["triangle"], 1000.0, 1000.0)
    run_for(app, instrument, lambda: wanted in library.calls)
    instrument.stop()
    run_for(app, instrument, lambda: states == [True, False])


# --- what can be set ---------------------------------------------------------------------------
def test_every_setting_offered_is_one_the_back_end_reads():
    """A control whose key nothing reads would look as if it worked."""
    defaults = {s.key: s.default for s in pico.SETTINGS}
    assert len(defaults) == len(pico.SETTINGS)
    by_default = pico.Settings(defaults)
    plain = pico.Settings()
    assert vars(by_default) == vars(plain)
    for setting in pico.SETTINGS:
        other = next(
            (value for value, _label in setting.choices if value != setting.default),
            setting.maximum,
        )
        changed = pico.Settings(defaults | {setting.key: other})
        # The generator's numbers only show once it is on.
        if setting.key.startswith("gen_") and setting.key != "gen_wave":
            assert changed.generator != plain.generator
        else:
            assert vars(changed) != vars(plain), setting.key


def test_only_the_generator_changes_without_a_restart():
    assert {s.key for s in pico.SETTINGS if s.live} == {
        "gen_wave",
        "gen_frequency",
        "gen_amplitude",
        "gen_offset",
    }


# --- the library -----------------------------------------------------------------------------
def test_the_library_named_in_the_environment_is_the_one_used():
    environ = {pico.LIBRARY_ENV: "/somewhere/libps2000.so"}
    assert pico.find_library("linux", environ) == Path("/somewhere/libps2000.so")


def test_windows_looks_where_the_sdk_and_picoscope_7_put_it(tmp_path):
    edition = tmp_path / "Pico Technology" / "PicoScope 7 T&M Stable"
    edition.mkdir(parents=True)
    (edition / "ps2000.dll").write_bytes(b"")
    candidates = pico.library_candidates("win32", {"ProgramFiles": str(tmp_path)})
    assert candidates[0] == tmp_path / "Pico Technology" / "SDK" / "lib" / "ps2000.dll"
    assert edition / "ps2000.dll" in candidates
    assert pico.find_library("win32", {"ProgramFiles": str(tmp_path)}) == edition / "ps2000.dll"


def test_without_the_library_the_instrument_says_what_to_install(app, monkeypatch):
    monkeypatch.setattr(pico, "find_library", lambda: None)
    with pytest.raises(ImportError, match=r"picotech\.com/downloads"):
        backends.create("picoscope2000")


def test_every_function_used_has_its_arguments_declared():
    """A call with undeclared arguments passes Python ints as C ints, which
    is the wrong width for most of these."""
    used = {name for name in dir(FakeLibrary) if name.startswith("ps2000_")}
    assert used == set(pico.PROTOTYPES)


# --- the instrument, on its thread -----------------------------------------------------------
def run_for(app, instrument, until, timeout_s=5.0):
    import time

    deadline = time.monotonic() + timeout_s
    while not until() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert until(), "timed out"


def test_the_instrument_streams_on_its_thread_and_closes_the_scope(app, monkeypatch):
    library = FakeLibrary()
    library.waiting += [([100] * 10, [200] * 10), ([300] * 5, [400] * 5)]
    monkeypatch.setattr(pico, "load_library", lambda: library)
    instrument = backends.create("picoscope2000", None, {"range_a": "1V"})
    assert [c.name for c in instrument.channels()] == ["A: ±1V", "B: ±5V"]
    blocks, states, notes = [], [], []
    instrument.block.connect(blocks.append)
    instrument.state_changed.connect(states.append)
    instrument.note.connect(notes.append)
    instrument.start()
    run_for(app, instrument, lambda: len(blocks) == 2)
    instrument.stop()
    run_for(app, instrument, lambda: states == [True, False])
    assert not instrument.running
    assert [b.first for b in blocks] == [0, 10]
    assert any("2204A" in note for note in notes)
    assert library.calls[-2:] == [("stop",), ("close",)]


def test_a_scope_that_is_not_there_is_an_error_and_not_running(app, monkeypatch):
    monkeypatch.setattr(pico, "load_library", lambda: FakeLibrary(handle=0))
    instrument = backends.create("picoscope2000")
    errors, states = [], []
    instrument.error.connect(errors.append)
    instrument.state_changed.connect(states.append)
    instrument.start()
    run_for(app, instrument, lambda: states == [False])
    assert len(errors) == 1 and "No PicoScope was found" in errors[0]
    assert not instrument.running
