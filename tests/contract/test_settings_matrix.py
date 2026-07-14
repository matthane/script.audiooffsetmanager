"""Contract test: the offset-settings matrix in resources/settings.xml.

The addon keys every stored offset by `<hdr>_<fps>_<audio>`. There must be one
integer setting per combination of the format vocabulary, with the exact
-1000/+1000/25 constraints. This pins all 315 ids and cross-checks the
vocabulary against the valid_* lists in resources/lib/stream_info.py, so a drift
between the code's vocabulary and the shipped settings (which silently means "no
offset found") fails the build.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_XML = REPO_ROOT / "resources" / "settings.xml"

# The frozen vocabulary — INTENTIONALLY hardcoded, independent of
# aom.domain.formats. This test is the drift ORACLE: if it derived its
# expectations from formats.py, a bad vocabulary edit would update the
# expectations in lockstep and the test would prove nothing. Growing the
# vocabulary means updating BOTH formats.py and this copy, deliberately.
# `test_formats_enumeration_matches_independent_oracle` bridges the two.
HDR_TYPES = ("dolbyvision", "hdr10", "hdr10plus", "hlg", "sdr")
FPS_SPECIFIC = ("23", "24", "25", "29", "30", "50", "59", "60")
FPS_BUCKETS = ("all",) + FPS_SPECIFIC        # 'all' = per-HDR FPS override off
AUDIO_FORMATS = ("truehd", "eac3", "ac3", "dtshd_ma", "dtshd_hra", "dca", "pcm")

EXPECTED_IDS = tuple(
    "{0}_{1}_{2}".format(hdr, fps, audio)
    for hdr in HDR_TYPES
    for fps in FPS_BUCKETS
    for audio in AUDIO_FORMATS
)

_OFFSET_ID_RE = re.compile(
    r"^(?:{hdr})_(?:{fps})_(?:{audio})$".format(
        hdr="|".join(HDR_TYPES),
        fps="|".join(FPS_BUCKETS),
        audio="|".join(AUDIO_FORMATS),
    )
)


def _load_settings_by_id():
    tree = ET.parse(str(SETTINGS_XML))
    return {s.get("id"): s for s in tree.iter("setting")}


SETTINGS_BY_ID = _load_settings_by_id()


def test_expected_matrix_is_315_unique_ids():
    assert len(EXPECTED_IDS) == 315
    assert len(set(EXPECTED_IDS)) == 315


def test_vocabulary_matches_stream_info_valid_lists():
    # StreamInfo imports cleanly under Kodistubs; read its live vocabulary.
    from resources.lib.stream_info import StreamInfo
    stream_info = StreamInfo()
    assert tuple(stream_info.valid_hdr_types) == HDR_TYPES
    assert tuple(stream_info.valid_audio_formats) == AUDIO_FORMATS
    assert tuple(str(f) for f in stream_info.valid_fps_types) == FPS_SPECIFIC


@pytest.mark.parametrize("setting_id", EXPECTED_IDS)
def test_offset_setting_present_typed_and_constrained(setting_id):
    setting = SETTINGS_BY_ID.get(setting_id)
    assert setting is not None, "missing offset setting id: {0}".format(setting_id)
    assert setting.get("type") == "integer", \
        "{0}: expected type=integer".format(setting_id)
    assert setting.findtext("constraints/minimum") == "-1000", \
        "{0}: minimum must be -1000".format(setting_id)
    assert setting.findtext("constraints/maximum") == "1000", \
        "{0}: maximum must be 1000".format(setting_id)
    assert setting.findtext("constraints/step") == "25", \
        "{0}: step must be 25".format(setting_id)


def test_formats_enumeration_matches_independent_oracle():
    # Bridge: the SSOT's own enumeration must equal this test's independent
    # hardcoded product (same ids, same canonical order). Catches three-way
    # drift between formats.py, the generator, and this oracle.
    from resources.lib.aom.domain import formats
    assert tuple(formats.all_setting_keys()) == EXPECTED_IDS


def test_no_unexpected_offset_pattern_ids():
    # Every id shaped like an offset key must be one of the 315 — no typos,
    # no stray extra buckets.
    found = {sid for sid in SETTINGS_BY_ID if sid and _OFFSET_ID_RE.match(sid)}
    assert found == set(EXPECTED_IDS)
