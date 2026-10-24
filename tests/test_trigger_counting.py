# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The Nth time a trigger's condition is met, and a delay after it."""

from itertools import pairwise

import numpy as np
import pytest

from pyscopegui.backends import picoscope2000 as ps2000
from pyscopegui.backends import picoscope2000a as ps2000a
from pyscopegui.backends import rigol1000z as rigol
from pyscopegui.core.acquire import NORMAL
from pyscopegui.core.triggers import EDGE, PULSE, Condition, Taking
from pyscopegui.ui.trigger_dialog import TriggerDialog
from tests.test_acquire import acquisition, feed  # noqa: F401  acquisition is a fixture

RATE = 1000.0  # so a sample is a millisecond


def taken(condition, found, cuts=()):
    """The triggers among these times it is met, handed over cut into blocks."""
    taking = Taking(condition, RATE)
    edges = [0, *cuts, len(found)]
    out = []
    for start, stop in pairwise(edges):
        out += taking.take(np.array(found[start:stop], dtype=np.int64)).tolist()
    return out


@pytest.mark.parametrize("cuts", [(), (1,), (2, 5), (1, 2, 3, 4, 5, 6, 7)])
def test_every_nth_with_no_holdoff_counts_on_across_blocks(cuts):
    found = list(range(0, 100, 10))
    assert taken(Condition(nth=3), found, cuts) == [20, 50, 80]


@pytest.mark.parametrize("cuts", [(), (3,), (1, 4, 9, 11)])
def test_with_a_holdoff_each_burst_triggers_on_its_nth(cuts):
    # Three bursts of five edges, 1 ms apart, 50 ms between bursts.
    bursts = [start + edge for start in (0, 50, 100) for edge in range(5)]
    condition = Condition(nth=3, holdoff=0.010)
    assert taken(condition, bursts, cuts) == [2, 52, 102]


def test_a_holdoff_alone_is_as_it_was():
    rng = np.random.default_rng(1)
    found = np.sort(rng.choice(5000, 400, replace=False)).tolist()
    holdoff = 0.007
    last, wanted = -(10**18), []
    for at in found:
        if at - last >= round(holdoff * RATE):
            wanted.append(at)
            last = at
    assert taken(Condition(holdoff=holdoff), found, (17, 200, 201)) == wanted


def test_a_delay_puts_the_trigger_that_long_after():
    assert taken(Condition(delay=0.005), [10, 20]) == [15, 25]
    assert taken(Condition(nth=2, delay=0.001), [10, 20, 30, 40]) == [21, 41]


def test_what_is_saved_comes_back_and_nonsense_is_the_first_at_once():
    condition = Condition(PULSE, nth=4, delay=0.002)
    assert Condition.from_saved(condition.as_saved()) == condition
    for nth in (0, -3, 2.5, True, "3"):
        assert Condition.from_saved({"nth": nth}).nth == 1
    assert Condition.from_saved({"delay": -1.0}).delay == 0.0


def test_the_toolbar_says_it():
    assert Condition(EDGE, nth=3).summary() == "3rd time"
    assert Condition(EDGE, delay=0.001).summary() == "+1 ms"
    said = Condition(PULSE, shortest=0.001, nth=2, delay=0.0005).summary()
    assert said == "high pulse > 1 ms, 2nd time, +500 µs"
    assert [Condition(nth=n).summary() for n in (1, 11, 12, 13, 21, 102)] == [
        "",
        "11th time",
        "12th time",
        "13th time",
        "21st time",
        "102nd time",
    ]


# --- on what arrives -----------------------------------------------------------------------------
def square(periods, half=50):
    return np.tile(np.concatenate((-np.ones(half), np.ones(half))), periods)


def test_a_rising_edge_the_third_time_and_later(acquisition):  # noqa: F811
    acquisition.set_trigger(source="A", level=0.0, condition=Condition(EDGE, nth=3))
    acquisition.set_mode(NORMAL)
    feed(acquisition, square(4))  # rising edges at 50, 150, 250, 350
    feed(acquisition, square(4))  # and 450, 550, 650, 750
    assert acquisition._triggers.tolist() == [250, 550]
    acquisition.set_trigger(condition=Condition(EDGE, delay=0.020))
    feed(acquisition, square(2))  # 850, 950
    assert acquisition._triggers.tolist() == [870, 970]


# --- what no instrument does itself --------------------------------------------------------------
@pytest.mark.parametrize("counted", [Condition(nth=2), Condition(delay=1e-3)])
def test_no_scope_waits_for_the_nth_time_or_a_delay_itself(counted):
    assert not ps2000.triggers_itself(counted, "A", ["A"], "2204A")
    assert not ps2000a.triggers_itself(counted, "A", ["A"], [])
    assert not rigol.triggers_itself(counted, "CH1", ["CH1"])
    assert ps2000a.triggers_itself(Condition(), "A", ["A"], []), "and the first, at once, it does"


def test_the_details_ask_for_both_and_leave_out_what_the_instrument_cannot(app):
    dialog = TriggerDialog(Condition(EDGE), [])
    dialog.nth.setValue(5)
    dialog.delay.setText("2 ms")
    assert (dialog.condition().nth, dialog.condition().delay) == (5, 0.002)
    dialog.delay.setText("soon")
    dialog.accept()
    assert "not a time" in dialog.problem.text()
    by_itself = TriggerDialog(
        Condition(EDGE), [], doable=lambda c: rigol.triggers_itself(c, "CH1", ["CH1"])
    )
    assert not by_itself.nth.isEnabled() and not by_itself.delay.isEnabled()
    assert by_itself.holdoff.isEnabled(), "a Rigol has a holdoff of its own"
