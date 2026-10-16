# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""A channel decoded as a CAN bus, kept up to date as blocks arrive at its instrument."""

import numpy as np
import pytest

from pyscopegui.backends.base import DIGITAL, Block, Channel
from pyscopegui.core.can_decode import encode
from pyscopegui.core.capture import Capture
from pyscopegui.core.decoding import (
    CAN_H,
    CAN_L,
    DIFFERENTIAL,
    LOGIC,
    CanDecoding,
    CanSetup,
    from_saved,
    recessive,
)
from pyscopegui.core.maths import Maths

RATE = 1_000_000.0
BITRATE = 100_000  # ten samples a bit
FRAMES = [(0x100 + n, bytes([n, n + 1])) for n in range(6)]


def bus_bits():
    bits = [1] * 20
    for identifier, data in FRAMES:
        bits += encode(identifier, data) + [1] * 20
    return np.repeat(np.array(bits, dtype=bool), int(RATE / BITRATE))


def capture(seconds=1.0):
    held = Capture(history_s=seconds)
    held.set_channels(
        [
            Channel("RX", "RX", DIGITAL, ""),
            Channel("H", "CAN_H", full_scale=5.0),
            Channel("L", "CAN_L", full_scale=5.0),
        ],
        RATE,
    )
    return held


def block(first, recessive_part, sweep=False):
    return Block(
        first,
        RATE,
        {
            "RX": recessive_part.astype(np.uint8),
            "H": np.where(recessive_part, 2.5, 3.5).astype(np.float32),
            "L": np.where(recessive_part, 2.5, 1.5).astype(np.float32),
        },
        sweep=sweep,
    )


def ids(decoding):
    return [frame.identifier for frame in decoding.frames if frame.ok]


# --- how one is set up --------------------------------------------------------------------------
def test_a_setup_is_saved_and_comes_back_and_nonsense_does_not():
    setup = CanSetup("maths:H-L", DIFFERENTIAL, 500_000, 0.8)
    assert from_saved(setup.as_saved()) == setup
    for wrong in ({"channel": "H", "source": "spi"}, {"source": CAN_H}, "H", {"channel": 3}):
        assert from_saved(wrong) is None
    assert CanSetup("H", CAN_H).level == 3.0 and CanSetup("H", CAN_H, threshold=3.2).level == 3.2


@pytest.mark.parametrize(
    ("source", "recessive_volts", "dominant_volts"),
    [(CAN_H, 2.5, 3.5), (CAN_L, 2.5, 1.5), (DIFFERENTIAL, 0.0, 2.0), (LOGIC, 1, 0)],
)
def test_each_source_is_recessive_and_dominant_the_right_way_up(
    source, recessive_volts, dominant_volts
):
    samples = np.array([recessive_volts, dominant_volts, recessive_volts], dtype=np.float32)
    start = source in (LOGIC, CAN_L)
    levels_now, _high = recessive(CanSetup("X", source), samples, start)
    assert levels_now.tolist() == [True, False, True]


# --- as blocks arrive ------------------------------------------------------------------------
@pytest.mark.parametrize(("channel", "source"), [("RX", LOGIC), ("H", CAN_H), ("L", CAN_L)])
def test_a_stream_is_decoded_as_it_arrives_a_block_at_a_time(channel, source):
    held = capture()
    held.set_decodings([CanSetup(channel, source, BITRATE)])
    bits = bus_bits()
    for first in range(0, len(bits), 777):
        held.add(block(first, bits[first : first + 777]))
    assert ids(held.decodings[0]) == [identifier for identifier, _data in FRAMES]
    assert held.decodings[0].frames[0].data == FRAMES[0][1]


def test_a_maths_channel_of_can_h_less_can_l_is_decoded():
    held = capture()
    held.set_maths([Maths("H", "-", "L")])
    held.set_decodings([CanSetup("maths:H-L", DIFFERENTIAL, BITRATE)])
    held.add(block(0, bus_bits()))
    assert len(ids(held.decodings[0])) == len(FRAMES)


