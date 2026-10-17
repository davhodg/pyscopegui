# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Maths channels: worked out from two of one instrument's, and a channel like any other."""

import numpy as np
import pytest

from pyscopegui.backends.base import ANALOG, DIGITAL, Block, Channel
from pyscopegui.core.capture import Capture
from pyscopegui.core.maths import MOST_AVERAGED, ONE, Maths


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
    assert minus.name == "Math: A \u2212 B" and minus.unit == "V" and minus.full_scale == 4.0
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
    assert window.scope._names[key] == "Math: (A: sine) \u2212 (B: ramp)"
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
    assert name == "Math: (A: sine) \u2212 (A: sine)"
    assert names["measure"](name)["peak_to_peak"] == 0.0
    times, values = names["data"]("maths:A-A")
    assert len(times) == len(values) > 0


def test_the_console_says_what_it_cannot_make(held):
    from pyscopegui.ui.scripting import ScriptError

    with pytest.raises(ScriptError, match="No such operation"):
        held.console.namespace["maths"]("A", "%", "B")
    with pytest.raises(ScriptError, match="No analog channel 'D0'"):
        held.console.namespace["maths"]("A", "+", "D0")


def test_one_channel_alone_is_offered_only_what_is_done_to_one(window, monkeypatch):
    from pyscopegui.backends import demo
    from pyscopegui.ui.maths_dialog import MathsDialog

    window.open_instrument()
    monkeypatch.setattr(demo, "CHANNELS", [demo.CHANNELS[0]])
    unit = window.unit
    unit.capture.set_channels([demo.CHANNELS[0]], demo.RATE)
    shown = []
    monkeypatch.setattr(MathsDialog, "exec", lambda dialog: shown.append(dialog) or 0)
    window.scope.channel_list.maths_asked.emit("demo:A")
    dialog = shown[0]
    offered = [
        dialog.op.itemData(i)
        for i in range(dialog.op.count())
        if dialog.op.itemData(i) and dialog.op.model().item(i).isEnabled()
    ]
    assert offered == list(ONE) and dialog.op.currentData() == "neg"
    logic = Channel("D0", "D0", DIGITAL)
    unit.capture.set_channels([logic], demo.RATE)
    window.scope.redraw()
    window.scope.channel_list.maths_asked.emit(f"demo:{logic.key}")
    assert "needs an analog channel" in window.log.toPlainText()


def test_a_right_click_on_no_channel_offers_a_maths_channel(window, monkeypatch):
    from PySide6.QtWidgets import QMenu

    from pyscopegui.ui import scope_view
    from pyscopegui.ui.scope_view import MathsDialog

    window.set_mode("auto")
    window.set_mode("stop")
    window.scope.redraw()
    listed = window.scope.channel_list
    assert listed.makers == [("demo:A", "Demo")], "its first analog channel, to start from"
    offered = []

    class Menu(QMenu):
        """Says what it offers rather than waiting for a click."""

        def exec(self, *_where):
            offered.extend(self.actions())

    monkeypatch.setattr(scope_view, "QMenu", Menu)
    started = []
    monkeypatch.setattr(
        MathsDialog, "exec", lambda dialog: started.append(dialog.a.currentData()) or 0
    )
    listed._menu(listed.viewport().rect().bottomRight())  # below every row
    assert [action.text() for action in offered] == ["Maths channel..."]
    offered[0].trigger()
    assert started == ["A"]
    offered.clear()
    listed.makers = [("demo:A", "Demo"), ("rigol:CH1", "Rigol")]
    listed._menu(listed.viewport().rect().bottomRight())
    assert [action.text() for action in offered] == [
        "Maths channel, Demo...",
        "Maths channel, Rigol...",
    ]
    offered.clear()
    listed.makers = []
    listed._menu(listed.viewport().rect().bottomRight())
    assert not offered[0].isEnabled(), "says why there is none"


# --- what is done to one channel ------------------------------------------------------------------
@pytest.mark.parametrize(
    ("maths", "expected"),
    [
        (Maths("A", "neg"), [-4, 9]),
        (Maths("A", "abs"), [4, 9]),
        (Maths("A", "sq"), [16, 81]),
        (Maths("A", "scale", k=2, c=-1), [7, -19]),
    ],
)
def test_one_channel_sample_by_sample(maths, expected):
    held = capture()
    held.set_maths([maths])
    held.add(block(0, [4, -9], [0, 0]))
    assert held.records[maths.key].view().tolist() == pytest.approx(expected)


def test_the_root_of_less_than_nought_is_no_number():
    held = capture()
    held.set_maths([Maths("A", "sqrt")])
    held.add(block(0, [4, -1], [0, 0]))
    out = held.records["maths:sqrt(A)"].view()
    assert out[0] == 2.0 and np.isnan(out[1])


