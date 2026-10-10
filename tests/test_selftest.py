# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""`--selftest`, which is what the build check runs the built application with."""

from pyscopegui import __main__ as entry


def test_a_source_folder_passes_its_own_self_test():
    assert entry.selftest() == 0


def test_a_missing_module_fails_it(monkeypatch, capsys):
    monkeypatch.setattr(entry, "SELFTEST_MODULES", ("pyscopegui.no_such_module",))
    assert entry.selftest() == 1
    assert "no_such_module" in capsys.readouterr().err


def test_x11_libraries_are_only_asked_about_on_linux_under_x11(monkeypatch):
    monkeypatch.setattr(entry.sys, "platform", "linux")
    assert entry.uses_xcb({})
    assert not entry.uses_xcb({"XDG_SESSION_TYPE": "wayland"})
    assert not entry.uses_xcb({"QT_QPA_PLATFORM": "offscreen"})
    monkeypatch.setattr(entry.sys, "platform", "win32")
    assert not entry.uses_xcb({})


def test_missing_x11_libraries_are_named_by_package():
    def load(library):
        if "cursor" in library:
            raise OSError(library)

    assert entry.missing_xcb_packages(load) == ["libxcb-cursor0"]
