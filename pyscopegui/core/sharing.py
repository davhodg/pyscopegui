# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Decoded CAN frames, sent on to other programs: pycangui above all.

Through python-can's udp_multicast interface, which sends each frame to a
multicast group -- an address every program that has joined it hears. pycangui
offers 239.74.163.10 as "pyscopegui", so that the frames read off a scope or a
logic analyser arrive there as a channel of their own; any other python-can
program can join it too:

    bus = can.Bus(interface="udp_multicast", channel="239.74.163.10", hop_limit=0)

**It stays on this computer unless that is chosen otherwise.** Frames are sent
with a hop limit of 0, which keeps them on it. Tools > Settings > Share UDP
multicast on the local network sends them with a hop limit of 1: out onto the
local network, and no further, past a router. The same as pycangui, and for
the same reason: anything on that network could hear the bus.

Only good frames are sent, each once, as it is decoded: not the ones found
when a channel is first decoded from what is held, which would arrive as a
burst of the past. A frame's time is the computer's, when it started on the
bus: as long ago as its first sample is before the newest.

python-can is imported only when a frame is first sent.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Callable

from pyscopegui.core.can_decode import Frame

#: The group pycangui offers as "pyscopegui".
GROUP = "239.74.163.10"
#: How far a frame goes: 0 keeps it on this computer, 1 lets it out onto the
#: local network and no further. python-can's own default is 1.
LOCAL_ONLY, LOCAL_NETWORK = 0, 1


def is_group(address: str) -> bool:
    """Whether this is a multicast address: one a frame can be sent to."""
    try:
        return ipaddress.ip_address(address.strip()).is_multicast
    except ValueError:
        return False


def open_bus(group: str, hop_limit: int):
    """A python-can bus sending to this group. ImportError where python-can is
    not installed; whatever python-can raises where it cannot open it."""
    import can  # here, so that nothing pays for it until a frame is sent

    return can.Bus(interface="udp_multicast", channel=group, hop_limit=hop_limit)


def message(frame: Frame, timestamp: float):
    """A frame as python-can has it."""
    import can

    return can.Message(
        timestamp=timestamp,
        arbitration_id=frame.identifier,
        is_extended_id=frame.extended,
        is_remote_frame=frame.remote,
        dlc=frame.dlc if frame.remote else len(frame.data),
        data=b"" if frame.remote else frame.data,
    )


class Sharer:
    """Sends decoded frames to the groups they are asked to go to, a bus for each."""

    def __init__(self, say: Callable[[str, bool], None]) -> None:
        """``say`` is told what happened, in words, and whether it is a problem."""
        self._say = say
        self.hop_limit = LOCAL_ONLY
        #: Group -> its bus, opened when a frame is first sent to it.
        self._buses: dict[str, object] = {}
        #: Groups that could not be sent to: said once, and not tried again
        #: until the setting changes or pyscopegui starts again.
        self._failed: set[str] = set()
        #: Group -> how many frames have been sent to it.
        self.sent: dict[str, int] = {}

    def set_local_network(self, on: bool) -> None:
        """Whether frames reach the local network, from the next one sent."""
        wanted = LOCAL_NETWORK if on else LOCAL_ONLY
        if wanted != self.hop_limit:
            self.hop_limit = wanted
            self.close()  # opened again, as it is now, by the next frame

    def send(self, group: str, frames: list[tuple[Frame, float]]) -> None:
        """Send these frames -- each with its time -- to the group, the good ones."""
        good = [(frame, at) for frame, at in frames if frame.ok]
        if not good or group in self._failed:
            return
        bus = self._buses.get(group)
        if bus is None:
            bus = self._open(group)
            if bus is None:
                return
        try:
            for frame, at in good:
                bus.send(message(frame, at))
        except Exception as exc:  # python-can's own, or the network's
            self._fail(group, f"Decoded CAN frames could not be sent to {group}: {exc}.")
            return
        self.sent[group] = self.sent.get(group, 0) + len(good)

    def _open(self, group: str):
        try:
            bus = open_bus(group, self.hop_limit)
        except ImportError as exc:
            self._fail(
                group,
                f"Sending decoded CAN frames needs python-can, which is not installed: "
                f"pip install python-can, and start pyscopegui again ({exc}).",
            )
            return None
        except Exception as exc:
            self._fail(group, f"Decoded CAN frames could not be sent to {group}: {exc}.")
            return None
        self._buses[group] = bus
        where = "this computer" if self.hop_limit == LOCAL_ONLY else "the local network"
        self._say(f"Sending decoded CAN frames to {group}, on {where}.", False)
        return bus

    def _fail(self, group: str, said: str) -> None:
        self._failed.add(group)
        self._close(group)
        self._say(said, True)

    def _close(self, group: str) -> None:
        if (bus := self._buses.pop(group, None)) is not None:
            try:
                bus.shutdown()
            except Exception:  # nothing to be done about a bus that will not close
                pass

    def close(self) -> None:
        """Let every bus go, and try again any that failed."""
        for group in list(self._buses):
            self._close(group)
        self._failed.clear()
