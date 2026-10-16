# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""CAN frames read off a channel: made up here as bits, turned into samples, and read back."""

import numpy as np
import pytest

from pyscopegui.core import can_decode
from pyscopegui.core.can_decode import CanDecoder, crc15, encode, guess_bitrate, levels

RNG = np.random.default_rng(1)


def samples_of(frames, per_bit, idle=15, jitter=0.0):
    """Recessive (True) and dominant (False) samples for these frames, as a bus
    carries them: idle before, between and after. ``jitter`` moves each edge
    by up to that share of a bit."""
    bits = [1] * idle
    starts = []
    for frame in frames:
        starts.append(len(bits))
        bits += encode(**frame) + [1] * idle
    edges = np.arange(len(bits) + 1) * float(per_bit)
    if jitter:
        edges[1:-1] += RNG.uniform(-jitter, jitter, len(bits) - 1) * per_bit
    count = int(edges[-1])
    out = np.ones(count, dtype=bool)
    for number, bit in enumerate(bits):
        out[round(edges[number]) : round(edges[number + 1])] = bool(bit)
    return out, [round(s * per_bit) for s in starts]


def read(recessive, per_bit=10.0, pieces=1):
    decoder = CanDecoder(per_bit * 500_000, 500_000)
    found = []
    cuts = (
        sorted(RNG.choice(np.arange(1, len(recessive)), pieces - 1, replace=False))
        if pieces > 1
        else []
    )
    for start, stop in zip([0, *cuts], [*cuts, len(recessive)], strict=True):
        found += decoder.feed(recessive[start:stop], start)
    return found + decoder.flush()


FRAMES = [
    {"identifier": 0x123, "data": bytes([0xDE, 0xAD, 0xBE, 0xEF])},
    {"identifier": 0x000, "data": bytes(8)},  # stuffing all the way through
    {"identifier": 0x7FF, "data": bytes([0xFF] * 8)},
    {"identifier": 0x456, "data": b""},
    {"identifier": 0x1ABCDEF, "data": bytes([1, 2, 3]), "extended": True},
    {"identifier": 0x00000000, "data": bytes(8), "extended": True},
    {"identifier": 0x1FFFFFFF, "data": bytes([0xFF] * 8), "extended": True},
    {"identifier": 0x321, "remote": True, "dlc": 4},
    {"identifier": 0x18FEF100, "remote": True, "dlc": 8, "extended": True},
]


def same(found, frames):
    assert [f.error for f in found] == [""] * len(frames)
    for got, sent in zip(found, frames, strict=True):
        assert got.identifier == sent["identifier"]
        assert got.extended == sent.get("extended", False)
        assert got.remote == sent.get("remote", False)
        assert got.dlc == sent.get("dlc", len(sent.get("data", b"")))
        assert got.data == (b"" if sent.get("remote") else sent["data"])
        assert got.acked


# --- the CRC and the bits ---------------------------------------------------------------------
def test_a_message_with_its_crc_after_it_leaves_nothing_over():
    for frame in FRAMES:
        bits = [int(b) for b in RNG.integers(0, 2, 40)]
        crc = crc15(bits)
        assert crc15(bits + [(crc >> (14 - i)) & 1 for i in range(15)]) == 0, frame


def test_no_six_bits_the_same_from_the_start_of_frame_to_the_crc():
    for frame in FRAMES:
        bits = encode(**frame)[:-10]  # up to the CRC delimiter
        runs = np.diff(np.flatnonzero(np.diff([2, *bits, 2])))
        assert runs.max() <= 5, frame


# --- frames read back ------------------------------------------------------------------------
def test_every_kind_of_frame_is_read_back():
    recessive, starts = samples_of(FRAMES, per_bit=10)
    found = read(recessive)
    same(found, FRAMES)
    assert [f.start for f in found] == starts, "each from its start of frame"


@pytest.mark.parametrize("per_bit", [4, 6.4, 8, 13.2, 50])
def test_any_number_of_samples_a_bit_with_the_edges_a_little_off(per_bit):
    recessive, _starts = samples_of(FRAMES, per_bit, jitter=0.12)
    same(read(recessive, per_bit), FRAMES)


@pytest.mark.parametrize("pieces", [2, 7, 60])
def test_fed_a_block_at_a_time_is_the_same_as_all_at_once(pieces):
    recessive, _starts = samples_of(FRAMES, per_bit=9.5, jitter=0.1)
    same(read(recessive, 9.5, pieces), FRAMES)


def test_a_frame_at_the_very_end_is_read_when_more_comes_or_the_capture_ends():
    recessive, _starts = samples_of(FRAMES[:1], per_bit=10, idle=12)
    end = len(recessive) - 12 * 10  # just after its end of frame
    decoder = CanDecoder(5_000_000, 500_000)
    found = decoder.feed(recessive[:end], 0)
    same(found, FRAMES[:1])  # read as soon as its last bit is there


