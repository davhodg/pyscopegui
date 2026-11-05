# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""A parallel bus as the rest of pyscopegui sees it: set up, saved, decoded from
an instrument's channels, chosen in its dialog, listed, and waited for."""

from types import SimpleNamespace

import numpy as np

from pyscopegui.backends.base import DIGITAL, Block, Channel
from pyscopegui.core.capture import Capture
from pyscopegui.core.decoding import (
    OFFSET,
    TWOS,
    UNSIGNED,
    ParallelSetup,
    from_saved,
    signed,
)
from pyscopegui.core.parallel_decode import BOTH, encode
from pyscopegui.core.parallel_decode import Transfer as ParallelTransfer

RATE = 1_000_000.0
TWELVE = tuple(f"D{b}" for b in range(12))
AD9238 = ParallelSetup(TWELVE, clock="D12", edge=BOTH, mux="D12", coding=OFFSET)


def logic_capture(*keys):
    held = Capture(history_s=1.0)
    held.set_channels([Channel(k, k, kind=DIGITAL) for k in keys], RATE)
    return held


def test_a_setup_is_saved_and_comes_back_and_nonsense_does_not():
    for setup in (
        AD9238,
        ParallelSetup(("D7", "D6", "D5"), settle_s=50e-9, enable="D8", enable_active_low=False),
        ParallelSetup(TWELVE, "D12", mux="D13", mux_swapped=True, coding=TWOS, threshold=1.65),
    ):
        assert from_saved(setup.as_saved()) == setup, setup
    good = AD9238.as_saved()
    for change in (
        {"data": []},
        {"data": ["D0", "D0"]},
        {"clock": "D3"},  # one of the data lines
        {"edge": "sideways"},
        {"mux_kind": "address"},  # not yet
        {"coding": "bcd"},
        {"settle_s": -1},
    ):
        assert from_saved({**good, **change}) is None, change


def test_its_lines_are_each_named_once_though_the_clock_is_the_select():
    assert AD9238.channels() == (*TWELVE, "D12")
    assert AD9238.key == "parallel:D0" and AD9238.main == "D0" and AD9238.width == 12
    assert (AD9238.stream_name(0), AD9238.stream_name(1)) == ("A", "B")
    swapped = ParallelSetup(TWELVE, mux="D12", mux_swapped=True)
    assert (swapped.stream_name(0), swapped.stream_name(1)) == ("B", "A")


def test_words_are_the_numbers_their_coding_says():
    words = np.array([0x000, 0x7FF, 0x800, 0xFFF])
    assert signed(words, 12, UNSIGNED).tolist() == [0, 2047, 2048, 4095]
    assert signed(words, 12, OFFSET).tolist() == [-2048, -1, 0, 2047]
    assert signed(words, 12, TWOS).tolist() == [0, 2047, -2048, -1]


def test_a_bus_is_decoded_from_an_instrument_s_logic_inputs_as_they_arrive():
    words = [0x7FF, 0x123, 0x800]
    samples = encode(words, 12, per_word=6)
    held = logic_capture(*TWELVE, "CLK")
    held.set_decodings([ParallelSetup(TWELVE, clock="CLK")])
    count = len(samples["D0"])
    for first in range(0, count, 11):
        part = {key: samples[key][first : first + 11].astype(np.uint8) for key in (*TWELVE, "CLK")}
        held.add(Block(first, RATE, part))
    assert not held.decodings[0].items, "not finished until the bus has rested a while"
    quiet = {key: np.zeros(100, np.uint8) for key in (*TWELVE, "CLK")}
    held.add(Block(count, RATE, quiet))
    assert [w for t in held.decodings[0].items for w in t.words] == words


# --- the dialog ---------------------------------------------------------------------------------
MSO = [(f"D{b}", f"D{b}", False) for b in range(16)] + [("A", "A", True)]


