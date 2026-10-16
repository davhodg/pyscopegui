# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The kinds of trigger from the window: the toolbar's Type and Either, and the details dialog."""

from itertools import pairwise

import pytest

from pyscopegui.core.triggers import (
    BETWEEN,
    EDGE,
    EITHER,
    KINDS,
    LONGER,
    PATTERN,
    PULSE,
    WINDOW,
    Condition,
)
from pyscopegui.ui.trigger_dialog import TriggerDialog, parse_time, time_text


def choose(box, data):
    box.setCurrentIndex(box.findData(data))
    box.activated.emit(box.currentIndex())


@pytest.fixture
def sourced(window):
    """The demo, triggered on D0."""
    window.set_mode("auto")
    window.set_mode("stop")
    bar = window.trigger_bar
    choose(bar.source, "D0")
    return window


# --- times -------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("typed", "seconds"),
    [("1 ms", 1e-3), ("500us", 500e-6), ("500 µs", 500e-6), ("2e-6", 2e-6), ("0.5 s", 0.5)],
)
def test_a_time_is_typed_as_it_is_said(typed, seconds):
    assert parse_time(typed) == pytest.approx(seconds)


def test_what_is_not_a_time_is_none():
    for typed in ("fast", "1 hour", "", "-1 ms"):
        assert parse_time(typed) is None, typed
    assert time_text(0.0015) == "1.5 ms" and time_text(2e-9) == "2 ns"


# --- the dialog --------------------------------------------------------------------------------
def test_a_pulse_s_details_and_what_is_wrong_with_them(app):
    dialog = TriggerDialog(Condition(PULSE), [("D0", "D0")])
    dialog.compare.setCurrentIndex(dialog.compare.findData(BETWEEN))
    dialog.shortest.setText("2 ms")
    dialog.longest.setText("1 ms")
    dialog.accept()
    assert "longer than the first" in dialog.problem.text() and not dialog.result()
    dialog.longest.setText("5 ms")
    dialog.holdoff.setText("10 ms")
    dialog.accept()
    condition = dialog.condition()
    assert (condition.compare, condition.shortest, condition.longest, condition.holdoff) == (
        BETWEEN,
        pytest.approx(2e-3),
        pytest.approx(5e-3),
        pytest.approx(10e-3),
    )


def test_a_pattern_is_each_channels_level_and_needs_one_at_least(app):
    channels = [("D0", "D0"), ("D1", "D1"), ("D2", "D2")]
    dialog = TriggerDialog(Condition(PATTERN), channels)
    dialog.accept()
    assert "one channel at least" in dialog.problem.text()
    dialog.pattern["D0"].setCurrentIndex(dialog.pattern["D0"].findData("1"))
    dialog.pattern["D2"].setCurrentIndex(dialog.pattern["D2"].findData("0"))
    dialog.held.setText("1 us")
    assert dialog.condition().pattern == (("D0", 1), ("D2", 0))
    assert dialog.condition().held == pytest.approx(1e-6)


def test_a_window_asks_its_upper_level(app):
    dialog = TriggerDialog(Condition(WINDOW, upper=1.0), [], unit="A")
    assert dialog.upper.suffix() == " A"
    dialog.upper.setValue(2.5)
    assert dialog.condition().upper == 2.5


# --- the toolbar --------------------------------------------------------------------------------
def test_the_toolbar_offers_every_kind_and_either_edge(sourced):
    bar = sourced.trigger_bar
    assert [bar.kind.itemData(i) for i in range(bar.kind.count())] == list(KINDS)
    assert [bar.edge.itemData(i) for i in range(bar.edge.count())] == ["rising", "falling", EITHER]
    choose(bar.edge, EITHER)
    assert sourced.acquisition.condition.edge == EITHER
    assert bar.said.text().strip() == "either edge"


def test_a_kind_chosen_asks_its_details_and_is_kept(sourced, monkeypatch):
    window = sourced
    monkeypatch.setattr(TriggerDialog, "exec", lambda self: TriggerDialog.Accepted)
    choose(window.trigger_bar.kind, PULSE)
    condition = window.acquisition.condition
    assert condition.kind == PULSE and condition.compare == LONGER
    assert window.trigger_bar.said.text().strip() == "high pulse > 1 ms"
    assert window.ctx.settings.get("trigger.demo.condition") == condition.as_saved()
    assert not window.trigger_bar.edge.isEnabled(), "an edge is only for the edge kind"


def test_kept_with_the_workspace_and_the_trigger_the_next_time(sourced, monkeypatch):
    from pyscopegui.ui.main_window import MainWindow

    monkeypatch.setattr(TriggerDialog, "exec", lambda self: TriggerDialog.Accepted)
    choose(sourced.trigger_bar.kind, WINDOW)
    again = MainWindow()
    try:
        again.set_mode("auto")
        again.set_mode("stop")
        assert again.session.units["demo"].acquisition.condition.kind == WINDOW
        assert again.trigger_bar.kind.currentData() == WINDOW
    finally:
        again.close()
        again.deleteLater()


