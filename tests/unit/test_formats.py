"""Unit tests for aom.domain.formats — the vocabulary's internal integrity.

The settings.xml side of the vocabulary is guarded by the contract tests;
these check the module's own invariants and that legacy consumers stay wired
to it.
"""

from resources.lib.aom.domain import formats


def test_vocabulary_sizes():
    assert len(formats.HDR_TYPES) == 5
    assert len(formats.AUDIO_FORMATS) == 7
    assert len(formats.FPS_BUCKETS) == 8
    assert len(formats.all_setting_keys()) == 315


def test_audio_match_order_eac3_before_ac3():
    # 'ac3' is a substring of 'eac3'; substring matching must test eac3 first.
    assert formats.AUDIO_FORMATS.index('eac3') < formats.AUDIO_FORMATS.index('ac3')


def test_display_maps_cover_vocabulary():
    assert set(formats.HDR_DISPLAY_NAMES) == set(formats.HDR_TYPES)
    assert set(formats.AUDIO_DISPLAY_NAMES) == set(formats.AUDIO_FORMATS) | {formats.UNKNOWN}
    assert set(formats.FPS_DISPLAY_NAMES) == {str(b) for b in formats.FPS_BUCKETS}


def test_string_id_tables_cover_vocabulary():
    assert set(formats.AUDIO_STRING_IDS) == set(formats.AUDIO_FORMATS)
    assert set(formats.FPS_OPTION_LABEL_IDS) == set(formats.FPS_BUCKETS)
    # Every id is a 32xxx string (strings.po contract tests verify existence).
    for label, help_id in formats.AUDIO_STRING_IDS.values():
        assert label.startswith('32') and help_id.startswith('32')


def test_setting_key_format_is_frozen():
    assert formats.setting_key('dolbyvision', 'all', 'truehd') == 'dolbyvision_all_truehd'
    assert formats.setting_key('hdr10', 23, 'eac3') == 'hdr10_23_eac3'


def test_all_setting_keys_unique_and_ordered_by_hdr():
    keys = formats.all_setting_keys()
    assert len(set(keys)) == 315
    assert keys[0] == 'dolbyvision_all_truehd'
    assert keys[-1] == 'sdr_60_pcm'


def test_stream_info_consumes_this_vocabulary():
    # Legacy StreamInfo must stay wired to formats (imports under Kodistubs).
    from resources.lib.stream_info import StreamInfo
    info = StreamInfo()
    assert tuple(info.valid_audio_formats) == formats.AUDIO_FORMATS
    assert tuple(info.valid_hdr_types) == formats.HDR_TYPES
    assert tuple(info.valid_fps_types) == formats.FPS_BUCKETS
