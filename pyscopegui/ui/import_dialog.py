# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Opening a CSV: which lines to skip, how it is divided, and which columns are what.

A file of pyscopegui's own Export CSV is right as it opens, and OK is all
there is to press. Anything else -- a scope's own CSV, a spreadsheet's -- has
lines of its own at the top, or columns that are not channels, and this is
where they are left out: skip the lines, untick the columns, say which one
is time. The first rows are shown as they would be read, so it can be seen
to be right before anything is opened.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from pyscopegui.core.capture_file import (
    ANALOG_ROLE,
    LOGIC,
    PREVIEW_ROWS,
    SEPARATORS,
    TIME,
    CaptureError,
    Column,
    CsvLayout,
    guess_layout,
    rows,
)

ROLES = {TIME: "Time", ANALOG_ROLE: "Analog", LOGIC: "Logic"}
#: The columns of the table of columns.
USE, NAME, ROLE, UNIT = 0, 1, 2, 3


class ImportDialog(QDialog):
    def __init__(self, path: Path, parent=None) -> None:
        super().__init__(parent)
        self.path = path
        self.setWindowTitle(f"Open {path.name}")
        self.resize(760, 560)

        self.skip = QSpinBox()
        self.skip.setRange(0, 100_000)
        self.skip.setToolTip(
            "Lines at the top that are not the table: a scope's own settings, say."
        )
        self.separator = QComboBox()
        for character, label in SEPARATORS.items():
            self.separator.addItem(label, character)
        self.names = QCheckBox("The first row after them is the columns' names")
        self.rate = QDoubleSpinBox()
        self.rate.setRange(0.001, 1e10)
        self.rate.setDecimals(3)
        self.rate.setSuffix(" S/s")
        self.rate.setToolTip("With no column of time: how many samples a second the rows are.")

        form = QFormLayout()
        form.addRow("Skip lines:", self.skip)
        form.addRow("Separator:", self.separator)
        form.addRow(self.names)
        form.addRow("Sample rate:", self.rate)

        self.preview = QTableWidget()
        self.preview.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview.setToolTip("The first rows, as they would be read.")
        self.columns = QTableWidget(0, 4)
        self.columns.setHorizontalHeaderLabels(["Use", "Name", "Is", "Unit"])
        self.columns.horizontalHeader().setStretchLastSection(True)
        self.columns.setToolTip(
            "Untick a column to leave it out. One column can be time; the others\n"
            "are channels, analog or logic (0 and 1)."
        )
        self.problem = QLabel()
        self.problem.setStyleSheet("color: #d08000;")

        self.columns.itemChanged.connect(lambda _item: self._check())
        self.buttons = QDialogButtonBox(QDialogButtonBox.Open | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("The first rows:"))
        layout.addWidget(self.preview, 2)
        layout.addWidget(QLabel("The columns:"))
        layout.addWidget(self.columns, 2)
        layout.addWidget(self.problem)
        layout.addWidget(self.buttons)

        self._fill(guess_layout(path))
        self.skip.valueChanged.connect(lambda _v: self._guess_again())
        self.separator.activated.connect(lambda _i: self._guess_again())
        self.names.toggled.connect(lambda _on: self._guess_again(keep_names=True))

    # --- filling it in ----------------------------------------------------------------------
    def _guess_again(self, keep_names: bool = False) -> None:
        guessed = guess_layout(self.path, self.skip.value(), self.separator.currentData())
        if keep_names and guessed.names != self.names.isChecked():
            guessed.names = self.names.isChecked()
            if not guessed.names:
                # Numbered, and the row that was their names is data now, or not.
                for column in guessed.columns:
                    column.name = f"Column {column.index + 1}"
        self._fill(guessed)

    def _fill(self, layout: CsvLayout) -> None:
        for widget in (self.skip, self.separator, self.names):
            widget.blockSignals(True)
        self.skip.setValue(layout.skip)
        self.separator.setCurrentIndex(max(self.separator.findData(layout.separator), 0))
        self.names.setChecked(layout.names)
        self.rate.setValue(layout.rate)
        for widget in (self.skip, self.separator, self.names):
            widget.blockSignals(False)
        self._show_preview(layout)
        # Emptied first, drop-downs and all: one left from before is drawn on top.
        self.columns.blockSignals(True)
        self.columns.clearContents()
        self.columns.setRowCount(0)
        self.columns.setRowCount(len(layout.columns))
        for row, column in enumerate(layout.columns):
            use = QTableWidgetItem()
            use.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            use.setCheckState(Qt.Checked if column.used else Qt.Unchecked)
            self.columns.setItem(row, USE, use)
            self.columns.setItem(row, NAME, QTableWidgetItem(column.name))
            role = QComboBox()
            for value, label in ROLES.items():
                role.addItem(label, value)
            role.setCurrentIndex(role.findData(column.role))
            role.currentIndexChanged.connect(lambda _i: self._check())
            self.columns.setCellWidget(row, ROLE, role)
            self.columns.setItem(row, UNIT, QTableWidgetItem(column.unit))
        self.columns.blockSignals(False)
        self._check()

    def _show_preview(self, layout: CsvLayout) -> None:
        try:
            found = rows(self.path, layout.skip, layout.separator, PREVIEW_ROWS)
        except CaptureError as exc:
            found = [[str(exc)]]
        width = max((len(row) for row in found), default=0)
        self.preview.clear()
        self.preview.setRowCount(len(found))
        self.preview.setColumnCount(width)
        for r, row in enumerate(found):
            for c, cell in enumerate(row):
                self.preview.setItem(r, c, QTableWidgetItem(cell))

    # --- what was chosen --------------------------------------------------------------------
    def layout(self) -> CsvLayout:
        columns = []
        for row in range(self.columns.rowCount()):
            role = self.columns.cellWidget(row, ROLE)
            columns.append(
                Column(
                    index=row,
                    name=self.columns.item(row, NAME).text().strip(),
                    role=role.currentData(),
                    unit=self.columns.item(row, UNIT).text().strip(),
                    used=self.columns.item(row, USE).checkState() == Qt.Checked,
                )
            )
        return CsvLayout(
            skip=self.skip.value(),
            separator=self.separator.currentData(),
            names=self.names.isChecked(),
            columns=columns,
            rate=self.rate.value(),
        )

    def _check(self) -> None:
        """Say what is wrong, if anything, and only let it be opened when nothing is."""
        layout = self.layout()
        times = [c for c in layout.columns if c.used and c.role == TIME]
        if not layout.channel_columns():
            said = "Tick at least one column that is a channel."
        elif len(times) > 1:
            said = "Only one column can be time."
        else:
            said = ""
        self.rate.setEnabled(not times)
        self.problem.setText(said)
        self.buttons.button(QDialogButtonBox.Open).setEnabled(not said)
