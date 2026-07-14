"""Characterization tests for ActiveMonitor.convert_delay_to_ms.

Pins the CURRENT locale-safe parsing of Kodi's `Player.AudioDelay` infolabel
string before Phase 1 relocates it to aom.domain.policies.parse_delay_ms.

ActiveMonitor.__init__(event_manager, stream_info, offset_manager,
settings_manager): convert_delay_to_ms touches none of these, so dummy Nones
suffice for the first three; the required settings_manager is the singleton,
which imports and constructs cleanly under Kodistubs.

Current implementation (verbatim):
    normalized = delay_str.replace(' s', '').replace('\\u202f', '') \\
                          .replace(' ', '').replace(',', '.')
    delay_seconds = max(-10.0, min(float(normalized), 10.0))
    return int(delay_seconds * 1000)
"""

import pytest

from resources.lib.active_monitor import ActiveMonitor
from resources.lib.settings_manager import SettingsManager

NNBSP = " "  # narrow no-break space (U+202F)


@pytest.fixture
def convert():
    monitor = ActiveMonitor(None, None, None, SettingsManager())
    return monitor.convert_delay_to_ms


@pytest.mark.parametrize("delay_str, expected", [
    ("-0.075 s", -75),        # canonical negative
    ("0.075 s", 75),          # canonical positive
    ("0.000 s", 0),           # zero
    ("-0,075 s", -75),        # comma decimal (European locale)
    ("1.5 s", 1500),
    ("-0.025 s", -25),
])
def test_valid_conversions(convert, delay_str, expected):
    assert convert(delay_str) == expected


@pytest.mark.parametrize("delay_str, expected", [
    # A NNBSP that precedes the regular " s" unit is stripped -> parses fine.
    ("-0.075" + NNBSP + " s", -75),
    ("-0,075" + NNBSP + " s", -75),
])
def test_narrow_no_break_space_before_unit_parses(convert, delay_str, expected):
    assert convert(delay_str) == expected


@pytest.mark.parametrize("delay_str", [
    "abc",
    "garbage s",
    "",
    None,
    "s",
])
def test_junk_returns_none(convert, delay_str):
    assert convert(delay_str) is None


@pytest.mark.parametrize("delay_str, expected", [
    ("-15.5 s", -10000),   # below -10 s clamps to -10000
    ("20 s", 10000),       # above +10 s clamps to +10000
    ("10.0 s", 10000),     # exact upper bound
    ("-10.0 s", -10000),   # exact lower bound
    ("10.001 s", 10000),   # just over upper bound
    ("9.999 s", 9999),     # just under upper bound (not clamped)
    ("-9.999 s", -9999),   # just above lower bound (not clamped)
])
def test_clamping_to_plus_minus_10_seconds(convert, delay_str, expected):
    assert convert(delay_str) == expected


# --- FLAGGED CURRENT-BEHAVIOR ODDITY (do not "fix" in Phase 0) --------------
# When a narrow no-break space sits DIRECTLY between the value and the unit with
# no regular space (the modern CLDR unit-separator convention, e.g. Kodi could
# emit "-0.075<NNBSP>s"), the replacement order strips the NNBSP and leaves
# "-0.075s", which float() then rejects -> None. So a plausible real locale
# string silently fails to parse. Pinned here as-is; flagged in the report.
def test_narrow_no_break_space_as_sole_unit_separator_currently_returns_none(convert):
    assert convert("-0.075" + NNBSP + "s") is None
