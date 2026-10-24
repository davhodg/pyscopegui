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
        self.streaming = False
        #: Which channels are on, as the scope was last told: 0 is A, 1 is B.
        self.enabled = {0: True, 1: True}
        #: For blocks: whether one is in yet, and what each channel reads in
        #: one, in counts, given its length. A step up through nought at the
        #: middle, unless a test says otherwise.
        self.ready = 1
        self.takes_blocks = True
        self.slowest = 19
        self.block_wave = lambda n: np.where(np.arange(n) < n // 2, -16000, 16000)
        self.overrun = False
        #: Whether it is still plugged in, as asking it says.
        self.present = True

    def ps2000PingUnit(self, handle):
        self.calls.append(("ping",))
        return int(self.present)

    def ps2000_open_unit(self):
        self.calls.append(("open",))
        return self.handle

    def ps2000_get_unit_info(self, handle, text, length, line):
        value = self.info.get(line, b"")
        text.value = value[: length - 1]
        return len(value)

    def ps2000_set_channel(self, handle, channel, enabled, dc, code):
        self.calls.append(("channel", channel, bool(enabled), bool(dc), code))
        if code in self.refused_ranges:
            return 0
        self.enabled[channel] = bool(enabled)
        return 1

    def ps2000_set_trigger(self, handle, source, threshold, direction, delay, auto_ms):
        if source == pico.NO_TRIGGER:
            self.calls.append(("trigger", source))
        else:
            self.calls.append(("trigger", source, threshold, direction, delay, auto_ms))
        return 1

    # The advanced trigger, recorded as what each call was given.
    def ps2000SetAdvTriggerChannelConditions(self, handle, conditions, count):
        if not count:
            self.calls.append(("adv conditions", None))
        else:
            wanted = conditions._obj
            self.calls.append(("adv conditions", wanted.a, wanted.b, wanted.pulse_width))
        return 1

    def ps2000SetAdvTriggerChannelDirections(self, handle, *directions):
        self.calls.append(("adv directions", *directions))
        return 1

    def ps2000SetAdvTriggerChannelProperties(self, handle, properties, count, auto_ms):
        each = tuple((p.major, p.minor, p.channel, p.mode) for p in properties)
        self.calls.append(("adv properties", each, auto_ms))
        return 1

    def ps2000SetPulseWidthQualifier(self, handle, conditions, count, way, lower, upper, kind):
        if not count:
            self.calls.append(("pulse width", None))
        else:
            timed = conditions._obj
            self.calls.append(("pulse width", timed.a, timed.b, way, lower, upper, kind))
        return 1

    def ps2000SetAdvTriggerDelay(self, handle, delay, before):
        self.calls.append(("adv delay", delay, before))
        return 1

    def ps2000_get_timebase(self, handle, timebase, samples, interval, units, oversample, most):
        """As a 2204A: 10 ns at its fastest, doubling, with 8000 samples shared
        between the channels that are on, and no fastest timebase with both on."""
        on = sum(self.enabled.values()) or 1
        if timebase > self.slowest or (on == 2 and timebase == 0):
            return 0
        interval._obj.value = 10 * 2**timebase
        most._obj.value = 8000 // on
        return 1

    def ps2000_run_block(self, handle, samples, timebase, oversample, taken):
        self.calls.append(("block", samples, timebase))
        self.streaming = False
        return 1 if self.takes_blocks else 0

    def ps2000_ready(self, handle):
        return self.ready

    def ps2000_get_values(self, handle, a, b, c, d, overflow, samples):
        for buffer in (a, b):
            if buffer is not None:
                np.ctypeslib.as_array(buffer)[:] = self.block_wave(samples)
        return samples

    def ps2000_run_streaming_ns(self, handle, interval, units, most, auto_stop, per, overview):
        self.calls.append(("stream", interval, units, most, auto_stop, per, overview))
        self.streaming = bool(self.streams)
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
        # As a 2204A was seen to: it takes no new output while it is streaming.
        return 1 if self.generates and not self.streaming else 0

    def ps2000_stop(self, handle):
        self.calls.append(("stop",))
        self.streaming = False
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


def test_either_channel_can_be_switched_off():
    assert pico.Settings({"enabled_b": False}).keys() == ["A"]
    assert pico.Settings({"enabled_a": False}).keys() == ["B"]


def test_channel_b_alone_is_read_and_a_is_told_to_be_off():
    library = FakeLibrary()
    reading = stream(library, {"enabled_a": False, "range_b": "1V"})
    reading.open()
    reading.start()
    assert ("channel", pico.CHANNEL_A, False, True, 8) in library.calls
    library.waiting.append((None, [pico.MAX_VALUE, 0]))
    block = reading.poll()
    assert set(block.data) == {"B"}
    assert block.values("B").tolist() == pytest.approx([1.0, 0.0])


def test_both_channels_off_is_said_without_setting_anything_up():
    library = FakeLibrary()
    opened = stream(library, {"enabled_a": False, "enabled_b": False})
    opened.open()
    with pytest.raises(pico.ScopeError, match="Both channels are switched off"):
        opened.start()
    assert library.calls == [("open",)]
    assert not opened.streaming


# --- opening ---------------------------------------------------------------------------------
def test_opening_sets_both_channels_and_starts_fast_streaming():
    library = FakeLibrary()
    opened = stream(library, {"range_a": "1V", "coupling_b": "AC"})
    opened.open()
    opened.start()
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
    opened = stream(library, {"range_a": "20mV"})
    opened.open()
    with pytest.raises(pico.ScopeError, match="channel A to ±20mV"):
        opened.start()


def test_a_rate_the_scope_refuses_is_said():
    library = FakeLibrary()
    library.streams = False
    opened = stream(library)
    opened.open()
    with pytest.raises(pico.ScopeError, match="lower rate"):
        opened.start()
    assert not opened.streaming


def test_closing_stops_and_lets_go_and_does_nothing_if_it_never_opened():
    library = FakeLibrary()
    never = stream(library)
    never.close()
    assert library.calls == []
    opened = stream(library)
    opened.open()
    opened.start()
    opened.close()
    assert library.calls[-2:] == [("stop",), ("close",)]


# --- reading ---------------------------------------------------------------------------------
def test_counts_become_volts_at_the_range_each_channel_is_on():
    library = FakeLibrary()
    reading = stream(library, {"range_a": "5V", "range_b": "200mV"})
    reading.open()
    reading.start()
    library.waiting.append(([pico.MAX_VALUE, 0, -pico.MAX_VALUE], [pico.MAX_VALUE, 0, 0]))
    block = reading.poll()
    assert block.first == 0 and block.rate == pico.DEFAULT_RATE
    assert block.values("A").dtype == np.float32
    assert block.values("A").tolist() == pytest.approx([5.0, 0.0, -5.0])
    assert block.values("B").tolist() == pytest.approx([0.2, 0.0, 0.0])


def test_blocks_are_numbered_from_the_samples_before_them():
    library = FakeLibrary()
    reading = stream(library)
    reading.open()
    reading.start()
    library.waiting += [([1] * 700, [2] * 700), ([3] * 50, [4] * 50)]
    first, second = reading.poll(), reading.poll()
    assert (first.first, len(first)) == (0, 700)
    assert (second.first, len(second)) == (700, 50)


def test_nothing_waiting_is_no_block():
    reading = stream(FakeLibrary())
    reading.open()
    reading.start()
    assert reading.poll() is None


def test_a_sample_the_driver_lost_is_a_gap_and_not_minus_full_scale():
    library = FakeLibrary()
    reading = stream(library)
    reading.open()
    reading.start()
    library.waiting.append(([100, pico.LOST_DATA, 100], [0, 0, 0]))
    samples = reading.poll().values("A")
    assert np.isnan(samples[1]) and not np.isnan(samples[[0, 2]]).any()


def test_a_channel_that_is_off_sends_nothing():
    library = FakeLibrary()
    reading = stream(library, {"enabled_b": False})
    reading.open()
    reading.start()
    library.waiting.append(([1, 2, 3], None))
    assert set(reading.poll().data) == {"A"}


def test_the_samples_are_copied_out_of_the_drivers_buffer():
    """The driver reuses its buffers as soon as the callback returns."""
    library = FakeLibrary()
    reading = stream(library)
    reading.open()
    reading.start()
    theirs = np.array([1000, 2000], dtype=np.int16)
    library.waiting.append((theirs, theirs))
    block = reading.poll()
    theirs[:] = 0
    assert block.values("A")[0] != 0


def test_every_batch_the_driver_hands_over_in_one_poll_is_kept():
    """A batch replaced by the next was samples gone without a word, and the
    time of everything after them wrong by as many."""
    library = FakeLibrary()
    reading = stream(library)
    reading.open()
    reading.start()
    real = library.ps2000_get_streaming_last_values

    def twice(handle, callback):
        real(handle, callback)
        return real(handle, callback)

    library.ps2000_get_streaming_last_values = twice
    library.waiting += [([1] * 10, [2] * 10), ([3] * 5, [4] * 5)]
    block = reading.poll()
    assert len(block) == 15, "both batches, in order"
    assert block.values("A").tolist() == pytest.approx([1 * 5 / 32767] * 10 + [3 * 5 / 32767] * 5)
    library.waiting.append(([5] * 2, [6] * 2))
    assert reading.poll().first == 15, "and the next starts where they ended"


def test_samples_the_driver_lost_are_said_and_not_only_drawn_as_a_gap():
    library = FakeLibrary()
    clock = Clock()
    reading = stream(library, None, clock)
    reading.open()
    reading.start()
    library.waiting.append(([1, pico.LOST_DATA, pico.LOST_DATA, 1], [1, 1, pico.LOST_DATA, 1]))
    reading.poll()
    warnings = [text for text, warning in reading.notes if warning]
    assert warnings == [
        "The driver lost 2 samples, which are shown as a gap. The computer did not read them "
        "in time: a lower rate, or fewer programs running, may stop it."
    ]


def test_lost_samples_are_said_once_in_a_while_with_how_many_since():
    library = FakeLibrary()
    clock = Clock()
    reading = stream(library, None, clock)
    reading.open()
    reading.start()
    for _ in range(3):
        library.waiting.append(([pico.LOST_DATA, 1], [1, 1]))
        reading.poll()
        clock.now += 1.0

    def lost():
        return [text for text, _warning in reading.notes if text.startswith("The driver lost")]

    assert lost() == [lost()[0]] and lost()[0].startswith("The driver lost 1 sample, which is")
    clock.now += pico.LOST_SAID_S
    library.waiting.append(([pico.LOST_DATA, 1], [1, 1]))
    reading.poll()
    assert len(lost()) == 2 and lost()[1].startswith("The driver lost 3 samples"), "since the last"


def test_a_full_driver_buffer_is_a_warning():
    library = FakeLibrary()
    reading = stream(library)
    reading.open()
    reading.start()
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
    reading.start()
    reading.notes.clear()
    clock.now = pico.CHECK_AFTER_S + 1
    library.waiting += [([0] * 1_500_000, [0] * 1_500_000), ([0], [0])]
    reading.poll()
    reading.poll()
    warnings = [text for text, is_warning in reading.notes if is_warning]
    assert len(warnings) == 1
    assert "arriving at 250,000 a second where 500,000 were expected" in warnings[0]
    assert "computer" in warnings[0], "and says where to look"


def test_samples_arriving_at_the_rate_asked_for_say_nothing():
    library, clock = FakeLibrary(), Clock()
    reading = stream(library, clock=clock)
    reading.open()
    reading.start()
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
    opened.start()
    assert ("generator", 250_000, 1_500_000, pico.WAVES["square"], 250.0, 250.0) in library.calls
    assert ("Signal generator: square, 250 Hz, 1.5 V peak to peak, 0.25 V offset.", False) in (
        opened.notes
    )


STREAM = ("stream", 2000, pico.TIME_UNITS_NS, pico.DRIVER_SAMPLES, 0, 1, pico.OVERVIEW_SAMPLES)


def test_a_generator_change_while_running_stops_the_stream_for_it_and_starts_it_again():
    """The scope takes no new output while it is streaming -- found on a
    2204A, where the change was refused until the scope was stopped and run
    again -- so the stream is stopped for it, with the scope left open."""
    library = FakeLibrary()
    reading = stream(library)
    reading.open()
    reading.start()
    library.calls.clear()
    reading.notes.clear()
    reading.wanted = pico.Settings({"gen_wave": "sine"})
    reading.poll()
    reading.poll()
    assert library.calls == [
        ("stop",),
        ("generator", 0, 2_000_000, pico.WAVES["sine"], 1000.0, 1000.0),
        STREAM,
    ]
    assert reading.notes == [
        ("Signal generator: sine, 1000 Hz, 2 V peak to peak, 0 V offset.", False)
    ]
    reading.wanted = pico.Settings({"gen_wave": "off"})
    reading.poll()
    assert library.calls[-2] == ("generator", 0, 0, pico.WAVES["off"], 1000.0, 1000.0)
    assert [text for text, _ in reading.notes][-1] == "Signal generator: off."
    assert ("open",) not in library.calls and ("close",) not in library.calls


def test_the_time_a_generator_change_took_is_a_gap_and_not_lost_samples():
    library, clock = FakeLibrary(), Clock()
    reading = stream(library, clock=clock)
    reading.open()
    reading.start()
    library.waiting.append(([1] * 100, [1] * 100))
    assert reading.poll().after_pause is False

    def takes_a_while(handle):
        clock.now += 0.04  # the forty milliseconds the scope was not reading
        return 1

    library.ps2000_stop = takes_a_while
    reading.wanted = pico.Settings({"gen_wave": "sine"})
    library.waiting.append(([2] * 50, [2] * 50))
    after = reading.poll()
    assert after.after_pause is True
    assert after.first == 100 + round(0.04 * pico.DEFAULT_RATE)
    library.waiting.append(([3] * 10, [3] * 10))
    following = reading.poll()
    assert following.after_pause is False and following.first == after.first + 50


def test_a_stream_that_will_not_start_again_after_the_generator_is_said():
    library = FakeLibrary()
    reading = stream(library)
    reading.open()
    reading.start()
    library.streams = False
    reading.wanted = pico.Settings({"gen_wave": "sine"})
    with pytest.raises(pico.ScopeError, match="would not stream"):
        reading.poll()


# --- ranges and coupling, changed while it runs ------------------------------------------------
def test_a_range_change_while_running_stops_the_stream_sets_it_and_starts_again():
    library = FakeLibrary()
    reading = stream(library, {"range_a": "5V"})
    reading.open()
    reading.start()
    library.calls.clear()
    reading.wanted = pico.Settings({"range_a": "1V", "coupling_b": "AC"})
    library.waiting.append(([pico.MAX_VALUE], [0]))
    block = reading.poll()
    assert library.calls == [
        ("stop",),
        ("channel", pico.CHANNEL_A, True, True, 6),
        ("channel", pico.CHANNEL_B, True, False, 8),
        STREAM,
    ]
    assert ("open",) not in library.calls, "the scope is not opened again for it"
    assert block.after_pause and block.values("A").tolist() == pytest.approx([1.0])


def test_a_range_the_scope_refuses_while_running_leaves_it_as_it_was_and_says_so():
    library = FakeLibrary()
    reading = stream(library, {"range_a": "5V"})
    reading.open()
    reading.start()
    reading.notes.clear()
    library.refused_ranges = {1}
    reading.wanted = pico.Settings({"range_a": "20mV"})
    library.waiting.append(([pico.MAX_VALUE], [0]))
    block = reading.poll()
    assert reading.streaming
    assert reading.settings.ranges["A"] == "5V"
    assert block.values("A").tolist() == pytest.approx([5.0])
    warnings = [text for text, is_warning in reading.notes if is_warning]
    assert len(warnings) == 1 and "It is still set as it was." in warnings[0]


def test_a_second_run_does_not_open_the_scope_again():
    library = FakeLibrary()
    reading = stream(library)
    reading.open()
    reading.start()
    library.waiting.append(([1] * 10, [1] * 10))
    assert reading.poll().first == 0
    reading.stop()
    reading.start(pico.Settings({"rate": 100_000}))
    library.waiting.append(([1] * 10, [1] * 10))
    again = reading.poll()
    assert again.first == 0 and again.rate == 100_000, "counted from zero, at the new rate"
    assert library.calls.count(("open",)) == 1
    assert ("close",) not in library.calls


def test_what_was_asked_for_after_a_start_was_is_not_lost_when_the_start_happens(app, monkeypatch):
    """The start is done on the scope's thread, a moment after it was asked for."""
    library = FakeLibrary()
    monkeypatch.setattr(pico, "load_library", lambda: library)
    instrument = backends.create("picoscope2000", None, {"mode": "block"})
    instrument.set_trigger("A", 0.0, True, 0.5, auto=False)
    instrument.start()
    instrument.set_trigger("A", 0.0, True, 0.5, auto=True)  # before the thread has started
    waits = lambda: [c[-1] for c in library.calls if c[0] == "trigger" and len(c) > 2]  # noqa: E731
    run_for(app, instrument, lambda: pico.AUTO_TRIGGER_MS in waits())
    instrument.close()


def test_a_scope_with_no_generator_warns_only_when_one_is_asked_for():
    library = FakeLibrary()
    library.generates = False
    quiet = stream(library)
    quiet.open()
    quiet.start()
    assert not any(is_warning for _text, is_warning in quiet.notes)
    asked = stream(library, {"gen_wave": "sine"})
    asked.open()
    asked.start()
    assert any("would not set its signal generator" in text for text, _ in asked.notes)


def test_the_running_instrument_passes_a_setting_to_its_thread(app, monkeypatch):
    library = FakeLibrary()
    monkeypatch.setattr(pico, "load_library", lambda: library)
    instrument = backends.create("picoscope2000")
    states = []
    instrument.state_changed.connect(states.append)
    instrument.start()
    run_for(app, instrument, lambda: states == [True])
    instrument.set("gen_wave", "triangle")
    wanted = ("generator", 0, 2_000_000, pico.WAVES["triangle"], 1000.0, 1000.0)
    run_for(app, instrument, lambda: wanted in library.calls and library.streaming)
    instrument.set("range_b", "1V")
    assert instrument.channels()[1].full_scale == 1.0
    run_for(app, instrument, lambda: ("channel", pico.CHANNEL_B, True, True, 6) in library.calls)
    assert library.calls.count(("open",)) == 1, "the scope is not opened again for either"
    instrument.close()


# --- what can be set ---------------------------------------------------------------------------
def test_every_setting_offered_is_one_the_back_end_reads():
    """A control whose key nothing reads would look as if it worked."""
    defaults = {s.key: s.default for s in pico.SETTINGS}
    assert len(defaults) == len(pico.SETTINGS)
    by_default = pico.Settings(defaults)
    plain = pico.Settings()
    assert vars(by_default) == vars(plain)
    for setting in pico.SETTINGS:
        if isinstance(setting.default, bool):
            other = not setting.default
        else:
            other = next(
                (value for value, _label in setting.choices if value != setting.default),
                setting.maximum,
            )
        # With what it needs to have a say: a sensitivity, a current probe.
        needed = dict([setting.needs]) if setting.needs else {}
        changed = pico.Settings(defaults | needed | {setting.key: other})
        plain = pico.Settings(defaults | needed)
        # The generator's numbers only show once it is on.
        if setting.key.startswith("gen_") and setting.key != "gen_wave":
            assert changed.generator != plain.generator
        else:
            assert vars(changed) != vars(plain), setting.key


# --- blocks, around the scope's own trigger ----------------------------------------------------
def blocks(library, options=None, trigger=None, clock=None):
    """A stream set to read blocks, opened and started."""
    reading = stream(library, {"mode": "block"} | (options or {}), clock)
    reading.open()
    reading.start(trigger=trigger)
    return reading


def test_a_block_is_as_fast_as_the_scopes_memory_allows_for_its_length():
    """Two channels share 8000 samples, so 1 ms needs 320 ns a sample: timebase 5."""
    library = FakeLibrary()
    reading = blocks(library, {"block_ms": 1.0})
    assert (reading._timebase, reading._block_samples) == (5, 3125)
    assert reading._block_rate == pytest.approx(3_125_000)
    assert ("Blocks of 3125 samples at 3,125,000 a second: 1 ms each.", False) in reading.notes


def test_one_channel_has_all_the_memory_and_the_fastest_timebase():
    library = FakeLibrary()
    reading = blocks(library, {"block_ms": 0.05, "enabled_b": False})
    assert (reading._timebase, reading._block_samples) == (0, 5000)
    assert reading._block_rate == pytest.approx(100e6)


def test_a_block_longer_than_the_scope_can_take_is_its_longest_and_says_so():
    library = FakeLibrary()
    library.slowest = 10  # about 10 us a sample, so 82 ms of memory
    reading = blocks(library, {"block_ms": 1000.0, "enabled_b": False})
    assert reading._timebase == 10 and reading._block_samples == 8000
    warnings = [text for text, is_warning in reading.notes if is_warning]
    assert len(warnings) == 1 and "longest block the scope can take" in warnings[0]


def test_the_first_poll_asks_for_a_block_and_the_next_brings_it_in():
    library = FakeLibrary()
    reading = blocks(library, trigger=pico.Trigger("A", 0.0, True, 0.5, auto=False))
    library.calls.clear()
    assert reading.poll() is None
    assert library.calls == [
        ("trigger", pico.CHANNEL_A, 0, pico.RISING, -50, 0),
        ("block", 3125, 5),
    ]
    block = reading.poll()
    assert block.sweep and block.first == 0 and len(block) == 3125
    assert block.rate == pytest.approx(3_125_000)
    assert block.trigger == 1562 and block.triggered
    assert block.values("A")[0] == pytest.approx(-16000 * 5 / pico.MAX_VALUE)
    assert block.values("A").dtype == np.float32
    # ...and the poll after that asks for the next one.
    assert reading.poll() is None
    assert library.calls[-1] == ("block", 3125, 5)


def test_a_block_that_is_not_in_yet_is_waited_for():
    library = FakeLibrary()
    reading = blocks(library)
    library.ready = 0
    assert reading.poll() is None and reading.poll() is None and reading.poll() is None
    assert library.calls.count(("block", 3125, 5)) == 1, "asked for once, not at every poll"
    library.ready = 1
    assert reading.poll().sweep


def test_the_trigger_is_given_in_counts_of_the_range_the_channel_is_on():
    library = FakeLibrary()
    reading = blocks(
        library,
        {"range_b": "2V"},
        pico.Trigger("B", level=1.0, rising=False, position=0.2, auto=True),
    )
    reading.poll()
    half_scale = round(pico.MAX_VALUE / 2)
    assert ("trigger", pico.CHANNEL_B, half_scale, pico.FALLING, -20, pico.AUTO_TRIGGER_MS) in (
        library.calls
    )


def test_normal_waits_for_ever_and_auto_gives_up_after_a_while():
    library = FakeLibrary()
    waiting = blocks(library, trigger=pico.Trigger("A", auto=False))
    waiting.poll()
    assert library.calls[-2][-1] == 0, "nought is for ever"
    library = FakeLibrary()
    giving_up = blocks(library, {"block_ms": 200.0}, pico.Trigger("A", auto=True))
    giving_up.poll()
    assert library.calls[-2][-1] == 400, "twice the block's length, when that is longer"


def test_with_no_trigger_blocks_are_taken_one_after_another():
    library = FakeLibrary()
    reading = blocks(library, trigger=pico.Trigger(None))
    reading.poll()
    assert ("trigger", pico.NO_TRIGGER) in library.calls
    block = reading.poll()
    assert block.sweep and block.trigger is None and not block.triggered


def test_a_trigger_on_a_channel_that_is_off_is_no_trigger():
    library = FakeLibrary()
    reading = blocks(library, {"enabled_b": False}, pico.Trigger("B"))
    reading.poll()
    assert library.calls[-2] == ("trigger", pico.NO_TRIGGER)
    assert reading.poll().trigger is None


def test_a_block_taken_because_nothing_came_is_not_called_triggered():
    library = FakeLibrary()
    library.block_wave = lambda n: np.full(n, -16000)  # never near the level
    reading = blocks(library, trigger=pico.Trigger("A", level=0.0, auto=True))
    reading.poll()
    block = reading.poll()
    assert block.trigger == 1562 and not block.triggered


def test_a_new_trigger_gives_up_the_block_being_waited_for():
    """In Normal it would otherwise be waited for for ever, with the old level."""
    library = FakeLibrary()
    reading = blocks(library, trigger=pico.Trigger("A", level=4.0, auto=False))
    library.ready = 0
    reading.poll()
    library.calls.clear()
    reading.wanted_trigger = pico.Trigger("A", level=0.0, auto=False)
    reading.poll()
    assert library.calls == [
        ("stop",),
        ("trigger", pico.CHANNEL_A, 0, pico.RISING, -50, 0),
        ("block", 3125, 5),
    ]


def test_a_range_change_between_blocks_is_taken_up_without_opening_again():
    library = FakeLibrary()
    reading = blocks(library, {"range_a": "5V"}, pico.Trigger("A", level=1.0))
    reading.poll()
    library.calls.clear()
    reading.wanted = pico.Settings({"mode": "block", "range_a": "2V"})
    reading.poll()
    assert ("channel", pico.CHANNEL_A, True, True, 7) in library.calls
    assert ("open",) not in library.calls
    # The level is now half of the new range, not a fifth.
    assert ("trigger", pico.CHANNEL_A, round(pico.MAX_VALUE / 2), pico.RISING, -50, 100) in (
        library.calls
    )
    assert reading.poll().values("A")[-1] == pytest.approx(16000 * 2 / pico.MAX_VALUE)


def test_a_scope_that_was_unplugged_while_a_block_was_waited_for_is_said():
    library = FakeLibrary()
    reading = blocks(library)
    reading.poll()
    library.ready = -1
    with pytest.raises(pico.ScopeError, match="unplugged"):
        reading.poll()


def test_a_block_the_scope_will_not_take_is_said():
    library = FakeLibrary()
    library.takes_blocks = False
    reading = blocks(library)
    with pytest.raises(pico.ScopeError, match="would not take a block"):
        reading.poll()


def test_stopping_gives_up_the_block_and_leaves_the_scope_open():
    library = FakeLibrary()
    reading = blocks(library)
    reading.poll()
    reading.stop()
    assert library.calls[-1] == ("stop",) and not reading.streaming
    reading.start()
    reading.poll()
    assert library.calls.count(("open",)) == 1


@pytest.mark.parametrize(
    ("samples", "rising", "found"),
    [
        ([-1, -1, -1, 1, 1, 1, 1], True, True),
        ([1, 1, 1, -1, -1, -1, -1], False, True),
        ([-1, -1, -1, 1, 1, 1, 1], False, False),
        ([-1, -1, -1, -1, -1, -1, -1], True, False),
        ([2, 2, 2, 2, 2, 2, 2], True, False),
    ],
)
def test_whether_the_signal_crossed_the_level_where_the_trigger_should_be(samples, rising, found):
    assert pico.crossed(np.array(samples, dtype=np.float32), 3, 0.0, rising) is found


def test_the_instrument_sends_sweeps_and_is_told_its_trigger(app, monkeypatch):
    library = FakeLibrary()
    monkeypatch.setattr(pico, "load_library", lambda: library)
    instrument = backends.create("picoscope2000", None, {"mode": "block"})
    assert instrument.sweeps
    blocks_in = []
    instrument.block.connect(blocks_in.append)
    instrument.set_trigger("A", 0.0, True, 0.25, auto=False)
    instrument.start()
    run_for(app, instrument, lambda: len(blocks_in) >= 2)
    assert all(block.sweep and block.trigger == 781 for block in blocks_in)
    assert instrument.rate == pytest.approx(3_125_000), "the rate the scope chose"
    instrument.set_trigger("A", 0.0, True, 0.75, auto=False)
    run_for(app, instrument, lambda: blocks_in[-1].trigger == 2344)
    instrument.close()


# --- a scale and a probe, for a scope that has ranges ----------------------------------------
def test_a_scale_is_the_range_that_holds_eight_divisions_of_it():
    for name, scale in pico.SCALES.items():
        assert pico.RANGES[name][1] >= 4 * scale, name
        assert pico.range_for(scale, 1) == name
        assert pico.range_for(scale * 10, 10) == name


def test_a_scale_out_of_reach_through_a_probe_is_the_nearest_there_is():
    assert pico.range_for(100.0, 1) == "20V"
    assert pico.range_for(0.01, 100) == "20mV"
    assert pico.Settings({"scale_a": "x", "probe_a": 7}).ranges["A"] == pico.DEFAULT_RANGE


def test_a_range_saved_by_name_is_used_until_a_scale_is_chosen():
    assert pico.Settings({"range_a": "1V"}).ranges["A"] == "1V"
    assert pico.Settings({"range_a": "1V", "scale_a": 2.0}).ranges["A"] == "10V"


def test_a_probe_multiplies_what_is_read_and_divides_the_trigger_level():
    library = FakeLibrary()
    library.waiting += [([16384], [16384])]
    reading = stream(library, {"scale_a": 10.0, "probe_a": 10, "scale_b": 1.0})
    assert reading.settings.ranges == {"A": "5V", "B": "5V"}
    block = reading.poll()
    assert block.values("A")[0] == pytest.approx(25.0, rel=1e-3)
    assert block.values("B")[0] == pytest.approx(2.5, rel=1e-3)
    assert reading.settings.volts("A") == 50.0 and reading.settings.scale("A") == 10.0
    reading.close()
    library = FakeLibrary()
    reading = blocks(
        library, {"scale_a": 10.0, "probe_a": 10}, pico.Trigger("A", level=25.0, auto=False)
    )
    reading.poll()
    half_scale = round(pico.MAX_VALUE / 2)
    assert ("trigger", pico.CHANNEL_A, half_scale, pico.RISING, -50, 0) in library.calls
    reading.close()


# --- which model it is -------------------------------------------------------------------------
def test_before_a_scope_is_open_the_ranges_offered_are_a_2204as():
    scales = [value for value, _label in setting("scale_a", pico.settings_for(None)).choices]
    # From its ±50 mV range to its ±20 V range, at its input.
    assert scales[0] == 0.01 and scales[-1] == 5 and 0.005 not in scales
    # Offered through whichever probe is on the channel.
    through = pico.PicoScope2000.fitted(pico.settings_for(None), {"probe_a": 100})
    scales = [value for value, _label in setting("scale_a", through).choices]
    assert scales[0] == 1 and scales[-1] == 500


def setting(key, settings):
    return next(s for s in settings if s.key == key)


def test_a_model_that_is_known_is_offered_what_it_has():
    for model in ("2204A", "2205A"):
        offered = pico.settings_for(model)
        assert 0.005 not in [v for v, _ in setting("scale_b", offered).choices]
        assert any(s.key == "gen_wave" for s in offered)


def test_a_scope_with_no_generator_is_not_offered_one():
    offered = pico.settings_for("2202")
    assert not any(s.key.startswith("gen_") for s in offered)
    assert any(s.key == "scale_a" for s in offered)


def test_a_model_nobody_has_checked_is_offered_every_range():
    """And refuses the ones it lacks, which is said when it does."""
    offered = pico.settings_for("2203")
    assert setting("scale_a", offered).choices[0][0] == pico.SCALES["20mV"]
    assert any(s.key == "gen_wave" for s in offered)


def test_every_model_named_has_ranges_the_driver_knows():
    for model in pico.MODELS.values():
        assert set(model.ranges) <= set(pico.RANGES)


def test_the_instrument_offers_what_its_model_has_once_it_is_open(app, monkeypatch):
    library = FakeLibrary(info={pico.INFO_VARIANT: b"2202"})
    monkeypatch.setattr(pico, "load_library", lambda: library)
    instrument = backends.create("picoscope2000")
    assert any(s.key == "gen_wave" for s in instrument.settings_offered())
    opened = []
    instrument.opened_changed.connect(opened.append)
    instrument.open()
    run_for(app, instrument, lambda: opened == [True])
    assert not any(s.key == "gen_wave" for s in instrument.settings_offered())
    instrument.close()


def test_what_is_taken_up_as_it_runs_and_what_starts_the_run_again():
    """A range, the coupling and the generator leave the samples what they
    were; the rate and which channels are read do not."""
    live = {s.key for s in pico.SETTINGS if s.live}
    assert live == {
        "scale_a",
        "coupling_a",
        "probe_a",
        "sensitivity_a",
        "scale_b",
        "coupling_b",
        "probe_b",
        "sensitivity_b",
        "gen_wave",
        "gen_frequency",
        "gen_amplitude",
        "gen_offset",
    }
    assert {s.key for s in pico.SETTINGS} - live == {
        "mode",
        "rate",
        "block_ms",
        "enabled_a",
        "enabled_b",
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
    used = {name for name in dir(FakeLibrary) if name.startswith("ps2000")}
    assert used == set(pico.PROTOTYPES)


# --- the instrument, on its thread -----------------------------------------------------------
@pytest.fixture(autouse=True)
def closed_afterwards(monkeypatch):
    """Every instrument a test makes is closed when the test ends, passed or
    failed. One whose thread is still running when it is collected brings the
    whole worker down, and the test that happens to run next fails with it."""
    made = []
    create = backends.create

    def creating(*args, **kwargs):
        instrument = create(*args, **kwargs)
        made.append(instrument)
        return instrument

    monkeypatch.setattr(backends, "create", creating)
    yield
    for instrument in made:
        instrument.close()


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
    assert [(c.name, c.detail) for c in instrument.channels()] == [
        ("A", "200 mV/div, 1x, DC"),
        ("B", "1 V/div, 1x, DC"),
    ]
    blocks, states, opened, notes = [], [], [], []
    instrument.block.connect(blocks.append)
    instrument.state_changed.connect(states.append)
    instrument.opened_changed.connect(opened.append)
    instrument.note.connect(notes.append)
    instrument.start()  # which opens it first
    run_for(app, instrument, lambda: len(blocks) == 2)
    assert opened == [True] and instrument.is_open
    instrument.stop()
    assert states == [True, False] and not instrument.running
    assert instrument.is_open, "stopped, and still open"
    assert [b.first for b in blocks] == [0, 10]
    assert any("2204A" in note for note in notes)
    instrument.close()
    run_for(app, instrument, lambda: opened == [True, False])
    assert not instrument.is_open
    assert library.calls[-2:] == [("stop",), ("close",)]


def test_open_alone_connects_and_reads_nothing(app, monkeypatch):
    library = FakeLibrary()
    monkeypatch.setattr(pico, "load_library", lambda: library)
    instrument = backends.create("picoscope2000")
    opened, states = [], []
    instrument.opened_changed.connect(opened.append)
    instrument.state_changed.connect(states.append)
    instrument.open()
    run_for(app, instrument, lambda: opened == [True])
    assert library.calls == [("open",)] and states == []
    assert not instrument.running
    instrument.close()
    run_for(app, instrument, lambda: opened == [True, False])


def test_running_again_after_a_stop_is_quick_and_counts_from_zero(app, monkeypatch):
    library = FakeLibrary()
    monkeypatch.setattr(pico, "load_library", lambda: library)
    instrument = backends.create("picoscope2000")
    blocks, states = [], []
    instrument.block.connect(blocks.append)
    instrument.state_changed.connect(states.append)
    library.waiting.append(([1] * 10, [1] * 10))
    instrument.start()
    run_for(app, instrument, lambda: len(blocks) == 1)
    instrument.stop()
    instrument.set("rate", 100_000)
    instrument.start()
    # What the second run reads, once it is running: handed over sooner, the
    # first run's last poll can take it, and what it takes is rightly dropped.
    run_for(app, instrument, lambda: states == [True, False, True])
    library.waiting.append(([2] * 4, [2] * 4))
    run_for(app, instrument, lambda: len(blocks) == 2)
    assert (blocks[1].first, blocks[1].rate) == (0, 100_000)
    assert library.calls.count(("open",)) == 1
    instrument.close()


def test_what_a_run_sends_after_it_was_stopped_is_dropped(app, monkeypatch):
    """A block already on its way when Stop was pressed belongs to a run that is over."""
    library = FakeLibrary()
    monkeypatch.setattr(pico, "load_library", lambda: library)
    instrument = backends.create("picoscope2000")
    blocks, states = [], []
    instrument.block.connect(blocks.append)
    instrument.state_changed.connect(states.append)
    instrument.start()
    run_for(app, instrument, lambda: states == [True])
    instrument.stop()
    instrument._on_block(instrument._run, "late")
    assert blocks == []
    instrument.close()


def test_a_scope_that_is_not_there_is_an_error_and_not_running(app, monkeypatch):
    monkeypatch.setattr(pico, "load_library", lambda: FakeLibrary(handle=0))
    instrument = backends.create("picoscope2000")
    errors, states = [], []
    instrument.error.connect(errors.append)
    instrument.state_changed.connect(states.append)
    instrument.start()
    run_for(app, instrument, lambda: states == [False])
    assert len(errors) == 1 and "No PicoScope was found" in errors[0]
    assert not instrument.running and not instrument.is_open


# --- a scope that is unplugged ----------------------------------------------------------------
def test_a_quiet_scope_is_asked_whether_it_is_there_and_one_that_is_not_is_an_error():
    library, clock = FakeLibrary(), Clock()
    reading = stream(library, clock=clock)
    reading.open()
    clock.now = pico.QUIET_S - 0.1
    reading.check_there()
    assert ("ping",) not in library.calls, "not before it has been quiet a while"
    clock.now = pico.QUIET_S
    reading.check_there()
    reading.check_there()
    assert library.calls.count(("ping",)) == 1, "once a quiet spell, not every look"
    library.present = False
    clock.now = 2 * pico.QUIET_S
    with pytest.raises(pico.ScopeError, match="stopped answering"):
        reading.check_there()


def test_a_scope_that_is_streaming_samples_is_never_asked():
    library, clock = FakeLibrary(), Clock()
    reading = stream(library, clock=clock)
    reading.open()
    reading.start()
    for step in range(1, 20):
        clock.now = step * pico.STALLED_S / 2
        library.waiting.append(([1] * 10, [1] * 10))
        assert reading.poll() is not None
        reading.heard_from()
        reading.check_there()
    assert ("ping",) not in library.calls
    # Nothing arriving for a moment, though, is asked about at once.
    clock.now += pico.STALLED_S
    library.present = False
    with pytest.raises(pico.ScopeError, match="stopped answering"):
        reading.check_there()


def test_a_scope_unplugged_while_stopped_is_closed_and_said(app, monkeypatch):
    library = FakeLibrary()
    monkeypatch.setattr(pico, "load_library", lambda: library)
    monkeypatch.setattr(pico, "QUIET_S", 0.05)
    instrument = backends.create("picoscope2000")
    errors = []
    instrument.error.connect(errors.append)
    instrument.open()
    run_for(app, instrument, lambda: instrument.is_open)
    run_for(app, instrument, lambda: ("ping",) in library.calls)
    library.present = False
    run_for(app, instrument, lambda: not instrument.is_open)
    assert len(errors) == 1 and "unplugged" in errors[0]
    assert ("close",) in library.calls


# --- what an older scope waits for itself, beyond an edge --------------------------------------
from pyscopegui.core.triggers import (  # noqa: E402
    BETWEEN,
    EDGE,
    EITHER,
    LEAVE,
    LOW,
    PATTERN,
    PULSE,
    RUNT,
    TIMEOUT,
    WINDOW,
    Condition,
)

NONE5 = [pico.ADV_NONE] * 5


def counts(volts, full=5.0):
    return round(volts / full * pico.MAX_VALUE)


def armed_with(condition, source="A", level=1.0, position=0.5, auto=False, library=None):
    library = library or FakeLibrary()
    trigger = pico.Trigger(source, level, True, position, auto, condition)
    reading = blocks(library, None, trigger)
    reading.poll()
    return reading, library


def test_an_edge_either_way_is_the_advanced_trigger_with_its_place_in_the_block():
    _reading, library = armed_with(Condition(EDGE, edge=EITHER), position=0.25)
    level = counts(1.0)
    kinds = [call[0] for call in library.calls]
    assert (
        kinds.index("adv conditions")
        < kinds.index("adv directions")
        < kinds.index("adv properties")
        < kinds.index("adv delay")
        < kinds.index("block")
    ), "in the order Pico's example sets them"
    assert ("adv conditions", pico.CONDITION_TRUE, 0, 0) in library.calls
    assert ("adv directions", pico.ADV_EITHER, *NONE5[1:]) in library.calls
    assert ("adv properties", ((level, level, 0, pico.LEVEL_MODE),), 0) in library.calls
    assert ("adv delay", 0, -25.0) in library.calls
    assert not any(call[0] == "trigger" for call in library.calls), "not the simple trigger"


def test_a_window_has_its_higher_level_as_the_major_threshold():
    _reading, library = armed_with(Condition(WINDOW, upper=-1.0, direction=LEAVE), "B", 2.0)
    assert ("adv properties", ((counts(2.0), counts(-1.0), 1, pico.WINDOW_MODE),), 0) in (
        library.calls
    )
    assert ("adv directions", pico.ADV_NONE, pico.ADV_EXIT, *NONE5[2:]) in library.calls


def test_a_pulse_is_timed_from_one_edge_and_triggered_at_the_other():
    pulse = Condition(PULSE, compare=BETWEEN, shortest=1e-6, longest=2e-6)
    reading, library = armed_with(pulse, level=0.5)
    rate = reading._block_rate
    assert ("adv conditions", pico.CONDITION_TRUE, 0, pico.CONDITION_TRUE) in library.calls
    assert ("adv directions", pico.ADV_FALLING, *NONE5[1:]) in library.calls, "at its end"
    timed = next(call for call in library.calls if call[0] == "pulse width")
    assert timed == (
        "pulse width",
        pico.CONDITION_TRUE,
        0,
        pico.ADV_RISING,
        round(1e-6 * rate),
        round(2e-6 * rate),
        pico.PW_IN_RANGE,
    ), "from its start"
    del library.calls[:]
    low = Condition(PULSE, polarity=LOW)
    reading.wanted_trigger = pico.Trigger("A", 0.5, True, 0.5, False, low)
    reading.poll()
    timed = next(call for call in library.calls if call[0] == "pulse width")
    assert timed[3] == pico.ADV_FALLING and timed[6] == pico.PW_GREATER_THAN
    del library.calls[:]
    reading.wanted_trigger = pico.Trigger("A", 0.5, True, 0.5, False)
    reading.poll()
    kinds = [call[0] for call in library.calls]
    assert kinds == ["stop", "adv conditions", "pulse width", "trigger", "block"], (
        "the advanced trigger cleared for the simple one"
    )


def test_a_pattern_of_both_channels():
    pattern = Condition(PATTERN, pattern=(("A", 1), ("B", 0)))
    _reading, library = armed_with(pattern, source=None, level=1.0)
    level = counts(1.0)
    assert ("adv conditions", pico.CONDITION_TRUE, pico.CONDITION_TRUE, 0) in library.calls
    assert ("adv directions", pico.ADV_ABOVE, pico.ADV_BELOW, *NONE5[2:]) in library.calls
    assert (
        "adv properties",
        ((level, level, 0, pico.LEVEL_MODE), (level, level, 1, pico.LEVEL_MODE)),
        0,
    ) in library.calls


def test_a_block_in_auto_is_triggered_if_what_was_waited_for_is_where_the_trigger_is():
    library = FakeLibrary()
    either = Condition(EDGE, edge=EITHER)
    reading, _library = armed_with(either, level=0.0, auto=True, library=library)
    assert reading.poll().triggered, "the wave steps through nought at the trigger"
    reading.wanted_trigger = pico.Trigger("A", 4.0, True, 0.5, True, either)
    reading.poll()
    assert not reading.poll().triggered


def test_only_the_models_with_the_advanced_trigger_do_more_than_an_edge():
    on = ["A", "B"]
    can = pico.triggers_itself
    for model in pico.ADVANCED_MODELS:
        assert can(Condition(EDGE, edge=EITHER), "A", on, model)
        assert can(Condition(WINDOW), "B", on, model) and can(Condition(PULSE), "A", on, model)
        assert can(Condition(PATTERN, pattern=(("A", 1), ("B", 0))), None, on, model)
        assert not can(Condition(RUNT), "A", on, model), "the driver has no runt"
        assert not can(Condition(TIMEOUT), "A", on, model)
        assert not can(Condition(EDGE, edge=EITHER, holdoff=1e-3), "A", on, model)
    for model in ("2203", "2104", "2105", None):
        assert can(Condition(EDGE), "A", on, model), "a plain edge, on any"
        assert not can(Condition(EDGE, edge=EITHER), "A", on, model), model


def test_the_instrument_says_what_it_can_wait_for_once_it_knows_the_model(app, monkeypatch):
    library = FakeLibrary()
    monkeypatch.setattr(pico, "load_library", lambda: library)
    instrument = backends.create("picoscope2000", None, {"mode": "block"})
    assert not instrument.triggers_itself(Condition(WINDOW), "A"), "not before it is open"
    instrument._model = "2204A"
    assert instrument.triggers_itself(Condition(WINDOW), "A")
    assert instrument.triggers_itself(Condition(PATTERN), None), "its channels still to be chosen"
    instrument.set_trigger("A", 0.0, True, 0.5, False, Condition(WINDOW))
    assert instrument._trigger.condition == Condition(WINDOW)