def test_a_frame_nobody_acknowledged_is_read_and_says_so():
    recessive, _starts = samples_of([{"identifier": 0x10, "data": b"\x01", "acked": False}], 10)
    (found,) = read(recessive)
    assert found.ok and not found.acked


def test_a_wrong_bit_is_a_wrong_crc_or_a_stuff_error():
    bits = encode(0x123, bytes([1, 2, 3, 4]))
    for flipped in (20, 30, 40, 50):
        broken = list(bits)
        broken[flipped] ^= 1
        recessive = np.repeat(np.array([1] * 15 + broken + [1] * 15, dtype=bool), 10)
        (found,) = read(recessive)
        assert found.error in ("the CRC is wrong", "a stuff error: six bits the same") or (
            "dominant" in found.error
        ), flipped


def test_an_error_frame_part_way_through_is_a_stuff_error_and_the_next_frame_is_read():
    bits = [1] * 15 + encode(0x123, b"\x55\x55")[:25] + [0] * 6 + [1] * 8 + [1] * 15
    bits += encode(0x124, b"\x01") + [1] * 15
    recessive = np.repeat(np.array(bits, dtype=bool), 10)
    first, second = read(recessive)
    assert first.error.startswith("a stuff error")
    assert second.ok and second.identifier == 0x124


def test_a_can_fd_frame_is_said_to_be_one():
    bits = encode(0x123, b"\x01")
    bits[14] = 1  # FDF: recessive where classic CAN has r0 dominant
    recessive = np.repeat(np.array([1] * 15 + bits + [1] * 15, dtype=bool), 10)
    found = read(recessive)
    assert found and "CAN FD" in found[0].error


def test_joining_part_way_through_a_frame_waits_for_the_bus_to_be_idle():
    recessive, starts = samples_of(FRAMES[:2], per_bit=10)
    found = read(recessive[starts[0] + 100 :])
    same(found, FRAMES[1:2])


def test_lost_samples_abandon_the_frame_being_read():
    recessive, starts = samples_of(FRAMES[:2], per_bit=10)
    decoder = CanDecoder(5_000_000, 500_000)
    cut = starts[0] + 300
    found = decoder.feed(recessive[:cut], 0)
    found += decoder.feed(recessive[cut + 50 :], cut + 50)  # 50 samples never came
    found += decoder.flush()
    assert found[0].error == "samples were lost"
    same(found[1:], FRAMES[1:2])


def test_a_capture_that_ends_part_way_through_a_frame_says_so():
    recessive, starts = samples_of(FRAMES[:1], per_bit=10)
    decoder = CanDecoder(5_000_000, 500_000)
    decoder.feed(recessive[: starts[0] + 400], 0)
    (found,) = decoder.flush()
    assert found.error == "the capture ends part way through it"


def test_too_few_samples_a_bit_is_refused():
    with pytest.raises(ValueError, match="too few"):
        CanDecoder(1_000_000, 500_000)


# --- from voltages ---------------------------------------------------------------------------
def test_can_h_with_noise_and_slow_edges_is_read_with_hysteresis():
    recessive, _starts = samples_of(FRAMES, per_bit=16)
    volts = np.where(recessive, 2.5, 3.5).astype(np.float32)
    volts = np.convolve(volts, np.ones(5) / 5, mode="same")  # edges a few samples long
    volts += RNG.normal(0, 0.08, len(volts)).astype(np.float32)
    # CAN_H is higher when dominant: the levels are the other way up.
    found = read(~levels(volts, 2.8, 3.2, start=False), 16)
    same(found, FRAMES)


def test_can_h_less_can_l_is_read_and_a_gap_keeps_the_level():
    recessive, _starts = samples_of(FRAMES, per_bit=10)
    volts = np.where(recessive, 0.0, 2.0).astype(np.float32)
    volts[5] = np.nan
    assert ~levels(volts, 0.5, 0.9, start=False)[5] == recessive[4]
    same(read(~levels(volts, 0.5, 0.9, start=False), 10), FRAMES)


# --- the bit rate ----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("bitrate", "rate"), [(125_000, 1e6), (500_000, 1e7), (1_000_000, 31.25e6)]
)
def test_the_bit_rate_is_found_from_the_shortest_pulses(bitrate, rate):
    recessive, _starts = samples_of(FRAMES, rate / bitrate, jitter=0.08)
    assert guess_bitrate(recessive, rate) == bitrate


def test_too_few_edges_have_no_bit_rate():
    assert guess_bitrate(np.ones(1000, dtype=bool), 1e6) is None
    assert can_decode.BITRATES[0] == 10_000
