# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Decoding a bus from the window: its menu, its dialogs, and the Decoded buses pane."""

from itertools import pairwise

import pytest
from PySide6.QtWidgets import QApplication

from pyscopegui.backends import demo
from pyscopegui.core.decoding import CAN_H, CAN_L, DIFFERENTIAL, LOGIC, CanSetup
from pyscopegui.ui.can_dialog import CanDialog, bitrate_text, source_for
from pyscopegui.ui.decoded_view import NOTHING_DECODED


def feed(window, seconds=0.3):
    window.instrument._started -= seconds
    window.instrument._tick()


@pytest.fixture
def held(window):
    window.set_mode("auto")
    feed(window)
    window.set_mode("stop")
    window.scope.redraw()
    return window


def decoded(window):
    window.scope.add_decoding(window.unit, CanSetup("CAN", LOGIC, demo.CAN_BITRATE))
    return window.unit.capture.decodings[0]


# --- the dialog ------------------------------------------------------------------------------
def test_a_bit_rate_can_be_chosen_or_typed(app):
    dialog = CanDialog("CAN", "CAN", analog=False)
    assert dialog.chosen_bitrate() == 0, "found from the signal, to start with"
    for typed, bits in (("83.333k", 83_333), ("250 kbit/s", 250_000), ("1M", 1_000_000)):
        dialog.bitrate.setEditText(typed)
        assert dialog.chosen_bitrate() == bits, typed
    dialog.bitrate.setEditText("fast")
    assert dialog.chosen_bitrate() is None
    dialog.accept()
    assert "not one" in dialog.problem.text() and not dialog.result()


def test_a_logic_channel_is_a_logic_level_and_an_analog_one_is_on_the_bus(app):
    logic = CanDialog("CAN", "CAN", analog=False)
    assert [logic.source.itemData(i) for i in range(logic.source.count())] == [LOGIC]
    assert not logic.threshold.isEnabled()
    analog = CanDialog("CH1", "CH1", analog=True)
    assert LOGIC not in [analog.source.itemData(i) for i in range(analog.source.count())]
    analog.source.setCurrentIndex(analog.source.findData(CAN_L))
    assert analog.threshold.value() == 2.0, "the usual for CAN_L"
    analog.threshold.setValue(1.8)
    assert analog.setup() == CanSetup("CH1", CAN_L, 0, 1.8)


def test_what_a_channel_is_likely_to_be_is_where_the_dialog_starts():
    assert source_for("maths:CH1-CH2", "CH1 \u2212 CH2", True) == DIFFERENTIAL
    assert source_for("CH1", "CANH", True) == CAN_H
    assert source_for("CH2", "CAN_L", True) == CAN_L
    assert source_for("D3", "D3", False) == LOGIC
    assert bitrate_text(500_000) == "500 kbit/s" and bitrate_text(1_000_000) == "1 Mbit/s"


def test_it_opens_as_the_channel_is_decoded_already(app):
    setup = CanSetup("CH1", CAN_H, 250_000, 3.2)
    dialog = CanDialog("CH1", "CH1", analog=True, setup=setup)
    assert dialog.setup() == setup


# --- from the channel list -------------------------------------------------------------------
def test_decode_as_can_from_the_channel_list_finds_the_bit_rate_and_the_frames(held, monkeypatch):
    window = held
    monkeypatch.setattr(CanDialog, "exec", lambda self: CanDialog.Accepted)
    window.scope.channel_list.decode_asked.emit("demo:CAN", "can")
    (decoding,) = window.unit.capture.decodings
    assert decoding.setup == CanSetup("CAN", LOGIC, 0)
    assert decoding.bitrate == demo.CAN_BITRATE
    good = [frame for frame in decoding.frames if frame.ok]
    assert {frame.identifier for frame in good} >= {0x0C8, 0x18FEF100}
    assert window.ctx.settings.get("decode.demo") == [decoding.setup.as_saved()]
    assert window.scope.channel_list.decoded == {"demo:CAN": "can"}


def test_stop_decoding_takes_it_away(held):
    window = held
    decoded(window)
    window.scope.channel_list.decode_removed.emit("demo:CAN")
    assert window.unit.capture.decodings == []
    assert window.ctx.settings.get("decode.demo") == []
    assert "demo:CAN" not in window.scope.channel_list.decoded


def test_decoding_goes_on_as_the_instrument_runs(window):
    window.set_mode("auto")
    decoding = decoded(window)
    feed(window, 0.2)
    before = len(decoding.frames)
    feed(window, 0.2)
    assert len(decoding.frames) > before > 0
    window.set_mode("stop")


def test_kept_with_the_workspace_and_decoded_again_the_next_time(held):
    from pyscopegui.ui.main_window import MainWindow

    decoded(held)
    again = MainWindow()
    try:
        assert [d.setup for d in again.session.units["demo"].capture.decodings] == [
            CanSetup("CAN", LOGIC, demo.CAN_BITRATE)
        ]
    finally:
        again.close()
        again.deleteLater()


# --- the CAN frames pane ---------------------------------------------------------------------
def test_with_nothing_decoded_the_pane_says_how(window):
    window.panes.show("decoded")
    window.decoded.refresh()
    assert window.decoded.over.text() == NOTHING_DECODED and not window.decoded.items.rows


