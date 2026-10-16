# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Instruments on USB, through a VISA library: which are plugged in, and talking to one.

A scope on USB speaks the same commands as it does on a network or a serial
port, so each back end keeps its commands and takes its link from here. What
differs from one maker to the next -- how its instruments are known on the
bus, where a VISA library comes from, what to check when none is found, and
the error it raises -- is a Maker.

pyvisa is imported only when a scope is opened on USB, so that nothing else
needs it, and it in turn needs a VISA library: National Instruments' or
Keysight's, or one a scope maker installs with its own software.
"""

from __future__ import annotations

from dataclasses import dataclass

#: What a VISA library is asked to list: every instrument on USB.
USB_QUERY = "USB?*INSTR"


@dataclass(frozen=True)
class Maker:
    """What is said, and looked for, about one maker's instruments on USB."""

    #: As said in a message: "Rigol", "Tektronix".
    name: str
    #: How its instruments are known on the bus: its USB vendor id, as a VISA
    #: library writes it in hex and in decimal.
    marks: tuple[str, ...]
    #: Where a VISA library comes from, said when there is none.
    library: str
    #: What to check when none of its instruments is found.
    check: str
    #: What the back end raises: its own error, said in words in the Event Log.
    error: type[Exception]
    #: Seconds to wait for an answer.
    answer_s: float

    def owns(self, name: str) -> bool:
        return any(mark in name.upper() for mark in self.marks)


def open_visa():
    """The VISA library's list of what is plugged in. ImportError where pyvisa
    is not installed; whatever the library raises where there is no library."""
    import pyvisa  # here, so that a scope on a network or a serial port does not need it

    return pyvisa.ResourceManager()


def plugged_in(maker: Maker) -> list[tuple[str, str]]:
    """The maker's instruments on USB now, as (serial number, what to call it in a list).

    Nothing where there is no VISA library, or none plugged in: the list is
    then only "first found", and opening says what is wrong.
    """
    try:
        manager = open_visa()
    except Exception:  # no pyvisa, or no library: opening it says so
        return []
    try:
        listed = tuple(manager.list_resources(USB_QUERY))
    except Exception:
        listed = ()
    finally:
        try:
            manager.close()
        except Exception:
            pass
    found = []
    for name in listed:
        if not maker.owns(name):
            continue
        # USB0::0x1AB1::0x04CE::DS1ZA000000000::INSTR: the fourth part is the serial number.
        parts = name.split("::")
        serial = parts[3] if len(parts) > 3 else name
        found.append((serial, f"{serial}   {name}"))
    return found


def find(listed: tuple[str, ...], wanted: str, maker: Maker) -> str | None:
    """Which of the USB instruments a VISA library lists is the one asked for.

    ``wanted`` is a serial number or any other part of the name, or the whole
    of it; empty is the first one of the maker's.
    """
    if wanted:
        return next((name for name in listed if wanted.upper() in name.upper()), None)
    return next((name for name in listed if maker.owns(name)), None)


class VisaLink:
    """Lines of commands to the scope and back, over USB, through a VISA library."""

    def __init__(self, wanted: str, maker: Maker) -> None:
        self._maker = maker
        error = maker.error
        try:
            self._manager = open_visa()
        except ImportError as exc:
            raise error(
                "USB needs pyvisa, which is not installed: pip install pyvisa, and open "
                "the scope again."
            ) from exc
        except Exception as exc:  # each VISA library fails in its own way
            raise error(
                f"No VISA library was found for USB: {str(exc).rstrip('.')}. {maker.library}"
            ) from exc
        try:
            listed = tuple(self._manager.list_resources(USB_QUERY))
            name = find(listed, wanted, maker)
            if name is None:
                found = ", ".join(listed) if listed else "nothing"
                asked = f"matching {wanted!r}" if wanted else f"of {maker.name}'s"
                raise error(
                    f"No scope {asked} was found on USB: the VISA library lists {found}. "
                    f"{maker.check}"
                )
            self._instrument = self._manager.open_resource(name)
            self._instrument.timeout = int(maker.answer_s * 1000)
            self._instrument.write_termination = "\n"
            # None, so that a read ends where the scope says the message ends and
            # not at the first byte of a waveform that happens to be a new line.
            self._instrument.read_termination = None
        except error:
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise error(f"The scope on USB could not be opened: {exc}.") from exc
        self.name = name

    def write(self, command: str) -> None:
        try:
            self._instrument.write(command)
        except Exception as exc:
            raise self._maker.error(f"The scope stopped answering on USB: {exc}.") from exc

    def ask(self, command: str, wait: float | None = None) -> str:
        """Ask, and wait for the answer: for ``wait`` seconds where the scope
        has other things to finish first."""
        if wait is None:
            try:
                return self._instrument.query(command).strip()
            except Exception as exc:
                raise self._fail(command, exc) from exc
        self.write(command)
        return self.answer(command, wait)

    def answer(self, command: str, wait: float | None = None, hint: str = "") -> str:
        """The answer to what was asked last, waited for: for ``wait`` seconds
        where the scope has other things to finish first."""
        before = self._instrument.timeout
        if wait is not None:
            self._instrument.timeout = int(wait * 1000)
        try:
            return bytes(self._instrument.read_raw()).decode("ascii", "replace").strip()
        except Exception as exc:
            raise self._fail(command, exc, hint) from exc
        finally:
            self._instrument.timeout = before

    def ask_bytes(self, command: str) -> bytes:
        """The answer to a query that comes as a block: #, how many digits, how many bytes."""
        error = self._maker.error
        try:
            self._instrument.write(command)
            data = bytes(self._instrument.read_raw())
            if len(data) < 2 or data[:1] != b"#" or not data[1:2].isdigit():
                raise error(f"The scope answered {command} with something else: {data[:8]!r}.")
            digits = int(data[1:2])
            length = int(data[2 : 2 + digits])
            # A long block arrives in more than one piece.
            while len(data) < 2 + digits + length:
                data += bytes(self._instrument.read_raw())
        except error:
            raise
        except Exception as exc:
            raise self._fail(command, exc) from exc
        return data[2 + digits : 2 + digits + length]

    def clear(self) -> None:
        """Throw away whatever the scope had ready that nobody asked for."""
        try:
            self._instrument.clear()
        except Exception:  # not every library, or every scope, has it
            pass

    def _fail(self, command: str, exc: Exception, hint: str = "") -> Exception:
        return self._maker.error(f"The scope did not answer {command} on USB: {exc}.{hint}")

    def close(self) -> None:
        for closing in (getattr(self, "_instrument", None), getattr(self, "_manager", None)):
            try:
                if closing is not None:
                    closing.close()
            except Exception:  # nothing to be done about a library that will not let go
                pass