def offered(bar):
    return [
        bar.kind.itemData(row)
        for row in range(bar.kind.count())
        if bar.kind.model().item(row).isEnabled()
    ]


def test_an_instrument_that_triggers_itself_does_an_edge_up_or_down(sourced, monkeypatch):
    window = sourced
    monkeypatch.setattr(type(window.instrument), "sweeps", property(lambda _self: True))
    bar = window.trigger_bar
    bar.show_usable()
    assert offered(bar) == [EDGE] and not bar.details.isEnabled()
    either = bar.edge.model().item(bar.edge.findData(EITHER))
    assert not either.isEnabled() and "triggers itself" in bar.kind.toolTip()


def test_one_that_can_do_more_itself_offers_it(sourced, monkeypatch):
    window = sourced
    kind = type(window.instrument)
    monkeypatch.setattr(kind, "sweeps", property(lambda _self: True))

    def triggers_itself(_self, condition, _source):
        return condition.kind in (EDGE, WINDOW) and not condition.holdoff

    monkeypatch.setattr(kind, "triggers_itself", triggers_itself)
    bar = window.trigger_bar
    bar.show_usable()
    assert offered(bar) == [EDGE, WINDOW]
    assert bar.edge.model().item(bar.edge.findData(EITHER)).isEnabled()
    assert not bar.details.isEnabled(), "an edge has only a holdoff, which it has not"
    window.acquisition.set_trigger(condition=Condition(WINDOW, upper=1.0))
    bar.show_usable()
    assert bar.details.isEnabled()
    dialog = TriggerDialog(
        Condition(WINDOW), [], "V", doable=lambda c: window.instrument.triggers_itself(c, "A")
    )
    assert not dialog.holdoff.isEnabled() and dialog.holdoff.text() == "0"
    dialog.holdoff.setText("1 ms")
    assert dialog.condition().holdoff == 0.001
    dialog.accept()
    assert "cannot wait for that itself" in dialog.problem.text()


def test_a_window_s_upper_level_is_drawn_too(window, monkeypatch):
    window.set_mode("auto")
    window.set_mode("stop")
    window.acquisition.set_trigger(source="A", level=-1.0, condition=Condition(WINDOW, upper=1.5))
    window.scope._show_trigger()
    upper = window.scope._upper_lines[0]
    assert upper.isVisible() and upper.value() == 1.5
    window.acquisition.set_trigger(condition=Condition(EDGE))
    window.scope._show_trigger()
    assert not upper.isVisible()


def test_a_pattern_trigger_holds_the_plot_on_it_as_the_demo_runs(window):
    window.acquisition.set_trigger(
        condition=Condition(PATTERN, pattern=(("D0", 1), ("D1", 1), ("D2", 1)))
    )
    window.set_mode("normal")
    window.instrument._started -= 0.05
    window.instrument._tick()
    found = window.acquisition._triggers.tolist()
    # The counter at 7, 15, 23 ...: a count every 50 samples, so every 400 from 350.
    assert found[:3] == [350, 750, 1150]
    window.set_mode("stop")


# --- protocol triggers ---------------------------------------------------------------------------
def test_an_id_with_any_digits_and_data_with_any_bytes():
    from pyscopegui.core.triggers import parse_data, parse_id

    assert parse_id("18FEXX00") == (0x18FE0000, 0xFFFF00FF)
    assert parse_id("0x123") == (0x123, 0xFFF) and parse_id("") == (0, 0)
    assert parse_id("12G") is None
    assert parse_data("12 xx 0x34") == [0x12, None, 0x34]
    assert parse_data('"OK"') == [ord("O"), ord("K")] and parse_data("") == []
    assert parse_data("123") is None


def test_what_matches_on_each_protocol():
    from pyscopegui.core.can_decode import Frame
    from pyscopegui.core.decoding import Message
    from pyscopegui.core.i2c_decode import Transfer as I2c
    from pyscopegui.core.spi_decode import Transfer as Spi
    from pyscopegui.core.triggers import (
        DATA,
        NACK,
        PROBLEM,
        PROTOCOL,
        READ,
        REMOTE,
        item_matches,
    )

    def wants(**how):
        return Condition(PROTOCOL, bus="x", **how)

    frame = Frame(0, identifier=0x18FEF100, extended=True, dlc=3, data=b"\x01\x02\x03")
    assert item_matches("can", frame, wants(match_id="18FEXX00"))
    assert not item_matches("can", frame, wants(match_id="18FEXX01"))
    assert item_matches("can", frame, wants(match_data="02 03"))
    assert not item_matches("can", frame, wants(match_data="03 02"))
    assert item_matches("can", frame, wants(match_type=DATA))
    assert not item_matches("can", frame, wants(match_type=REMOTE))
    assert not item_matches("can", frame, wants(which=PROBLEM))
    read = I2c(0, 1, 0x50, read=True, data=[7], acks=[True, False])
    assert item_matches("i2c", read, wants(match_id="50", match_type=READ))
    assert not item_matches("i2c", read, wants(match_type=NACK))
    assert item_matches("i2c", I2c(0, 1, 0x3C, acks=[False]), wants(match_type=NACK))
    assert item_matches("uart", Message(0, 1, list(b"Error: 42")), wants(match_data='"Error"'))
    assert item_matches("spi", Spi(0, 1, [0x9F], [0xEF, 0x40]), wants(match_data="EF 40"))