def test_the_pane_lists_the_frames_and_says_what_is_decoded(held):
    window = held
    decoded(window)
    window.panes.show("decoded")
    window.decoded.refresh()
    rows = window.decoded.items.rows
    assert rows and all(a.seconds <= b.seconds for a, b in pairwise(rows))
    said = window.decoded.over.text()
    assert "CAN on CAN (Logic level)" in said and "10 kbit/s" in said and "read" in said
    model = window.decoded.items
    first_ok = next(n for n, row in enumerate(rows) if row.item.ok)
    texts = [model.data(model.index(first_ok, c)) for c in range(model.columnCount())]
    assert texts[2] in ("0C8", "18FEF100", "321") and texts[5] == "yes" and texts[6] == ""


def test_clicking_a_frame_puts_the_cursor_on_it(held):
    window = held
    decoded(window)
    window.panes.show("decoded")
    window.decoded.refresh()
    row = window.decoded.items.rows[-1]
    window.decoded.go_to(len(window.decoded.items.rows) - 1)
    scope = window.scope
    assert scope.cursor_count() >= 1 and scope.cursor_time(0) == pytest.approx(row.seconds)
    low, high = scope.analog.getViewBox().viewRange()[0]
    assert low <= row.seconds <= high


def test_rows_copy_with_a_heading(held):
    window = held
    decoded(window)
    window.panes.show("decoded")
    window.decoded.refresh()
    window.decoded.table.selectRow(0)
    window.decoded.copy()
    lines = QApplication.clipboard().text().splitlines()
    assert lines[0].startswith("Time (s)\tBus\tID / address") and len(lines) == 2


# --- UART, SPI and I2C ---------------------------------------------------------------------------
BUS = [
    ("D0", "SCK", False),
    ("D1", "MOSI", False),
    ("D2", "MISO", False),
    ("D3", "CS", False),
    ("D4", "SDA", False),
    ("D5", "SCL", False),
    ("CH1", "CH1", True),
]


def test_the_lines_of_a_bus_are_guessed_from_their_names(app):
    from pyscopegui.ui.decode_dialog import I2cDialog, SpiDialog

    spi = SpiDialog(BUS, "D0")
    assert [spi.line(r) for r in ("sclk", "mosi", "miso", "cs")] == ["D0", "D1", "D2", "D3"]
    assert spi.setup().cs == "D3" and not spi.threshold.isEnabled(), "all logic"
    i2c = I2cDialog(BUS, "D5")
    assert (i2c.line("scl"), i2c.line("sda")) == ("D5", "D4")


def test_one_channel_cannot_be_two_lines_and_spi_needs_a_data_line(app):
    from pyscopegui.ui.decode_dialog import I2cDialog, SpiDialog

    i2c = I2cDialog(BUS, "D5")
    i2c.lines["sda"].setCurrentIndex(i2c.lines["sda"].findData("D5"))
    i2c.accept()
    assert "of its own" in i2c.problem.text() and not i2c.result()
    spi = SpiDialog(BUS, "D0")
    for role in ("mosi", "miso"):
        spi.lines[role].setCurrentIndex(0)  # None
    spi.accept()
    assert "MOSI, MISO or both" in spi.problem.text()


def test_a_serial_line_s_baud_rate_can_be_typed_and_an_analog_one_has_a_threshold(app):
    from pyscopegui.core.decoding import UartSetup
    from pyscopegui.ui.decode_dialog import UartDialog

    dialog = UartDialog(BUS, "CH1")
    assert dialog.threshold.isEnabled() and dialog.chosen_baud() == 115200
    dialog.baud.setEditText("250k")
    assert dialog.chosen_baud() == 250_000
    dialog.threshold.setValue(1.65)
    assert dialog.setup() == UartSetup("CH1", 250_000, threshold=1.65)
    again = UartDialog(BUS, "CH1", UartSetup("CH1", 9600, 7, "even", 2))
    assert again.setup() == UartSetup("CH1", 9600, 7, "even", 2)


def test_each_protocol_reads_as_a_row(app):
    from types import SimpleNamespace

    from pyscopegui.core.decoding import I2cSetup, Message, SpiSetup, UartSetup
    from pyscopegui.core.i2c_decode import Transfer as I2cTransfer
    from pyscopegui.core.spi_decode import Transfer as SpiTransfer
    from pyscopegui.ui.decoded_view import Row, texts

    def row(setup, item):
        return Row(0.5, "bus", SimpleNamespace(setup=setup), item)

    uart = texts(row(UartSetup("TX", 9600), Message(0, 1, list(b"Hi\n"))))
    assert uart[3] == "3 characters" and uart[4] == r'48 69 0A  "Hi\n"'
    spi = texts(row(SpiSetup("SCK", "MOSI", "MISO", bits=12), SpiTransfer(0, 1, [0xABC], [0x123])))
    assert spi[3] == "1 word" and spi[4] == "MOSI ABC   MISO 123"
    read = I2cTransfer(0, 1, 0x50, read=True, data=[1, 2], acks=[True, True, False])
    assert texts(row(I2cSetup("SCL", "SDA"), read))[2:6] == ["0x50", "Read", "01 02", "yes"]
    nobody = I2cTransfer(0, 1, 0x3C, acks=[False])
    assert texts(row(I2cSetup("SCL", "SDA"), nobody))[5] == "no: nobody there"


def test_decode_as_from_the_menu_offers_every_protocol(held, monkeypatch):
    from pyscopegui.ui.decode_dialog import UartDialog

    window = held
    monkeypatch.setattr(UartDialog, "exec", lambda self: UartDialog.Accepted)
    window.scope.channel_list.decode_asked.emit("demo:D0", "uart")
    (decoding,) = window.unit.capture.decodings
    assert decoding.setup.protocol == "uart" and decoding.setup.line == "D0"
    assert window.scope.channel_list.decoded == {"demo:D0": "uart"}
    assert window.ctx.settings.get("decode.demo") == [decoding.setup.as_saved()]