def test_the_bit_rate_is_found_when_it_is_not_said():
    held = capture()
    held.set_decodings([CanSetup("RX", LOGIC)])
    held.add(block(0, bus_bits()))
    decoding = held.decodings[0]
    assert decoding.bitrate == BITRATE and len(ids(decoding)) == len(FRAMES)


def test_what_is_held_is_decoded_as_soon_as_it_is_asked_for():
    held = capture()
    held.add(block(0, bus_bits()))
    held.set_decodings([CanSetup("RX", LOGIC, BITRATE)])
    assert len(ids(held.decodings[0])) == len(FRAMES)


def test_a_decoding_already_there_is_left_as_it_is_and_one_taken_away_goes():
    held = capture()
    setup = CanSetup("RX", LOGIC, BITRATE)
    held.set_decodings([setup])
    first = held.decodings[0]
    held.set_decodings([setup, CanSetup("H", CAN_H, BITRATE)])
    assert held.decodings[0] is first and len(held.decodings) == 2
    held.set_decodings([])
    assert held.decodings == []


def test_a_frame_whose_samples_have_gone_from_the_history_goes_too():
    bits = bus_bits()
    held = capture(seconds=len(bits) / RATE / 2)  # room for half of it
    held.set_decodings([CanSetup("RX", LOGIC, BITRATE)])
    for first in range(0, len(bits), 1000):
        held.add(block(first, bits[first : first + 1000]))
    decoding = held.decodings[0]
    assert 0 < len(decoding.frames) < len(FRAMES)
    assert decoding.frames[0].start >= held.records["RX"].first


def test_each_sweep_replaces_what_was_found_in_the_last():
    held = capture()
    held.set_decodings([CanSetup("RX", LOGIC, BITRATE)])
    bits = bus_bits()
    held.add(block(0, bits, sweep=True))
    held.add(block(0, bits, sweep=True))
    assert len(ids(held.decodings[0])) == len(FRAMES), "not twice over"


def test_a_new_run_or_the_history_cleared_starts_with_nothing_found():
    held = capture()
    held.set_decodings([CanSetup("RX", LOGIC, BITRATE)])
    held.add(block(0, bus_bits()))
    held.clear()
    assert not held.decodings[0].frames
    held.add(block(0, bus_bits()))
    held.set_channels([Channel("RX", "RX", DIGITAL, "")], RATE)
    assert not held.decodings[0].frames


def test_too_few_samples_a_bit_says_so_and_decodes_nothing():
    decoding = CanDecoding(CanSetup("RX", LOGIC, 500_000))
    assert decoding.take(np.ones(100, dtype=np.uint8), 0, RATE) == []
    assert "too few" in decoding.problem


# --- the other protocols ---------------------------------------------------------------------
def logic_capture(*keys, rate=1_000_000.0):
    held = Capture(history_s=1.0)
    held.set_channels([Channel(k, k, DIGITAL, "") for k in keys], rate)
    return held


def test_a_serial_line_is_read_a_burst_at_a_time():
    from pyscopegui.core import uart_decode
    from pyscopegui.core.decoding import UartSetup

    def line(text):
        bits = [1] * 30 + uart_decode.encode(text) + [1] * 30
        return np.repeat(np.array(bits, dtype=np.uint8), 10)  # 100 kbaud at 1 MS/s

    held = logic_capture("TX")
    held.set_decodings([UartSetup("TX", 100_000)])
    samples = np.concatenate((line(b"Hello"), np.ones(2000, np.uint8), line(b"world")))
    for first in range(0, len(samples), 333):
        held.add(Block(first, RATE, {"TX": samples[first : first + 333]}))
    messages = list(held.decodings[0].items)
    assert [bytes(m.values) for m in messages] == [b"Hello", b"world"]
    assert all(m.ok for m in messages) and messages[0].end < messages[1].start


