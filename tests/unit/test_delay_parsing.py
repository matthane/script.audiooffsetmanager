"""Behavior matrix for aom.domain.policies.parse_delay_ms.

Began in Phase 0 as characterization tests for ActiveMonitor.convert_delay_to_ms
(relocated to the domain in Phase 1). Phase 6 gave the parser to the
AdjustmentWatcher and fixed its two pinned limitations — the
NNBSP-as-sole-separator parse failure and the int() ms truncation — so this
matrix now pins the FIXED semantics, targeting the domain function directly
(the legacy delegating wrapper died with ActiveMonitor).
"""

import pytest

from resources.lib.aom.domain.policies import parse_delay_ms

NNBSP = " "  # narrow no-break space (U+202F)
UMINUS = "−"  # Unicode minus sign


@pytest.mark.parametrize("delay_str, expected", [
    ("-0.075 s", -75),        # canonical negative
    ("0.075 s", 75),          # canonical positive
    ("0.000 s", 0),           # zero
    ("-0,075 s", -75),        # comma decimal (European locale)
    ("1.5 s", 1500),
    ("-0.025 s", -25),
])
def test_valid_conversions(delay_str, expected):
    assert parse_delay_ms(delay_str) == expected


@pytest.mark.parametrize("delay_str, expected", [
    # NNBSP preceding the regular " s" unit.
    ("-0.075" + NNBSP + " s", -75),
    ("-0,075" + NNBSP + " s", -75),
    # Phase 6 fix (flipped pin): NNBSP as the SOLE unit separator — the
    # modern CLDR convention ("-0.075<NNBSP>s") — used to return None.
    ("-0.075" + NNBSP + "s", -75),
    ("-0,075" + NNBSP + "s", -75),
    # No separator at all: same trailing-unit strip handles it.
    ("-0.075s", -75),
])
def test_unit_separator_variants_parse(delay_str, expected):
    assert parse_delay_ms(delay_str) == expected


@pytest.mark.parametrize("delay_str", [
    "abc",
    "garbage s",
    "",
    None,
    "s",
    NNBSP + "s",
])
def test_junk_returns_none(delay_str):
    assert parse_delay_ms(delay_str) is None


@pytest.mark.parametrize("delay_str, expected", [
    ("-15.5 s", -10000),   # below -10 s clamps to -10000
    ("20 s", 10000),       # above +10 s clamps to +10000
    ("10.0 s", 10000),     # exact upper bound
    ("-10.0 s", -10000),   # exact lower bound
    ("10.001 s", 10000),   # just over upper bound
    ("9.999 s", 9999),     # just under upper bound (not clamped)
    ("-9.999 s", -9999),   # just above lower bound (not clamped)
])
def test_clamping_to_plus_minus_10_seconds(delay_str, expected):
    assert parse_delay_ms(delay_str) == expected


@pytest.mark.parametrize("delay_str, expected", [
    # Phase 6 fix (flipped pin): values whose float round-trip lands just
    # below the integer ("0.115" * 1000 == 114.999...) round instead of
    # truncating toward zero.
    ("0.115 s", 115),
    ("-0.115 s", -115),
    ("0.185 s", 185),
    ("-0.185 s", -185),
])
def test_ms_conversion_rounds(delay_str, expected):
    assert parse_delay_ms(delay_str) == expected


@pytest.mark.parametrize("delay_str, expected", [
    # Phase 6 review fix: a Unicode minus sign (CLDR negative-number
    # convention in some locales) is normalized to ASCII '-'; combined
    # locale styling (comma decimal + NNBSP unit separator) parses too.
    (UMINUS + "0.075 s", -75),
    (UMINUS + "0,075" + NNBSP + "s", -75),
])
def test_unicode_minus_sign_parses(delay_str, expected):
    assert parse_delay_ms(delay_str) == expected