def test_the_dialog_takes_a_run_of_lines_from_the_one_right_clicked(app):
    from pyscopegui.ui.decode_dialog import ParallelDialog

    dialog = ParallelDialog(MSO, "D0")
    dialog.width.setValue(12)
    assert (
        dialog.data_lines() == list(TWELVE) and "Bit 0 is D0, bit 11 is D11" in dialog.span.text()
    )
    assert dialog.line("clock") == "" and not dialog.edge.isEnabled() and dialog.settle.isEnabled()
    for role in ("clock", "mux"):
        dialog.lines[role].setCurrentIndex(dialog.lines[role].findData("D12"))
    dialog.edge.setCurrentIndex(dialog.edge.findData(BOTH))
    dialog.coding.setCurrentIndex(dialog.coding.findData(OFFSET))
    dialog.accept()
    assert dialog.result(), dialog.problem.text()
    assert dialog.setup() == AD9238
    assert not dialog.threshold.isEnabled(), "all logic"
    again = ParallelDialog(MSO, "D0", AD9238)
    assert again.setup() == AD9238


def test_bit_0_can_be_the_last_line_and_comes_back_so(app):
    from pyscopegui.ui.decode_dialog import ParallelDialog

    dialog = ParallelDialog(MSO, "D4")
    dialog.width.setValue(4)
    dialog.bit0_first.setChecked(False)
    setup = dialog.setup()
    assert setup.data == ("D7", "D6", "D5", "D4")
    again = ParallelDialog(MSO, "D0", setup)
    assert again.data_lines() == ["D4", "D5", "D6", "D7"] and not again.bit0_first.isChecked()


def test_the_dialog_says_what_cannot_be(app):
    from pyscopegui.ui.decode_dialog import ParallelDialog

    dialog = ParallelDialog(MSO, "D10")
    dialog.width.setValue(12)
    dialog.accept()
    assert "only 7 channels from D10" in dialog.problem.text() and not dialog.result()
    dialog = ParallelDialog(MSO, "D0")
    dialog.width.setValue(8)
    dialog.lines["clock"].setCurrentIndex(dialog.lines["clock"].findData("D3"))
    dialog.accept()
    assert "clock is one of the data lines" in dialog.problem.text()


# --- listed, and waited for ---------------------------------------------------------------------
def row_texts(setup, item):
    from pyscopegui.ui.decoded_view import Row, texts

    return texts(Row(0.5, "bus", SimpleNamespace(setup=setup), item))


def test_a_transfer_reads_as_a_row_each_channel_s_words_together(app):
    plain = row_texts(ParallelSetup(TWELVE), ParallelTransfer(0, 1, [0x7FF, 0x001]))
    assert plain[3] == "2 words" and plain[4] == "7FF 001"
    muxed = ParallelTransfer(0, 1, [0x7FF, 0x123, 0x800], [0, 1, 0])
    assert row_texts(AD9238, muxed)[4] == "A 7FF 800   B 123"
    byte = row_texts(ParallelSetup(TWELVE[:8]), ParallelTransfer(0, 1, [0x0A]))
    assert byte[4] == "0A"


def test_a_protocol_trigger_looks_for_words_in_each_channel():
    from pyscopegui.core.triggers import PROTOCOL, Condition, item_matches, parse_data

    assert parse_data("7FF XXX 800", 8) == [0x7FF, None, 0x800]
    assert parse_data("7FF") is None, "wider than a byte, where a byte is looked for"
    muxed = ParallelTransfer(0, 1, [0x7FF, 0x123, 0x800], [0, 1, 0])
    wanted = Condition(kind=PROTOCOL, match_data="7FF 800")
    assert item_matches("parallel", muxed, wanted), "A's, one after the other"
    assert not item_matches("parallel", muxed, Condition(kind=PROTOCOL, match_data="7FF 123"))


# --- its words drawn as channels ----------------------------------------------------------------
def ad9238_samples(a, b, per_half=4):
    """Both channels on twelve lines, a word each half clock: A while it is low."""
    clock, words = [0] * 8, [0] * 8
    for word_a, word_b in zip(a, b, strict=True):
        clock += [0] * per_half + [1] * per_half
        words += [word_a] * per_half + [word_b] * per_half
    clock += [0] * per_half  # the fall that reads the last B
    words += [0] * per_half
    samples = {f"D{bit}": np.array([(w >> bit) & 1 for w in words], np.uint8) for bit in range(12)}
    samples["D12"] = np.array(clock, np.uint8)
    return samples


