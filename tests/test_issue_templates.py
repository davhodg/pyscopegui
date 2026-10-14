# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The issue templates and policy files, checked against the application they describe.

A template that sends people to a menu entry which has since been renamed
costs a round of questions on every report, and nothing about the template
would ever say so. So what it quotes is read back from the real thing.
"""

from pathlib import Path

from pyscopegui import backends

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / ".github" / "ISSUE_TEMPLATE"
SECURITY_FORM = "https://github.com/davhodg/pyscopegui/security/advisories/new"


def read(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def test_each_form_has_what_github_needs():
    for name in ("bug_report.yml", "feature_request.yml"):
        text = read(name)
        assert text.startswith("name: "), name
        assert "\ndescription: " in text and "\nbody:\n" in text, name


def test_security_reports_go_where_the_policy_sends_them():
    assert SECURITY_FORM in read("config.yml")
    assert SECURITY_FORM in (ROOT / "SECURITY.md").read_text(encoding="utf-8")


def test_the_manual_link_is_the_manual():
    assert "blob/master/pyscopegui/help/manual.md" in read("config.yml")
    assert (ROOT / "pyscopegui" / "help" / "manual.md").is_file()


def test_the_menu_entries_the_forms_name_exist(window):
    """Help > Diagnostics... is where a bug report is sent for its details."""
    entries = [action.text() for action in window.help_menu.menu.actions()]
    assert "Diagnostics..." in entries
    assert "*Help > Diagnostics...*" in read("bug_report.yml")
    assert any(entry.startswith("About ") for entry in entries)
    assert "*Help > About pyscopegui*" in (ROOT / "SECURITY.md").read_text(encoding="utf-8")


def test_the_library_variable_the_security_policy_names_is_the_real_one():
    from pyscopegui.backends import picoscope2000, picoscope2000a

    policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert f"`{picoscope2000.LIBRARY_ENV}`" in policy
    assert f"`{picoscope2000a.LIBRARY_ENV}`" in policy


def test_the_launchers_the_bug_form_names_exist():
    assert "pyscopegui.cmd or pyscopegui.sh" in read("bug_report.yml")
    assert (ROOT / "pyscopegui.cmd").is_file() and (ROOT / "pyscopegui.sh").is_file()


def test_the_policy_files_the_readme_and_contributing_point_at_exist():
    for document in ("README.md", "CONTRIBUTING.md"):
        text = (ROOT / document).read_text(encoding="utf-8")
        for linked in ("SECURITY.md", "CODE_OF_CONDUCT.md"):
            assert f"]({linked})" in text, f"{document} does not link {linked}"
            assert (ROOT / linked).is_file()


def test_the_code_of_conduct_is_about_this_project():
    text = (ROOT / "CODE_OF_CONDUCT.md").read_text(encoding="utf-8")
    assert "for pyscopegui, the maintainer" in text
    assert "pycangui" not in text


def test_every_instrument_can_be_named_in_a_bug_report():
    """The form's list has a way to say each one, or to say it is another."""
    form = read("bug_report.yml")
    assert "Demo signals" in form and "ps2000" in form and "Another" in form
    assert "DS1000Z" in form and "TPS 2000" in form and "ps2000a" in form
    assert len(backends.names()) == 5, "a new instrument wants an entry in bug_report.yml"


def test_questions_are_sent_to_discussions():
    discussions = "https://github.com/davhodg/pyscopegui/discussions"
    assert discussions in read("config.yml")
    assert discussions in (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
