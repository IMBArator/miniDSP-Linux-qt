"""About dialog HTML — app version always shown, device/firmware when known.

`_about_html` is a pure string builder so it can be asserted without popping a
modal. Covers the connected (model + firmware) and disconnected (offline /
not-connected status line) branches.
"""

from __future__ import annotations

import pytest

from minidspqt.views.main_window import MainWindow


def _stop_worker(window, qtbot):
    """Stop the background device thread so teardown is clean."""
    window._thread.request_stop()
    window._thread.wait(2000)
    qtbot.wait(50)


@pytest.fixture
def offline_window(qtbot):
    w = MainWindow(offline=True)
    qtbot.addWidget(w)
    _stop_worker(w, qtbot)
    return w


@pytest.fixture
def online_window(qtbot, fake_dsp):
    w = MainWindow(offline=False, dsp_instance=fake_dsp)
    qtbot.addWidget(w)
    _stop_worker(w, qtbot)
    return w


class TestAboutHtml:
    def test_app_version_always_shown(self, offline_window):
        from minidspqt import __version__

        html = offline_window._about_html()
        assert "DSP 4x4 Mini" in html
        assert f"v{__version__}" in html

    def test_offline_shows_offline_status(self, offline_window):
        html = offline_window._about_html()
        assert "Offline mode" in html
        assert "Device:" not in html

    def test_online_without_firmware_shows_not_connected(self, online_window):
        # Online but no firmware learned yet (fake DSP carries none).
        online_window._state.firmware_model = ""
        html = online_window._about_html()
        assert "Not connected" in html
        assert "Offline mode" not in html

    def test_firmware_shown_when_known(self, offline_window):
        offline_window._state.firmware_model = "4x4MINI"
        offline_window._state.firmware_version = "V010"
        html = offline_window._about_html()
        assert "4x4MINI" in html
        assert "V010" in html
        assert "Offline mode" not in html
        assert "Not connected" not in html

    def test_firmware_version_missing_falls_back_to_dash(self, offline_window):
        offline_window._state.firmware_model = "4x4MINI"
        offline_window._state.firmware_version = ""
        html = offline_window._about_html()
        assert "4x4MINI" in html
        assert "—" in html  # firmware value placeholder
