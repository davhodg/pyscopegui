# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Writing a large file on a thread of its own, with a progress bar."""

import threading

import numpy as np
import pytest

from pyscopegui.backends.base import DIGITAL, LOST, Channel, Scale
from pyscopegui.core.capture import Bit, Record
from pyscopegui.ui.progress import CancelledError, _Job, with_progress


def test_the_job_runs_on_another_thread_and_what_it_gives_comes_back(app):
    ran_on = []

    def job(progress):
        ran_on.append(threading.current_thread())
        for done in range(0, 101, 25):
            progress(done)
        return "written"

    assert with_progress(None, "Writing", 100, job) == "written"
    assert ran_on and ran_on[0] is not threading.main_thread()


def test_what_the_job_raises_is_raised_here(app):
    def job(_progress):
        raise OSError("disc full")

    with pytest.raises(OSError, match="disc full"):
        with_progress(None, "Writing", 1, job)


def test_cancel_stops_the_job_at_its_next_step(app):
    worker = _Job(lambda progress: progress(1), 10)
    worker.cancelled.set()
    worker.run()  # here, rather than on its thread: what it does is the same
    assert isinstance(worker.error, CancelledError)


# --- what the thread writes from ----------------------------------------------------------------
def test_a_copy_is_numbered_as_the_record_is_and_does_not_change_with_it():
    record = Record(Channel("A", "A", counts=True), 10.0, 100)
    record.append(np.arange(40, dtype=np.int16), Scale(0.5))
    record.append(np.array([LOST, 7], dtype=np.int16), Scale(0.25))
    copy = record.copied(30, 42)
    assert (copy.first, copy.total) == (30, 42)
    assert np.array_equal(copy.values(30, 42), record.values(30, 42), equal_nan=True)
    record.append(np.full(100, 1, dtype=np.int16), Scale(0.5))
    assert copy.values(30, 32).tolist() == [15.0, 15.5], "the record moved on; the copy did not"


def test_the_inputs_of_a_port_share_one_copy_of_it():
    port = Record(Channel("port0", "port0", DIGITAL), 10.0, 100)
    port.append(np.array([0b01, 0b10, 0b11], dtype=np.uint8))
    bits = [Bit(Channel(f"D{b}", f"D{b}", DIGITAL, port="port0", bit=b), port) for b in (0, 1)]
    ports: dict = {}
    copies = [bit.copied(0, 3, ports) for bit in bits]
    assert copies[0].port is copies[1].port and len(ports) == 1
    assert copies[0].values().tolist() == [1, 0, 1] and copies[1].values().tolist() == [0, 1, 1]