def test_an_adc_s_two_channels_are_drawn_in_volts_each_held_until_its_next_word():
    drawn = ParallelSetup(TWELVE, "D12", BOTH, mux="D12", coding=OFFSET, plot=True, full_scale=2.0)
    a, b = [0x800, 0xC00, 0x400], [0x000, 0xFFF, 0x800]
    samples = ad9238_samples(a, b)
    held = logic_capture(*TWELVE, "D12")
    held.set_decodings([drawn])
    assert {"bus:parallel:D0:A", "bus:parallel:D0:B"} <= set(held.records)
    channel = held.records["bus:parallel:D0:A"].channel
    assert (channel.name, channel.unit, channel.full_scale) == ("Parallel D0 A", "V", 1.0)
    count = len(samples["D0"])
    for first in range(0, count, 5):
        held.add(Block(first, RATE, {k: v[first : first + 5] for k, v in samples.items()}))
    volts_a = held.records["bus:parallel:D0:A"].values(0, count)
    volts_b = held.records["bus:parallel:D0:B"].values(0, count)
    # Offset binary across 2 V: 0x800 is nought, 0xC00 half a volt, 0x400 minus half.
    assert np.isnan(volts_a[0]), "nothing before the first word"
    assert sorted(set(np.round(volts_a[~np.isnan(volts_a)], 3))) == [-0.5, 0.0, 0.5]
    assert np.round(volts_b[-1], 3) == 0.0 and np.round(np.nanmin(volts_b), 3) == -1.0
    # A's word 0x800 is read at the clock's first rise, and held until its next.
    rise = int(np.flatnonzero(samples["D12"])[0])
    assert volts_a[rise] == 0.0 and np.isnan(volts_a[rise - 1])


def test_drawn_channels_come_and_go_with_the_bus_and_what_is_held_is_drawn_at_once():
    words = list(range(16))
    samples = encode(words, 4, per_word=6)
    held = logic_capture("D0", "D1", "D2", "D3", "CLK")
    lines = {k: samples[k].astype(np.uint8) for k in ("D0", "D1", "D2", "D3", "CLK")}
    held.add(Block(0, RATE, lines))
    four = ("D0", "D1", "D2", "D3")
    held.set_decodings([ParallelSetup(four, "CLK", plot=True)])
    numbers = held.records["bus:parallel:D0"].values(0, len(samples["D0"]))
    assert np.nanmax(numbers) == 15 and held.records["bus:parallel:D0"].channel.unit == ""
    held.set_decodings([ParallelSetup(four, "CLK")])
    assert not any(key.startswith("bus:") for key in held.records), "gone with the tick"


def test_the_dialog_draws_the_words_across_a_full_scale(app):
    from pyscopegui.ui.decode_dialog import ParallelDialog

    dialog = ParallelDialog(MSO, "D0")
    assert not dialog.full_scale.isEnabled()
    dialog.plot.setChecked(True)
    dialog.full_scale.setValue(2.0)
    assert dialog.full_scale.isEnabled() and dialog.setup().full_scale == 2.0
    assert ParallelDialog(MSO, "D0", dialog.setup()).setup() == dialog.setup()


def test_the_demo_s_counter_is_a_bus_drawn_on_the_plot(window):
    window.set_mode("auto")
    window.instrument._started -= 0.3
    window.instrument._tick()
    four = ("D0", "D1", "D2", "D3")
    window.scope.add_decoding(window.unit, ParallelSetup(four, plot=True))
    window.instrument._started -= 0.2
    window.instrument._tick()
    window.set_mode("stop")
    window.scope.redraw()
    assert any(name == "Parallel D0" for _key, name in window.scope.shown_channels())
    record = window.unit.capture.records["bus:parallel:D0"]
    counted = record.values(record.first, record.total)
    assert set(np.unique(counted[~np.isnan(counted)])) == set(range(16)), "it counts"
    items = window.unit.capture.decodings[0].items
    assert items and all(t.ok for t in items)


def test_a_maths_channel_can_be_worked_out_from_an_adc_s_two_channels():
    from pyscopegui.core.maths import Maths

    drawn = ParallelSetup(TWELVE, "D12", BOTH, mux="D12", coding=OFFSET, plot=True, full_scale=2.0)
    samples = ad9238_samples([0xC00, 0xC00], [0x800, 0x400])
    held = logic_capture(*TWELVE, "D12")
    held.set_decodings([drawn])
    difference = Maths("bus:parallel:D0:A", "-", "bus:parallel:D0:B")
    held.set_maths([difference])
    held.add(Block(0, RATE, samples))
    worked = held.records[difference.key].values(0, len(samples["D0"]))
    assert np.round(np.nanmax(worked), 3) == 1.0, "A's half a volt less B's minus half"
