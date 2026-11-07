# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Tools > Reset: the layout, the folders file dialogs remember, and everything -- which
is a new workspace rather than anything undone in place."""

from PySide6.QtWidgets import QMessageBox

from pyscopegui.ui import main_window
from pyscopegui.ui.main_window import REMEMBERED_FOLDERS


def entries(window):
    return [a.text() for a in window.reset_menu.actions() if not a.isSeparator()]


def test_it_is_under_tools_with_the_layout_the_folders_and_everything(window):
    tools = window.settings_menu.parent()
    assert window.reset_menu.menuAction() in tools.actions()
    assert entries(window) == ["Reset layout", "Forget remembered folders", "Reset everything..."]
    # The same action as under View, not a second one that could drift from it.
    assert window.reset_layout_action in window.reset_menu.actions()


def test_forgetting_the_folders_puts_each_dialog_back_and_says_how_many(window, app):
    window.ctx.settings.set(main_window.CAPTURE_FOLDER, "C:/captures")
    window.ctx.settings.set(main_window.SCRIPT_FOLDER, "C:/scripts")
    window._forget_folders()
    app.processEvents()
    assert all(window.ctx.settings.get(key) is None for key in REMEMBERED_FOLDERS)
    assert "Forgot 2 remembered folder(s)" in window.log.toPlainText()
    window._forget_folders()
    app.processEvents()
    assert "No folders were being remembered." in window.log.toPlainText()


def test_forgetting_the_folders_leaves_every_other_setting(window):
    window.ctx.settings.set(main_window.HISTORY_KEY, 5.0)
    window.ctx.settings.set(main_window.EXPORT_FOLDER, "C:/exports")
    window._forget_folders()
    assert window.ctx.settings.get(main_window.HISTORY_KEY) == 5.0


def answer_with(monkeypatch, text):
    """Press the button with this text when the message box comes up."""

    def exec_(box):
        box._pressed = next(b for b in box.buttons() if b.text() == text)
        return 0

    monkeypatch.setattr(QMessageBox, "exec", exec_)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda box: box._pressed)


def test_resetting_everything_offers_a_new_workspace(window, monkeypatch):
    asked = []
    monkeypatch.setattr(window.workspace_menu, "new_empty", lambda: asked.append(True))
    answer_with(monkeypatch, "New workspace...")
    window._reset_everything()
    assert asked == [True]


def test_cancelling_reset_everything_changes_nothing(window, monkeypatch):
    asked = []
    monkeypatch.setattr(window.workspace_menu, "new_empty", lambda: asked.append(True))
    answer_with(monkeypatch, "Cancel")
    window._reset_everything()
    assert asked == []
