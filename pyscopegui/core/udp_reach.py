# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""How far UDP multicast goes: off, this computer only, or the local network.

One choice for everything pyscopegui does over UDP multicast, in both
directions, the same three as pycangui offers: the decoded CAN frames sent on
(core/sharing.py), and pycangui's signals received (backends/pycangui.py). A
hop limit only stops what is sent from leaving the computer; a socket joined
to a group hears every network adapter, so "this computer only" also needs
what arrives from another computer dropped, which :class:`OwnAddresses` tells.
"""

from __future__ import annotations

import ipaddress
import time

from PySide6.QtNetwork import QNetworkInterface

OFF, COMPUTER, NETWORK = "off", "computer", "network"
CHOICES = (OFF, COMPUTER, NETWORK)
#: Hop limits: 0 keeps a datagram on this computer, 1 lets it onto the local
#: network and no further, as no router passes it on.
LOCAL_ONLY, LOCAL_NETWORK = 0, 1

#: This computer only unless chosen otherwise: what was done before there was
#: a choice, so nothing that worked stops working.
_reach = COMPUTER


def set_reach(reach: str) -> None:
    global _reach
    _reach = reach if reach in CHOICES else COMPUTER


def reach() -> str:
    return _reach


def is_off() -> bool:
    return _reach == OFF


def hop_limit() -> int:
    return LOCAL_NETWORK if _reach == NETWORK else LOCAL_ONLY


def where() -> str:
    """Where it goes, in words: "this computer only", say."""
    return {OFF: "nowhere", COMPUTER: "this computer only", NETWORK: "the local network"}[_reach]


class OwnAddresses:
    """This computer's addresses, looked up again when a stranger turns up.

    Again rather than once: an adapter that gets a new address, or a VPN
    coming up, would otherwise make this computer's own datagrams look like
    another's. At most once a second, so a flood from another computer costs
    a set lookup each rather than a walk of the adapters.
    """

    REFRESH_S = 1.0

    def __init__(self) -> None:
        self._known: set = set()
        self._looked = 0.0
        self._refresh()

    def _refresh(self) -> None:
        found = set()
        for address in QNetworkInterface.allAddresses():
            parsed = _parse(address.toString())
            if parsed is not None:
                found.add(parsed)
        self._known, self._looked = found, time.monotonic()

    def __contains__(self, host: str) -> bool:
        parsed = _parse(host)
        if parsed is None:
            return False
        if parsed in self._known or parsed.is_loopback:
            return True
        if time.monotonic() - self._looked >= self.REFRESH_S:
            self._refresh()
        return parsed in self._known


def _parse(host: str):
    """An address without its IPv6 zone (fe80::1%eth0), or None. An IPv4
    address carried as IPv6 (::ffff:192.168.1.5) is taken as the IPv4 one."""
    try:
        parsed = ipaddress.ip_address(str(host).split("%", 1)[0])
    except ValueError:
        return None
    mapped = getattr(parsed, "ipv4_mapped", None)
    return mapped if mapped is not None else parsed
