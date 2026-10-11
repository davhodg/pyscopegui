# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Number boxes whose arrows go 1, 2, 5, 10, as a scope's knobs do."""

import pytest

from pyscopegui.backends.base import Setting
from pyscopegui.ui.instrument_view import InstrumentView
from pyscopegui.ui.spin import SequenceSpin, step_125


@pytest.mark.parametrize(
    ("value", "above", "below"),
    [
        (0.001, 0.002, 0.0005),
        (0.002, 0.005, 0.001),
        (0.005, 0.01, 0.002),
        (1.0, 2.0, 0.5),
        (50.0, 100.0, 20.0),
        (0.003, 0.005, 0.002),  # not on a step: to the nearest one each way
        (7.0, 10.0, 5.0),
        (1000.0, 2000.0, 500.0),
    ],
)
def test_the_next_step_each_way(value, above, below):
    assert step_125(value, up=True) == pytest.approx(above)
    assert step_125(value, up=False) == pytest.approx(below)


def test_a_whole_run_up_and_back_lands_on_every_step(app):
    spin = SequenceSpin()
    spin.setDecimals(3)
    spin.setRange(0.001, 3600)
    spin.setValue(0.001)
    seen = []
    for _ in range(9):
        spin.stepBy(1)
        seen.append(spin.value())
    assert seen == pytest.approx([0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0])
    for _ in range(9):
        spin.stepBy(-1)
    assert spin.value() == pytest.approx(0.001)


def test_the_arrows_stop_at_the_ends(app):
    spin = SequenceSpin()
    spin.setDecimals(3)
    spin.setRange(0.001, 3600)
    spin.setValue(0.001)
    spin.stepBy(-1)
    assert spin.value() == pytest.approx(0.001)
    spin.setValue(2000)
    spin.stepBy(1)
    assert spin.value() == pytest.approx(3600)


def test_any_number_can_still_be_typed(app):
    spin = SequenceSpin()
    spin.setDecimals(3)
    spin.setRange(0.001, 3600)
    spin.setValue(0.037)
    assert spin.value() == pytest.approx(0.037)
    spin.stepBy(1)
    assert spin.value() == pytest.approx(0.05)


def test_one_press_on_the_plots_time_box_is_not_a_thousand_times_as_much(window):
    """What it did: a step of a whole second, from a millisecond."""
    box = window.scope.window_s
    box.setValue(0.001)
    box.stepUp()
    assert box.value() == pytest.approx(0.002)
    box.stepDown()
    box.stepDown()
    assert box.value() == pytest.approx(0.001), "and not below what it can show"


def test_an_instruments_number_steps_as_it_says(app):
    view = InstrumentView()
    view.show_settings(
        (
            Setting("frequency", "Frequency", 1000.0, minimum=1.0, maximum=100_000.0),
            Setting("level", "Level", 2.0, maximum=4.0, decimals=2, step=0.1),
        ),
        {},
    )
    frequency, level = view.controls["frequency"], view.controls["level"]
    frequency.stepUp()
    assert frequency.value() == pytest.approx(2000.0)
    level.stepUp()
    assert level.value() == pytest.approx(2.1)


def test_the_generators_numbers_do_not_jump_a_volt_at_a_press(window):
    from pyscopegui.backends import picoscope2000 as pico

    box = window.instrument_bar.instrument
    box.setCurrentIndex(box.findData("picoscope2000"))
    controls = window.instrument_view.controls
    controls["gen_amplitude"].stepUp()
    controls["gen_offset"].stepDown()
    controls["gen_frequency"].stepUp()
    assert controls["gen_amplitude"].value() == pytest.approx(2.1)
    assert controls["gen_offset"].value() == pytest.approx(-0.1)
    assert controls["gen_frequency"].value() == pytest.approx(2000.0)
    assert controls["gen_frequency"].maximum() == pico.GENERATOR_HZ
