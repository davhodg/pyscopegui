# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""pycangui's signals as an instrument: its messages read, the values held and
read out at a steady rate, and the instrument listening on its group (#1)."""

import json
import math
import socket
import time

import numpy as np
import pytest

from pyscopegui import backends
from pyscopegui.core.signal_receive import GROUP, PORT, Held, Receiver


def description(gen=1, run="r1", signals=None, part=1, parts=1):
    signals = (
        [
            {"n": 1, "group": "DBC Engine", "name": "Speed", "unit": "rpm", "min": 0, "max": 8000},
            {"n": 2, "group": "DBC Engine", "name": "State", "names": {"0": "Off", "1": "Run"}},
        ]
        if signals is None
        else signals
    )
    return json.dumps(
        {
            "v": 1,
            "k": "description",
            "run": run,
            "gen": gen,
            "clock": [time.monotonic(), time.time()],
            "signals": signals,
            "part": part,
            "parts": parts,
        }
    ).encode()


def values(frames, gen=1, run="r1"):
    return json.dumps({"v": 1, "k": "values", "run": run, "gen": gen, "frames": frames}).encode()


# --- reading the messages -------------------------------------------------------------------
def test_a_description_makes_the_signals_and_saying_it_again_changes_nothing():
    receiver = Receiver()
    assert receiver.feed(description())
    speed, state = receiver.signals
    assert speed.key == "DBC Engine/Speed" and speed.unit == "rpm"
    assert (speed.low, speed.high) == (0, 8000)
    assert state.names == {0: "Off", 1: "Run"} and state.low is None
    assert not receiver.feed(description()), "said again every second"


def test_a_description_in_parts_is_taken_once_it_is_all_there():
    receiver = Receiver()
    one = [{"n": 1, "group": "G", "name": "A"}]
    two = [{"n": 2, "group": "G", "name": "B"}]
    assert not receiver.feed(description(signals=two, part=2, parts=2))
    assert receiver.signals == []
    assert receiver.feed(description(signals=one, part=1, parts=2))
    assert [s.name for s in receiver.signals] == ["A", "B"], "in pycangui's order"


def test_values_are_read_only_against_their_own_description():
    receiver = Receiver()
    receiver.feed(values([[1.0, [[1, 100]]]]))
    assert receiver.pending == {}, "before there is a description"
    receiver.feed(description())
    receiver.feed(values([[1.0, [[1, 100], [2, 1]]]]))
    receiver.feed(values([[2.0, [[1, 200]]]], gen=2))  # another description's numbers
    receiver.feed(values([[3.0, [[1, 300]]]], run="other"))  # another pycangui
    assert receiver.pending == {
        "DBC Engine/Speed": [(1.0, 100.0)],
        "DBC Engine/State": [(1.0, 1.0)],
    }
    assert receiver.passed_over == 3


def test_numbered_again_the_same_signals_are_the_same_channels():
    receiver = Receiver()
    receiver.feed(description())
    renumbered = [
        {"n": 7, "group": "DBC Engine", "name": "Speed", "unit": "rpm", "min": 0, "max": 8000},
        {"n": 8, "group": "DBC Engine", "name": "State", "names": {"0": "Off", "1": "Run"}},
    ]
    assert not receiver.feed(description(gen=2, signals=renumbered)), "nothing to start again"
    receiver.feed(values([[1.0, [[7, 1500]]]], gen=2))
    assert receiver.pending["DBC Engine/Speed"] == [(1.0, 1500.0)]
    assert receiver.feed(description(gen=3, signals=renumbered[:1])), "one fewer: a change"


@pytest.mark.parametrize(
    "datagram",
    [b"\x93\x01\x02", b"[]", json.dumps({"v": 2, "k": "values"}).encode(), b"{}"],
)
def test_anything_else_is_passed_over(datagram):
    receiver = Receiver()
    assert not receiver.feed(datagram)
    assert receiver.passed_over == 1 and receiver.signals == []


# --- read out at a steady rate --------------------------------------------------------------
def test_a_signal_is_a_step_at_each_value_and_nothing_before_its_first():
    held = Held()
    changes = [(0.0025, 5.0), (0.0055, 7.0)]
    out = held.sample(np.arange(8) / 1000, changes)
    assert math.isnan(out[0]) and math.isnan(out[2])
    assert out[3:6].tolist() == [5.0, 5.0, 5.0] and out[6:].tolist() == [7.0, 7.0]
    assert changes == []
    assert held.sample(np.arange(8, 10) / 1000, changes).tolist() == [7.0, 7.0], "held"


def test_a_value_for_later_waits_and_one_that_came_late_is_taken_up():
    held = Held()
    changes = [(0.020, 9.0), (0.001, 3.0)]  # out of order, and one beyond these samples
    out = held.sample(np.arange(5) / 1000, changes)
    assert out[1:].tolist() == [3.0] * 4
    assert changes == [(0.020, 9.0)], "for the samples that reach it"


# --- the instrument ---------------------------------------------------------------------------
def send(*datagrams):
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sender.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 0)
    sender.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    try:
        for datagram in datagrams:
            sender.sendto(datagram, (GROUP, PORT))
    finally:
        sender.close()


