# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Decoded CAN frames sent on by UDP multicast, to pycangui and other python-can programs."""

import time

import pytest
from PySide6.QtCore import QSettings

from pyscopegui.backends import demo
from pyscopegui.core import sharing
from pyscopegui.core.can_decode import Frame
from pyscopegui.core.decoding import LOGIC, CanSetup
from pyscopegui.core.sharing import GROUP, LOCAL_NETWORK, LOCAL_ONLY, Sharer, is_group, message

#: Not pycangui's group: a test sends nothing a running pycangui would hear.
TEST_GROUP = "239.74.163.250"


class FakeBus:
    def __init__(self, group, hop_limit):
        self.group, self.hop_limit = group, hop_limit
        self.sent = []
        self.shut = False

    def send(self, msg):
        self.sent.append(msg)

    def shutdown(self):
        self.shut = True


@pytest.fixture
def buses(monkeypatch):
    opened = []

    def open_bus(group, hop_limit):
        bus = FakeBus(group, hop_limit)
        opened.append(bus)
        return bus

    monkeypatch.setattr(sharing, "open_bus", open_bus)
    return opened


def said_to(sharer_said):
    return lambda text, problem: sharer_said.append((text, problem))


GOOD = Frame(start=100, identifier=0x123, data=b"\x01\x02", dlc=2, acked=True)
BAD = Frame(start=200, identifier=0x124, error="the CRC is wrong")


# --- what is sent ------------------------------------------------------------------------------
def test_a_group_is_a_multicast_address():
    assert is_group(GROUP) and is_group(" 239.74.163.11 ") and is_group("ff15::1")
    assert not is_group("192.168.1.13") and not is_group("pycangui")


def test_a_frame_as_python_can_has_it():
    sent = message(GOOD, 12.5)
    assert (sent.arbitration_id, bytes(sent.data), sent.dlc, sent.timestamp) == (
        0x123,
        b"\x01\x02",
        2,
        12.5,
    )
    assert not sent.is_extended_id and not sent.is_remote_frame
    remote = message(Frame(0, identifier=0x18FEF100, extended=True, remote=True, dlc=8), 0.0)
    assert remote.is_extended_id and remote.is_remote_frame and remote.dlc == 8


def test_only_the_good_frames_go_and_one_bus_a_group_on_this_computer(buses):
    said = []
    sharer = Sharer(said_to(said))
    sharer.send(GROUP, [(GOOD, 1.0), (BAD, 2.0)])
    sharer.send(GROUP, [(GOOD, 3.0)])
    (bus,) = buses
    assert (bus.group, bus.hop_limit) == (GROUP, LOCAL_ONLY)
    assert [m.timestamp for m in bus.sent] == [1.0, 3.0] and sharer.sent[GROUP] == 2
    assert said == [(f"Sending decoded CAN frames to {GROUP}, on this computer.", False)]


def test_the_local_network_is_a_choice_and_the_bus_is_opened_again_for_it(buses):
    sharer = Sharer(lambda *_said: None)
    sharer.send(GROUP, [(GOOD, 1.0)])
    sharer.set_local_network(True)
    assert buses[0].shut
    sharer.send(GROUP, [(GOOD, 2.0)])
    assert buses[1].hop_limit == LOCAL_NETWORK


def test_a_group_that_cannot_be_opened_is_said_once_and_not_tried_again(monkeypatch):
    tries = []

    def refuse(group, hop_limit):
        tries.append(group)
        raise OSError("no multicast here")

    monkeypatch.setattr(sharing, "open_bus", refuse)
    said = []
    sharer = Sharer(said_to(said))
    for _ in range(3):
        sharer.send(GROUP, [(GOOD, 1.0)])
    assert tries == [GROUP] and len(said) == 1 and said[0][1]
    assert "could not be sent to 239.74.163.10: no multicast here" in said[0][0]
    sharer.close()  # and tried again once things change
    sharer.send(GROUP, [(GOOD, 1.0)])
    assert len(tries) == 2


