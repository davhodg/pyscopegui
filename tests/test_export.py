# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Writing what a plot shows as CSV."""

import csv

import numpy as np
import pytest

from pyscopegui.backends.base import DIGITAL, Channel
from pyscopegui.core import export
from pyscopegui.core.capture import Record


def record(key, samples, rate=1000.0, kind="analog", name=None):
    made = Record(Channel(key, name or key, kind=kind), rate, max(len(samples), 1))
    made.append(np.asarray(samples, dtype=np.float32 if kind == "analog" else np.uint8))
    return made


def rows_of(path):
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.reader(file))


# --- one file ----------------------------------------------------------------------------------
def test_every_sample_in_the_stretch_is_written_with_its_time(tmp_path):
    held = {"A": record("A", [0.0, 0.5, 1.0, 1.5, 2.0])}
    done = export.write_csv(tmp_path / "out.csv", held, origin=0.0, t_from=0.001, t_to=0.003)
    rows = rows_of(tmp_path / "out.csv")
    assert rows[0] == ["time (s)", "A (V)"]
    assert rows[1:] == [["0.001", "0.5"], ["0.002", "1"], ["0.003", "1.5"]]
    assert (done.rows, done.channels) == (3, 1)


def test_time_is_from_the_trigger_as_the_plot_has_it(tmp_path):
    held = {"A": record("A", [1, 2, 3, 4, 5])}
    export.write_csv(tmp_path / "out.csv", held, origin=0.002, t_from=-0.002, t_to=0.002)
    assert [row[0] for row in rows_of(tmp_path / "out.csv")[1:]] == [
        "-0.002",
        "-0.001",
        "0",
        "0.001",
        "0.002",
    ]


def test_a_logic_channel_is_noughts_and_ones_with_no_unit(tmp_path):
    held = {
        "A": record("A", [0.25, 0.5]),
        "D0": record("D0", [0, 1], kind=DIGITAL),
    }
    export.write_csv(tmp_path / "out.csv", held, 0.0, 0.0, 1.0)
    assert rows_of(tmp_path / "out.csv") == [
        ["time (s)", "A (V)", "D0"],
        ["0", "0.25", "0"],
        ["0.001", "0.5", "1"],
    ]


def test_a_gap_is_written_as_not_a_number(tmp_path):
    held = {"A": record("A", [1.0, np.nan, 3.0])}
    export.write_csv(tmp_path / "out.csv", held, 0.0, 0.0, 1.0)
    assert [row[1] for row in rows_of(tmp_path / "out.csv")[1:]] == ["1", "nan", "3"]


def test_a_deep_capture_is_written_whole_and_in_order(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "CHUNK", 1000)
    samples = np.arange(2500, dtype=np.float32)
    done = export.write_csv(tmp_path / "out.csv", {"A": record("A", samples)}, 0.0, 0.0, 10.0)
    rows = rows_of(tmp_path / "out.csv")
    assert done.rows == 2500 and len(rows) == 2501
    assert [float(row[1]) for row in rows[1:]] == list(range(2500))
    assert float(rows[-1][0]) == pytest.approx(2.499)


def test_a_time_a_nanosecond_apart_is_told_apart(tmp_path):
    held = {"A": record("A", np.zeros(1000), rate=1e9)}
    export.write_csv(tmp_path / "out.csv", held, 0.0, 0.0, 1.0)
    times = [row[0] for row in rows_of(tmp_path / "out.csv")[1:]]
    assert len(set(times)) == 1000


def test_a_name_with_a_comma_does_not_make_a_column(tmp_path):
    held = {"A, the first": record("A", [1.0])}
    export.write_csv(tmp_path / "out.csv", held, 0.0, 0.0, 1.0)
    assert rows_of(tmp_path / "out.csv")[0] == ["time (s)", "A  the first (V)"]


def test_nothing_to_write_is_said_and_no_file_is_made(tmp_path):
    empty = Record(Channel("A", "A"), 1000.0, 10)
    with pytest.raises(ValueError, match="no samples"):
        export.write_csv(tmp_path / "out.csv", {"A": empty}, 0.0, 0.0, 1.0)
    with pytest.raises(ValueError, match="stretch of time"):
        export.write_csv(tmp_path / "out.csv", {"A": record("A", [1.0])}, 0.0, 5.0, 6.0)
    assert not (tmp_path / "out.csv").exists()


def test_one_instrument_has_the_name_asked_for_and_several_have_their_own(tmp_path):
    path = tmp_path / "capture.csv"
    assert export.paths_for(path, ["Pico"]) == {"Pico": path}
    assert export.paths_for(path, ["Pico", "Rigol"]) == {
        "Pico": tmp_path / "capture-Pico.csv",
        "Rigol": tmp_path / "capture-Rigol.csv",
    }


# --- from the plot -----------------------------------------------------------------------------
def feed(window, seconds=0.2):
    window.instrument._started -= seconds
    window.instrument._tick()


def test_the_plot_writes_what_it_shows(window, tmp_path):
    window.set_mode("auto")
    feed(window)
    window.scope.window_s.setValue(0.01)
    window.scope._on_shown("demo:B", False)
    written = window.scope.export_csv(tmp_path / "shot.csv")
    assert [done.path for done in written] == [tmp_path / "shot.csv"]
    rows = rows_of(tmp_path / "shot.csv")
    assert rows[0] == ["time (s)", "A: sine (V)", "D0", "D1", "D2", "D3"], "and not B, unticked"
    # Ten milliseconds at 100 kS/s, to within a sample at either end.
    assert 999 <= len(rows) - 1 <= 1002
    low, high = window.scope.analog.getViewBox().viewRange()[0]
    assert float(rows[1][0]) == pytest.approx(low, abs=2e-5)
    assert float(rows[-1][0]) == pytest.approx(high, abs=2e-5)
    assert "Exported" in window.log.toPlainText() and "shot.csv" in window.log.toPlainText()


def test_around_a_trigger_the_times_are_from_it(window, tmp_path):
    window.set_mode("auto")
    box = window.trigger_bar.source
    box.setCurrentIndex(box.findData("A"))
    box.activated.emit(box.currentIndex())
    window.scope.window_s.setValue(0.01)
    feed(window)
    window.scope.export_csv(tmp_path / "shot.csv")
    rows = rows_of(tmp_path / "shot.csv")
    times = np.array([float(row[0]) for row in rows[1:]])
    values = np.array([float(row[1]) for row in rows[1:]])
    assert times[0] == pytest.approx(-0.005, abs=2e-5) and times[-1] == pytest.approx(
        0.005, abs=2e-5
    )
    # The sine goes up through nought at the trigger, which is at nought.
    assert values[times < -1e-4][-1] < 0 < values[times > 1e-4][0]


def test_nothing_on_the_plot_says_so(window, tmp_path):
    assert window.scope.export_csv(tmp_path / "none.csv") == []
    assert not (tmp_path / "none.csv").exists()
    assert "nothing on the plot to export" in window.log.toPlainText()


def test_the_folder_last_exported_to_is_where_the_next_starts(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from pyscopegui.ui.scope_view import EXPORT_FOLDER

    asked = []

    def choose(_parent, _title, start, _filter):
        asked.append(start)
        return str(tmp_path / "sub" / "one.csv"), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", choose)
    window.set_mode("auto")
    feed(window)
    window.scope.ask_export()
    assert (tmp_path / "sub" / "one.csv").is_file()
    assert window.ctx.settings.get(EXPORT_FOLDER) == str(tmp_path / "sub")
    window.scope.ask_export()
    assert asked[1] == str(tmp_path / "sub" / "capture.csv")
