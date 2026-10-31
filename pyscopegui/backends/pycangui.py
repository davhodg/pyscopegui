# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""pycangui's decoded signals, as an instrument: a channel for each signal
ticked *UDP out* in pycangui.

Nothing to connect to: opening it listens on pycangui's group for signals
(core/signal_receive.py), and its channels are whatever pycangui describes.
The values are held and read out at a steady rate, a step at each new value,
a tenth of a second behind, so that values decoded at the same moment and
arriving a little apart are in their places. Their times are pycangui's, on
the clock pyscopegui lines instruments up on, so the samples are where the
CAN frames were, not where they arrived.

A signal ticked or unticked in pycangui changes what the channels are: a run
in progress starts again with them.
"""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QUdpSocket

from pyscopegui.backends.base import Block, Channel, Instrument, Setting
from pyscopegui.core.signal_receive import GROUP, PORT, Held, Receiver

#: The steady rates a signal can be read out at.
RATES = ((100.0, "100 S/s"), (1_000.0, "1 kS/s"), (10_000.0, "10 kS/s"))
RATE = 1_000.0
#: How far behind now the samples are: values decoded at one moment arrive a
#: little apart, and the last of them is waited for.
BEHIND_S = 0.1
#: How often a block is sent.
TICK_MS = 50
#: The most one block holds, as for the demo: a computer that was asleep is not
#: answered with all it missed at once.
MOST_S = 0.5
#: pycangui describes its signals every second: this long without, and it is
#: taken to have stopped sending.
QUIET_S = 3.0

SETTINGS = (
    Setting(
        "rate",
        "Sample rate",
        RATE,
        choices=RATES,
        group="Signals",
        tip=(
            "How often each signal is read out: it is held at its last value\n"
            "between. 1 kS/s puts a value within a millisecond of its frame."
        ),
    ),
)


class PycanguiSignals(Instrument):
    SETTINGS = SETTINGS

    #: The signals pycangui sends are not the ones there were: a run starts again.
    signals_changed = Signal()

    def __init__(self, parent: QObject | None = None, options: dict | None = None) -> None:
        super().__init__(parent)
        options = options if isinstance(options, dict) else {}
        chosen = options.get("rate")
        self._rate = float(chosen) if chosen in dict(RATES) else RATE
        self.receiver = Receiver()
        self._socket: QUdpSocket | None = None
        self._timer = QTimer(self, interval=TICK_MS, timeout=self._tick)
        self._watch = QTimer(self, interval=1000, timeout=self._check_heard)
        #: The computer's clock at sample nought, and samples sent since.
        self._zero = 0.0
        self._sent = 0
        self._held: dict[str, Held] = {}
        #: When pycangui was last heard describing its signals, and whether its
        #: silence has been said.
        self._heard: float | None = None
        self._quiet_said = False
        self._opened_at = 0.0

    # --- what it is ------------------------------------------------------------------------
    def channels(self) -> list[Channel]:
        channels = []
        for signal in self.receiver.signals:
            middle = full = 0.0
            if signal.low is not None and signal.high is not None:
                middle = (signal.low + signal.high) / 2
                full = (signal.high - signal.low) / 2
            channels.append(
                Channel(
                    signal.key,
                    signal.name,
                    unit=signal.unit,
                    full_scale=full,
                    middle=middle,
                    detail=signal.group,
                )
            )
        return channels

    @property
    def rate(self) -> float:
        return self._rate

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    @property
    def is_open(self) -> bool:
        return self._socket is not None

    def set(self, key: str, value: object) -> None:
        if key == "rate" and value in dict(RATES):
            self._rate = float(value)

    def diagnostics(self) -> list[str]:
        receiver = self.receiver
        heard = (
            f"{time.monotonic() - self._heard:.1f} s ago" if self._heard is not None else "never"
        )
        run = receiver.described_as
        return [
            f"listening on {GROUP}:{PORT}: {'yes' if self.is_open else 'no'}",
            f"pycangui last described its signals: {heard}"
            + (f" (run {run[0]}, description {run[1]})" if run else ""),
            f"signals: {', '.join(s.key for s in receiver.signals) or 'none'}",
            f"values read: {receiver.values_read:,}; messages passed over: "
            f"{receiver.passed_over:,}",
        ]

    # --- listening -------------------------------------------------------------------------
    def open(self) -> None:
        if self._socket is not None:
            return
        socket = QUdpSocket(self)
        bound = socket.bind(
            QHostAddress(QHostAddress.AnyIPv4),
            PORT,
            QAbstractSocket.ShareAddress | QAbstractSocket.ReuseAddressHint,
        )
        if not bound or not socket.joinMulticastGroup(QHostAddress(GROUP)):
            self.error.emit(
                f"Could not listen for pycangui's signals on {GROUP}:{PORT}: "
                f"{socket.errorString()}."
            )
            socket.deleteLater()
            self.opened_changed.emit(False)
            return
        socket.readyRead.connect(self._read)
        self._socket = socket
        self._opened_at = time.monotonic()
        self._quiet_said = False
        self._watch.start()
        self.note.emit(
            f"Listening for pycangui's signals on {GROUP}:{PORT}. In pycangui: Tools > "
            "Settings > Send ticked signals over UDP multicast, and tick UDP out."
        )
        self.opened_changed.emit(True)

    def close(self) -> None:
        self.stop()
        if self._socket is None:
            return
        self._watch.stop()
        self._socket.close()
        self._socket.deleteLater()
        self._socket = None
        self.opened_changed.emit(False)

    def _read(self) -> None:
        changed = False
        read = self.receiver.messages_read
        while self._socket is not None and self._socket.hasPendingDatagrams():
            datagram = self._socket.receiveDatagram()
            changed |= self.receiver.feed(bytes(datagram.data().data()))
        if self.receiver.messages_read > read:
            self._heard_now()
        if changed:
            self._held = {key: self._held.get(key, Held()) for key in self._keys()}
            names = ", ".join(s.name for s in self.receiver.signals) or "none"
            self.note.emit(f"pycangui is sending {len(self.receiver.signals)} signals: {names}.")
            self.signals_changed.emit()

    def _heard_now(self) -> None:
        self._heard = time.monotonic()
        if self._quiet_said:
            self._quiet_said = False
            self.note.emit("pycangui's signals are arriving again.")

    def _check_heard(self) -> None:
        since = self._heard if self._heard is not None else self._opened_at
        if not self._quiet_said and time.monotonic() - since > QUIET_S:
            self._quiet_said = True
            self.warning.emit(
                f"Nothing from pycangui for {QUIET_S:g} s: is it running, with Tools > "
                "Settings > Send ticked signals over UDP multicast on, and a signal ticked "
                "UDP out?"
            )

    def _keys(self) -> list[str]:
        return [s.key for s in self.receiver.signals]

    # --- sending samples -------------------------------------------------------------------
    def start(self) -> None:
        if self.running:
            return
        self.open()
        if not self.is_open:
            return
        self._zero = time.monotonic() - BEHIND_S
        self._sent = 0
        self._held = {key: Held() for key in self._keys()}
        # What came before the run is not part of it, but where each signal
        # was is: held from the start, not a gap until it next changes.
        for key, changes in self.receiver.pending.items():
            if key in self._held and changes:
                self._held[key].value = max(changes, key=lambda change: change[0])[1]
                changes.clear()
        self._timer.start()
        self.state_changed.emit(True)

    def stop(self) -> None:
        if not self.running:
            return
        self._timer.stop()
        self.state_changed.emit(False)

    def _tick(self) -> None:
        """Send the samples that have fallen due, a tenth of a second behind now."""
        due = int((time.monotonic() - BEHIND_S - self._zero) * self._rate) - self._sent
        if due > MOST_S * self._rate:
            self._sent += due - int(MOST_S * self._rate)
            due = int(MOST_S * self._rate)
        if due <= 0:
            return
        times = self._zero + (self._sent + np.arange(due)) / self._rate
        data = {}
        for key, held in self._held.items():
            data[key] = held.sample(times, self.receiver.pending.setdefault(key, []))
        if data:
            self.block.emit(Block(self._sent, self._rate, data, zero=self._zero))
        self._sent += due
