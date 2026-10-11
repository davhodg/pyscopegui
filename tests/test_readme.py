# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The badges on the README, checked against what they claim to describe,
and the classifiers PyPI shows beside them.

A badge is a fact stated somewhere nobody will think to update. The static
ones -- the Python floor, the platforms and the licence -- are read back from
pyproject.toml here; the CI, release and PyPI badges are fetched live and only
need to be present.

The release badge asks for pre-releases too. Without that, a repository with
no releases reads "no releases or repo not found", which looks like a fault
rather than the plain fact that nothing is tagged yet.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
REPOSITORY = "https://github.com/davhodg/pyscopegui"


def badge(label: str) -> str:
    """The message part of ``![label](.../badge/label-message-colour)``."""
    # Greedy, and the colour anchors the end: a message can itself contain a
    # dash, which shields writes doubled -- "Apache--2.0".
    found = re.search(
        rf"!\[{label}\]\(https://img\.shields\.io/badge/{label}-(.+)-[a-z]+\)", README
    )
    assert found, f"no {label} badge on the page"
    return found.group(1)


def test_the_python_badge_is_the_floor_the_project_declares():
    floor = PROJECT["requires-python"].lstrip(">=").strip()
    assert badge("python") == f"{floor}+"


def test_the_licence_badge_is_the_licence():
    assert badge("license").replace("--", "-") == PROJECT["license"]


def test_the_platform_badge_names_the_systems_the_classifiers_do():
    named = badge("platform").replace("%20", " ").replace("%7C", "|")
    systems = [
        c.rsplit(" :: ", 1)[1]
        for c in PROJECT["classifiers"]
        if c.startswith("Operating System :: ")
    ]
    assert [part.strip() for part in named.split("|")] == systems


def test_the_ci_badge_is_the_live_one():
    """The workflow's own badge, so a static "passing" cannot be left behind to lie."""
    live = f"[![CI]({REPOSITORY}/actions/workflows/ci.yml/badge.svg)]"
    assert live in README
    assert f"]({REPOSITORY}/actions/workflows/ci.yml)" in README
    assert (ROOT / ".github" / "workflows" / "ci.yml").is_file()
    assert "img.shields.io/badge/tests-" not in README


def test_the_release_badge_is_live():
    """Live rather than a static version number: until something is tagged it
    says so, and after that it cannot disagree with the releases page."""
    live = "https://img.shields.io/github/v/release/davhodg/pyscopegui?include_prereleases"
    assert f"[![release]({live})]({REPOSITORY}/releases)" in README
    assert "img.shields.io/badge/version-" not in README


def test_the_pypi_badge_is_live_and_names_the_package():
    name = PROJECT["name"]
    assert (
        f"[![PyPI](https://img.shields.io/pypi/v/{name})](https://pypi.org/project/{name}/)"
        in README
    )


def test_the_python_classifiers_start_at_the_floor():
    """The versions listed are the ones requires-python allows, from its floor up."""
    floor = PROJECT["requires-python"].lstrip(">=").strip()
    listed = [
        c.rsplit(" :: ", 1)[1]
        for c in PROJECT["classifiers"]
        if re.fullmatch(r"Programming Language :: Python :: 3\.\d+", c)
    ]
    assert listed and listed[0] == floor
    assert "Programming Language :: Python :: 3 :: Only" in PROJECT["classifiers"]


def test_the_licence_and_notice_are_links():
    assert "[LICENSE](LICENSE)" in README and "[NOTICE](NOTICE)" in README
    assert (ROOT / "LICENSE").is_file() and (ROOT / "NOTICE").is_file()


# --- the page PyPI shows -------------------------------------------------------------------------
PYPI = (ROOT / "PYPI.md").read_text(encoding="utf-8")


def test_pypi_is_shown_the_page_written_for_it():
    import tomllib

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["readme"] == "PYPI.md"


def test_the_pypi_page_has_no_link_or_picture_pypi_cannot_follow():
    """PyPI has only the page: anything relative to the repository is broken there."""
    import re

    targets = re.findall(r"\]\(([^)]+)\)", PYPI) + re.findall(r'src="([^"]+)"', PYPI)
    assert targets, "there are links to check"
    assert [t for t in targets if not t.startswith("https://")] == []


def test_the_pypi_page_opens_as_the_readme_does():
    opening = "Oscilloscopes and logic analysers in one view"
    assert opening in README and opening in PYPI


def test_every_instrument_in_the_readme_is_on_the_pypi_page():
    import re

    named = re.findall(
        r"^- \*\*([^*]+)\*\*", README.split("## Instruments")[1].split("##")[0], re.M
    )
    assert named and all(f"**{name}**" in PYPI for name in named)
