# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The changelog: in the manual, in Keep a Changelog form, and the source of
each release's description."""

import importlib
import re
import sys
from pathlib import Path

from pyscopegui import __version__
from pyscopegui.help import PAGES, page_text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
release_notes = importlib.import_module("release_notes")

TEXT = page_text("changelog.md")
HEADINGS = [m.group(0) for m in release_notes.HEADING.finditer(TEXT)]
GROUPS = {"Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"}


def test_it_is_a_page_of_the_manual():
    assert "changelog.md" in PAGES and TEXT
    assert "(changelog.md)" in page_text("manual.md"), "and the contents lead to it"


def test_unreleased_comes_first():
    assert HEADINGS[0] == "## [Unreleased]"


def test_the_version_being_worked_on_has_its_notes():
    """Under its own heading once it is released, and under Unreleased until then.

    A tag with no section of its own would make a release with no
    description, and the release job stops on that; see the last test here.
    """
    assert release_notes.section(__version__, TEXT) or release_notes.section("Unreleased", TEXT)


def test_every_version_is_dated_and_newest_first():
    released = [
        re.fullmatch(r"## \[(\d+(?:\.\d+)*)\] - \d{4}-\d{2}-\d{2}", h) for h in HEADINGS[1:]
    ]
    assert all(released), "each is '## [x.y.z] - YYYY-MM-DD'"
    versions = [tuple(int(n) for n in m.group(1).split(".")) for m in released]
    assert versions == sorted(versions, reverse=True)


def test_changes_are_grouped_as_the_format_names_them():
    used = set(re.findall(r"^### (.+)$", TEXT, re.M))
    assert used and used <= GROUPS, used - GROUPS


def test_a_release_s_notes_are_its_section_on_one_line_per_item():
    """GitHub keeps every line break in a release description, so wrapped
    lines would break each item part way through a sentence."""
    text = (
        "## [Unreleased]\n\n### Fixed\n\n- Something small.\n\n"
        "## [1.0.0] - 2026-01-02\n\nIntro that is\nwrapped.\n\n### Added\n\n"
        "- **A thing** that goes on\n  over two lines.\n- Another.\n\n"
        "## [0.9.0] - 2025-12-01\n\n### Added\n\n- Old.\n\n"
        "[1.0.0]: https://example/1.0.0\n"
    )
    assert release_notes.section("1.0.0", text) == (
        "Intro that is wrapped.\n\n### Added\n\n"
        "- **A thing** that goes on over two lines.\n- Another.\n"
    )
    assert release_notes.section("0.9.0", text) == "### Added\n\n- Old.\n", "no link lines"
    assert release_notes.section("2.0.0", text) is None


def test_a_list_inside_an_item_keeps_one_line_per_item():
    text = (
        "## [1.0.0] - 2026-01-02\n\n### Changed\n\n- Transmit:\n"
        "  - one that goes on\n    over two lines.\n  - two.\n- After.\n"
    )
    assert release_notes.section("1.0.0", text) == (
        "### Changed\n\n- Transmit:\n  - one that goes on over two lines.\n  - two.\n- After.\n"
    )


def test_a_tag_with_no_notes_stops_the_release(tmp_path, monkeypatch):
    changelog = tmp_path / "changelog.md"
    changelog.write_text(
        "## [Unreleased]\n\n## [1.2.3] - 2026-01-02\n\n### Added\n\n- A thing.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(release_notes, "CHANGELOG", changelog)
    out = tmp_path / "notes.md"
    assert release_notes.main(["release_notes.py", "v99.0.0", str(out)]) == 1
    assert not out.exists()
    assert release_notes.main(["release_notes.py", "v1.2.3", str(out)]) == 0
    said = out.read_text(encoding="utf-8")
    assert said.startswith("### Added\n\n- A thing.")
    assert "not code-signed" in said, "and it says so while releases are unsigned"
