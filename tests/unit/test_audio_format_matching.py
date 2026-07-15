"""Characterization tests for the audio-format match order.

Phase 4 home: ``aom.app.stream_detector._derive_audio_format`` (the pure
derivation the StreamDetector runs on every probe). Pins how a raw Kodi codec
string is mapped to one of the seven settings audio-format buckets. Two
properties are load-bearing and must not regress:

  * substring match order: 'eac3' is tested before 'ac3' (ac3 is a substring
    of eac3), so a Dolby Digital+ stream keys to eac3, never ac3;
  * fallback: an unrecognized-but-present codec becomes 'pcm' (never
    'unknown'), while the 'unknown'/'none' sentinels normalize to
    formats.UNKNOWN — the legacy two-layer behavior (get_audio_info passed
    sentinels through; gather_stream_info collapsed both to 'unknown')
    combined into one function.

The 'pt-' passthrough prefix is stripped in the gateway (see
tests/unit/test_gateway.py); the substring match also tolerates an
unstripped prefix, pinned here as defense in depth.
"""

import pytest

from resources.lib.aom.app.stream_detector import (_derive_audio_format,
                                                   derive_stream_facts)
from resources.lib.aom.domain import formats


@pytest.mark.parametrize("raw_codec, expected", [
    ("truehd", "truehd"),
    ("eac3", "eac3"),          # NOT 'ac3' — order matters
    ("ac3", "ac3"),
    ("dtshd_ma", "dtshd_ma"),
    ("dtshd_hra", "dtshd_hra"),
    ("dca", "dca"),
    ("pcm", "pcm"),
])
def test_recognized_codecs_map_to_their_bucket(raw_codec, expected):
    assert _derive_audio_format(raw_codec) == expected


def test_eac3_is_matched_before_ac3():
    # 'ac3' is a substring of 'eac3'; the ordered list must catch eac3 first.
    assert _derive_audio_format("eac3") == "eac3"
    # And the ordering that guarantees it is pinned directly on the source list.
    order = list(formats.AUDIO_FORMATS)
    assert order.index("eac3") < order.index("ac3")


@pytest.mark.parametrize("raw_codec", ["aac", "flac", "opus", "mp3", "vorbis"])
def test_unrecognized_present_codec_falls_back_to_pcm(raw_codec):
    assert _derive_audio_format(raw_codec) == "pcm"


@pytest.mark.parametrize("sentinel", ["unknown", "none"])
def test_unknown_and_none_sentinels_normalize_to_unknown(sentinel):
    assert _derive_audio_format(sentinel) == formats.UNKNOWN


def test_matching_is_case_insensitive():
    assert _derive_audio_format("EAC3") == "eac3"


def test_unstripped_pt_prefix_still_matches_by_substring():
    # The gateway strips 'pt-'; even if one slipped through, the substring
    # match keys it correctly.
    assert _derive_audio_format("pt-eac3") == "eac3"
    assert _derive_audio_format("pt-truehd") == "truehd"


def test_channels_and_format_flow_into_the_profile():
    facts = derive_stream_facts(
        player_id=1,
        raw_codec="truehd",
        raw_channels=8,
        raw_fps="23.976",
        raw_hdr="dolbyvision",
        raw_hdr_fallback="",
        raw_gamut="",
        fps_override_enabled=lambda hdr: False,
    )
    assert facts.profile.audio_format == "truehd"
    assert facts.profile.audio_channels == 8
    assert facts.profile.setting_id() == "dolbyvision_all_truehd"
