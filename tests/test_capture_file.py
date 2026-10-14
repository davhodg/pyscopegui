# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Captures in files: saved and opened again exactly, and CSVs read as they are laid out."""

import json

import numpy as np
import pytest
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog

from pyscopegui import backends
from pyscopegui.backends.base import ANALOG, DIGITAL, Channel
from pyscopegui.core import capture_file
from pyscopegui.core.capture_file import (
    ANALOG_ROLE,
    LOGIC,
    TIME,
    CaptureError,
    Column,
    CsvLayout,
    Loaded,
    guess_layout,
    read_csv,
)


def feed(window, seconds=0.2):
    window.instrument._started -= seconds
    window.instrument._tick()


@pytest.fixture
def held(window):
    """The demo, run, stopped, with a fifth of a second of it on the plot."""
    window.set_mode("auto")
    feed(window)
    window.set_mode("stop")
    window.scope.redraw()
    return window


# --- pyscopegui's own file ----------------------------------------------------------------------
def test_a_capture_comes_back_exactly_as_it_went(tmp_path):
    channels = [
        Channel("A", "A: sine", ANALOG, "V", 2.0, "1 V/div", "Channel A", "#123456"),
        Channel("D0", "D0", DIGITAL, ""),
    ]
    data = {
        "A": np.linspace(-2, 2, 100, dtype=np.float32),
        "D0": (np.arange(100) % 2).astype(np.uint8),
    }
    capture_file.save(tmp_path / "c.npz", Loaded(channels, 100_000.0, data, 50), "demo")
    back = capture_file.load(tmp_path / "c.npz")
    assert back.channels == channels and back.rate == 100_000.0 and back.zero == 50
    assert np.array_equal(back.data["A"], data["A"]) and back.data["A"].dtype == np.float32
    assert np.array_equal(back.data["D0"], data["D0"]) and back.data["D0"].dtype == np.uint8


def test_another_npz_is_not_taken_for_a_capture(tmp_path):
    np.savez(tmp_path / "other.npz", meta=np.array(json.dumps({"format": "something"})))
    with pytest.raises(CaptureError, match="not a capture saved by pyscopegui"):
        capture_file.load(tmp_path / "other.npz")
    (tmp_path / "broken.npz").write_bytes(b"not a zip")
    with pytest.raises(CaptureError, match="could not be read"):
        capture_file.load(tmp_path / "broken.npz")


# --- reading a CSV ------------------------------------------------------------------------------
def write(tmp_path, text, name="c.csv"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_our_own_export_is_laid_out_right_as_it_opens(held, tmp_path):
    held.scope.window_s.setValue(0.01)
    held.scope.export_csv(tmp_path / "shot.csv")
    layout = guess_layout(tmp_path / "shot.csv")
    assert (layout.skip, layout.separator, layout.names) == (0, ",", True)
    roles = {c.name: (c.role, c.unit) for c in layout.columns}
    assert roles["time"] == (TIME, "s")
    assert roles["A: sine"] == (ANALOG_ROLE, "V") and roles["D0"][0] == LOGIC
    loaded = read_csv(tmp_path / "shot.csv", layout)
    assert loaded.rate == pytest.approx(100_000.0)
    assert [c.name for c in loaded.channels] == ["A: sine", "B: ramp", "D0", "D1", "D2", "D3"]
    assert loaded.data["D0"].dtype == np.uint8 and loaded.data["A: sine"].dtype == np.float32


def test_lines_at_the_top_are_skipped_and_the_separator_found(tmp_path):
    path = write(
        tmp_path, "Model,TPS 2014\nSerial,C0123\n\nt;ch1;ch2\n0;1,5;2\n0.001;2;3\n0.002;3;4\n"
    )
    layout = guess_layout(path, skip=3)
    assert layout.separator == ";" and layout.names
    assert [c.name for c in layout.columns] == ["t", "ch1", "ch2"]


def test_columns_left_out_are_not_read(tmp_path):
    path = write(tmp_path, "time,a,b,label\n0,1,2,x\n1,3,4,y\n2,5,6,z\n")
    layout = guess_layout(path)
    assert [c.used for c in layout.columns] == [True, True, True, False], "words are not a channel"
    layout.columns[2].used = False
    loaded = read_csv(path, layout)
    assert list(loaded.data) == ["a"] and loaded.data["a"].tolist() == [1, 3, 5]
    assert loaded.rate == 1.0


def test_no_column_of_time_takes_the_rate_given(tmp_path):
    path = write(tmp_path, "1\n2\n3\n4\n")
    layout = guess_layout(path)
    assert not layout.names and layout.time_column() is None
    layout.rate = 250.0
    loaded = read_csv(path, layout)
    assert loaded.rate == 250.0 and loaded.zero is None
    assert loaded.data["Column 1"].tolist() == [1, 2, 3, 4]


def test_time_through_nought_is_where_the_plot_measures_from(tmp_path):
    path = write(tmp_path, "time (s),v (V)\n-0.002,1\n-0.001,2\n0.000,3\n0.001,4\n")
    assert read_csv(path, guess_layout(path)).zero == 2


def test_uneven_time_is_read_and_said(tmp_path):
    path = write(tmp_path, "time,v\n0,1\n1,2\n2.5,3\n3.5,4\n")
    loaded = read_csv(path, guess_layout(path))
    assert loaded.notes and "not evenly spaced" in loaded.notes[0]


def test_a_layout_that_cannot_be_read_says_what_to_check(tmp_path):
    path = write(tmp_path, "a,b\n1,2\n3,x\n")
    layout = CsvLayout(names=True, columns=[Column(0, "a"), Column(1, "b")])
    with pytest.raises(CaptureError, match="Check the lines skipped"):
        read_csv(path, layout)
    with pytest.raises(CaptureError, match="No columns are chosen"):
        read_csv(path, CsvLayout(columns=[Column(0, "a", used=False)]))


def test_a_layout_survives_being_saved_in_the_settings():
    layout = CsvLayout(3, ";", False, [Column(0, "t", TIME, "s"), Column(1, "x", LOGIC, "")], 9.0)
    assert CsvLayout.from_options(json.loads(json.dumps(layout.as_options()))) == layout
    assert CsvLayout.from_options("nonsense") == CsvLayout()


# --- in the window ------------------------------------------------------------------------------
def test_saving_and_opening_puts_it_back_beside_the_instruments(held, tmp_path, app):
    window = held
    written = window.scope.save_captures(tmp_path / "shot")
    assert written == [tmp_path / "shot.npz"]
    before = window.session.units["demo"].capture.records["A"].view().copy()
    name = window.open_capture(tmp_path / "shot.npz")
    app.processEvents()  # it arrives from the event loop, as an instrument's block does
    assert name == "file" and window.chosen == "file"
    unit = window.session.units["file"]
    assert set(unit.capture.records) == {"A", "B", "D0", "D1", "D2", "D3"}
    assert np.array_equal(unit.capture.records["A"].view(), before)
    assert "Opened shot.npz: 6 channels" in window.log.toPlainText()
    assert not unit.running, "it is all there, and stops"


def test_the_capture_file_is_not_offered_under_add_instrument(window):
    assert "file" not in backends.names()
    assert "file" not in [a.data() for a in window.instrument_bar.kinds.actions()]


def test_a_file_has_a_tab_and_a_read_button_and_no_trigger(held, tmp_path):
    window = held
    window.scope.save_captures(tmp_path / "shot.npz")
    window.open_capture(tmp_path / "shot.npz")
    assert window.instrument_bar.reads() and not window.trigger_bar.source.isEnabled()
    assert "File" in window.instrument_view.listed() or "file" in window.instrument_view.listed()
    assert window.scope.time.currentText() == "All", "shown whole, as a snapshot is"


def test_a_csv_opened_through_the_dialog(held, tmp_path, monkeypatch):
    window = held
    window.scope.window_s.setValue(0.01)
    window.scope.export_csv(tmp_path / "shot.csv")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileNames", lambda *a, **k: ([str(tmp_path / "shot.csv")], "")
    )
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.Accepted)
    window.ask_open_capture()
    unit = window.session.units["file"]
    assert "A: sine" in unit.capture.records
    saved = window.ctx.settings.get("instrument.file")
    assert saved["path"] == str(tmp_path / "shot.csv") and saved["csv"]["names"] is True


