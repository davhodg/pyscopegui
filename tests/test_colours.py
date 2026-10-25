# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""A channel's colour: the one its scope draws it in, kept whatever else is open,
and changed here when that is wanted."""

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog

from pyscopegui.backends import picoscope2000, rigol1000z, tektronix2000
from pyscopegui.backends.base import Channel
from pyscopegui.ui import scope_view
from pyscopegui.ui.scope_view import CHOSEN_COLOURS, COLOURS, NAME
from tests.test_rigol1000z import fake  # noqa: F401
from tests.test_several import RIGOL, both  # noqa: F401  the demo and a pretend Rigol, open


def pen_colour(window, key):
    return window.scope._curves[key].opts["pen"].color().name()


def list_colour(window, key):
    return window.scope.channel_list._items[key].foreground(NAME).color().name()


# --- what each scope says -----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("module", "keys"),
    [
        (rigol1000z, ["CH1", "CH2", "CH3", "CH4"]),
        (tektronix2000, ["CH1", "CH2", "CH3", "CH4"]),
        (picoscope2000, ["A", "B", "C", "D"]),
    ],
)
def test_every_channel_of_a_scope_has_a_colour_of_its_own(module, keys):
    colours = [module.COLOURS[key] for key in keys]
    assert all(QColor(colour).isValid() for colour in colours)
    assert len(set(colours)) == len(colours), "no two the same"


def test_a_scope_hands_its_colours_to_its_channels(app):
    instrument = rigol1000z.Rigol1000Z(None, {"enabled_3": True})
    assert {c.key: c.colour for c in instrument.channels()} == {
        key: rigol1000z.COLOURS[key] for key in ("CH1", "CH3")
    }


def test_a_channel_says_no_colour_unless_it_is_given_one():
    assert Channel("A", "A").colour == ""


# --- what the plot does with them ---------------------------------------------------------------
def test_the_plot_draws_a_channel_in_its_scopes_colour(both):  # noqa: F811
    window = both
    key = f"{RIGOL}:CH1"
    assert pen_colour(window, key) == rigol1000z.COLOURS["CH1"]
    assert list_colour(window, key) == rigol1000z.COLOURS["CH1"]


def test_a_channel_with_no_colour_of_its_own_is_given_one_by_where_it_is_in_its_instrument(both):  # noqa: F811
    window = both
    assert pen_colour(window, "demo:A") == COLOURS[0]
    assert pen_colour(window, "demo:B") == COLOURS[1]


def test_opening_another_instrument_changes_nobodys_colour(window, app, fake):  # noqa: F811
    window.open_instrument()
    before = {key: pen_colour(window, key) for key in window.scope._curves}
    window.ctx.settings.set(f"instrument.{RIGOL}", {"address": fake.address})
    window.add_instrument(RIGOL)
    window.open_instrument()
    from tests.test_several import wait_for

    wait_for(app, lambda: window.instrument.is_open)
    for key, colour in before.items():
        assert pen_colour(window, key) == colour, key
    window.close_instrument()


def test_the_cursors_are_unlike_any_scopes_channels():
    taken = {
        *rigol1000z.COLOURS.values(),
        *tektronix2000.COLOURS.values(),
        *picoscope2000.COLOURS.values(),
    }
    assert not set(scope_view.CURSOR_COLOURS) & taken


# --- choosing one -------------------------------------------------------------------------------
def test_a_colour_chosen_is_drawn_and_kept_in_the_workspace(both):  # noqa: F811
    window = both
    key = f"{RIGOL}:CH1"
    window.scope.set_colour(key, "#123456")
    assert pen_colour(window, key) == "#123456" and list_colour(window, key) == "#123456"
    assert window.ctx.settings.get(CHOSEN_COLOURS) == {key: "#123456"}


def test_it_is_the_same_on_every_plot(both):  # noqa: F811
    window = both
    extra = window.panes.view(window.panes.add("scope", floating=True))
    window.scope.set_colour("demo:A", "#abcdef")
    assert extra._curves["demo:A"].opts["pen"].color().name() == "#abcdef"


def test_going_back_to_its_own_colour(both):  # noqa: F811
    window = both
    key = f"{RIGOL}:CH1"
    window.scope.set_colour(key, "#123456")
    window.scope.set_colour(key, "")
    assert pen_colour(window, key) == rigol1000z.COLOURS["CH1"]
    assert window.ctx.settings.get(CHOSEN_COLOURS) == {}


def test_choosing_from_the_list_asks_for_a_colour(both, monkeypatch):  # noqa: F811
    window = both
    key = f"{RIGOL}:CH1"
    asked = []

    def pick(start, parent, title):
        asked.append((start.name(), title))
        return QColor("#00ff00")

    monkeypatch.setattr(QColorDialog, "getColor", staticmethod(pick))
    window.scope.channel_list.colour_asked.emit(key, "choose")
    assert asked == [(rigol1000z.COLOURS["CH1"], "Colour of DS1054Z CH1")]
    assert pen_colour(window, key) == "#00ff00"


def test_cancelling_the_colour_dialog_changes_nothing(both, monkeypatch):  # noqa: F811
    window = both
    monkeypatch.setattr(QColorDialog, "getColor", staticmethod(lambda *a: QColor()))
    window.scope.channel_list.colour_asked.emit("demo:A", "choose")
    assert window.ctx.settings.get(CHOSEN_COLOURS) is None


def test_two_scopes_of_one_model_can_be_told_apart(window, app, fake):  # noqa: F811
    """Each draws its CH1 in the same yellow: one of them is given another colour."""
    window.ctx.settings.set(f"instrument.{RIGOL}", {"address": fake.address})
    window.ctx.settings.set(f"instrument.{RIGOL}#2", {"address": fake.address})
    window.scope.set_colour(f"{RIGOL}#2:CH1", "#ffffff")
    from tests.test_several import wait_for

    for name in (RIGOL, f"{RIGOL}#2"):
        window.add_instrument(RIGOL) if name not in window.added else None
        window.choose(name)
        window.open_instrument()
        wait_for(app, lambda: window.instrument.is_open)
    assert pen_colour(window, f"{RIGOL}:CH1") == rigol1000z.COLOURS["CH1"]
    assert pen_colour(window, f"{RIGOL}#2:CH1") == "#ffffff"
    for name in (RIGOL, f"{RIGOL}#2"):
        window.choose(name)
        window.close_instrument()


def test_a_colour_saved_wrong_by_hand_is_the_scopes_own(both):  # noqa: F811
    window = both
    key = f"{RIGOL}:CH1"
    window.ctx.settings.set(CHOSEN_COLOURS, {key: "not a colour", "demo:A": 7})
    window.scope._rebuild()
    assert pen_colour(window, key) == rigol1000z.COLOURS["CH1"]


def test_the_list_offers_its_own_colour_back_only_once_one_was_chosen(both):  # noqa: F811
    window = both
    key = f"{RIGOL}:CH1"
    item = window.scope.channel_list._items[key]
    assert not item.data(NAME, scope_view.Qt.UserRole + 1)
    window.scope.set_colour(key, "#123456")
    item = window.scope.channel_list._items[key]
    assert item.data(NAME, scope_view.Qt.UserRole + 1)
    assert scope_view.COLOUR_TIP in item.toolTip(NAME)
    assert item.toolTip(NAME).startswith("Rigol DS1000Z series\n"), "whose it is, in full"