def acquisition_on_the_demo_can(condition):
    from pyscopegui.backends import demo
    from pyscopegui.backends.base import Block
    from pyscopegui.core.acquire import AUTO, Acquisition
    from pyscopegui.core.capture import Capture
    from pyscopegui.core.decoding import LOGIC, CanSetup

    capture = Capture(history_s=2.0)
    capture.set_channels(demo.CHANNELS, demo.RATE)
    capture.set_decodings([CanSetup("CAN", LOGIC, demo.CAN_BITRATE)])
    acquisition = Acquisition(capture)
    acquisition.set_trigger(condition=condition)
    acquisition.set_mode(AUTO)
    step = 3000
    for first in range(0, len(demo.CAN_BUS), step):
        block = Block(first, demo.RATE, demo.samples(first, step))
        capture.add(block)
        acquisition.examine(block)
    return capture.decodings[0], acquisition._triggers.tolist()


def test_a_protocol_trigger_is_at_the_start_of_each_frame_that_matches():
    from pyscopegui.core.triggers import PROTOCOL

    decoding, found = acquisition_on_the_demo_can(
        Condition(PROTOCOL, bus="can:CAN", match_id="0C8")
    )
    wanted = [f.start for f in decoding.frames if f.identifier == 0x0C8 and f.ok]
    assert found == wanted and len(found) > 10
    # The engine speed's counter, its third byte, at 5.
    _decoding, counted = acquisition_on_the_demo_can(
        Condition(PROTOCOL, bus="can:CAN", match_id="0C8", match_data="XX XX 05")
    )
    assert len(counted) == 1


def test_a_protocol_trigger_with_a_holdoff_takes_fewer():
    from pyscopegui.core.triggers import PROTOCOL

    _decoding, every = acquisition_on_the_demo_can(Condition(PROTOCOL, bus="can:CAN"))
    _decoding, fewer = acquisition_on_the_demo_can(Condition(PROTOCOL, bus="can:CAN", holdoff=0.1))
    assert 0 < len(fewer) < len(every)
    assert all(b - a >= 0.1 * 100_000 for a, b in pairwise(fewer))


def test_the_details_need_a_bus_and_hex(app):
    from pyscopegui.core.triggers import PROTOCOL
    from pyscopegui.ui.trigger_dialog import NO_BUS

    none = TriggerDialog(Condition(PROTOCOL), [])
    assert any(label.text() == NO_BUS for label in none.findChildren(type(none.problem)))
    dialog = TriggerDialog(
        Condition(PROTOCOL), [], buses=[("can:CAN", "CAN on CAN", "can"), ("i2c:D0", "I2C", "i2c")]
    )
    assert dialog.match_type.itemData(2) == "remote"
    dialog.bus.setCurrentIndex(1)
    assert dialog.match_type.itemData(3) == "nack", "an I2C bus's types"
    dialog.bus.setCurrentIndex(0)
    dialog.match_id.setText("12G")
    dialog.accept()
    assert "not hex" in dialog.problem.text()
    dialog.match_id.setText("0C8")
    dialog.match_data.setText("XX 05")
    dialog.accept()
    condition = dialog.condition()
    assert (condition.bus, condition.match_id, condition.match_data) == ("can:CAN", "0C8", "XX 05")


def test_a_protocol_trigger_from_the_toolbar_on_the_demo_s_bus(window, monkeypatch):
    from pyscopegui.backends import demo
    from pyscopegui.core.decoding import LOGIC, CanSetup
    from pyscopegui.core.triggers import PROTOCOL

    window.set_mode("auto")
    window.set_mode("stop")
    window.scope.add_decoding(window.unit, CanSetup("CAN", LOGIC, demo.CAN_BITRATE))
    monkeypatch.setattr(TriggerDialog, "exec", lambda self: TriggerDialog.Accepted)
    choose(window.trigger_bar.kind, PROTOCOL)
    condition = window.acquisition.condition
    assert condition.kind == PROTOCOL and condition.bus == "can:CAN"
    assert window.trigger_bar.said.text().strip() == "CAN"
    assert not window.trigger_bar.source.isEnabled() and not window.trigger_bar.level.isEnabled()
    window.set_mode("normal")
    window.instrument._started -= 0.1
    window.instrument._tick()
    assert len(window.acquisition._triggers) > 0
    window.scope._show_trigger()
    assert not window.scope._level_lines[0].isVisible(), "a protocol trigger has no level"
    window.set_mode("stop")
