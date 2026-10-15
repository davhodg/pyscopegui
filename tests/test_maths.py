# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Maths channels: worked out from two of one instrument's, and a channel like any other."""

import numpy as np
import pytest

from pyscopegui.backends.base import ANALOG, DIGITAL, Block, Channel
from pyscopegui.core.capture import Capture
from pyscopegui.core.maths import Maths


def capture(**units):
    made = Capture()
    made.set_channels(
        [
            Channel("A", "A", unit=units.get("a", "V"), full_scale=1.0),
            Channel("B", "B", unit=units.get("b", "V"), full_scale=2.0),
            Channel("D0", "D0", DIGITAL, ""),
        ],
        1000.0,
        100,
    )
    return made


def block(first, a, b):
    return Block(
        first,
        1000.0,
        {
            "A": np.array(a, dtype=np.float32),
            "B": np.array(b, dtype=np.float32),
            "D0": np.zeros(len(a), dtype=np.uint8),
        },
    )


@pytest.mark.parametrize(
    ("op", "expected"), [("+", [4, 6]), ("-", [-2, -2]), ("*", [3, 8]), ("/", [1 / 3, 0.5])]
)
def test_each_operation_sample_by_sample(op, expected):
    held = capture()
    held.set_maths([Maths("A", op, "B")])
    held.add(block(0, [1, 2], [3, 4]))
    assert held.records[f"maths:A{op}B"].view().tolist() == pytest.approx(expected)


def test_what_is_held_already_is_worked_out_at_once_and_what_comes_after_too():
    held = capture()
    held.add(block(0, [5, 6], [1, 1]))
    held.set_maths([Maths("A", "-", "B")])
    record = held.records["maths:A-B"]
    assert record.view().tolist() == [4, 5] and (record.first, record.total) == (0, 2)
    held.add(block(2, [9], [2]))
    assert record.view().tolist() == [4, 5, 7] and record.total == 3


def test_a_gap_in_either_is_a_gap_and_dividing_by_nought_is_one_too():
    held = capture()
    held.set_maths([Maths("A", "/", "B")])
    held.add(block(0, [1, np.nan, 1], [0, 1, 2]))
    assert np.isnan(held.records["maths:A/B"].view()[:2]).all()
    held.add(block(5, [4], [2]))  # three samples went missing between
    record = held.records["maths:A/B"]
    assert record.total == 6 and record.view()[-1] == 2.0


def test_what_it_is_named_and_measured_in():
    held = capture()
    held.set_maths([Maths("A", "-", "B"), Maths("A", "*", "B"), Maths("A", "/", "B")])
    minus, times, over = (held.records[k].channel for k in ("maths:A-B", "maths:A*B", "maths:A/B"))
    assert minus.name == "A \u2212 B" and minus.unit == "V" and minus.full_scale == 4.0
    assert times.unit == "V\u00b2" and over.unit == ""
    assert minus.kind == ANALOG and minus.detail == "maths"
    other = capture(b="A")
    other.set_maths([Maths("A", "*", "B"), Maths("A", "+", "B")])
    assert other.records["maths:A*B"].channel.unit == "V\u00b7A"
    assert other.records["maths:A+B"].channel.unit == "", "volts and amps do not add"


def test_a_logic_channel_or_one_not_there_makes_none():
    held = capture()
    held.set_maths([Maths("A", "+", "D0"), Maths("A", "+", "nowhere")])
    assert not [key for key in held.records if key.startswith("maths:")]


def test_it_is_there_again_when_the_run_starts_again():
    held = capture()
    held.set_maths([Maths("A", "+", "B")])
    held.set_channels([Channel("A", "A"), Channel("B", "B")], 1000.0, 10)
    assert "maths:A+B" in held.records


def test_removed_it_is_gone_and_the_same_one_twice_is_one():
    held = capture()
    held.set_maths([Maths("A", "+", "B"), Maths("A", "+", "B")])
    assert [m.key for m in held.maths] == ["maths:A+B"]
    held.set_maths([])
    assert "maths:A+B" not in held.records


def test_a_saved_one_comes_back_and_nonsense_does_not():
    assert Maths.from_saved(["CH1", "-", "CH2"]) == Maths("CH1", "-", "CH2")
    for wrong in (["CH1", "%", "CH2"], ["CH1", "-"], "CH1-CH2", [1, "-", 2]):
        assert Maths.from_saved(wrong) is None


# --- in the window ------------------------------------------------------------------------------
def feed(window, seconds=0.2):
    window.instrument._started -= seconds
    window.instrument._tick()


@pytest.fixture
def held(window):
    window.set_mode("auto")
    feed(window)
    window.set_mode("stop")
    window.scope.redraw()
    return window


def test_made_from_the_channel_list_it_is_on_the_plot_and_kept(held, monkeypatch):
    from pyscopegui.ui.maths_dialog import MathsDialog

    window = held
    monkeypatch.setattr(MathsDialog, "exec", lambda self: MathsDialog.Accepted)
    window.scope.channel_list.maths_asked.emit("demo:A")
    key = "demo:maths:A-B"
    assert key in window.scope._curves
    assert window.scope._names[key] == "A: sine \u2212 B: ramp"
    assert window.ctx.settings.get("maths.demo") == [["A", "-", "B"]]
    unit = window.session.units["demo"]
    a, b, d = (unit.capture.records[k].view() for k in ("A", "B", "maths:A-B"))
    assert np.allclose(d, a - b)


def test_removed_from_the_channel_list(held):
    window = held
    window.scope.add_maths(window.unit, Maths("A", "+", "B"))
    window.scope.channel_list.maths_removed.emit("demo:maths:A+B")
    assert "demo:maths:A+B" not in window.scope._curves
    assert window.ctx.settings.get("maths.demo") == []


def test_kept_with_the_workspace_and_there_the_next_time(held):
    from pyscopegui.ui.main_window import MainWindow

    held.scope.add_maths(held.unit, Maths("A", "*", "B"))
    again = MainWindow()
    try:
        again.set_mode("auto")
        again.set_mode("stop")
        assert "maths:A*B" in again.session.units["demo"].capture.records
    finally:
        again.close()
        again.deleteLater()


def test_measured_and_read_by_the_console(held):
    names = held.console.namespace
    name = names["maths"]("A", "-", "A")
    assert name == "A: sine \u2212 A: sine"
    assert names["measure"](name)["peak_to_peak"] == 0.0
    times, values = names["data"]("maths:A-A")
    assert len(times) == len(values) > 0


def test_the_console_says_what_it_cannot_make(held):
    from pyscopegui.ui.scripting import ScriptError

    with pytest.raises(ScriptError, match="No such operation"):
        held.console.namespace["maths"]("A", "%", "B")
    with pytest.raises(ScriptError, match="No analog channel 'D0'"):
        held.console.namespace["maths"]("A", "+", "D0")


def test_one_channel_alone_cannot_be_given_one(window, monkeypatch):
    from pyscopegui.backends import demo

    window.open_instrument()
    monkeypatch.setattr(demo, "CHANNELS", [demo.CHANNELS[0]])
    unit = window.unit
    unit.capture.set_channels([demo.CHANNELS[0]], demo.RATE)
    window.scope.channel_list.maths_asked.emit("demo:A")
    assert "needs two analog channels" in window.log.toPlainText()