def test_a_rate_of_change_and_an_integral_carry_on_from_one_block_to_the_next():
    held = capture()
    held.set_maths([Maths("A", "ddt"), Maths("A", "int")])
    held.add(block(0, [0, 1, 3], [0, 0, 0]))
    held.add(block(3, [6, 6], [0, 0]))
    # A thousand samples a second.
    slope = held.records["maths:ddt(A)"].view()
    assert np.isnan(slope[0]), "nothing before the first"
    assert slope[1:].tolist() == pytest.approx([1000, 2000, 3000, 0])
    total = held.records["maths:int(A)"].view()
    assert total.tolist() == pytest.approx([0, 0.001, 0.004, 0.010, 0.016])


def test_they_start_afresh_after_a_gap():
    held = capture()
    held.set_maths([Maths("A", "ddt"), Maths("A", "int")])
    held.add(block(0, [1, 1], [0, 0]))
    held.add(block(5, [7, 7], [0, 0]))  # three samples went missing between
    assert np.isnan(held.records["maths:ddt(A)"].view()[-2]), "not a slope across the gap"
    assert held.records["maths:int(A)"].view()[-2] == pytest.approx(0.007)


def test_an_average_is_over_the_time_before_each_sample_lost_ones_left_out():
    held = capture()
    held.set_maths([Maths("A", "avg", span=3e-3)])  # three samples
    held.add(block(0, [3, 6, 9], [0, 0, 0]))
    held.add(block(3, [np.nan, 12], [0, 0]))
    out = held.records["maths:avg(A,0.003)"].view()
    assert out.tolist() == pytest.approx([3, 4.5, 6, 7.5, 10.5])


def test_an_average_is_over_no_more_than_a_million_samples():
    from pyscopegui.core.maths import Worker

    worker = Worker(Maths("A", "avg", span=10.0), 1e6)
    worker.take(np.ones(10, dtype=np.float32))
    assert len(worker._tail) < MOST_AVERAGED


def test_a_sweep_is_worked_out_by_itself():
    held = capture()
    held.set_maths([Maths("A", "int")])
    data = {"A": np.ones(2, np.float32), "B": np.zeros(2, np.float32)}
    sweep = Block(0, 1000.0, data, sweep=True)
    held.add(sweep)
    held.add(sweep)
    assert held.records["maths:int(A)"].view()[-1] == pytest.approx(0.002), "not 0.004"


def test_names_and_units_of_what_is_done_to_one():
    held = capture()
    made = [
        Maths("A", "ddt"),
        Maths("A", "int"),
        Maths("A", "scale", k=10, unit="A"),
        Maths("A", "avg", span=2e-3),
    ]
    held.set_maths(made)
    slope, total, amps, mean = (held.records[m.key].channel for m in made)
    assert slope.name == "Math: dA/dt" and slope.unit == "V/s"
    assert total.name == "Math: \u222bA dt" and total.unit == "V\u00b7s"
    reach = held.records["A"].channel.full_scale
    assert amps.name == "Math: 10\u00d7A" and amps.unit == "A" and amps.full_scale == 10 * reach
    assert mean.name == "Math: avg A, 2 ms" and mean.unit == "V"


def test_one_of_one_channel_is_saved_with_its_settings_and_comes_back():
    for made in (Maths("CH1", "scale", k=2.5, c=-1, unit="A"), Maths("CH1", "avg", span=0.02)):
        assert Maths.from_saved(made.as_saved()) == made
    assert Maths.from_saved({"a": "CH1", "op": "ddt"}) == Maths("CH1", "ddt")
    for wrong in ({"a": "CH1", "op": "nope"}, {"op": "abs"}, {"a": "CH1", "op": "avg", "span": 0}):
        assert Maths.from_saved(wrong) is None


def test_the_dialog_asks_what_a_scale_and_an_average_need(app):
    from pyscopegui.ui.maths_dialog import MathsDialog

    dialog = MathsDialog([("A", "A"), ("B", "B")], "A")
    assert dialog.b.isEnabled() and dialog.scale_rows.isHidden()
    dialog.op.setCurrentIndex(dialog.op.findData("scale"))
    assert not dialog.b.isEnabled() and not dialog.scale_rows.isHidden()
    dialog.k.setValue(10)
    dialog.unit.setText("A")
    assert dialog.maths() == Maths("A", "scale", k=10, unit="A")
    dialog.op.setCurrentIndex(dialog.op.findData("avg"))
    assert not dialog.span_rows.isHidden()
    dialog.span.setText("20 us")
    made = dialog.maths()
    assert made.op == "avg" and made.span == pytest.approx(20e-6)
    dialog.span.setText("soon")
    dialog.accept()
    assert "not a time" in dialog.problem.text() and not dialog.result()


def test_the_console_makes_one_of_one_channel(held):
    names = held.console.namespace
    name = names["maths"]("A", "scale", k=2, unit="A")
    assert name == "Math: 2\u00d7(A: sine)"
    from pyscopegui.ui.scripting import ScriptError

    with pytest.raises(ScriptError, match="takes two channels"):
        names["maths"]("A", "-")
