# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Writing what a plot shows as CSV."""

import csv
from pathlib import Path

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
    # Time to a tenth of a sample: at 1 kS/s, four places.
    assert rows[1:] == [["0.0010", "0.5"], ["0.0020", "1"], ["0.0030", "1.5"]]
    assert (done.rows, done.channels) == (3, 1)


def test_time_is_from_the_trigger_as_the_plot_has_it(tmp_path):
    held = {"A": record("A", [1, 2, 3, 4, 5])}
    export.write_csv(tmp_path / "out.csv", held, origin=0.002, t_from=-0.002, t_to=0.002)
    assert [row[0] for row in rows_of(tmp_path / "out.csv")[1:]] == [
        "-0.0020",
        "-0.0010",
        "0.0000",
        "0.0010",
        "0.0020",
    ]


def test_a_logic_channel_is_noughts_and_ones_with_no_unit(tmp_path):
    held = {
        "A": record("A", [0.25, 0.5]),
        "D0": record("D0", [0, 1], kind=DIGITAL),
    }
    export.write_csv(tmp_path / "out.csv", held, 0.0, 0.0, 1.0)
    assert rows_of(tmp_path / "out.csv") == [
        ["time (s)", "A (V)", "D0"],
        ["0.0000", "0.25", "0"],
        ["0.0010", "0.5", "1"],
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


@pytest.mark.parametrize(
    ("rate", "start_s"),
    [(1e6, 1000.0), (31.25e6, 10.0), (500e6, 0.0), (5000.0, 3600.0), (100.0, 0.0)],
)
def test_every_sample_has_a_time_of_its_own_however_far_into_a_run(tmp_path, rate, start_s):
    """Nine figures were a microsecond a thousand seconds in: at 1 MS/s every
    sample there was written at the same time as its neighbours."""
    made = Record(Channel("A", "A"), rate, 10)
    made.skip(round(start_s * rate))  # where the run had got to
    made.append(np.arange(4, dtype=np.float32))
    t_from = (made.total - 4) / rate
    export.write_csv(tmp_path / "out.csv", {"A": made}, 0.0, t_from, t_from + 3.5 / rate)
    times = [float(row[0]) for row in rows_of(tmp_path / "out.csv")[1:]]
    assert len(times) == 4 and len(set(times)) == 4
    for row, time in enumerate(times):
        assert time == pytest.approx(start_s + row / rate, abs=0.1 / rate)


def test_time_is_written_to_a_tenth_of_a_sample():
    assert export.time_format(1e6) == "%.7f"
    assert export.time_format(31.25e6) == "%.9f"
    assert export.time_format(500e6) == "%.10f"
    assert export.time_format(1.0) == "%.1f"
    assert export.time_format(0.0) == "%.1f", "and something sensible for no rate at all"


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
    assert rows[0] == ["time (s)", "A: sine (V)", "D0", "D1", "D2", "D3", "CAN"], "and not B"
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


def test_between_the_cursors_is_what_is_written_wherever_the_view_is(window, tmp_path):
    window.set_mode("auto")
    feed(window)
    window.scope.window_s.setValue(0.01)
    window.scope.cursors.setCurrentIndex(2)
    assert window.scope.between_action.isEnabled()
    window.scope.redraw()
    low, high = window.scope.analog.getViewBox().viewRange()[0]
    later, earlier = low + 0.6 * (high - low), low + 0.4 * (high - low)
    window.scope.set_cursor(0, later)
    window.scope.set_cursor(1, earlier)
    window.scope.export_csv(tmp_path / "between.csv", between_cursors=True)
    times = [float(row[0]) for row in rows_of(tmp_path / "between.csv")[1:]]
    # A fifth of 10 ms at 100 kS/s, to within a sample at either end, whichever cursor is first.
    assert 199 <= len(times) <= 202
    assert times[0] == pytest.approx(earlier, abs=2e-5)
    assert times[-1] == pytest.approx(later, abs=2e-5)


def test_between_the_cursors_wants_two(window, tmp_path):
    window.set_mode("auto")
    feed(window)
    window.scope.cursors.setCurrentIndex(1)
    assert not window.scope.between_action.isEnabled()
    assert window.scope.export_csv(tmp_path / "x.csv", between_cursors=True) == []
    assert "Choose two cursors" in window.log.toPlainText()


def test_an_export_cancelled_part_way_leaves_no_file(window, tmp_path, monkeypatch):
    from pyscopegui.ui import scope_view
    from pyscopegui.ui.progress import CancelledError

    def cancelled_at_once(_parent, _title, _total, job):
        def progress(_done):
            raise CancelledError

        return job(progress)

    monkeypatch.setattr(scope_view, "with_progress", cancelled_at_once)
    monkeypatch.setattr(export, "CHUNK", 10)
    window.set_mode("auto")
    feed(window)
    assert window.scope.export_csv(tmp_path / "gone.csv") == []
    assert not (tmp_path / "gone.csv").exists()
    assert "cancelled" in window.log.toPlainText()


# --- a picture of the plot ---------------------------------------------------------------------
def test_the_export_button_writes_csv_and_its_arrow_offers_a_picture_too(window, monkeypatch):
    asked = []
    monkeypatch.setattr(type(window.scope), "ask_export", lambda self: asked.append("csv"))
    button = window.scope.export_button
    assert button.text() == "Export CSV..."
    assert [action.text() for action in button.menu().actions()] == [
        "Export CSV...",
        "Export CSV between cursors...",
        "Export PNG...",
    ]
    file_menu = window.menuBar().actions()[0].menu()
    assert "Export PNG..." in [action.text() for action in file_menu.actions()]


def test_pressing_the_export_button_itself_is_still_csv(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    asked = []

    def fake(parent, title, start, kinds):
        asked.append((title, Path(start).name))
        return "", ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(fake))
    window.scope.export_button.click()
    window.scope.export_button.menu().actions()[2].trigger()
    assert asked == [("Export CSV", "capture.csv"), ("Export PNG", "capture.png")]


def test_a_picture_of_the_plot_is_saved_as_png(window, tmp_path):
    from PySide6.QtGui import QImage

    window.set_mode("auto")
    feed(window)
    assert window.scope.export_png(tmp_path / "shot.png")
    picture = QImage(str(tmp_path / "shot.png"))
    assert not picture.isNull() and picture.width() > 200 and picture.height() > 100
    assert "Saved a picture of the plot" in window.log.toPlainText()
    assert "shot.png" in window.log.toPlainText()


def test_a_picture_is_named_png_whatever_was_typed(window, tmp_path):
    assert window.scope.export_png(tmp_path / "shot")
    assert (tmp_path / "shot.png").is_file()


def test_a_picture_that_cannot_be_saved_says_so(window, tmp_path):
    assert not window.scope.export_png(tmp_path / "no such folder" / "shot.png")
    assert "could not be saved" in window.log.toPlainText()