def until(app, done, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not done() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    return done()


@pytest.fixture
def signals(app):
    from pyscopegui.backends.pycangui import PycanguiSignals

    instrument = PycanguiSignals()
    instrument.open()
    if not instrument.is_open:
        pytest.skip("no multicast on this machine")
    yield instrument
    instrument.close()


def test_it_is_offered_under_add_instrument():
    assert "pycangui" in backends.names()
    assert backends.title("pycangui") == "pycangui signals"


def test_its_channels_are_what_pycangui_describes(signals, app):
    changed = []
    signals.signals_changed.connect(lambda: changed.append(1))
    send(description())
    assert until(app, lambda: changed)
    speed, state = signals.channels()
    assert (speed.key, speed.name, speed.unit, speed.detail) == (
        "DBC Engine/Speed",
        "Speed",
        "rpm",
        "DBC Engine",
    )
    assert (speed.middle, speed.full_scale) == (4000, 4000), "Range from the database's limits"
    assert state.full_scale == 0


def test_running_it_sends_each_signal_at_its_times(signals, app):
    send(description())
    assert until(app, lambda: signals.channels())
    blocks = []
    signals.block.connect(blocks.append)
    signals.start()
    now = time.monotonic()
    send(values([[round(now, 6), [[1, 1500], [2, 1]]]]))
    assert until(app, lambda: blocks and not np.isnan(blocks[-1].data["DBC Engine/Speed"][-1]))
    signals.stop()
    last = blocks[-1]
    assert last.data["DBC Engine/Speed"][-1] == 1500 and last.data["DBC Engine/State"][-1] == 1
    assert last.zero is not None, "on the computer's clock exactly"
    # The step is where the frame was: its sample's time is the frame's.
    speed = np.concatenate([b.data["DBC Engine/Speed"] for b in blocks])
    first = int(np.argmax(~np.isnan(speed)))
    assert abs(last.zero + first / signals.rate - now) <= 1.5 / signals.rate


def test_a_quiet_pycangui_is_said_once(signals, app, monkeypatch):
    from pyscopegui.backends import pycangui

    warned = []
    signals.warning.connect(warned.append)
    monkeypatch.setattr(pycangui, "QUIET_S", 0.0)
    signals._check_heard()
    signals._check_heard()
    assert len(warned) == 1 and "Send ticked signals" in warned[0]


# --- in the window ------------------------------------------------------------------------------
def test_its_signals_are_channels_on_the_plot_in_their_own_units(window, app):
    window.add_instrument("pycangui")
    window.open_instrument()
    if not window.unit.is_open:
        pytest.skip("no multicast on this machine")
    send(description())
    assert until(app, lambda: "pycangui:DBC Engine/Speed" in window.scope._names)
    window.set_mode("auto")
    send(values([[round(time.monotonic(), 6), [[1, 2500], [2, 1]]]]))
    record = window.capture.records["DBC Engine/Speed"]
    assert until(app, lambda: record.count and not np.isnan(record.values()[-1]))
    window.set_mode("stop")
    # Beside the demo's volts, a speed in rpm has an axis of its own.
    assert window.scope.axis_of("pycangui:DBC Engine/Speed") == 1
    assert window.scope.axis_of("demo:A") == 0
    # A signal ticked in pycangui: the run is started again with it.
    more = [
        {"n": 1, "group": "DBC Engine", "name": "Speed", "unit": "rpm"},
        {"n": 3, "group": "DBC Engine", "name": "Torque", "unit": "Nm"},
    ]
    send(description(gen=2, signals=more))
    assert until(app, lambda: "pycangui:DBC Engine/Torque" in window.scope._names)
