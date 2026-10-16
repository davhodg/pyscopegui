# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""UART, SPI and I2C read off logic levels: made up here as samples, and read back."""

import numpy as np
import pytest

from pyscopegui.core import i2c_decode, spi_decode, uart_decode
from pyscopegui.core.i2c_decode import I2cDecoder
from pyscopegui.core.spi_decode import SpiDecoder
from pyscopegui.core.uart_decode import EVEN, NONE, ODD, UartDecoder

RNG = np.random.default_rng(7)


def in_blocks(length, pieces):
    """Where to cut a run of samples into this many blocks, at random."""
    if pieces <= 1:
        return [(0, length)]
    cuts = sorted(RNG.choice(np.arange(1, length), pieces - 1, replace=False).tolist())
    return list(zip([0, *cuts], [*cuts, length], strict=True))


# --- UART --------------------------------------------------------------------------------------
def line_of(bits, per_bit, idle=3):
    """A line's samples for these bits -- a bit time each -- with rest before and after."""
    levels = [1.0] * idle + list(bits) + [1.0] * idle
    edges = np.arange(len(levels) + 1) * float(per_bit)
    out = np.ones(int(edges[-1]), dtype=bool)
    for number, level in enumerate(levels):
        out[round(edges[number]) : round(edges[number + 1])] = bool(level)
    return out


def uart(line, per_bit, pieces=1, **how):
    decoder = UartDecoder(1_000_000, 1_000_000 / per_bit, **how)
    found = []
    for start, stop in in_blocks(len(line), pieces):
        found += decoder.feed(line[start:stop], start)
    return found


@pytest.mark.parametrize(
    "how",
    [
        {},
        {"bits": 7, "parity": EVEN},
        {"bits": 8, "parity": ODD, "stop_bits": 2},
        {"bits": 9},
        {"msb_first": True},
        {"bits": 5, "stop_bits": 1.5},
    ],
)
@pytest.mark.parametrize("per_bit", [8, 10.4, 16])
def test_every_byte_comes_back_however_the_line_is_set(how, per_bit):
    bits = how.get("bits", 8)
    data = bytes(range(0, 256, 3)) if bits >= 8 else bytes(v & ((1 << bits) - 1) for v in range(64))
    sent = uart_decode.encode(data, **how)
    found = uart(line_of(sent, per_bit), per_bit, **how)
    assert [c.error for c in found] == [""] * len(data)
    assert bytes(c.value & 0xFF for c in found) == bytes(v & 0xFF for v in data)


def test_a_nine_bit_character_keeps_its_ninth_bit():
    sent = [0, *[1] * 9, 1]  # 0x1FF, least significant first
    (found,) = uart(line_of(sent, 10), 10, bits=9)
    assert found.value == 0x1FF


@pytest.mark.parametrize("pieces", [3, 40])
def test_a_line_fed_a_block_at_a_time_is_the_same_as_all_at_once(pieces):
    data = bytes(RNG.integers(0, 256, 60).tolist())
    line = line_of(uart_decode.encode(data), 9.6)
    assert bytes(c.value for c in uart(line, 9.6, pieces)) == data


def test_a_baud_rate_a_little_off_is_still_read():
    data = b"Hello, world"
    # Sent two percent slow: each character is timed from its own start bit.
    found = uart(line_of(uart_decode.encode(data), 10.2), 10)
    assert bytes(c.value for c in found) == data and all(c.ok for c in found)


def test_rs232_at_the_connector_is_the_other_way_up():
    line = ~line_of(uart_decode.encode(b"OK"), 10)
    assert bytes(c.value for c in uart(line, 10, inverted=True)) == b"OK"


def test_a_low_stop_bit_a_wrong_parity_and_a_break_are_said():
    framing = [0, 1, 0, 1, 0, 1, 0, 1, 0, 0]  # stop bit low
    (bad,) = uart(line_of(framing + [1] * 3, 10), 10)
    assert bad.error.startswith("a framing error")
    parity = uart_decode.encode(b"\x01", parity=EVEN)
    parity[9] ^= 1
    (wrong,) = uart(line_of(parity, 10), 10, parity=EVEN)
    assert wrong.error == "the parity is wrong"
    (held_low,) = uart(line_of([0] * 10 + [1] * 3, 10), 10)
    assert held_low.error.startswith("a break")


def test_a_glitch_is_not_a_start_bit():
    line = line_of(uart_decode.encode(b"A"), 10, idle=6)
    line[5:7] = False  # two samples low, long before the character
    assert [c.value for c in uart(line, 10)] == [ord("A")]


def test_too_few_samples_a_bit_is_refused():
    with pytest.raises(ValueError, match="too few"):
        UartDecoder(100_000, 50_000)
    assert NONE == "none"


# --- SPI ---------------------------------------------------------------------------------------
def spi(samples, pieces=1, cs=True, **how):
    decoder = SpiDecoder(**how)
    found = []
    for start, stop in in_blocks(len(samples["sclk"]), pieces):
        found += decoder.feed(
            start,
            samples["sclk"][start:stop],
            mosi=samples["mosi"][start:stop],
            miso=samples["miso"][start:stop] if "miso" in samples else None,
            cs=samples["cs"][start:stop] if cs else None,
        )
    return found + decoder.flush()


