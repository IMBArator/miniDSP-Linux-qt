"""24-bit level feed and per-channel clip indication.

Covers the payload adapter in ``minidspqt.levels`` (24-bit keys, the
uint16 fallback, short lists), the meter's clip latch (decided on the raw
sample, held for ``CLIP_HOLD`` frames, overridable by the device's own
flag), the re-zoned bar, and the plumbing through the views.

Every threshold comes from the protocol library via ``minidspqt.levels``;
no literal clip level or 24-bit scale factor appears here, so the tests
keep passing when the calibration or the editor's clip point is corrected
upstream.
"""

from __future__ import annotations

import math

import pytest

from minidspqt.levels import (
    LEVEL24_PER_UINT16,
    LEVEL_CLIP_LEVEL24,
    ChannelLevels,
    clip_for,
    level24_for,
    level24_to_dbu,
    levels_from_payload,
)
from minidspqt.views.detail_view import RoutedMetersPanel
from minidspqt.views.home_view import HomeView
from minidspqt.widgets.level_meter import (
    CLIP_HOLD,
    DB_FLOOR,
    NUM_SEGMENTS,
    RED_SEGMENTS,
    LevelMeter,
    _db_ceil,
    _db_to_segments,
)

BELOW_CLIP = math.floor(LEVEL_CLIP_LEVEL24)
AT_CLIP = math.ceil(LEVEL_CLIP_LEVEL24)
CLIP_UINT16 = math.ceil(LEVEL_CLIP_LEVEL24 / LEVEL24_PER_UINT16)
MAX_LEVEL_SEGMENTS = NUM_SEGMENTS - RED_SEGMENTS


@pytest.fixture
def meter(qtbot):
    m = LevelMeter()
    qtbot.addWidget(m)
    return m


