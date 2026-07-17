"""Characterization tests for aom.domain.profile.StreamProfile.

Pins the behavior of the settings-lookup key (`setting_id()`) and the display
helpers. Written in Phase 0 against the legacy module and retargeted when the
Phase 1 re-export shim was deleted (Phase 7). The setting-id format is frozen:
existing users' stored offsets are keyed by it, so these assertions must
survive every refactor unchanged.

StreamProfile depends only on `dataclasses` (pure Python) — no Kodi stubs needed.
"""

import pytest

from resources.lib.aom.domain.profile import StreamProfile


def make_profile(hdr_type, fps_type, audio_format,
                 video_fps=None, player_id=1, audio_channels=6):
    """Build a StreamProfile; only hdr/fps/audio affect the assertions here."""
    return StreamProfile(
        hdr_type=hdr_type,
        fps_type=fps_type,
        audio_format=audio_format,
        video_fps=video_fps,
        player_id=player_id,
        audio_channels=audio_channels,
    )


# --- setting_id() -----------------------------------------------------------

@pytest.mark.parametrize("hdr_type, fps_type, audio_format, expected", [
    ("dolbyvision", 23, "truehd", "dolbyvision_23_truehd"),
    ("dolbyvision", "all", "truehd", "dolbyvision_all_truehd"),
    ("hdr10", 24, "eac3", "hdr10_24_eac3"),
    ("hdr10plus", 60, "ac3", "hdr10plus_60_ac3"),
    ("hlg", 50, "dtshd_ma", "hlg_50_dtshd_ma"),
    ("sdr", 29, "dca", "sdr_29_dca"),
    ("sdr", "all", "pcm", "sdr_all_pcm"),
    ("hdr10", "all", "dtshd_hra", "hdr10_all_dtshd_hra"),
])
def test_setting_id(hdr_type, fps_type, audio_format, expected):
    assert make_profile(hdr_type, fps_type, audio_format).setting_id() == expected


def test_setting_id_fps_key_stringifies_int_and_str_identically():
    # fps_type may arrive as int (specific bucket) or str; setting_id() must key
    # them identically via str(fps_type).
    assert make_profile("hdr10", 23, "eac3").setting_id() == \
        make_profile("hdr10", "23", "eac3").setting_id()


def test_setting_id_unknown_values_pass_through():
    profile = make_profile("unknown", "unknown", "unknown")
    assert profile.setting_id() == "unknown_unknown_unknown"


# --- display_hdr / display_audio / display_fps ------------------------------

@pytest.mark.parametrize("hdr_type, expected", [
    ("dolbyvision", "DV"),
    ("hdr10", "HDR10"),
    ("hdr10plus", "HDR10+"),
    ("hlg", "HLG"),
    ("sdr", "SDR"),
    ("unknown", "unknown"),      # not in map -> raw value
])
def test_display_hdr(hdr_type, expected):
    assert make_profile(hdr_type, 23, "truehd").display_hdr() == expected


@pytest.mark.parametrize("audio_format, expected", [
    ("truehd", "TrueHD"),
    ("eac3", "DD+"),
    ("ac3", "DD"),
    ("dtshd_ma", "DTS-HD MA"),
    ("dtshd_hra", "DTS-HD HRA"),
    ("dca", "DTS"),
    ("pcm", "PCM"),
    ("unknown", "Unknown Format"),
    ("weirdcodec", "weirdcodec"),  # not in map -> raw value
])
def test_display_audio(audio_format, expected):
    assert make_profile("hdr10", 23, audio_format).display_audio() == expected


@pytest.mark.parametrize("fps_type, expected", [
    (23, "23.98"),
    (24, "24.00"),
    (25, "25.00"),
    (29, "29.97"),
    (30, "30.00"),
    (50, "50.00"),
    (59, "59.94"),
    (60, "60.00"),
    ("23", "23.98"),         # str form maps the same
    ("all", "all"),          # not in map -> raw key
    ("unknown", "unknown"),  # not in map -> raw key
])
def test_display_fps(fps_type, expected):
    assert make_profile("hdr10", fps_type, "truehd").display_fps() == expected


# --- summary() --------------------------------------------------------------

def test_summary_includes_fps_for_specific_bucket():
    profile = make_profile("dolbyvision", 23, "truehd")
    assert profile.summary() == "DV | 23.98 FPS | TrueHD"


def test_summary_omits_fps_when_bucket_is_all():
    # fps_type == 'all' collapses the summary to "<hdr> | <audio>".
    profile = make_profile("hdr10", "all", "eac3")
    assert profile.summary() == "HDR10 | DD+"


def test_summary_include_fps_false_omits_fps_even_for_specific_bucket():
    profile = make_profile("dolbyvision", 23, "truehd")
    assert profile.summary(include_fps=False) == "DV | TrueHD"


def test_summary_unknown_profile():
    # Unknown hdr/fps fall back to their raw strings; 'unknown' audio maps to a
    # friendly name. 'unknown' fps is NOT 'all', so the FPS segment is kept.
    profile = make_profile("unknown", "unknown", "unknown")
    assert profile.summary() == "unknown | unknown FPS | Unknown Format"


# --- frozen dataclass contract ---------------------------------------------

def test_profile_is_frozen():
    profile = make_profile("hdr10", 23, "truehd")
    with pytest.raises(Exception):
        profile.hdr_type = "sdr"  # frozen dataclass -> FrozenInstanceError
