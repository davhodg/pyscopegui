# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Whether a scope with knobs of its own has what it was sent.

A Rigol or a Tektronix set up from here holds its settings itself, and they
can be changed at the bench too. So what it was sent is asked back: once it
is open, to say where the pane and the scope differ, and after every change,
to say when the scope has taken it -- or that it would not.
"""

from __future__ import annotations

import math

#: On and off, as a scope may say them back.
_ON_OFF = {"ON": "1", "OFF": "0"}
#: How near two numbers have to be to be the same: a scope says back
#: "1.000000e-03" for 1e-3, and rounds a little.
_NEAR = 1e-3


def same(sent: str, said: str, close: float = 0.0) -> bool:
    """Whether what the scope says it has is what it was sent. Numbers within
    a thousandth of each other, or ``close``; words in their short form or in
    full, as a scope says either -- DC and DC, POS and POSITIVE; ON as 1."""
    sent, said = sent.strip().strip('"').upper(), said.strip().strip('"').upper()
    if not said:
        return False
    sent, said = _ON_OFF.get(sent, sent), _ON_OFF.get(said, said)
    try:
        wanted, has = float(sent), float(said)
    except ValueError:
        return sent == said or sent.startswith(said) or said.startswith(sent)
    return math.isclose(wanted, has, rel_tol=_NEAR, abs_tol=max(close, 1e-12))