def test_no_python_can_says_what_to_install(monkeypatch):
    def missing(group, hop_limit):
        raise ImportError("No module named 'can'")

    monkeypatch.setattr(sharing, "open_bus", missing)
    said = []
    Sharer(said_to(said)).send(GROUP, [(GOOD, 1.0)])
    assert "pip install python-can" in said[0][0]


def test_a_send_that_fails_is_said_and_the_bus_let_go(buses):
    said = []
    sharer = Sharer(said_to(said))
    sharer.send(GROUP, [(GOOD, 1.0)])

    def broken(_msg):
        raise OSError("network unreachable")

    buses[0].send = broken
    sharer.send(GROUP, [(GOOD, 2.0)])
    assert buses[0].shut and said[-1][1] and "network unreachable" in said[-1][0]


def test_a_setup_keeps_where_it_is_sent_and_nonsense_is_not_sent():
    setup = CanSetup("CAN", LOGIC, 10_000, None, GROUP)
    assert CanSetup.from_saved(setup.as_saved()) == setup
    saved = setup.as_saved() | {"share": "not an address"}
    assert CanSetup.from_saved(saved).share == ""
    assert CanSetup.from_saved({"channel": "CAN", "source": LOGIC}).share == "", "from before"


# --- from the window ---------------------------------------------------------------------------
def feed(window, seconds):
    window.instrument._started -= seconds
    window.instrument._tick()


def test_frames_decoded_as_the_demo_runs_are_sent_with_their_time(window, buses):
    window.set_mode("auto")
    window.scope.add_decoding(window.unit, CanSetup("CAN", LOGIC, demo.CAN_BITRATE, None, GROUP))
    feed(window, 0.3)
    window.set_mode("stop")
    (bus,) = buses
    assert bus.group == GROUP and bus.hop_limit == LOCAL_ONLY
    assert {m.arbitration_id for m in bus.sent} >= {0x0C8, 0x18FEF100}
    times = [m.timestamp for m in bus.sent]
    assert times == sorted(times) and abs(times[-1] - time.time()) < 5


def test_nothing_held_already_is_sent_when_a_channel_is_first_decoded(window, buses):
    window.set_mode("auto")
    feed(window, 0.3)
    window.set_mode("stop")
    window.scope.add_decoding(window.unit, CanSetup("CAN", LOGIC, demo.CAN_BITRATE, None, GROUP))
    assert window.unit.capture.decodings[0].frames, "decoded, all the same"
    assert not buses or not buses[0].sent


def test_a_channel_not_sent_on_sends_nothing(window, buses):
    window.set_mode("auto")
    window.scope.add_decoding(window.unit, CanSetup("CAN", LOGIC, demo.CAN_BITRATE))
    feed(window, 0.3)
    window.set_mode("stop")
    assert not buses


def test_the_local_network_is_under_tools_settings_and_kept_for_the_computer(window):
    action = window.udp_network_action
    assert not action.isChecked() and window.sharer.hop_limit == LOCAL_ONLY
    try:
        action.setChecked(True)
        assert window.sharer.hop_limit == LOCAL_NETWORK
        assert QSettings().value("udp/local_network", type=bool)
        assert "reach the local network" in window.log.toPlainText()
    finally:
        action.setChecked(False)
    assert QSettings().value("udp/local_network", type=bool) is False


# --- for real, through python-can ---------------------------------------------------------------
def test_a_frame_sent_is_heard_by_another_python_can_program():
    can = pytest.importorskip("can")
    try:
        listener = can.Bus(interface="udp_multicast", channel=TEST_GROUP, hop_limit=0)
    except Exception as exc:  # no multicast on this machine
        pytest.skip(f"no UDP multicast here: {exc}")
    sharer = Sharer(lambda *_said: None)
    try:
        sharer.send(TEST_GROUP, [(GOOD, 1234.5)])
        heard = listener.recv(timeout=2.0)
        if heard is None:
            pytest.skip("UDP multicast is not carried on this machine")
        assert heard.arbitration_id == 0x123 and bytes(heard.data) == b"\x01\x02"
    finally:
        sharer.close()
        listener.shutdown()
