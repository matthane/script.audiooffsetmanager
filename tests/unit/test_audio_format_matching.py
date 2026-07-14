"""Characterization tests for StreamInfo.get_audio_info match order.

Pins how a raw Kodi codec string is mapped to one of the seven settings
audio-format buckets, before Phase 1/4 relocate this into aom.domain.formats +
the gateway. Two properties are load-bearing and must not regress:

  * substring match order: 'eac3' is tested before 'ac3' (ac3 is a substring of
    eac3), so a Dolby Digital+ stream keys to eac3, never ac3;
  * fallback: an unrecognized-but-present codec becomes 'pcm' (never 'unknown'),
    while the literal 'unknown'/'none' sentinels pass through untouched.

StreamInfo.get_audio_info delegates the actual JSON-RPC read to
rpc_client.get_audio_info, which is monkeypatched here so no live RPC runs.
The 'pt-' passthrough prefix is stripped inside rpc_client (verified in its own
test at the xbmc.executeJSONRPC level), so StreamInfo sees already-stripped codecs.
"""

import json

import pytest

from resources.lib import rpc_client
from resources.lib.settings_facade import SettingsFacade
from resources.lib.settings_manager import SettingsManager
from resources.lib.stream_info import StreamInfo


@pytest.fixture
def stream_info():
    manager = SettingsManager()
    return StreamInfo(manager, SettingsFacade(manager))


def _patch_rpc(monkeypatch, codec, channels=6):
    monkeypatch.setattr(rpc_client, "get_audio_info",
                        lambda player_id: (codec, channels))


@pytest.mark.parametrize("raw_codec, expected", [
    ("truehd", "truehd"),
    ("eac3", "eac3"),          # NOT 'ac3' — order matters
    ("ac3", "ac3"),
    ("dtshd_ma", "dtshd_ma"),
    ("dtshd_hra", "dtshd_hra"),
    ("dca", "dca"),
    ("pcm", "pcm"),
])
def test_recognized_codecs_map_to_their_bucket(monkeypatch, stream_info,
                                               raw_codec, expected):
    _patch_rpc(monkeypatch, raw_codec)
    audio_format, _channels = stream_info.get_audio_info(player_id=1)
    assert audio_format == expected


def test_eac3_is_matched_before_ac3(monkeypatch, stream_info):
    # 'ac3' is a substring of 'eac3'; the ordered list must catch eac3 first.
    _patch_rpc(monkeypatch, "eac3")
    assert stream_info.get_audio_info(1)[0] == "eac3"
    # And the ordering that guarantees it is pinned directly on the source list.
    formats = stream_info.valid_audio_formats
    assert formats.index("eac3") < formats.index("ac3")


@pytest.mark.parametrize("raw_codec", ["aac", "flac", "opus", "mp3", "vorbis"])
def test_unrecognized_present_codec_falls_back_to_pcm(monkeypatch, stream_info,
                                                      raw_codec):
    _patch_rpc(monkeypatch, raw_codec)
    assert stream_info.get_audio_info(1)[0] == "pcm"


@pytest.mark.parametrize("sentinel", ["unknown", "none"])
def test_unknown_and_none_sentinels_pass_through(monkeypatch, stream_info,
                                                 sentinel):
    _patch_rpc(monkeypatch, sentinel)
    assert stream_info.get_audio_info(1)[0] == sentinel


def test_matching_is_case_insensitive(monkeypatch, stream_info):
    _patch_rpc(monkeypatch, "EAC3")
    assert stream_info.get_audio_info(1)[0] == "eac3"


def test_channels_are_passed_through_unchanged(monkeypatch, stream_info):
    _patch_rpc(monkeypatch, "truehd", channels=8)
    assert stream_info.get_audio_info(1) == ("truehd", 8)


# --- rpc layer: 'pt-' passthrough prefix stripping --------------------------

def _fake_audio_rpc(codec, channels):
    def _rpc(_request):
        return json.dumps(
            {"result": {"currentaudiostream": {"codec": codec, "channels": channels}}}
        )
    return _rpc


@pytest.mark.parametrize("raw_codec, expected", [
    ("pt-truehd", "truehd"),
    ("pt-eac3", "eac3"),
    ("truehd", "truehd"),   # no prefix -> unchanged
])
def test_rpc_client_strips_pt_passthrough_prefix(monkeypatch, raw_codec, expected):
    import xbmc
    monkeypatch.setattr(xbmc, "executeJSONRPC", _fake_audio_rpc(raw_codec, 8))
    audio_format, channels = rpc_client.get_audio_info(1)
    assert audio_format == expected
    assert channels == 8


def test_pt_prefixed_codec_end_to_end_through_stream_info(monkeypatch, stream_info):
    # rpc strips 'pt-' -> 'eac3', then StreamInfo matches it to the eac3 bucket.
    import xbmc
    monkeypatch.setattr(xbmc, "executeJSONRPC", _fake_audio_rpc("pt-eac3", 6))
    assert stream_info.get_audio_info(1)[0] == "eac3"