def _payload(inputs24, outputs24=None, clipping=None):
    """Build a modern poll payload carrying the 24-bit keys."""
    outputs24 = outputs24 if outputs24 is not None else [0, 0, 0, 0]
    payload = {
        "inputs": [v // LEVEL24_PER_UINT16 for v in inputs24],
        "outputs": [v // LEVEL24_PER_UINT16 for v in outputs24],
        "inputs24": list(inputs24),
        "outputs24": list(outputs24),
        "limiter_mask": 0,
        "state": 0,
    }
    if clipping is not None:
        payload["clipping"] = clipping
    return payload


# --- payload adapter ---------------------------------------------------


def test_adapter_prefers_the_24_bit_keys():
    flags = [True] + [False] * 7
    lv = levels_from_payload(_payload([AT_CLIP, 1, 2, 3], [4, 5, 6, 7], flags))
    assert lv.inputs24 == [AT_CLIP, 1, 2, 3]
    assert lv.outputs24 == [4, 5, 6, 7]
    assert lv.clipping == flags
    assert level24_for(lv, 0) == AT_CLIP
    assert level24_for(lv, 4) == 4
    assert clip_for(lv, 0) is True
    assert clip_for(lv, 1) is False


def test_adapter_scales_a_legacy_payload():
    lv = levels_from_payload(
        {"inputs": [100, 0, 0, 0], "outputs": [50, 0, 0, 0], "limiter_mask": 0}
    )
    assert lv.inputs24 == [100 * LEVEL24_PER_UINT16, 0, 0, 0]
    assert lv.outputs24 == [50 * LEVEL24_PER_UINT16, 0, 0, 0]
    assert lv.clipping is None
    assert clip_for(lv, 0) is None


def test_adapter_ignores_a_short_clipping_list():
    lv = levels_from_payload(_payload([0, 0, 0, 0], clipping=[True, False]))
    assert lv.clipping is None


def test_adapter_reports_missing_channels_as_none():
    lv = levels_from_payload({"inputs": [10, 20], "outputs": []})
    assert level24_for(lv, 1) == 20 * LEVEL24_PER_UINT16
    assert level24_for(lv, 2) is None
    assert level24_for(lv, 4) is None
    assert level24_for(lv, -1) is None
    assert clip_for(ChannelLevels([], [], None), 0) is None


# --- bar zoning --------------------------------------------------------


def test_db_ceiling_is_the_clip_point():
    assert _db_ceil() == pytest.approx(level24_to_dbu(LEVEL_CLIP_LEVEL24))


def test_level_never_lights_the_red_segment():
    assert _db_to_segments(float("-inf")) == 0
    assert _db_to_segments(DB_FLOOR) == 0
    for db in (-49.0, -20.0, -0.1, 0.0, 1.0, _db_ceil() - 0.01):
        assert 0 <= _db_to_segments(db) < MAX_LEVEL_SEGMENTS
    for db in (_db_ceil(), _db_ceil() + 20.0, 200.0):
        assert _db_to_segments(db) == MAX_LEVEL_SEGMENTS


# --- clip decision -----------------------------------------------------


def test_clip_is_decided_on_the_raw_sample(meter):
    meter.set_level(BELOW_CLIP)
    assert meter.is_clipping is False
    meter.set_level(AT_CLIP)
    assert meter.is_clipping is True


def test_a_single_clipping_frame_survives_the_smoothing(meter):
    """One loud frame lights the LED even though the EMA stays below clip."""
    meter.set_level(AT_CLIP)
    assert meter.is_clipping is True
    # The smoothed level is only a fraction of the sample, so the bar is
    # still in the yellow zone — the LED cannot be coming from the bar.
    assert meter.current_db < _db_ceil()
    assert meter.value() < MAX_LEVEL_SEGMENTS


def test_clip_latch_holds_then_releases(meter):
    meter.set_level(2 * LEVEL_CLIP_LEVEL24)
    assert meter.is_clipping is True
    assert meter.value() < NUM_SEGMENTS  # the bar never reaches the red index

    for frame in range(1, CLIP_HOLD):
        meter.set_level(0)
        assert meter.is_clipping is True, f"released early at frame {frame}"
        assert meter.value() < NUM_SEGMENTS

    meter.set_level(0)
    assert meter.is_clipping is False


def test_the_device_flag_wins_over_the_level(meter):
    meter.set_level(1000, clipping=True)
    assert meter.is_clipping is True
    meter.reset()
    meter.set_level(2 * LEVEL_CLIP_LEVEL24, clipping=False)
    assert meter.is_clipping is False


def test_reset_clears_the_latch(meter):
    meter.set_level(AT_CLIP)
    assert meter.is_clipping is True
    meter.reset()
    assert meter.is_clipping is False
    assert meter.value() == 0


# --- 24-bit resolution -------------------------------------------------


def test_the_low_byte_changes_the_readout(qtbot):
    """Two levels sharing a uint16 must not produce the same dB value."""
    coarse, fine = LevelMeter(), LevelMeter()
    qtbot.addWidget(coarse)
    qtbot.addWidget(fine)
    base = 80 * LEVEL24_PER_UINT16
    coarse.set_level(base)
    fine.set_level(base + LEVEL24_PER_UINT16 - 56)
    assert coarse.current_db != fine.current_db


# --- plumbing through the views ----------------------------------------


@pytest.fixture
def home(qtbot):
    v = HomeView()
    qtbot.addWidget(v)
    return v


def _home_clip_flags(view):
    return [s.meter.is_clipping for s in view._input_strips + view._output_strips]


def test_home_view_lights_only_the_clipping_channel(home):
    flags = [True] + [False] * 7
    home.update_levels(_payload([AT_CLIP, 0, 0, 0], clipping=flags))
    assert _home_clip_flags(home) == flags


def test_home_view_falls_back_to_the_legacy_payload(home):
    home.update_levels(
        {
            "inputs": [CLIP_UINT16, 0, 0, 0],
            "outputs": [0, 0, 0, 0],
            "limiter_mask": 0,
        }
    )
    assert _home_clip_flags(home) == [True] + [False] * 7


def test_home_view_resets_a_missing_channel(home):
    home.update_levels(_payload([AT_CLIP, 0, 0, 0], clipping=[True] + [False] * 7))
    home.update_levels({"inputs": [], "outputs": [], "limiter_mask": 0})
    assert _home_clip_flags(home) == [False] * 8
    assert home._input_strips[0].meter.value() == 0


def test_routed_meters_panel_lights_the_clipping_channel(qtbot):
    panel = RoutedMetersPanel()
    qtbot.addWidget(panel)
    panel.set_channels([0, 4])
    panel.update_levels(
        _payload(
            [AT_CLIP, 0, 0, 0],
            [AT_CLIP, 0, 0, 0],
            clipping=[True] + [False] * 3 + [False] * 4,
        )
    )
    in_meter = panel._meters[0][2]
    out_meter = panel._meters[1][2]
    # Input 0's flag says clipping; output 0's flag says it is not, and the
    # device flag wins over its (equally loud) level.
    assert in_meter.is_clipping is True
    assert out_meter.is_clipping is False
