"""Device-busy chip — both views render it, and offline mode ignores it.

When another process holds the DSP the worker keeps retrying, so the UI must
say *why* nothing is happening instead of showing a plain "Disconnected".
These tests cover the two view renderings (text, the QSS ``state`` property
and the explanatory tooltip) plus MainWindow's mediation: in offline mode the
signal is dropped, because a VirtualDSP session can never be blocked by
another program and the chip must keep reading "Offline".
"""

from __future__ import annotations

import pytest

from minidspqt.views.detail_view import DetailView
from minidspqt.views.home_view import HomeView
from minidspqt.views.main_window import MainWindow


@pytest.fixture
def home(qtbot):
    v = HomeView()
    qtbot.addWidget(v)
    return v


@pytest.fixture
def detail(qtbot):
    v = DetailView()
    qtbot.addWidget(v)
    return v


def _chip(view):
    """Return the connection chip of either view (the attribute names differ)."""
    if hasattr(view, "connectionLabel"):
        return view.connectionLabel
    return view._connection_label


@pytest.fixture(params=["home", "detail"])
def view(request, home, detail):
    """Both views in turn — their chip behaviour is specified to be identical."""
    return home if request.param == "home" else detail


class TestChipRendering:
    def test_busy_shows_labelled_chip_with_help(self, view):
        view.set_connected(False)
        view.set_device_busy(True)

        chip = _chip(view)
        assert chip.text() == "Device busy"
        assert chip.property("state") == "busy"
        # The tooltip is the only place the user learns what to do.
        assert "holding the DSP" in chip.toolTip()

    def test_clearing_busy_reverts_to_disconnected(self, view):
        view.set_device_busy(True)
        view.set_device_busy(False)

        chip = _chip(view)
        assert chip.text() == "Disconnected"
        assert chip.property("state") == "disconnected"
        assert chip.toolTip() == ""

    def test_connecting_drops_a_leftover_tooltip(self, view):
        view.set_device_busy(True)
        view.set_connected(True)

        chip = _chip(view)
        assert chip.text() == "Connected"
        assert chip.toolTip() == ""

    def test_offline_mode_drops_a_leftover_tooltip(self, view):
        view.set_device_busy(True)
        view.set_offline_mode()

        chip = _chip(view)
        assert chip.text() == "Offline"
        assert chip.toolTip() == ""

    def test_busy_leaves_strips_disabled(self, home):
        """The chip is informational — there is still no session to write to."""
        home.set_connected(False)
        home.set_device_busy(True)

        # set_enabled_state(False) disables the strip's controls, not the
        # strip widget itself, so the gain knob is what to look at.
        assert not any(s._knob.isEnabled() for s in home._all_strips())


class TestMainWindowMediation:
    """ADR-0006: the window filters worker signals; the views stay passive."""

    def test_offline_window_ignores_device_busy(self, qtbot):
        w = MainWindow(offline=True)
        qtbot.addWidget(w)
        w._thread.request_stop()
        w._thread.wait(2000)
        qtbot.wait(50)

        w._on_device_busy(True)

        assert w._home_view.connectionLabel.text() == "Offline"
        assert w._detail_view._connection_label.text() == "Offline"

    def test_online_window_forwards_device_busy_to_both_views(self, qtbot, fake_dsp):
        w = MainWindow(offline=False, dsp_instance=fake_dsp)
        qtbot.addWidget(w)
        w._thread.request_stop()
        w._thread.wait(2000)
        qtbot.wait(50)

        w._on_device_busy(True)

        assert w._home_view.connectionLabel.text() == "Device busy"
        assert w._detail_view._connection_label.text() == "Device busy"

    def test_device_busy_is_wired_to_the_worker(self, qtbot, fake_dsp):
        """The signal must actually be connected, not just handled."""
        w = MainWindow(offline=False, dsp_instance=fake_dsp)
        qtbot.addWidget(w)
        w._thread.request_stop()
        w._thread.wait(2000)
        qtbot.wait(50)

        w._thread.device_busy.emit(True)
        qtbot.wait(50)  # queued connection: let the delivery happen

        assert w._home_view.connectionLabel.text() == "Device busy"
