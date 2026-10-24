# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The Python Console, and the commands it drives the scopes with, against the demo."""

import numpy as np
import pytest
from PySide6.QtWidgets import QFileDialog

from pyscopegui.backends import demo
from pyscopegui.ui.scripting import ScriptError


@pytest.fixture
def console(window):
    return window.console


@pytest.fixture
def names(console):
    return console.namespace


def typed(console, line):
    """Type a line, and what the console said to it."""
    before = len(console.text())
    console.type(line)
    return console.text()[before:]


# --- the pane ----------------------------------------------------------------------------------
def test_it_starts_with_what_there_is_to_type(console):
    assert "pyscopegui console" in console.text() and "single(timeout=30)" in console.text()


def test_a_line_is_run_and_what_it_prints_is_shown(console):
    assert "4" in typed(console, "print(2 + 2)")


def test_a_block_carries_on_until_it_is_finished(console):
    typed(console, "for n in range(3):")
    assert console.prompt.text() == "..."
    typed(console, "    print(n * 10)")
    said = typed(console, "")
    assert "0\n10\n20" in said and console.prompt.text() == ">>>"


def test_a_mistake_is_shown_under_it_and_not_reported_as_a_bug(console, window):
    before = window.log.toPlainText()
    said = typed(console, "no_such_name")
    assert "NameError" in said
    # Only what the mistake added: what was said at the start is not about it.
    added = window.log.toPlainText()[len(before) :]
    assert "pyscopegui" not in added.split("NameError")[0][-200:]


def test_up_goes_back_through_what_was_typed(console):
    typed(console, "x = 1")
    typed(console, "y = 2")
    console.input.history and console.input.keyPressEvent  # noqa: B018
    assert console.input.history == ["x = 1", "y = 2"]


def test_a_script_runs_with_the_same_names(console, tmp_path, monkeypatch):
    script = tmp_path / "check.py"
    script.write_text("open()\nprint(channels())\n", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(script), ""))
    console._run_script_dialog()
    assert "--- running" in console.text() and "A: sine" in console.text()
    assert console.ctx.settings.get("console.folder") == str(tmp_path)


def test_a_script_that_fails_says_where(console, tmp_path):
    script = tmp_path / "bad.py"
    script.write_text("x = 1\nraise ValueError('nope')\n", encoding="utf-8")
    console.run_file(script)
    assert 'bad.py", line 2' in console.text() and "ValueError: nope" in console.text()


def test_a_script_that_exits_does_not_close_anything(console, tmp_path, window):
    script = tmp_path / "exit.py"
    script.write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
    console.run_file(script)
    assert "SystemExit ignored" in console.text() and window.isVisible()


# --- the commands ------------------------------------------------------------------------------
def test_a_capture_end_to_end(names, window):
    names["run"]("auto")
    names["wait"](0.3)
    names["stop"]()
    assert not window.instrument.running
    times, volts = names["data"]("A: sine")
    assert len(times) == len(volts) > 1000
    assert volts.max() == pytest.approx(2.0, abs=0.05)
    assert np.all(np.diff(times) > 0)


def test_data_by_the_chosen_instruments_own_name(names):
    names["run"]("auto")
    names["wait"](0.1)
    names["stop"]()
    _times, logic = names["data"]("D0")
    assert logic.dtype == np.uint8 and set(np.unique(logic)) <= {0, 1}


def test_a_channel_that_is_not_there_says_which_are(names):
    names["open"]()
    with pytest.raises(ScriptError, match=r"There are: .*A: sine"):
        names["data"]("CH9")


def test_open_waits_until_it_is_open_and_close_closes(names, window):
    names["open"]()
    assert window.instrument.is_open
    names["close"]()
    assert not window.instrument.is_open


def test_an_instrument_that_will_not_open_says_so(names, window):
    names["add"]("rigol1000z")  # with no address
    with pytest.raises(ScriptError, match="would not open"):
        names["open"](timeout=10)


def test_add_and_choose(names, window):
    assert names["add"]("demo") == "demo#2" and window.chosen == "demo#2"
    names["choose"]("demo")
    assert window.chosen == "demo"
    with pytest.raises(ScriptError, match="No kind of instrument"):
        names["add"]("nosuch")
    with pytest.raises(ScriptError, match="Those in use: demo, demo#2"):
        names["choose"]("nosuch")


def test_set_is_what_the_pane_does_and_the_pane_follows(names, window):
    names["add"]("rigol1000z")
    names["set"]("scale_1", 0.5)
    assert window.ctx.settings.get("instrument.rigol1000z")["scale_1"] == 0.5
    assert window.instrument_view.value("scale_1") == 0.5
    assert names["get"]("scale_1") == 0.5
    assert names["get"]("time_div") == 1e-3, "and the default where nothing was set"


def test_set_with_a_name_or_value_it_does_not_know_says_what_there_is(names):
    names["add"]("rigol1000z")
    with pytest.raises(ScriptError, match=r"no setting 'scale_9'.*scale_1"):
        names["set"]("scale_9", 1.0)
    with pytest.raises(ScriptError, match=r"read can be .*'memory'"):
        names["set"]("read", "everything")


def test_single_waits_for_the_capture(names, window):
    names["trigger"]("A", level=0.0, rising=True)
    assert names["single"](timeout=10) is True
    assert not window.instrument.running and window.acquisition.mode == "stop"


def test_single_with_nothing_to_trigger_on_gives_up(names, window):
    names["trigger"]("A", level=50.0)  # far above a 2 V sine
    assert names["single"](timeout=0.5) is False
    assert not window.instrument.running


def test_read_is_only_for_a_scope_read_as_it_is(names):
    with pytest.raises(ScriptError, match="not read as it is"):
        names["read"]()


def test_trigger_sets_what_the_toolbar_shows(names, window):
    names["trigger"]("A", level=0.5, rising=False, position=0.25)
    bar = window.trigger_bar
    assert bar.source.currentData() == "A" and bar.edge.currentText() == "Falling"
    assert bar.level.value() == 0.5 and bar.position.value() == 25
    names["trigger"](None)
    assert bar.source.currentData() is None
    with pytest.raises(ScriptError, match="No channel 'CH1' to trigger on"):
        names["trigger"]("CH1")


def test_run_knows_only_the_run_buttons(names):
    with pytest.raises(ScriptError, match="One of stop, single, normal, auto"):
        names["run"]("fast")


def test_exports(names, tmp_path):
    names["run"]("auto")
    names["wait"](0.1)
    names["stop"]()
    assert names["export_csv"](tmp_path / "a.csv") == [tmp_path / "a.csv"]
    assert names["export_png"](tmp_path / "a.png") and (tmp_path / "a.png").exists()


def test_wait_keeps_the_window_going(names, window):
    names["run"]("auto")
    before = window.capture.stored()
    names["wait"](0.2)
    assert window.capture.stored() > before, "samples kept arriving"
    names["stop"]()


def test_the_names_given_are_documented(names):
    from pyscopegui.help import page_text

    page = page_text("console.md")
    for name in names:
        assert f"`{name}" in page, name


def test_every_command_says_what_it_does(names):
    for name, value in names.items():
        if callable(value) and name not in ("window", "ctx", "session"):
            assert value.__doc__, name


def test_the_demo_has_the_channels_the_examples_use():
    assert "A: sine" in [channel.name for channel in demo.CHANNELS]
