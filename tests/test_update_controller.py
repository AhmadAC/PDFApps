"""Tests for app.update_controller.UpdateController (R4 refactor).

The auto-update subsystem was extracted verbatim from MainWindow into a
dedicated controller. These tests pin the behaviour that matters and is
headless-testable:

  * Flatpak/Snap installs short-circuit the check (host handles updates).
  * The controller is a main-thread QObject parented to the window — the
    property that makes the worker's cross-thread ``done`` signal resume
    ``_on_update_found`` on the MAIN thread (the Py3.14-safe pattern; no
    lambda crosses the thread boundary).
  * End-to-end worker wiring: ``check_async`` runs the worker, the queued
    slot resumes on the main thread, ``_update_release`` is populated and
    the worker/thread are torn down.
  * The no-update path leaves ``_update_release`` None and ``release_worker``
    cleans up defensively.
  * The notify decision only opens the update dialog when the user accepts.

GUI limits: the modal QMessageBox in ``_notify_update`` and the real
UpdateDialog in ``show_update_dialog`` are not driven here (they block on
user input); the decision branch is exercised by stubbing the prompt.
"""
import os
import sys
import threading
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QObject, QElapsedTimer
from PySide6.QtWidgets import QApplication, QWidget, QPushButton, QMessageBox

import app.updater as updater_mod
from app.update_controller import UpdateController


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def _spin_until(app, predicate, timeout_ms=8000):
    """Pump the event loop until ``predicate`` is true or we time out."""
    timer = QElapsedTimer()
    timer.start()
    while not predicate() and timer.elapsed() < timeout_ms:
        app.processEvents()
    return predicate()


def _make(qt_app):
    window = QWidget()
    btn = QPushButton(window)
    # MainWindow creates the update button hidden (setVisible(False)); mirror
    # that so isVisibleTo reflects whether _notify_update revealed it.
    btn.setVisible(False)
    ctrl = UpdateController(window, btn)
    return window, btn, ctrl


# ── Flatpak / Snap short-circuit ───────────────────────────────────────


@pytest.mark.parametrize("var", ["FLATPAK_ID", "SNAP"])
def test_check_async_short_circuits_in_managed_packages(qt_app, monkeypatch, var):
    """Inside Flatpak/Snap the host package manager owns updates, so
    check_async must return before spinning up any worker/thread."""
    monkeypatch.setenv(var, "com.example.whatever")
    _window, _btn, ctrl = _make(qt_app)
    ctrl.check_async()
    assert ctrl._update_thread is None
    assert ctrl._update_worker is None
    assert ctrl._update_cancel is None


# ── Threading contract: main-thread QObject ────────────────────────────


def test_controller_is_main_thread_qobject(qt_app):
    """The controller must be a QObject parented to the window so the
    worker's cross-thread ``done`` signal resumes on the main thread via
    Qt's automatic queued connection (Py3.14-safe; preserved from the
    original MainWindow implementation)."""
    window, _btn, ctrl = _make(qt_app)
    assert isinstance(ctrl, QObject)
    assert ctrl.parent() is window
    assert ctrl.thread() is window.thread()


# ── End-to-end worker wiring ───────────────────────────────────────────


def test_check_async_populates_release_on_main_thread(qt_app, monkeypatch):
    """check_async runs the worker; when an update is found the queued
    slot resumes on the MAIN thread, sets _update_release and tears the
    worker/thread down."""
    release = {"tag_name": "v99.0.0"}
    monkeypatch.setattr(updater_mod, "check_for_update", lambda *a, **k: dict(release))

    main_ident = threading.get_ident()
    recorded = {}

    # Replace the class-level _notify_update (called synchronously from
    # inside the real _on_update_found) so no modal dialog appears and we
    # can record the thread the queued slot resumed on. The Qt connection
    # is to the *real* _on_update_found bound method — the property under
    # test — so thread routing is genuine.
    def fake_notify(self):
        recorded["ident"] = threading.get_ident()
        recorded["release"] = self._update_release
    monkeypatch.setattr(UpdateController, "_notify_update", fake_notify)

    _window, _btn, ctrl = _make(qt_app)
    ctrl.check_async()

    assert _spin_until(qt_app, lambda: "ident" in recorded), \
        "worker never resumed _on_update_found"
    assert recorded["release"] == release
    assert recorded["ident"] == main_ident, \
        "the queued slot must resume on the main thread (Py3.14-safe)"
    assert ctrl._update_release == release
    # _on_update_found tears the worker down after the check.
    assert _spin_until(qt_app, lambda: ctrl._update_worker is None)
    assert ctrl._update_thread is None
    assert ctrl._update_cancel is None


def test_check_async_no_update_leaves_release_none(qt_app, monkeypatch):
    """When check_for_update returns None the worker never emits ``done``;
    _update_release stays None and release_worker cleans up without error."""
    monkeypatch.setattr(updater_mod, "check_for_update", lambda *a, **k: None)
    # Guard: _notify_update must not run on this path.
    monkeypatch.setattr(
        UpdateController, "_notify_update",
        lambda self: pytest.fail("_notify_update must not run when no update"))

    _window, _btn, ctrl = _make(qt_app)
    ctrl.check_async()
    # Give the worker time to finish (it quits its own thread).
    _spin_until(qt_app, lambda: False, timeout_ms=500)
    assert ctrl._update_release is None
    # Simulate the closeEvent teardown path — must be safe even after the
    # worker thread has already finished.
    ctrl.release_worker()
    assert ctrl._update_worker is None
    assert ctrl._update_thread is None
    assert ctrl._update_cancel is None


# ── Notify decision ────────────────────────────────────────────────────


def test_notify_returns_without_prompt_when_release_none(qt_app, monkeypatch):
    """The None-guard short-circuits before touching the button or prompt."""
    _window, btn, ctrl = _make(qt_app)
    ctrl._update_release = None
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: pytest.fail("must not prompt when release is None"))
    assert ctrl._notify_update() is None
    assert not btn.isVisibleTo(_window)


def test_notify_opens_dialog_only_when_user_accepts(qt_app, monkeypatch):
    """_notify_update reveals the button and opens the dialog only when the
    user answers Yes to the install prompt."""
    _window, btn, ctrl = _make(qt_app)
    ctrl._update_release = {"tag_name": "v1.2.3"}
    calls = []
    monkeypatch.setattr(ctrl, "show_update_dialog", lambda: calls.append(1))

    # User declines → button revealed, but no dialog.
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    ctrl._notify_update()
    assert btn.isVisibleTo(_window)
    assert calls == []

    # User accepts → dialog opened.
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    ctrl._notify_update()
    assert calls == [1]
