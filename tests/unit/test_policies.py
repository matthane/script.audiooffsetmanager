"""Unit tests for aom.domain.policies — parsing, completeness, gating.

parse_delay_ms behavior is verbatim from ActiveMonitor.convert_delay_to_ms
(also pinned via delegation by tests/unit/test_delay_parsing.py); the direct
cases here keep coverage when the legacy module is deleted in Phase 7.
"""

import pytest

from resources.lib.aom.domain import policies
from resources.lib.aom.domain.profile import StreamProfile

NNBSP = " "


def make_profile(hdr_type="hdr10", fps_type=23, audio_format="truehd"):
    return StreamProfile(
        hdr_type=hdr_type,
        fps_type=fps_type,
        audio_format=audio_format,
        video_fps=23,
        player_id=1,
        audio_channels=6,
    )


# --- parse_delay_ms ----------------------------------------------------------

@pytest.mark.parametrize("delay_str, expected", [
    ("-0.075 s", -75),
    ("0.075 s", 75),
    ("-0,075 s", -75),              # comma decimal
    ("-0.075" + NNBSP + " s", -75),  # NNBSP before regular-space unit
    ("-15.5 s", -10000),             # clamps low
    ("20 s", 10000),                 # clamps high
])
def test_parse_delay_ms_valid(delay_str, expected):
    assert policies.parse_delay_ms(delay_str) == expected


@pytest.mark.parametrize("delay_str", ["abc", "", None, "s"])
def test_parse_delay_ms_junk_returns_none(delay_str):
    assert policies.parse_delay_ms(delay_str) is None


def test_parse_delay_ms_nnbsp_sole_separator_pinned_limitation():
    # Verbatim Phase 1 move keeps the known limitation (fix lands in Phase 6):
    # NNBSP directly against the unit fails to parse.
    assert policies.parse_delay_ms("-0.075" + NNBSP + "s") is None


# --- is_complete -------------------------------------------------------------

def test_is_complete_none_profile():
    assert policies.is_complete(None) is False


def test_is_complete_full_profile():
    assert policies.is_complete(make_profile()) is True
    assert policies.is_complete(make_profile(fps_type="all")) is True


@pytest.mark.parametrize("kwargs", [
    {"hdr_type": "unknown"},
    {"fps_type": "unknown"},
    {"audio_format": "unknown"},
])
def test_is_complete_any_unknown_axis(kwargs):
    assert policies.is_complete(make_profile(**kwargs)) is False


# --- should_apply ------------------------------------------------------------

def test_should_apply_ok():
    assert policies.should_apply(make_profile(), new_install=False,
                                 hdr_enabled=True) == (True, None)


def test_should_apply_new_install_blocks_first():
    # new_install is checked before anything else (mirrors legacy order).
    assert policies.should_apply(None, new_install=True,
                                 hdr_enabled=False) == (False, "new_install")


def test_should_apply_no_profile():
    assert policies.should_apply(None, new_install=False,
                                 hdr_enabled=False) == (False, "no_profile")


def test_should_apply_unknown_format():
    profile = make_profile(audio_format="unknown")
    assert policies.should_apply(profile, new_install=False,
                                 hdr_enabled=True) == (False, "unknown_format")


def test_should_apply_hdr_disabled():
    assert policies.should_apply(make_profile(), new_install=False,
                                 hdr_enabled=False) == (False, "hdr_disabled")