@pytest.mark.parametrize("mode", [0, 1, 2, 3])
@pytest.mark.parametrize(("bits", "msb_first"), [(8, True), (8, False), (16, True), (12, True)])
def test_every_word_comes_back_in_every_mode(mode, bits, msb_first):
    words = [int(w) for w in RNG.integers(0, 1 << bits, 20)]
    samples = spi_decode.encode(words, bits, mode, msb_first, per_bit=6)
    samples["miso"] = ~samples["mosi"]  # the device sends back each bit the other way
    (transfer,) = spi(samples, mode=mode, bits=bits, msb_first=msb_first)
    assert transfer.ok and transfer.mosi == words
    assert transfer.miso == [w ^ ((1 << bits) - 1) for w in words]


@pytest.mark.parametrize("pieces", [5, 50])
def test_transfers_fed_a_block_at_a_time_are_read_whole(pieces):
    one = spi_decode.encode([1, 2, 3], per_bit=4)
    two = spi_decode.encode([0xAA, 0x55], per_bit=4)
    samples = {key: np.concatenate((one[key], two[key])) for key in one}
    transfers = spi(samples, pieces)
    assert [t.mosi for t in transfers] == [[1, 2, 3], [0xAA, 0x55]]
    assert transfers[0].end <= transfers[1].start


def test_without_a_chip_select_a_rest_of_the_clock_ends_a_transfer():
    one = spi_decode.encode([0x12, 0x34], per_bit=4)
    rest = {key: np.full(200, value[0]) for key, value in one.items()}
    two = spi_decode.encode([0x56], per_bit=4)
    samples = {key: np.concatenate((one[key], rest[key], two[key])) for key in one}
    assert [t.mosi for t in spi(samples, cs=False)] == [[0x12, 0x34], [0x56]]


def test_a_chip_select_released_part_way_through_a_word_says_so():
    samples = spi_decode.encode([0xFF, 0x0F], per_bit=4)
    cut = len(samples["cs"]) // 2 + 6
    samples["cs"][cut:] = True  # released early
    (transfer,) = spi(samples)
    assert transfer.error.startswith("a word cut short") and transfer.mosi == [0xFF]


def test_no_such_spi_is_refused():
    with pytest.raises(ValueError):
        SpiDecoder(mode=4)


# --- I2C ---------------------------------------------------------------------------------------
def i2c(samples, pieces=1):
    decoder = I2cDecoder()
    found = []
    for start, stop in in_blocks(len(samples["scl"]), pieces):
        found += decoder.feed(start, samples["scl"][start:stop], samples["sda"][start:stop])
    return found + decoder.flush()


def joined(*parts):
    return {key: np.concatenate([part[key] for part in parts]) for key in parts[0]}


def test_a_write_is_its_address_and_its_bytes_each_acknowledged():
    (transfer,) = i2c(i2c_decode.encode(0x50, [0x00, 0x10, 0xFF]))
    assert transfer.ok and transfer.ended == "stop"
    assert (transfer.address, transfer.read, transfer.data) == (0x50, False, [0x00, 0x10, 0xFF])
    assert transfer.acks == [True] * 4 and not transfer.nacked


def test_a_read_ends_with_the_controller_not_acknowledging_the_last_byte():
    sent = i2c_decode.encode(0x68, [0x12, 0x34], read=True, acks=[True, True, False])
    (transfer,) = i2c(sent)
    assert transfer.read and transfer.data == [0x12, 0x34] and transfer.acks[-1] is False


def test_nobody_at_the_address_is_a_nack():
    (transfer,) = i2c(i2c_decode.encode(0x3C, [], acks=[False]))
    assert transfer.ok and transfer.nacked and transfer.address == 0x3C


def test_a_repeated_start_ends_one_transfer_and_begins_the_next():
    write = i2c_decode.encode(0x50, [0x20], end="restart")
    read = i2c_decode.encode(0x50, [0xAB], read=True, acks=[True, False])
    first, second = i2c(joined(write, read))
    assert first.ok and first.ended == "restart" and first.data == [0x20]
    assert second.ok and second.read and second.data == [0xAB]


def test_a_ten_bit_address_is_read_from_its_two_bytes():
    high, low = 0x2A5 >> 8, 0x2A5 & 0xFF
    sent = i2c_decode.encode(0b11110000 >> 1 | high, [low, 0x99])
    (transfer,) = i2c(sent)
    assert transfer.ten_bit and transfer.address == 0x2A5 and transfer.data == [0x99]


@pytest.mark.parametrize("pieces", [4, 60])
def test_a_bus_fed_a_block_at_a_time_is_the_same_as_all_at_once(pieces):
    parts = [i2c_decode.encode(0x40 + n, [n, n + 1, n + 2]) for n in range(5)]
    transfers = i2c(joined(*parts), pieces)
    assert [(t.address, t.data) for t in transfers] == [
        (0x40 + n, [n, n + 1, n + 2]) for n in range(5)
    ]
    assert all(t.ok for t in transfers)


def test_a_stop_part_way_through_a_byte_says_so():
    sent = i2c_decode.encode(0x50, [0xFF])
    # Cut the bus off part way through the data byte, and STOP there.
    stop = i2c_decode.encode(0x50, [])
    middle = len(sent["scl"]) // 2
    tail = {"scl": stop["scl"][-24:], "sda": stop["sda"][-24:]}
    sent = {key: np.concatenate((sent[key][:middle], tail[key])) for key in sent}
    (transfer,) = i2c(sent)
    assert "part way through a byte" in transfer.error