def test_an_analog_line_is_read_at_the_logic_threshold():
    from pyscopegui.core import uart_decode
    from pyscopegui.core.decoding import UartSetup

    bits = [1] * 30 + uart_decode.encode(b"OK") + [1] * 60
    volts = np.repeat(np.array(bits, dtype=np.float32) * 3.3, 10)
    held = Capture(history_s=1.0)
    held.set_channels([Channel("CH1", "CH1", full_scale=5.0)], RATE)
    held.set_decodings([UartSetup("CH1", 100_000)])
    held.add(Block(0, RATE, {"CH1": volts}))
    assert [bytes(m.values) for m in held.decodings[0].items] == [b"OK"]


def test_an_spi_bus_is_read_from_its_lines_together_and_from_what_is_held():
    from pyscopegui.core import spi_decode
    from pyscopegui.core.decoding import SpiSetup

    lines = spi_decode.encode([0xDE, 0xAD, 0xBE, 0xEF], per_bit=6)
    held = logic_capture("SCK", "MOSI", "CS")
    held.add(
        Block(
            0,
            RATE,
            {
                "SCK": lines["sclk"].astype(np.uint8),
                "MOSI": lines["mosi"].astype(np.uint8),
                "CS": lines["cs"].astype(np.uint8),
            },
        )
    )
    held.set_decodings([SpiSetup("SCK", mosi="MOSI", cs="CS")])
    (transfer,) = held.decodings[0].items
    assert transfer.ok and transfer.mosi == [0xDE, 0xAD, 0xBE, 0xEF]


def test_an_i2c_bus_is_read_from_scl_and_sda():
    from pyscopegui.core import i2c_decode
    from pyscopegui.core.decoding import I2cSetup

    lines = i2c_decode.encode(0x50, [0x12, 0x34])
    held = logic_capture("SCL", "SDA")
    held.set_decodings([I2cSetup("SCL", "SDA")])
    for first in range(0, len(lines["scl"]), 50):
        held.add(
            Block(
                first,
                RATE,
                {
                    "SCL": lines["scl"][first : first + 50].astype(np.uint8),
                    "SDA": lines["sda"][first : first + 50].astype(np.uint8),
                },
            )
        )
    (transfer,) = held.decodings[0].items
    assert (transfer.address, transfer.data, transfer.ok) == (0x50, [0x12, 0x34], True)


def test_a_bus_with_a_line_the_instrument_has_not_got_decodes_nothing():
    from pyscopegui.core.decoding import I2cSetup

    held = logic_capture("SCL")
    held.set_decodings([I2cSetup("SCL", "SDA")])
    held.add(Block(0, RATE, {"SCL": np.ones(100, np.uint8)}))
    assert not held.decodings[0].items


def test_every_protocols_setup_is_saved_and_comes_back():
    from pyscopegui.core.decoding import EVEN, I2cSetup, SpiSetup, UartSetup

    for setup in (
        UartSetup("TX", 9600, 7, EVEN, 2, True, True, 1.65),
        SpiSetup("SCK", "MOSI", "MISO", "CS", 3, 16, False, False, 2.5),
        I2cSetup("SCL", "SDA"),
        CanSetup("RX", LOGIC, 250_000, None, "239.74.163.10"),
    ):
        assert from_saved(setup.as_saved()) == setup, setup
    for nonsense in (
        {"protocol": "uart", "line": "TX", "baud": 0},
        {"protocol": "uart", "line": "TX", "baud": 9600, "parity": "mark"},
        {"protocol": "spi", "sclk": "SCK"},  # no data line
        {"protocol": "spi", "sclk": "SCK", "mosi": "M", "mode": 5},
        {"protocol": "i2c", "scl": "X", "sda": "X"},
        {"protocol": "lin", "line": "L"},
    ):
        assert from_saved(nonsense) is None, nonsense
