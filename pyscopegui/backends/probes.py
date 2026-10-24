# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""What is on the end of a channel: a voltage probe, or a current probe.

A voltage probe divides: 10x puts a tenth of what is at its tip on the
scope's input, and what is read is multiplied back. The scopes that have a
probe setting of their own -- the Rigol, the Tektronix -- are told it, and
do the multiplying; a PicoScope has none, and pyscopegui does it. So does
it for a ratio a scope does not have on its own list: the scope is told 1x.

A current probe gives a voltage for a current: so many volts an amp, as its
own switch or label says -- 100 mV/A. That is the same on every scope, so it
is done here and not by any of them: the scope is told its probe is 1x, and
everything about the channel is in amps -- its scale, its offset, the level
it triggers at, and every sample read. A volt at the scope is an amp divided
by the sensitivity.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from pyscopegui.backends.base import Setting

#: The probe setting's value for a current probe.
CURRENT = "current"
#: What a voltage probe divides by, as the probes that are made do.
RATIOS = (1, 10, 20, 50, 100, 500, 1000)
#: Volts an amp a current probe gives, to start with: a common clamp's.
SENSITIVITY = 0.1
LEAST_SENSITIVITY, MOST_SENSITIVITY = 1e-4, 10.0

PROBE_TIP = (
    "What is on the end of the channel. A voltage probe divides by what its\n"
    "switch says. A current probe gives volts for amps -- say how many under\n"
    "Sensitivity -- and the channel is then in amps."
)
SENSITIVITY_TIP = (
    "How many volts the current probe gives for an amp, as its switch or label\n"
    "says: a clamp's 100 mV/A is 0.1. Everything about the channel is in amps."
)


def choices(ratios: tuple[int, ...] = RATIOS) -> tuple[tuple[object, str], ...]:
    """The probe setting's list: each voltage ratio, and a current probe."""
    return (*((ratio, f"{ratio}x") for ratio in ratios), (CURRENT, "Current probe"))


def settings(
    suffix: str, group: str, default: int = 10, live: bool = True, needs=None, tip: str = ""
) -> list[Setting]:
    """A channel's probe settings: the probe, and a current probe's sensitivity.
    ``needs`` and ``tip`` are the probe's, as Setting has them; the
    sensitivity needs a current probe as well."""
    return [
        Setting(
            f"probe_{suffix}",
            "Probe",
            default,
            choices=choices(),
            group=group,
            live=live,
            needs=needs,
            tip=PROBE_TIP + tip,
        ),
        Setting(
            f"sensitivity_{suffix}",
            "Sensitivity",
            SENSITIVITY,
            minimum=LEAST_SENSITIVITY,
            maximum=MOST_SENSITIVITY,
            decimals=4,
            unit="V/A",
            group=group,
            needs=(f"probe_{suffix}", CURRENT),
            live=live,
            beside=f"probe_{suffix}",
            named=False,
            tip=SENSITIVITY_TIP + tip,
        ),
    ]


@dataclass(frozen=True)
class Probe:
    """One channel's probe."""

    #: What a voltage probe divides by. 1 for a current probe.
    ratio: int = 1
    #: Volts an amp, for a current probe; None for a voltage probe.
    sensitivity: float | None = None
    #: What the scope's own probe setting is told: the ratio, where it has
    #: that ratio, and 1 for anything else -- the rest is counted here.
    told: int = 1

    @property
    def current(self) -> bool:
        return self.sensitivity is not None

    @property
    def unit(self) -> str:
        """What the channel is measured in."""
        return "A" if self.current else "V"

    @property
    def gain(self) -> float:
        """The channel's unit at the probe's tip for a volt at the scope:
        what a scope with no probe setting multiplies what it reads by."""
        return 1.0 / self.sensitivity if self.current else float(self.ratio)

    @property
    def from_scope(self) -> float:
        """What the scope's readings are multiplied by to be in the channel's
        unit at the probe's tip: one, where the scope was told the probe."""
        return self.gain / self.told

    def at_scope(self, value: float) -> float:
        """What the scope is told, for this much of the channel's unit at the
        probe's tip: its scale, its offset, its trigger level."""
        return value / self.from_scope

    def label(self) -> str:
        """How it is said beside the channel: "10x", "100 mV/A"."""
        if not self.current:
            return f"{self.ratio}x"
        volts = self.sensitivity
        return f"{volts * 1000:g} mV/A" if volts < 1 else f"{volts:g} V/A"


def read(
    options: dict, suffix: str, default: int = 10, ratios=RATIOS, told: tuple = RATIOS
) -> Probe:
    """A channel's probe, from what was saved: anything odd is the default.
    ``told`` are the ratios the scope's own probe setting has: none, for a
    scope with no such setting."""
    chosen = options.get(f"probe_{suffix}", default)
    if chosen == CURRENT:
        try:
            volts = float(options.get(f"sensitivity_{suffix}", SENSITIVITY))
        except (TypeError, ValueError):
            volts = SENSITIVITY
        return Probe(1, min(max(volts, LEAST_SENSITIVITY), MOST_SENSITIVITY))
    if isinstance(chosen, bool) or not isinstance(chosen, int | float):
        chosen = default
    # The nearest there is: a ratio saved from a list that has since grown or shrunk.
    ratio = min(ratios, key=lambda r: abs(r - chosen))
    return Probe(ratio, told=ratio if ratio in told else 1)


def per_division(value: float, unit: str) -> str:
    """A scale, in the unit that suits it: 0.05, "A" -> "50 mA/div"."""
    for scale, prefix in ((1.0, ""), (1e-3, "m"), (1e-6, "µ")):
        if abs(value) >= scale or prefix == "µ":
            return f"{value / scale:g} {prefix}{unit}/div"
    return f"0 {unit}/div"


def fitted(offered, options: dict, multiplied: bool = False) -> tuple[Setting, ...]:
    """The settings as they are with the probes chosen: each channel's scale
    and offset in what it measures, amps through a current probe.

    ``multiplied`` is for a scope with no probe setting of its own, whose
    scales are offered as they are at its input: they are offered here as
    they are at the probe's tip, through whichever probe is on the channel.
    """
    probe_settings = {s.key: s for s in offered if s.key.startswith("probe_")}
    made = []
    for setting in offered:
        what, _, suffix = setting.key.partition("_")
        chosen = probe_settings.get(f"probe_{suffix}")
        if chosen is None or what not in ("scale", "offset"):
            made.append(setting)
            continue
        ratios = tuple(v for v, _ in chosen.choices if v != CURRENT)
        probe = read(options, suffix, chosen.default, ratios, ratios)
        if what == "offset":
            made.append(replace(setting, unit=probe.unit))
            continue
        values = [value for value, _ in setting.choices]
        if multiplied:
            values = sorted({round(value * probe.gain, 9) for value in values})
        elif not probe.current:
            made.append(setting)
            continue
        made.append(
            replace(setting, choices=tuple((v, per_division(v, probe.unit)) for v in values))
        )
    return tuple(made)
