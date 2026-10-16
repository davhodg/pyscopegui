# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Probes: a voltage probe's ratio, and a current probe's volts an amp, on every scope."""

import pytest

from pyscopegui.backends import picoscope2000 as pico
from pyscopegui.backends import picoscope2000a as pico_a
from pyscopegui.backends import probes
from pyscopegui.backends import rigol1000z as rigol
from pyscopegui.backends import tektronix2000 as tek
from pyscopegui.backends.probes import CURRENT, Probe


def test_a_voltage_probe_the_scope_is_told_is_counted_by_the_scope():
    probe = probes.read({"probe_1": 20}, "1")
    assert (probe.ratio, probe.told, probe.unit) == (20, 20, "V")
    assert probe.from_scope == 1.0 and probe.at_scope(5.0) == 5.0 and probe.label() == "20x"


def test_a_ratio_the_scope_has_not_got_is_counted_here_with_the_scope_told_1x():
    probe = probes.read({"probe_1": 20}, "1", told=tek.TOLD)
    assert (probe.ratio, probe.told) == (20, 1)
    assert probe.from_scope == 20.0 and probe.at_scope(5.0) == pytest.approx(0.25)


def test_a_current_probe_is_in_amps_with_the_scope_told_1x():
    probe = probes.read({"probe_1": CURRENT, "sensitivity_1": 0.1}, "1")
    assert (probe.told, probe.unit, probe.label()) == (1, "A", "100 mV/A")
    # Ten amps a volt: an amp a division is a tenth of a volt a division to the scope.
    assert probe.from_scope == pytest.approx(10.0) and probe.at_scope(1.0) == pytest.approx(0.1)
    assert Probe(1, 2.5).label() == "2.5 V/A"


def test_anything_odd_saved_is_the_default_or_the_nearest():
    assert probes.read({}, "1") == Probe(10, told=10)
    assert probes.read({"probe_1": "x"}, "1", default=1) == Probe(1, told=1)
    assert probes.read({"probe_1": True}, "1").ratio == 10
    assert probes.read({"probe_1": 18}, "1").ratio == 20, "from a list since changed"
    odd = probes.read({"probe_1": CURRENT, "sensitivity_1": "x"}, "1")
    assert odd.sensitivity == probes.SENSITIVITY
    assert probes.read({"probe_1": CURRENT, "sensitivity_1": 1e9}, "1").sensitivity == 10.0


def test_each_channel_has_the_same_probes_on_every_scope():
    for offered in (rigol.SETTINGS, tek.SETTINGS, pico.SETTINGS, pico_a.SETTINGS):
        probe = next(s for s in offered if s.key.startswith("probe_"))
        values = [value for value, _label in probe.choices]
        assert values == [1, 10, 20, 50, 100, 500, 1000, CURRENT]
        suffix = probe.key.partition("_")[2]
        sensitivity = next(s for s in offered if s.key == f"sensitivity_{suffix}")
        assert sensitivity.needs == (probe.key, CURRENT) and sensitivity.unit == "V/A"


# --- the settings, as they are with a probe -----------------------------------------------------
def offered(settings, key):
    return next(s for s in settings if s.key == key)


def test_a_current_probe_puts_the_scale_and_offset_in_amps():
    fitted = rigol.Rigol1000Z.fitted(rigol.SETTINGS, {"probe_2": CURRENT})
    scale = offered(fitted, "scale_2")
    assert dict(scale.choices)[0.5] == "500 mA/div" and dict(scale.choices)[2.0] == "2 A/div"
    assert offered(fitted, "offset_2").unit == "A"
    # The other channels as they were.
    assert offered(fitted, "scale_1") == offered(rigol.SETTINGS, "scale_1")
    assert offered(fitted, "offset_1").unit == "V"


def test_a_picoscope_offers_its_scales_through_the_probe():
    scales = [v for v, _ in offered(pico.SETTINGS, "scale_a").choices]
    through = offered(pico.PicoScope2000.fitted(pico.SETTINGS, {"probe_a": 20}), "scale_a")
    assert [v for v, _ in through.choices] == pytest.approx([v * 20 for v in scales])
    current = pico.PicoScope2000.fitted(pico.SETTINGS, {"probe_a": CURRENT, "sensitivity_a": 0.01})
    labels = [label for _, label in offered(current, "scale_a").choices]
    # Its ±5 V range is 1 V a division: a hundred amps through 10 mV/A.
    assert "100 A/div" in labels and all(label.endswith("A/div") for label in labels)


# --- what each scope is told, and what it reads ----------------------------------------------
def test_the_rigol_is_told_a_current_probe_is_1x_and_its_volts():
    settings = rigol.Settings({"probe_1": CURRENT, "sensitivity_1": 0.1, "offset_1": 2.0})
    wanted = rigol.setup(settings, rigol.Trigger("CH1", 3.0))
    assert wanted[":CHAN1:PROB"] == "1"
    assert wanted[":CHAN1:SCAL"] == "0.1" and wanted[":CHAN1:OFFS"] == "0.2"
    assert wanted[":TRIG:EDG:LEV"] == "0.3"
    voltage = rigol.setup(rigol.Settings({"probe_1": 20}), rigol.Trigger("CH1", 3.0))
    assert voltage[":CHAN1:PROB"] == "20" and voltage[":TRIG:EDG:LEV"] == "3"