def test_a_file_that_is_gone_says_so(window, tmp_path):
    window.open_capture(tmp_path / "nowhere.npz")
    assert "is not there any more" in window.log.toPlainText()
    assert not window.unit.is_open


def test_nothing_on_the_plot_saves_nothing(window, tmp_path):
    assert window.scope.save_captures(tmp_path / "x.npz") == []
    assert "nothing on the plot to save" in window.log.toPlainText()


def test_a_saved_capture_is_one_file_for_each_instrument(held, tmp_path):
    window = held
    window.add_instrument("demo")
    window.set_mode("auto")  # which runs both
    for unit in window.session.units.values():
        unit.instrument._started -= 0.2
        unit.instrument._tick()
    window.set_mode("stop")
    written = window.scope.save_captures(tmp_path / "both.npz")
    assert sorted(p.name for p in written) == ["both-Demo 2.npz", "both-Demo.npz"]


# --- the dialog ---------------------------------------------------------------------------------
def test_the_dialog_starts_right_for_our_own_export_and_opens_it(held, tmp_path):
    from pyscopegui.ui.import_dialog import ImportDialog

    held.scope.window_s.setValue(0.01)
    held.scope.export_csv(tmp_path / "shot.csv")
    dialog = ImportDialog(tmp_path / "shot.csv")
    assert dialog.buttons.button(QDialogButtonBox.Open).isEnabled()
    assert dialog.layout().time_column().name == "time"
    assert dialog.preview.item(0, 0).text() == "time (s)"
    dialog.deleteLater()


def test_the_dialog_skips_lines_and_will_not_open_with_nothing_chosen(tmp_path):
    from PySide6.QtCore import Qt

    from pyscopegui.ui.import_dialog import ImportDialog

    path = write(tmp_path, "made by a scope\nwith,settings\ntime,v\n0,1\n1,2\n")
    dialog = ImportDialog(path)
    dialog.skip.setValue(2)
    assert dialog.layout().names and [c.name for c in dialog.layout().columns] == ["time", "v"]
    assert dialog.preview.item(0, 0).text() == "time"
    dialog.columns.item(1, 0).setCheckState(Qt.Unchecked)
    assert not dialog.buttons.button(QDialogButtonBox.Open).isEnabled()
    assert "at least one column" in dialog.problem.text()
    dialog.deleteLater()


def test_the_dialog_asks_for_a_rate_only_without_a_column_of_time(tmp_path):
    from pyscopegui.ui.import_dialog import ImportDialog

    dialog = ImportDialog(write(tmp_path, "1\n2\n3\n"))
    assert dialog.rate.isEnabled()
    dialog.deleteLater()
    dialog = ImportDialog(write(tmp_path, "time,v\n0,1\n1,2\n", "t.csv"))
    assert not dialog.rate.isEnabled()
    dialog.deleteLater()
