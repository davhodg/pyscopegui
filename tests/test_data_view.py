# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The Data pane: one instrument's samples, a row for each, read as they are drawn."""

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHeaderView

from pyscopegui.backends.base import DIGITAL, Channel
from pyscopegui.core.capture import Record
from pyscopegui.ui import data_view
from pyscopegui.ui.data_view import SAMPLE, TIME, Column, Samples


def record(values, kind="analog", rate=1000.0, first=0):
    held = Record(Channel("A", "A", kind, "V" if kind == "analog" else ""), rate, 100)
    held.total = first  # numbered from here, as a record that has let go of the start is
    dtype = np.float32 if kind == "analog" else np.uint8
    held.append(np.array(values, dtype=dtype))
    return held


# --- the table, on its own ------------------------------------------------------------------------
def test_a_row_is_a_sample_its_time_and_each_channels_value():
    model = Samples()
    analog, logic = record([1.5, -0.25, 2e-6]), record([0, 1, 1], DIGITAL)
    model.show([Column("A (V)", analog), Column("D0", logic)], 0, 3, 1000.0, 0.0)
    assert (model.rowCount(), model.columnCount()) == (3, 4)
    assert [model.headerData(c, Qt.Horizontal) for c in range(4)] == [
        "Sample",
        "Time (s)",
        "A (V)",
        "D0",
    ]
    assert [model.text(1, c) for c in range(4)] == ["1", "0.0010", "-0.25", "1"]
    assert model.text(2, 2) == "2e-06"


def test_time_is_on_the_plots_axis():
    model = Samples()
    model.show([Column("A", record([1, 2, 3]))], 0, 3, 1000.0, 0.002)
    assert model.text(0, TIME) == "-0.0020" and model.text(2, TIME) == "0.0000"


def test_a_gap_and_a_sample_no_longer_held_are_empty():
    model = Samples()
    held = record([1.0, np.nan, 3.0], first=50)
    model.show([Column("A", held)], 48, 6, 1000.0, 0.0)
    assert [model.text(n, 2) for n in range(48, 54)] == ["", "", "1", "", "3", ""]


def test_rows_copy_as_a_spreadsheet_pastes_them():
    model = Samples()
    model.show([Column("A (V)", record([1.0, 2.0]))], 0, 2, 1000.0, 0.0)
    assert model.rows_as_text([1]) == "Sample\tTime (s)\tA (V)\n1\t0.0010\t2\n"


def test_showing_the_same_again_is_not_laid_out_again():
    model = Samples()
    held = record([1.0, 2.0])
    reset, changed = [], []
    model.modelReset.connect(lambda: reset.append(1))
    model.dataChanged.connect(lambda *_: changed.append(1))
    model.show([Column("A", held)], 0, 2, 1000.0, 0.0)
    model.show([Column("A", held)], 0, 2, 1000.0, 0.0)
    assert reset == [1] and changed == [1], "only the values are drawn again"


# --- in the window -----------------------------------------------------------------------------
def feed(window, seconds=0.3):
    window.instrument._started -= seconds
    window.instrument._tick()


@pytest.fixture
def pane(window):
    window.set_mode("auto")
    feed(window)
    window.set_mode("stop")
    window.scope.redraw()
    window.panes.show("data")
    window.data.refresh()
    return window


def test_the_rows_are_the_samples_in_view(pane):
    window = pane
    model = window.data.samples
    unit = window.unit
    sine = unit.capture.records["A"]
    t_from, _t_to, cursors = window.scope.span()
    assert not cursors and model.count > 0
    assert window.data.instrument.currentData() == "demo"
    assert window.data.over.text().startswith("In view:")
    # Every channel ticked on the plot, sine and ramp and the logic inputs.
    headings = [model.headerData(c, Qt.Horizontal) for c in range(model.columnCount())]
    assert headings[:4] == ["Sample", "Time (s)", "A: sine (V)", "B: ramp (V)"]
    assert "D0" in headings
    number = model.first + 5
    assert float(model.text(number, 2)) == pytest.approx(
        float(sine.view()[number - sine.first]), rel=1e-5
    )
    origin = window.scope.origin_of("demo")
    assert t_from - 1 / sine.rate <= model.first / sine.rate - origin <= t_from + 1 / sine.rate


def test_between_two_cursors_the_rows_are_between_them_and_theirs_are_tinted(pane):
    window = pane
    window.scope.cursors.setCurrentIndex(2)
    window.data.refresh()
    model = window.data.samples
    assert window.data.over.text().startswith("Between the cursors:")
    rate, origin = model.rate, model.origin
    at = [round((window.scope.cursor_time(n) + origin) * rate) for n in range(2)]
    assert model.first <= at[0] and at[1] < model.first + model.count + 1
    assert model.data(model.index(at[0] - model.first, 0), Qt.BackgroundRole) is not None
    assert model.data(model.index(at[0] - model.first + 2, 0), Qt.BackgroundRole) is None


def test_a_channel_unticked_on_the_plot_is_not_a_column(pane):
    window = pane
    window.scope._on_shown("demo:B", False)
    window.data.refresh()
    model = window.data.samples
    headings = [model.headerData(c, Qt.Horizontal) for c in range(model.columnCount())]
    assert "B: ramp (V)" not in headings and "A: sine (V)" in headings


def test_ctrl_c_copies_the_rows_selected(pane):
    window = pane
    table = window.data.table
    table.selectRow(0)
    window.data.copy()
    lines = QApplication.clipboard().text().splitlines()
    assert lines[0].startswith("Sample\tTime (s)\tA: sine (V)")
    assert lines[1].split("\t")[0] == str(window.data.samples.first)
    assert len(lines) == 2


def test_a_stretch_longer_than_the_table_takes_is_cut_short_and_says_so(pane, monkeypatch):
    monkeypatch.setattr(data_view, "MOST_ROWS", 10)
    pane.data.refresh()
    assert pane.data.samples.count == 10
    assert "the first 10 of them here" in pane.data.over.text()


def test_the_columns_are_as_wide_as_their_numbers_get(pane):
    header = pane.data.table.horizontalHeader()
    assert header.sectionResizeMode(SAMPLE) == QHeaderView.Fixed
    assert header.sectionResizeMode(3) == QHeaderView.Fixed
    assert header.sectionSize(3) >= header.fontMetrics().horizontalAdvance("A: sine (V)")


def test_with_nothing_shown_it_says_so(window):
    window.panes.show("data")
    window.data.refresh()
    assert window.data.samples.count == 0
    assert window.data.over.text() in (
        "Nothing is shown on the plot.",
        "Nothing has been read yet.",
    )


def test_it_is_a_pane_put_away_to_start_with_and_shown_when_asked_for(window):
    dock = window.panes.docks["data"]
    assert not dock.isVisible()
    window.panes.show("data")
    assert dock.isVisible() and window.data.isVisible()