def test_the_tektronix_is_told_1x_for_a_ratio_the_older_ones_have_not_got():
    settings = tek.Settings({"probe_1": 20, "scale_1": 2.0, "offset_1": 4.0})
    wanted = tek.setup(settings, tek.Trigger("CH1", 10.0))
    assert wanted["CH1:PROBE"] == "1" and wanted["CH1:SCALE"] == "0.1"
    assert wanted["CH1:POSITION"] == "2", "in divisions, whatever the probe"
    assert wanted["TRIGGER:MAIN:LEVEL"] == "0.5"
    assert tek.setup(tek.Settings({"probe_1": 100}), tek.Trigger())["CH1:PROBE"] == "100"


def test_the_channel_says_it_is_in_amps(app):
    from pyscopegui import backends

    options = {"probe_1": CURRENT, "sensitivity_1": 0.1, "scale_1": 0.5, "offset_1": 1.0}
    for name in ("rigol1000z", "tektronix2000"):
        channel = backends.create(name, None, options).channels()[0]
        assert channel.unit == "A" and channel.full_scale == pytest.approx(2.0)
        assert channel.detail.startswith("500 mA/div, 100 mV/A, DC")
        assert "offset 1 A" in channel.detail
    as_is = backends.create("tektronix2000", None, options | {"read": tek.AS_IS}).channels()[0]
    assert as_is.unit == "V", "read as it is, the scope's own probe setting is all there is"


def test_an_offset_moves_the_middle_of_what_a_channel_reads(app):
    from pyscopegui import backends

    for name in ("rigol1000z", "tektronix2000"):
        channel = backends.create(name, None, {"offset_1": 2.0}).channels()[0]
        assert channel.middle == -2.0, name
    as_is = backends.create("tektronix2000", None, {"offset_1": 2.0, "read": tek.AS_IS})
    assert as_is.channels()[0].middle == 0.0, "its offset is the scope's own business"


def test_a_picoscope_reads_amps_through_a_current_probe():
    from tests.test_picoscope2000a import FakeLibrary, started

    library = FakeLibrary()
    options = {"scale_a": 10.0, "probe_a": CURRENT, "sensitivity_a": 0.1, "enabled_b": False}
    reading = started(library, options)
    # Ten amps a division through 100 mV/A is the scope's ±5 V range: fifty amps full scale.
    assert reading.settings.ranges["A"] == "5V"
    library.waiting.append({0: [32512, -16256]})
    assert reading.poll().data["A"].tolist() == pytest.approx([50.0, -25.0])


def test_a_picoscope_offset_through_a_current_probe_is_amps():
    from tests.test_picoscope2000a import FakeLibrary, started

    library = FakeLibrary()
    options = {"scale_a": 10.0, "probe_a": CURRENT, "sensitivity_a": 0.1, "offset_a": -2.0}
    reading = started(library, options)
    # Two amps through 100 mV/A is a fifth of a volt at the scope's input.
    assert library.offsets[0] == pytest.approx(-0.2)
    library.waiting.append({0: [0], 1: [0]})
    assert reading.poll().data["A"][0] == pytest.approx(2.0)
    assert reading.offset_at_tip("A") == pytest.approx(-2.0)


def test_the_rigol_reads_amps_through_a_current_probe(monkeypatch):
    from tests.test_rigol1000z import FakeScope, opened, sweep_of

    for name in ("SETTLE_S", "AUTO_S", "QUIET_S"):
        monkeypatch.setattr(rigol, name, 0.0)
    fake = FakeScope()
    try:
        scope = opened(fake, scale_1=0.5, probe_1=CURRENT, sensitivity_1=0.1)
        scope.start(scope.settings, rigol.Trigger())
        samples = sweep_of(scope).data["CH1"]
        # Four divisions down at half an amp a division.
        assert fake.state[":CHAN1:SCAL"] == "0.05" and fake.state[":CHAN1:PROB"] == "1"
        assert samples[0] == pytest.approx(-2.0)
        scope.close()
    finally:
        fake.shutdown()
        fake.server_close()


# --- in the window ---------------------------------------------------------------------------
def test_choosing_a_current_probe_puts_the_pane_in_amps(window):
    window.choose("rigol1000z")
    controls = window.instrument_view.controls
    assert not controls["sensitivity_1"].isEnabled()
    box = controls["probe_1"]
    box.setCurrentIndex(box.findData(CURRENT))
    box.activated.emit(box.currentIndex())
    controls = window.instrument_view.controls
    assert controls["sensitivity_1"].isEnabled()
    assert controls["scale_1"].currentText() == "1 A/div"
    assert controls["offset_1"].suffix() == " A"
    assert window.ctx.settings.get("instrument.rigol1000z")["probe_1"] == CURRENT


def test_a_scale_saved_through_another_probe_shows_as_the_nearest(window):
    window.ctx.settings.set("instrument.picoscope2000", {"scale_a": 3.0, "probe_a": 10})
    window.choose("picoscope2000")
    assert window.instrument_view.controls["scale_a"].currentText() == "2 V/div"


def test_read_as_it_is_the_sensitivity_has_no_say_either(window):
    window.ctx.settings.set("instrument.tektronix2000", {"probe_1": CURRENT, "read": tek.AS_IS})
    window.choose("tektronix2000")
    controls = window.instrument_view.controls
    assert not controls["probe_1"].isEnabled() and not controls["sensitivity_1"].isEnabled()


def test_a_script_sets_a_current_probe_and_a_scale_in_amps(window):
    names = window.console.namespace
    names["choose"]("rigol1000z")
    names["set"]("probe_1", CURRENT)
    names["set"]("sensitivity_1", 0.01)
    names["set"]("scale_1", 5.0)
    assert names["get"]("scale_1") == 5.0
