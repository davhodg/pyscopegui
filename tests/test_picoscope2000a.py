# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The ps2000a back end, against a stand-in for Pico's library.

As for the older driver: the stand-in answers the way Pico's programmer's
guide says the driver does -- a status from every call, buffers it was handed
filled, samples announced through the same C callback -- so what is checked
is everything on pyscopegui's side of that boundary.
"""

import ctypes
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from pyscopegui import backends
from pyscopegui.backends import picoscope2000a as pico
from pyscopegui.backends.base import DIGITAL, unpacked
from pyscopegui.backends.picoscope2000 import CHECK_AFTER_S
from pyscopegui.core.triggers import (
    BETWEEN,
    EDGE,
    EITHER,
    LEAVE,
    LOW,
    PATTERN,
    PULSE,
    RUNT,
    SHORTER,
    TIMEOUT,
    WINDOW,
    Condition,
)
from tests.test_picoscope2000 import (  # noqa: F401  closed_afterwards, used as a fixture
    Clock,
    closed_afterwards,
    run_for,
)

ALL_RANGES = tuple(code for code, _volts in pico.RANGES.values())


class FakeLibrary:
    """Pico's ps2000a library, as far as the back end uses it."""

    def __init__(self, model=b"2206B", found=True):
        self.info = {pico.INFO_VARIANT: model, pico.INFO_SERIAL: b"GQ123/0456"}
        self.found = found
        self.calls = []
        self.ranges = ALL_RANGES
        self.refused_ranges = set()
        #: What each poll hands over next: what the driver calls a channel
        #: or port -> its samples, in counts.
        self.waiting = []
        self.buffers = {}
        self.streams = True
        #: The interval streaming is really given, if not the one asked for.
        self.interval = None
        self.generates = True
        self.latest = pico.OK
        #: For blocks: whether one is in yet, what a channel reads in one
        #: given its length, and how much memory there is to share.
        self.ready = 1
        self.answers = True
        self.takes_blocks = True
        self.memory = 32_000_000
        self.slowest = 2**32 - 1
        self.block_wave = lambda n: np.where(np.arange(n) < n // 2, -16000, 16000)
        self.port_wave = lambda n: np.where(np.arange(n) < n // 2, 0b0000_0000, 0b0000_0101)
        self.on = {0: True, 1: True}
        self.asked = []
        #: Whether it can add an offset, and what each channel was last given.
        self.has_offset = True
        self.offsets: dict[int, float] = {}

    def ps2000aOpenUnit(self, handle, serial):
        self.calls.append(("open",))
        if not self.found:
            return pico.NOT_FOUND
        handle._obj.value = 1
        return pico.OK

    def ps2000aGetUnitInfo(self, handle, text, length, needed, line):
        text.value = self.info.get(line, b"")[: length - 1]
        return pico.OK

    def ps2000aMaximumValue(self, handle, value):
        value._obj.value = 32512
        return pico.OK

    def ps2000aGetChannelInformation(self, handle, info, probe, ranges, length, channels):
        for index, code in enumerate(self.ranges):
            ranges[index] = code
        length._obj.value = len(self.ranges)
        return pico.OK

    def ps2000aGetAnalogueOffset(self, handle, code, coupling, most, least):
        """Limits of the kind Pico gives: 0.25 V to ±200 mV, 2.5 V to ±2 V, 20 V above."""
        reach = 0.0 if not self.has_offset else 0.25 if code <= 4 else 2.5 if code <= 7 else 20.0
        most._obj.value, least._obj.value = reach, -reach
        return pico.OK

    def ps2000aSetChannel(self, handle, channel, enabled, coupling, code, offset):
        self.calls.append(("channel", channel, bool(enabled), coupling, code))
        self.offsets[channel] = offset
        if code in self.refused_ranges:
            return 0x0F
        self.on[channel] = bool(enabled)
        return pico.OK

    def ps2000aSetDigitalPort(self, handle, port, enabled, level):
        self.calls.append(("port", port, bool(enabled), level))
        self.on[port] = bool(enabled)
        return pico.OK

    def ps2000aSetSimpleTrigger(self, handle, enable, source, threshold, direction, delay, auto):
        if enable:
            self.calls.append(("trigger", source, threshold, direction, auto))
        else:
            self.calls.append(("trigger", None))
        return pico.OK

    def ps2000aSetTriggerChannelConditions(self, handle, conditions, count):
        wanted = conditions._obj
        self.conditions = wanted
        self.calls.append(("conditions", wanted.a, wanted.b, wanted.digital))
        return pico.OK

    def ps2000aSetTriggerChannelDirections(self, handle, *directions):
        self.calls.append(("directions", *directions))
        return pico.OK

    def ps2000aSetPulseWidthQualifier(self, handle, conditions, count, way, lower, upper, kind):
        if not count:
            self.calls.append(("pulse width", None))
        else:
            timed = conditions._obj
            self.calls.append(("pulse width", timed.a, timed.b, way, lower, upper, kind))
        return pico.OK

    def ps2000aSetTriggerDigitalPortProperties(self, handle, directions, count):
        if directions is None:
            self.calls.append(("digital trigger", None))
        else:
            # One handed over by reference, or several in an array.
            edges = directions if isinstance(directions, ctypes.Array) else [directions._obj]
            said = [n for edge in edges for n in (edge.channel, edge.direction)]
            self.calls.append(("digital trigger", *said))
        return pico.OK

    def ps2000aSetTriggerChannelProperties(self, handle, properties, count, aux, auto):
        if properties is None:
            self.calls.append(("auto", auto))
        else:
            each = tuple((p.upper, p.lower, p.channel, p.mode) for p in properties)
            self.calls.append(("properties", each, auto))
        return pico.OK

    def ps2000aGetTimebase2(self, handle, timebase, samples, interval, oversample, most, segment):
        """As a 2206B: 2, 4 and 8 ns, then steps of 16 ns, its memory shared
        between what is on, and no fastest timebase with two channels on."""
        self.asked.append(timebase)
        on = sum(self.on.values()) or 1
        if timebase > self.slowest or (on >= 2 and timebase == 0):
            return 0x0E
        interval._obj.value = 2.0 * 2**timebase if timebase < 3 else (timebase - 2) * 16.0
        most._obj.value = self.memory // on
        return pico.OK

    def ps2000aRunBlock(self, handle, before, after, timebase, oversample, busy, segment, a, b):
        self.calls.append(("block", before, after, timebase))
        return pico.OK if self.takes_blocks else 0x15

    def ps2000aIsReady(self, handle, ready):
        ready._obj.value = self.ready
        return pico.OK if self.answers else 0x07

    def ps2000aSetDataBuffer(self, handle, source, buffer, length, segment, mode):
        self.buffers[source] = (buffer, length)
        return pico.OK

    def ps2000aGetValues(self, handle, start, count, ratio, mode, segment, overflow):
        for source, (buffer, length) in self.buffers.items():
            wave = self.port_wave if source >= pico.DIGITAL_PORT0 else self.block_wave
            np.ctypeslib.as_array(buffer)[:] = wave(length)
        return pico.OK

    def ps2000aRunStreaming(
        self, handle, interval, units, before, after, auto_stop, ratio, mode, overview
    ):
        self.calls.append(("stream", interval._obj.value, units, auto_stop, ratio, overview))
        if self.interval is not None:
            interval._obj.value = self.interval
        self.at = 0
        return pico.OK if self.streams else 0x2B

    def ps2000aGetStreamingLatestValues(self, handle, callback, parameter):
        if self.latest != pico.OK:
            return self.latest
        if not self.waiting:
            return pico.OK
        arrived = self.waiting.pop(0)
        count = len(next(iter(arrived.values())))
        for source, samples in arrived.items():
            buffer, _length = self.buffers[source]
            np.ctypeslib.as_array(buffer)[self.at : self.at + count] = samples
        callback(1, count, self.at, 0, 0, 0, 0, None)
        self.at += count
        return pico.OK

    def ps2000aSetSigGenBuiltIn(self, handle, offset, pk_to_pk, wave, start, stop, *rest):
        self.calls.append(("generator", offset, pk_to_pk, wave, start, stop))
        assert len(rest) == 9
        #: shots, sweeps, trigger type and source, as last set.
        self.generator_trigger = rest[4:8]
        return pico.OK if self.generates else 0x13

    def ps2000aStop(self, handle):
        self.calls.append(("stop",))
        return pico.OK

    def ps2000aPingUnit(self, handle):
        self.calls.append(("ping",))
        return pico.OK if getattr(self, "present", True) else 0x07

    def ps2000aCloseUnit(self, handle):
        self.calls.append(("close",))
        return pico.OK


MSO = b"2206BMSO"
PORT0, PORT1 = pico.DIGITAL_PORT0, pico.DIGITAL_PORT0 + 1


def stream(library, options=None, clock=None):
    return pico.Stream(library, pico.Settings(options), clock or Clock())


def test_a_newer_scope_that_does_not_answer_is_an_error():
    library, clock = FakeLibrary(), Clock()
    reading = stream(library, clock=clock)
    reading.open()
    clock.now = pico.pico.QUIET_S
    reading.check_there()
    library.present = False
    clock.now = 2 * pico.pico.QUIET_S
    with pytest.raises(pico.ScopeError, match="stopped answering"):
        reading.check_there()


def started(library, options=None, trigger=None):
    reading = stream(library, options)
    reading.open()
    reading.start(None, trigger)
    return reading


# --- what a scope has ------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("model", "channels", "digital"),
    [
        ("2206B", 2, False),
        ("2208A", 2, False),
        ("2205MSO", 2, True),
        ("2206BMSO", 2, True),
        ("2405A", 4, False),
        ("2408B", 4, False),
        (None, 2, False),
    ],
)
def test_the_model_says_how_many_channels_and_whether_there_are_logic_inputs(
    model, channels, digital
):
    assert (pico.channels_of(model), pico.has_digital(model)) == (channels, digital)


def test_before_a_scope_is_open_two_channels_and_a_generator_are_offered():
    keys = [setting.key for setting in pico.SETTINGS]
    assert "enabled_b" in keys and "gen_wave" in keys
    assert "enabled_c" not in keys and "digital_0" not in keys


def test_a_four_channel_scope_is_offered_four_with_the_first_two_on():
    offered = {setting.key: setting for setting in pico.make_settings(4)}
    assert [offered[f"enabled_{key}"].default for key in "abcd"] == [True, True, False, False]
    assert offered["scale_d"].group == "Channel D"


def test_a_mixed_signal_scope_is_offered_its_two_ports_and_a_threshold_for_each():
    offered = {setting.key: setting for setting in pico.make_settings(2, True)}
    assert offered["digital_0"].label == "D0 to D7" and offered["digital_1"].label == "D8 to D15"
    assert offered["threshold_1"].live and offered["threshold_1"].default == 1.5
    assert not offered["digital_0"].live, "which changes what the channels are"


def test_the_scales_offered_are_those_of_the_ranges_the_scope_has():
    offered = {setting.key: setting for setting in pico.make_settings(2, False, ("1V", "2V"))}
    scales = [value for value, _label in offered["scale_a"].choices]
    assert scales == [0.2, 0.5]
    through = pico.PicoScope2000A.fitted(tuple(offered.values()), {"probe_a": 10})
    scales = [value for value, _label in next(s for s in through if s.key == "scale_a").choices]
    assert scales == [2.0, 5.0]


def test_the_generator_goes_to_a_megahertz():
    offered = {setting.key: setting for setting in pico.make_settings()}
    assert offered["gen_frequency"].maximum == 1_000_000
    assert pico.Settings({"gen_wave": "sine", "gen_frequency": 5e6}).generator[1] == 1_000_000


def test_every_setting_offered_is_one_the_back_end_reads():
    """A setting that is offered and not read would do nothing when it is changed."""
    for setting in pico.make_settings(4, True, offset=True):
        # With what it needs to have a say: a sensitivity, a current probe.
        needed = dict([setting.needs]) if setting.needs else {}
        options = needed | {setting.key: _another(setting)}
        assert vars(pico.Settings(options)) != vars(pico.Settings(needed)), setting.key


def _another(setting):
    if setting.choices:
        return next(value for value, _label in setting.choices if value != setting.default)
    if isinstance(setting.default, bool):
        return not setting.default
    return setting.default + 1


# --- settings --------------------------------------------------------------------------------
def test_the_defaults_are_two_channels_and_no_logic_inputs():
    settings = pico.Settings()
    assert settings.keys() == ["A", "B"] and settings.digital_keys() == []
    assert settings.ranges["A"] == "5V" and settings.rate == pico.DEFAULT_RATE


def test_what_a_scope_lacks_is_not_read_whatever_was_saved():
    saved = pico.Settings({"enabled_c": True, "digital_0": True})
    assert saved.keys() == ["A", "B", "C"] and len(saved.digital_keys()) == 8
    kept = saved.for_scope(2, False)
    assert kept.keys() == ["A", "B"] and kept.digital_keys() == []
    assert saved.keys() == ["A", "B", "C"], "and what was read is not changed by it"


def test_a_threshold_is_kept_to_what_the_inputs_take():
    assert pico.Settings({"threshold_0": 12}).threshold[0] == 5.0
    assert pico.Settings({"threshold_1": "high"}).threshold[1] == 1.5


@pytest.mark.parametrize("options", [None, [], "fast", {"rate": "fast"}, {"rate": 0}])
def test_settings_nobody_can_read_are_the_defaults(options):
    assert pico.Settings(options).rate == pico.DEFAULT_RATE


# --- opening ---------------------------------------------------------------------------------
def test_opening_asks_the_scope_what_it_is_and_what_it_has():
    library = FakeLibrary(MSO)
    library.ranges = ALL_RANGES[1:]
    opened = stream(library)
    opened.open()
    assert (opened.model, opened.channels, opened.digital) == ("2206BMSO", 2, True)
    assert opened.ranges == tuple(pico.RANGES)[1:]
    assert opened.notes == [("PicoScope 2206BMSO, GQ123/0456.", False)]


def test_a_scope_that_will_not_say_its_ranges_is_offered_them_all():
    library = FakeLibrary()
    library.ps2000aGetChannelInformation = lambda *_arguments: 0x0D
    opened = stream(library)
    opened.open()
    assert opened.ranges == tuple(pico.RANGES)


def test_no_scope_found_says_what_to_check():
    with pytest.raises(pico.ScopeError, match="plugged in"):
        stream(FakeLibrary(found=False)).open()


def test_a_scope_that_will_not_open_says_why():
    library = FakeLibrary()
    library.ps2000aOpenUnit = lambda handle, serial: 0x04
    with pytest.raises(pico.ScopeError, match="firmware"):
        stream(library).open()


def test_a_status_with_no_words_is_given_by_its_number():
    assert pico.why(0x99) == "driver status 0x99"


def test_a_driver_that_fails_inside_opening_is_said_and_not_raised_as_it_is():
    library = FakeLibrary()

    def fails(handle, serial):
        raise OSError("[WinError -529697949] Windows Error 0xe06d7363")

    library.ps2000aOpenUnit = fails
    with pytest.raises(pico.ScopeError, match="drops off USB"):
        stream(library).open()


# --- streaming -------------------------------------------------------------------------------
def test_starting_sets_the_channels_and_streams_into_buffers_it_hands_over():
    library = FakeLibrary()
    started(library, {"scale_a": 0.2, "coupling_b": "AC"})
    assert library.calls == [
        ("open",),
        ("channel", 0, True, pico.COUPLING_DC, 6),
        ("channel", 1, True, pico.COUPLING_AC, 8),
        ("generator", 0, 0, pico.WAVES["off"], 1000.0, 1000.0),
        ("trigger", None),
        ("stream", 2000, pico.TIME_UNITS_NS, 0, 1, pico.STREAM_SAMPLES),
    ]
    assert set(library.buffers) == {0, 1}


def test_a_two_channel_scope_is_not_told_about_channels_it_lacks():
    library = FakeLibrary()
    started(library, {"enabled_c": True})
    assert [call[1] for call in library.calls if call[0] == "channel"] == [0, 1]
    assert not any(call[0] == "port" for call in library.calls)


def test_a_four_channel_scope_has_all_four_set_and_reads_those_that_are_on():
    library = FakeLibrary(b"2406B")
    reading = started(library, {"enabled_b": False, "enabled_d": True, "scale_d": 0.2})
    assert [call[1:3] for call in library.calls if call[0] == "channel"] == [
        (0, True),
        (1, False),
        (2, False),
        (3, True),
    ]
    library.waiting.append({0: [0, 32512], 3: [16256, 0]})
    block = reading.poll()
    assert list(block.data) == ["A", "D"]
    assert block.values("A").tolist() == pytest.approx([0.0, 5.0])
    assert block.values("D").tolist() == pytest.approx([0.5, 0.0])


def test_counts_become_volts_through_the_probe():
    library = FakeLibrary()
    reading = started(library, {"scale_a": 2.0, "probe_a": 10, "enabled_b": False})
    library.waiting.append({0: [32512, -16256]})
    assert reading.poll().values("A").tolist() == pytest.approx([10.0, -5.0])


def test_blocks_of_a_stream_are_numbered_from_the_samples_before_them():
    library = FakeLibrary()
    reading = started(library, {"enabled_b": False})
    library.waiting += [{0: [1] * 10}, {0: [2] * 4}]
    first, second = reading.poll(), reading.poll()
    assert (first.first, len(first)) == (0, 10) and (second.first, len(second)) == (10, 4)
    assert second.values("A")[0] == pytest.approx(2 * 5.0 / 32512), "from where the driver put them"
    assert reading.poll() is None


def test_a_stream_is_sent_on_as_the_drivers_counts_with_their_scale():
    """Nothing worked out per sample: half the memory of volts, and no time spent."""
    library = FakeLibrary()
    reading = started(library, {"scale_a": 2.0, "enabled_b": False})
    library.waiting.append({0: [32512, -16256, pico.LOST_DATA]})
    block = reading.poll()
    assert block.data["A"].dtype == np.int16
    assert block.data["A"].tolist() == [32512, -16256, pico.LOST_DATA]
    assert block.scales["A"].per_count == pytest.approx(reading.settings.volts("A") / 32512)
    assert block.values("A")[0] == pytest.approx(10.0), "full scale of the ±10 V range"


def test_a_sample_the_driver_lost_is_a_gap_and_not_minus_full_scale():
    library = FakeLibrary()
    reading = started(library, {"enabled_b": False})
    library.waiting.append({0: [100, pico.LOST_DATA, 100]})
    assert np.isnan(reading.poll().values("A")).tolist() == [False, True, False]


def test_the_rate_is_the_one_the_driver_says_it_is_streaming_at():
    library = FakeLibrary()
    library.interval = 2048
    reading = started(library, {"enabled_b": False})
    library.waiting.append({0: [1, 2]})
    assert reading.poll().rate == pytest.approx(1e9 / 2048)
    assert any("nearest it has" in text for text, _warning in reading.notes)


def test_samples_arriving_at_the_rate_the_driver_gave_say_nothing():
    """Asked for 100 kS/s and given 12 us a sample: what arrives is checked against that."""
    library, clock = FakeLibrary(), Clock()
    library.interval = 12_000
    reading = stream(library, {"rate": 100_000, "enabled_b": False}, clock)
    reading.open()
    reading.start()
    reading.notes.clear()
    clock.now = CHECK_AFTER_S + 1
    arrived = round((CHECK_AFTER_S + 1) * 1e9 / 12_000)
    library.waiting.append({0: np.zeros(arrived, dtype=np.int16)})
    reading.poll()
    assert not [text for text, is_warning in reading.notes if is_warning]


def test_the_fastest_rate_offered_is_a_whole_number_of_nanoseconds_a_sample():
    offered = {setting.key: setting for setting in pico.make_settings()}
    fastest = offered["rate"].choices[0][0]
    assert fastest == pico.FASTEST_RATE and pico.Settings({"rate": fastest}).interval_ns == 32
    for rate, _label in offered["rate"].choices:
        assert pico.Settings({"rate": rate}).rate == rate, "none of them is rounded"


def test_a_fast_stream_is_given_room_for_a_second_between_polls():
    library = FakeLibrary()
    reading = started(library, {"rate": 20_000_000, "enabled_b": False})
    assert library.calls[-1] == ("stream", 50, pico.TIME_UNITS_NS, 0, 1, 20_000_000)
    assert library.buffers[0][1] == 20_000_000
    library.waiting.append({0: np.arange(200_000) % 100})
    block = reading.poll()
    assert (len(block), block.rate) == (200_000, 20e6)


def test_a_rate_the_scope_refuses_is_said():
    library = FakeLibrary()
    library.streams = False
    opened = stream(library)
    opened.open()
    with pytest.raises(pico.ScopeError, match=r"cannot sample at that interval\. Try a lower rate"):
        opened.start()
    assert not opened.streaming


def test_a_range_the_scope_refuses_is_said():
    library = FakeLibrary()
    library.refused_ranges = {1}
    opened = stream(library, {"scale_a": 0.005})
    opened.open()
    with pytest.raises(pico.ScopeError, match="channel A to ±20mV: it does not have that range"):
        opened.start()


def test_everything_off_is_said_without_setting_anything_up():
    library = FakeLibrary()
    opened = stream(library, {"enabled_a": False, "enabled_b": False})
    opened.open()
    with pytest.raises(pico.ScopeError, match="Every channel is switched off"):
        opened.start()
    assert library.calls == [("open",)]


def test_a_scope_unplugged_while_streaming_is_said():
    library = FakeLibrary()
    reading = started(library)
    library.latest = 0x07
    with pytest.raises(pico.ScopeError, match="unplugged"):
        reading.poll()


def test_a_driver_that_stalled_because_it_was_not_read_is_said():
    library = FakeLibrary()
    reading = started(library)
    library.latest = pico.BUFFER_STALL
    with pytest.raises(pico.ScopeError, match="did not keep up"):
        reading.poll()


def test_a_range_change_while_running_stops_the_stream_sets_it_and_starts_again():
    library = FakeLibrary()
    clock = Clock()
    reading = stream(library, {"enabled_b": False}, clock)
    reading.open()
    reading.start()
    library.waiting.append({0: [1] * 100})
    reading.poll()
    del library.calls[:]
    reading.wanted = pico.Settings({"enabled_b": False, "scale_a": 0.2})
    library.waiting.append({0: [32512]})
    block = reading.poll()
    assert [call[0] for call in library.calls] == ["stop", "channel", "channel", "stream"]
    assert block.after_pause and block.values("A").tolist() == pytest.approx([1.0])


def test_closing_stops_and_lets_go_and_does_nothing_if_it_never_opened():
    library = FakeLibrary()
    stream(library).close()
    assert library.calls == []
    reading = started(library)
    reading.close()
    assert library.calls[-2:] == [("stop",), ("close",)] and not reading.streaming


# --- logic inputs ----------------------------------------------------------------------------
def test_a_port_is_switched_on_with_its_threshold_and_read_as_eight_inputs():
    library = FakeLibrary(MSO)
    reading = started(library, {"enabled_b": False, "digital_0": True, "threshold_0": 2.5})
    assert ("port", PORT0, True, round(2.5 / 5 * 32767)) in library.calls
    assert ("port", PORT1, False, round(1.5 / 5 * 32767)) in library.calls
    library.waiting.append({0: [0, 0, 0], PORT0: [0b0000_0001, 0b1000_0010, 0b0000_0011]})
    block = reading.poll()
    assert list(block.data) == ["A", "port0"], "the port as the driver gave it"
    assert block.data["port0"].dtype == np.int16
    assert list(block.bits) == [f"D{bit}" for bit in range(8)]
    assert block.values("D0").tolist() == [1, 0, 1] and block.values("D0").dtype == np.uint8
    assert block.values("D1").tolist() == [0, 1, 1]
    assert block.values("D7").tolist() == [0, 1, 0]


def test_the_second_port_is_inputs_eight_to_fifteen():
    library = FakeLibrary(MSO)
    options = {"enabled_a": False, "enabled_b": False, "digital_1": True}
    reading = started(library, options)
    library.waiting.append({PORT1: [0b0000_0001, 0b1000_0000]})
    block = reading.poll()
    assert list(block.data) == ["port1"]
    assert block.bits["D8"] == ("port1", 0) and block.bits["D15"] == ("port1", 7)
    assert block.values("D8").tolist() == [1, 0] and block.values("D15").tolist() == [0, 1]


def test_logic_inputs_alone_are_something_to_read():
    library = FakeLibrary(MSO)
    reading = started(library, {"enabled_a": False, "enabled_b": False, "digital_0": True})
    assert reading.streaming and set(library.buffers) == {PORT0}


def test_a_threshold_is_taken_up_as_it_runs():
    library = FakeLibrary(MSO)
    options = {"digital_0": True}
    reading = started(library, options)
    del library.calls[:]
    reading.wanted = pico.Settings(options | {"threshold_0": 0.8})
    reading.poll()
    assert ("port", PORT0, True, round(0.8 / 5 * 32767)) in library.calls


# --- blocks ----------------------------------------------------------------------------------
def blocks(library, options=None, trigger=None):
    return started(library, {"mode": "block"} | (options or {}), trigger)


def test_a_short_block_is_taken_at_the_fastest_the_scope_has_for_what_is_on():
    library = FakeLibrary()
    reading = blocks(library, {"block_ms": 0.01, "enabled_b": False})
    # 10 us at 2 ns a sample is 5000 samples: nothing slower is needed.
    assert (reading._timebase, reading._block_samples, reading._block_rate) == (0, 5000, 500e6)
    both = blocks(FakeLibrary(), {"block_ms": 0.01})
    assert (both._timebase, both._block_rate) == (1, 250e6), "which has no 2 ns with two on"


def test_a_long_block_is_slowed_until_it_is_a_million_samples_at_most():
    library = FakeLibrary()
    reading = blocks(library, {"block_ms": 100.0, "enabled_b": False})
    # 100 ms in a million samples is 100 ns a sample: the next it has is 112 ns.
    assert reading._timebase == 9 and reading._block_rate == pytest.approx(1e9 / 112)
    assert reading._block_samples == 892_858
    assert len(library.asked) < 16, "found by closing in, not by trying each"
    assert ("Blocks of 892858 samples at 8,928,571 a second: 100 ms each.", False) in reading.notes


def test_memory_is_what_limits_a_scope_that_has_little():
    library = FakeLibrary()
    library.memory = 8000
    reading = blocks(library, {"block_ms": 10.0})
    interval_ns = 1e9 / reading._block_rate
    assert reading._block_samples <= 4000 and reading._block_samples * interval_ns >= 10e6
    faster = (reading._timebase - 3) * 16.0
    assert faster * 4000 < 10e6, "and the next faster would not have held it"


def test_a_block_longer_than_the_scope_can_take_is_its_longest_and_says_so():
    library = FakeLibrary()
    library.memory, library.slowest = 8000, 40
    reading = blocks(library, {"block_ms": 1000.0})
    assert reading._timebase == 40 and reading._block_samples == 4000
    assert any("longest block the scope can take" in text for text, warning in reading.notes)


def test_the_first_poll_asks_for_a_block_and_the_next_brings_it_in():
    library = FakeLibrary()
    trigger = pico.Trigger("A", level=1.0, rising=True, position=0.25, auto=False)
    reading = blocks(library, {"block_ms": 0.01, "enabled_b": False}, trigger)
    assert reading.poll() is None
    assert library.calls[-2:] == [
        ("trigger", 0, round(1.0 / 5.0 * 32512), pico.RISING, 0),
        ("block", 1250, 3750, 0),
    ]
    library.block_wave = lambda n: np.where(np.arange(n) < 1250, -16000, 16000)
    block = reading.poll()
    assert block.sweep and block.first == 0 and len(block) == 5000
    assert (block.trigger, block.triggered) == (1250, True)
    assert block.values("A")[0] == pytest.approx(-16000 * 5.0 / 32512)


def test_a_block_that_is_not_in_yet_is_waited_for():
    library = FakeLibrary()
    library.ready = 0
    reading = blocks(library)
    assert reading.poll() is None and reading.poll() is None
    assert [call[0] for call in library.calls].count("block") == 1


def test_normal_waits_for_ever_and_auto_gives_up_after_a_while():
    for auto, wait_ms in ((False, 0), (True, 100)):
        library = FakeLibrary()
        reading = blocks(library, None, pico.Trigger("B", 0.0, False, 0.5, auto))
        reading.poll()
        assert ("trigger", 1, 0, pico.FALLING, wait_ms) in library.calls


def test_with_no_trigger_blocks_are_taken_one_after_another():
    library = FakeLibrary()
    reading = blocks(library)
    reading.poll()
    block = reading.poll()
    assert ("trigger", None) in library.calls
    assert block.trigger is None and not block.triggered


def test_a_trigger_on_a_channel_that_is_off_is_no_trigger():
    library = FakeLibrary()
    reading = blocks(library, {"enabled_b": False}, pico.Trigger("B"))
    reading.poll()
    assert library.calls[-2] == ("trigger", None)


def test_a_block_taken_because_nothing_came_is_not_called_triggered():
    library = FakeLibrary()
    library.block_wave = lambda n: np.zeros(n)
    reading = blocks(library, None, pico.Trigger("A", level=1.0))
    reading.poll()
    assert not reading.poll().triggered


def test_a_logic_input_is_triggered_on_by_its_edge():
    library = FakeLibrary(MSO)
    trigger = pico.Trigger("D2", rising=True, auto=True)
    reading = blocks(library, {"digital_0": True}, trigger)
    reading.poll()
    assert library.calls[-4:-1] == [
        ("conditions", 0, 0, pico.CONDITION_TRUE),
        ("digital trigger", 2, pico.DIGITAL_RISING),
        ("auto", 100),
    ]
    block = reading.poll()
    assert block.triggered and block.values("D2").dtype == np.uint8
    assert block.values("D1").max() == 0, "which the wave leaves low"


def test_going_back_to_an_analog_trigger_clears_the_logic_one():
    library = FakeLibrary(MSO)
    reading = blocks(library, {"digital_0": True}, pico.Trigger("D0"))
    reading.poll()
    del library.calls[:]
    reading.wanted_trigger = pico.Trigger("A", level=0.5)
    reading.poll()
    kinds = [call[0] for call in library.calls]
    assert kinds == ["stop", "digital trigger", "trigger", "block"]
    assert library.calls[1] == ("digital trigger", None)


def test_a_range_change_between_blocks_is_taken_up_without_opening_again():
    library = FakeLibrary()
    reading = blocks(library, {"enabled_b": False})
    reading.poll()
    reading.wanted = pico.Settings({"mode": "block", "enabled_b": False, "scale_a": 0.2})
    reading.poll()
    block = reading.poll()
    assert block.values("A")[-1] == pytest.approx(16000 * 1.0 / 32512)
    assert library.calls.count(("open",)) == 1


def test_a_scope_that_was_unplugged_while_a_block_was_waited_for_is_said():
    library = FakeLibrary()
    reading = blocks(library)
    reading.poll()
    library.answers = False
    with pytest.raises(pico.ScopeError, match="unplugged"):
        reading.poll()


def test_a_block_the_scope_will_not_take_is_said():
    library = FakeLibrary()
    library.takes_blocks = False
    reading = blocks(library)
    with pytest.raises(pico.ScopeError, match="would not take a block"):
        reading.poll()


# --- the signal generator --------------------------------------------------------------------
def test_a_generator_asked_for_is_set_in_microvolts():
    library = FakeLibrary()
    options = {"gen_wave": "square", "gen_frequency": 250_000, "gen_amplitude": 1.5}
    reading = started(library, options | {"gen_offset": -0.5})
    assert ("generator", -500_000, 1_500_000, 1, 250_000, 250_000) in library.calls
    assert any("Signal generator: square, 250000 Hz" in text for text, _w in reading.notes)


def test_a_generator_the_scope_refuses_is_a_warning_with_the_reason():
    library = FakeLibrary()
    library.generates = False
    reading = started(library, {"gen_wave": "sine"})
    refused = (
        "The scope would not set its signal generator to that output: it has no signal generator."
    )
    assert (refused, True) in reading.notes
    quiet = FakeLibrary()
    quiet.generates = False
    assert not any(warning for _text, warning in started(quiet).notes), "off is not asking"


# --- the library -----------------------------------------------------------------------------
def test_the_library_named_in_the_environment_is_the_one_used():
    environ = {pico.LIBRARY_ENV: "/somewhere/libps2000a.so"}
    assert pico.find_library("linux", environ) == Path("/somewhere/libps2000a.so")


def test_windows_looks_for_this_drivers_library_and_not_the_older_ones(tmp_path):
    sdk = tmp_path / "Pico Technology" / "SDK" / "lib"
    sdk.mkdir(parents=True)
    (sdk / "ps2000.dll").write_bytes(b"")
    assert pico.find_library("win32", {"ProgramFiles": str(tmp_path)}) != sdk / "ps2000.dll"
    (sdk / "ps2000a.dll").write_bytes(b"")
    assert pico.find_library("win32", {"ProgramFiles": str(tmp_path)}) == sdk / "ps2000a.dll"


def test_without_the_library_the_instrument_says_what_to_install(app, monkeypatch):
    monkeypatch.setattr(pico, "find_library", lambda: None)
    with pytest.raises(ImportError, match=r"ps2000a library was not found.*PYSCOPEGUI_PS2000A"):
        backends.create("picoscope2000a")


def test_every_function_used_has_its_arguments_declared():
    used = {name for name in dir(FakeLibrary) if name.startswith("ps2000a")}
    assert used == set(pico.PROTOTYPES)


def test_the_structures_are_the_size_the_driver_packs_them_to():
    assert ctypes.sizeof(pico.Conditions) == 32 and ctypes.sizeof(pico.DigitalDirection) == 8
    assert ctypes.sizeof(pico.Properties) == 16 and ctypes.sizeof(pico.PwqConditions) == 28


# --- the instrument, on its thread -----------------------------------------------------------
def test_the_instrument_is_listed_and_named_apart_from_the_older_driver():
    assert backends.title("picoscope2000a") == "PicoScope 2000 series (ps2000a)"
    assert backends.short("picoscope2000a") != backends.short("picoscope2000")


def test_the_instrument_streams_on_its_thread_and_offers_what_the_scope_has(app, monkeypatch):
    library = FakeLibrary(MSO)
    library.ranges = ALL_RANGES[1:]
    library.waiting += [{0: [100] * 10, PORT0: [1] * 10}, {0: [300] * 5, PORT0: [0] * 5}]
    monkeypatch.setattr(pico, "load_library", lambda: library)
    options = {"enabled_b": False, "digital_0": True, "scale_a": 0.2}
    instrument = backends.create("picoscope2000a", None, options)
    assert instrument.settings_offered() == pico.SETTINGS
    received, opened, notes = [], [], []
    instrument.block.connect(received.append)
    instrument.opened_changed.connect(opened.append)
    instrument.note.connect(notes.append)
    instrument.start()  # which opens it first
    run_for(app, instrument, lambda: len(received) == 2)
    assert [block.first for block in received] == [0, 10]
    channels = instrument.channels()
    assert [(c.key, c.detail) for c in channels[:2]] == [
        ("A", "200 mV/div, 1x, DC"),
        ("D0", "above 1.5 V"),
    ]
    assert len(channels) == 9 and all(c.kind == DIGITAL for c in channels[1:])
    assert channels[0].counts and not channels[1].counts, "the channel held as counts"
    offered = {setting.key: setting for setting in instrument.settings_offered()}
    assert "digital_1" in offered and "enabled_c" not in offered
    assert offered["scale_a"].choices[0][0] == 0.01, "which is ±50 mV: it has no ±20 mV"
    assert any("2206BMSO" in note for note in notes)
    instrument.close()
    run_for(app, instrument, lambda: opened == [True, False])
    assert library.calls[-2:] == [("stop",), ("close",)]


def test_what_was_saved_for_another_scope_is_listed_until_this_one_says_what_it_has(
    app, monkeypatch
):
    library = FakeLibrary()
    monkeypatch.setattr(pico, "load_library", lambda: library)
    instrument = backends.create("picoscope2000a", None, {"enabled_c": True, "digital_0": True})
    assert len(instrument.channels()) == 3 + 8
    opened = []
    instrument.opened_changed.connect(opened.append)
    instrument.open()
    run_for(app, instrument, lambda: opened == [True])
    assert [channel.key for channel in instrument.channels()] == ["A", "B"]
    instrument.close()
    run_for(app, instrument, lambda: opened == [True, False])


def test_the_instrument_sends_sweeps_and_is_told_its_trigger(app, monkeypatch):
    library = FakeLibrary()
    monkeypatch.setattr(pico, "load_library", lambda: library)
    instrument = backends.create("picoscope2000a", None, {"mode": "block", "block_ms": 0.01})
    assert instrument.sweeps
    received = []
    instrument.block.connect(received.append)
    instrument.set_trigger("A", 0.0, True, 0.5, False)
    instrument.start()
    run_for(app, instrument, lambda: len(received) >= 1)
    assert received[0].sweep and received[0].triggered
    assert instrument.rate == received[0].rate
    instrument.close()
    run_for(app, instrument, lambda: not instrument.is_open)


def test_a_scope_that_is_not_there_is_an_error_and_not_running(app, monkeypatch):
    monkeypatch.setattr(pico, "load_library", lambda: FakeLibrary(found=False))
    instrument = backends.create("picoscope2000a")
    errors, states = [], []
    instrument.error.connect(errors.append)
    instrument.state_changed.connect(states.append)
    instrument.start()
    run_for(app, instrument, lambda: states == [False])
    assert len(errors) == 1 and "No PicoScope was found" in errors[0]
    assert not instrument.running and not instrument.is_open


# --- an offset, to read a small signal away from nought more finely ---------------------------
def test_a_scope_with_an_offset_is_offered_one_on_each_channel_beside_the_scale():
    offered = [s.key for s in pico.make_settings(2, offset=True) if s.group == "Channel A"]
    assert offered == ["enabled_a", "scale_a", "offset_a", "coupling_a", "probe_a", "sensitivity_a"]
    assert "offset_a" not in [s.key for s in pico.make_settings(2)], "and none without"


def test_the_offset_is_given_to_the_scope_and_taken_off_what_is_read():
    """A signal at 3.5 V, on the ±2 V range with -3.5 V... which that range cannot take."""
    library = FakeLibrary()
    # 500 mV/div is the ±2 V range, which takes 2.5 V of offset at most.
    reading = started(library, {"scale_a": 0.5, "offset_a": -2.0, "enabled_b": False})
    assert library.offsets[0] == pytest.approx(-2.0)
    library.waiting.append({0: [0, 32512]})
    # Nought counts is the offset taken off again: 2 V. Full scale is 2 V more.
    assert reading.poll().values("A").tolist() == pytest.approx([2.0, 4.0])


def test_an_offset_is_at_the_probes_tip():
    library = FakeLibrary()
    reading = started(library, {"scale_a": 5.0, "probe_a": 10, "offset_a": -20.0})
    assert library.offsets[0] == pytest.approx(-2.0), "the scope is given a tenth of it"
    library.waiting.append({0: [0], 1: [0]})
    assert reading.poll().values("A")[0] == pytest.approx(20.0)


def test_more_offset_than_the_range_takes_is_as_much_as_it_does_and_says_so():
    library = FakeLibrary()
    reading = started(library, {"scale_a": 0.5, "offset_a": -3.5, "enabled_b": False})
    assert library.offsets[0] == pytest.approx(-2.5)
    said = [text for text, warning in reading.notes if warning]
    assert said == [
        "Channel A's range of ±2V takes an offset of -2.5 V to 2.5 V, so it is -2.5 V where "
        "-3.5 V was asked for. A larger scale allows more."
    ]
    library.waiting.append({0: [0]})
    assert reading.poll().values("A")[0] == pytest.approx(2.5), "read with what it was given"


def test_a_scope_without_one_reads_with_none_and_says_so():
    library = FakeLibrary()
    library.has_offset = False
    reading = started(library, {"offset_a": -1.0, "enabled_b": False})
    assert not reading.has_offset and library.offsets[0] == 0.0
    assert any("has no offset" in text for text, warning in reading.notes if warning)


def test_the_trigger_level_is_where_the_signal_is_with_the_offset_in_it():
    library = FakeLibrary()
    trigger = pico.Trigger("A", level=3.0, rising=True, auto=False)
    reading = blocks(library, {"scale_a": 0.5, "offset_a": -2.0, "enabled_b": False}, trigger)
    reading.poll()
    # 3 V at the tip is 1 V on the scope once 2 V is taken off: half its ±2 V range.
    assert ("trigger", 0, round(0.5 * 32512), pico.RISING, 0) in library.calls


def test_an_offset_is_taken_up_as_it_runs():
    library = FakeLibrary()
    options = {"scale_a": 0.5, "enabled_b": False}
    reading = started(library, options)
    reading.wanted = pico.Settings(options | {"offset_a": -1.5})
    library.waiting.append({0: [0]})
    block = reading.poll()
    assert library.offsets[0] == pytest.approx(-1.5)
    assert block.values("A")[0] == pytest.approx(1.5)


def test_the_instrument_offers_an_offset_only_on_a_scope_that_has_one(app, monkeypatch):
    for has, offered in ((True, True), (False, False)):
        library = FakeLibrary()
        library.has_offset = has
        monkeypatch.setattr(pico, "load_library", lambda library=library: library)
        instrument = backends.create("picoscope2000a", None, {"offset_a": -1.0})
        opened = []
        instrument.opened_changed.connect(opened.append)
        instrument.open()
        run_for(app, instrument, lambda opened=opened: opened == [True])
        keys = [setting.key for setting in instrument.settings_offered()]
        assert ("offset_a" in keys) == offered
        channel = instrument.channels()[0]
        assert channel.detail.endswith(", offset -1 V") == offered
        # What is read is moved up by the volt the scope takes off.
        assert channel.middle == (1.0 if offered else 0.0)
        instrument.close()
        run_for(app, instrument, lambda opened=opened: opened == [True, False])


def test_samples_the_driver_lost_are_said_as_on_the_older_scopes():
    library = FakeLibrary()
    reading = started(library, {"enabled_b": False})
    library.waiting.append({0: [100, pico.LOST_DATA, pico.LOST_DATA, 100]})
    reading.poll()
    said = [text for text, warning in reading.notes if warning]
    assert said and said[0].startswith("The driver lost 2 samples, which are shown as a gap")


# --- what the scope waits for itself, beyond an edge -----------------------------------------
def counts(volts, full=5.0):
    return round(volts / full * 32512)


HYSTERESIS = round(0.02 * 32512)
NOWHERE = [pico.NO_DIRECTION] * 6


def test_an_edge_either_way_is_the_scopes_own_advanced_trigger():
    library = FakeLibrary()
    trigger = pico.Trigger("A", level=1.0, auto=False, condition=Condition(EDGE, edge=EITHER))
    reading = blocks(library, None, trigger)
    reading.poll()
    level = counts(1.0)
    assert ("properties", ((level, level, 0, pico.LEVEL_MODE),), 0) in library.calls
    assert ("conditions", pico.CONDITION_TRUE, 0, 0) in library.calls
    assert ("directions", pico.RISING_OR_FALLING, *NOWHERE[1:]) in library.calls
    assert not any(call[0] == "trigger" for call in library.calls), "not the simple trigger"
    assert reading.poll().triggered, "waited for, in Normal"


def test_a_window_entered_or_left_has_both_its_levels():
    library = FakeLibrary()
    window = Condition(WINDOW, upper=-1.0, direction=LEAVE)
    reading = blocks(library, None, pico.Trigger("B", level=2.0, condition=window))
    reading.poll()
    assert ("properties", ((counts(2.0), counts(-1.0), 1, pico.WINDOW_MODE),), 100) in (
        library.calls
    ), "the higher of the two is the upper, whichever was typed where"
    assert ("directions", pico.NO_DIRECTION, pico.EXIT_WINDOW, *NOWHERE[2:]) in library.calls


@pytest.mark.parametrize(("polarity", "way"), [("high", 9), (LOW, 10)])
def test_a_runt_high_or_low(polarity, way):
    library = FakeLibrary()
    runt = Condition(RUNT, upper=2.0, polarity=polarity)
    blocks(library, None, pico.Trigger("A", level=0.5, condition=runt)).poll()
    assert ("properties", ((counts(2.0), counts(0.5), 0, pico.WINDOW_MODE),), 100) in library.calls
    assert ("directions", way, *NOWHERE[1:]) in library.calls
    assert (pico.POSITIVE_RUNT, pico.NEGATIVE_RUNT) == (9, 10)


def test_a_pulse_is_timed_from_its_start_and_triggered_at_its_end():
    library = FakeLibrary()
    pulse = Condition(PULSE, compare=BETWEEN, shortest=1e-6, longest=2e-6)
    reading = blocks(library, {"block_ms": 0.01}, pico.Trigger("A", level=0.5, condition=pulse))
    reading.poll()
    rate = reading._block_rate
    assert ("directions", pico.FALLING, *NOWHERE[1:]) in library.calls, "a high pulse ends falling"
    assert library.conditions.a == library.conditions.pulse_width == pico.CONDITION_TRUE
    assert (
        "pulse width",
        pico.CONDITION_TRUE,
        0,
        pico.RISING_LOWER,
        round(1e-6 * rate),
        round(2e-6 * rate),
        pico.PW_IN_RANGE,
    ) in library.calls
    del library.calls[:]
    low = replace(pulse, polarity=LOW, compare=SHORTER)
    reading.wanted_trigger = pico.Trigger("A", level=0.5, condition=low)
    reading.poll()
    timed = next(call for call in library.calls if call[0] == "pulse width")
    assert timed[3] == pico.FALLING_LOWER and timed[6] == pico.PW_LESS_THAN
    assert ("directions", pico.RISING, *NOWHERE[1:]) in library.calls, "a low pulse ends rising"
    del library.calls[:]
    reading.wanted_trigger = pico.Trigger("A", level=0.5)
    reading.poll()
    kinds = [call[0] for call in library.calls]
    assert kinds == ["stop", "pulse width", "trigger", "block"], "the qualifier cleared"
    assert library.calls[1] == ("pulse width", None)


def test_a_pattern_of_channels_and_logic_inputs_together():
    library = FakeLibrary(MSO)
    pattern = Condition(PATTERN, pattern=(("A", 1), ("D3", 0), ("D9", 1)))
    trigger = pico.Trigger(None, level=1.0, condition=pattern)
    blocks(library, {"digital_0": True, "digital_1": True}, trigger).poll()
    assert ("properties", ((counts(1.0), counts(1.0), 0, pico.LEVEL_MODE),), 100) in library.calls
    assert ("conditions", pico.CONDITION_TRUE, 0, pico.CONDITION_TRUE) in library.calls
    assert ("directions", pico.ABOVE, *NOWHERE[1:]) in library.calls
    assert ("digital trigger", 3, pico.DIGITAL_LOW, 9, pico.DIGITAL_HIGH) in library.calls


def test_a_logic_input_either_way():
    library = FakeLibrary(MSO)
    either = Condition(EDGE, edge=EITHER)
    blocks(library, {"digital_0": True}, pico.Trigger("D2", condition=either)).poll()
    assert ("digital trigger", 2, pico.DIGITAL_EITHER) in library.calls
    assert ("conditions", 0, 0, pico.CONDITION_TRUE) in library.calls


def test_what_the_scope_cannot_do_itself_is_its_simple_trigger():
    library = FakeLibrary()
    timeout = Condition(TIMEOUT, shortest=1e-3)
    blocks(library, None, pico.Trigger("A", level=1.0, condition=timeout)).poll()
    assert ("trigger", 0, counts(1.0), pico.RISING, 100) in library.calls
    assert not any(call[0] == "directions" for call in library.calls)


def test_in_auto_a_block_is_triggered_if_what_was_waited_for_is_where_the_trigger_is():
    library = FakeLibrary()
    either = Condition(EDGE, edge=EITHER)
    reading = blocks(library, None, pico.Trigger("A", level=0.0, condition=either))
    reading.poll()
    assert reading.poll().triggered, "the wave steps up through nought in the middle"
    reading.wanted_trigger = pico.Trigger("A", level=4.0, condition=either)
    reading.poll()
    assert not reading.poll().triggered, "which never reaches four volts"


def test_the_instrument_says_what_it_can_wait_for_itself(app, monkeypatch):
    library = FakeLibrary(MSO)
    monkeypatch.setattr(pico, "load_library", lambda: library)
    instrument = backends.create(
        "picoscope2000a", None, {"mode": "block", "digital_0": True, "enabled_b": True}
    )
    can = instrument.triggers_itself
    assert can(Condition(EDGE, edge=EITHER), "A") and can(Condition(EDGE, edge=EITHER), "D0")
    assert can(Condition(WINDOW), "B") and can(Condition(RUNT), "A") and can(Condition(PULSE), "A")
    assert not can(Condition(PULSE), "D0"), "a logic input's pulses want the MSO's structures"
    assert not can(Condition(TIMEOUT), "A")
    assert not can(Condition(EDGE, holdoff=1e-3), "A"), "no holdoff"
    assert can(Condition(PATTERN, pattern=(("A", 1), ("D1", 0))), None)
    assert not can(Condition(PATTERN, pattern=(("A", 1),), held=1e-3), None)
    assert can(Condition(PATTERN), None), "its channels still to be chosen"
    assert not can(Condition(PATTERN, pattern=(("D9", 1),)), None), "a port that is off"
    instrument.set_trigger("A", 0.0, True, 0.5, False, Condition(TIMEOUT))
    assert instrument._trigger.condition == Condition(), "an edge, then"
    instrument.set_trigger("A", 0.0, True, 0.5, False, Condition(WINDOW))
    assert instrument._trigger.condition == Condition(WINDOW)


# --- the generator, on the scope's trigger --------------------------------------------------
def test_the_generator_runs_at_once_unless_it_is_to_wait_for_the_trigger():
    library = FakeLibrary()
    blocks(library, {"gen_wave": "sine"})
    assert library.generator_trigger == (0, 0, pico.SIGGEN_RISING, pico.SIGGEN_NONE)


def test_on_the_scopes_trigger_it_puts_out_its_cycles_each_time():
    library = FakeLibrary()
    reading = blocks(library, {"gen_wave": "square", "gen_start": "trigger", "gen_cycles": 3})
    assert library.generator_trigger == (3, 0, pico.SIGGEN_RISING, pico.SIGGEN_SCOPE_TRIG)
    assert any("3 cycles at each trigger" in text for text, _warning in reading.notes)
    library = FakeLibrary()
    blocks(library, {"gen_wave": "square", "gen_start": "trigger", "gen_cycles": 0})
    assert library.generator_trigger[0] == pico.SIGGEN_CONTINUOUS_RUN, "and runs on, for 0"


def test_waiting_for_a_trigger_while_streaming_is_said_to_wait_for_ever():
    library = FakeLibrary()
    reading = started(library, {"gen_wave": "sine", "gen_start": "trigger"})
    assert any("waits for ever" in text and warning for text, warning in reading.notes), (
        "the scope triggers itself only when reading blocks"
    )


def test_off_is_off_whatever_it_was_to_wait_for():
    library = FakeLibrary()
    blocks(library, {"gen_wave": "off", "gen_start": "trigger"})
    assert library.generator_trigger == (0, 0, pico.SIGGEN_RISING, pico.SIGGEN_NONE)


def test_the_start_and_the_cycles_are_offered_with_the_generator():
    keys = [setting.key for setting in pico.SETTINGS]
    assert keys.index("gen_offset") < keys.index("gen_start") < keys.index("gen_cycles")


def test_a_mixed_signal_run_in_the_window_holds_its_ports_packed(
    window, app, monkeypatch, tmp_path
):
    """Drawn, triggered on, written out and saved, each logic input read out of its port."""
    from pyscopegui.core import capture_file

    library = FakeLibrary(MSO)
    monkeypatch.setattr(pico, "load_library", lambda: library)
    window.ctx.settings.set("instrument.picoscope2000a", {"digital_0": True, "enabled_b": False})
    window.choose("picoscope2000a")
    window.instrument_view.open.click()
    run_for(app, window.instrument, lambda: window.instrument.is_open)
    square = [0b0000_0001] * 50 + [0b0000_0010] * 50
    library.waiting += [{0: [1000] * 100, PORT0: square} for _ in range(5)]
    window.set_mode("auto")
    capture = window.capture
    run_for(
        app,
        window.instrument,
        lambda: capture.records.get("D0") is not None and capture.records["D0"].total >= 500,
    )
    assert list(capture.ports) == ["port0"]
    assert capture.ports["port0"].memory_bytes < capture.records["A"].memory_bytes
    assert capture.records["D0"].values(0, 100).tolist() == [1] * 50 + [0] * 50
    assert capture.records["D1"].values(0, 100).tolist() == [0] * 50 + [1] * 50
    window.scope.redraw()
    window.set_mode("stop")
    written = window.scope.export_csv(tmp_path / "run.csv")
    assert written and written[0].rows >= 500
    saved = window.scope.save_captures(tmp_path / "run.npz")
    loaded = capture_file.load(saved[0])
    keys = [channel.key for channel in loaded.channels]
    assert "D0" in keys and "port0" not in keys
    # Saved as held: the inputs packed in their port, and A as counts.
    assert loaded.bits["D1"] == ("port0", 1) and "D1" not in loaded.data
    assert unpacked(loaded.data["port0"][:100], 1).tolist() == [0] * 50 + [1] * 50
    assert loaded.data["A"].dtype == np.int16 and "A" in loaded.scales
    # Opened again, it is held as the scope sent it, and reads the same.
    window.set_mode("stop")
    name = window.open_capture(saved[0])
    app.processEvents()
    opened = window.session.units[name].capture
    assert opened.records["A"].counts and list(opened.ports) == ["port0"]
    assert opened.records["D1"].values(0, 100).tolist() == [0] * 50 + [1] * 50
    assert opened.records["A"].values(0, 3).tolist() == capture.records["A"].values(0, 3).tolist()
    window.close_instrument()
