"""Pure decision functions: offset gating, profile completeness, delay parsing.

Pure Python: no Kodi imports, no I/O. Callers resolve settings/state and pass
explicit values; these functions only decide.
"""

from resources.lib.aom.domain import formats


def parse_delay_ms(delay_str):
    """Parse Kodi's localized `Player.AudioDelay` infolabel string to ms.

    Handles '-0.075 s', comma decimals ('-0,075 s'), and strips narrow
    no-break spaces. Clamps to +/-10 s. Returns None on unparseable input.

    Behavior is verbatim from ActiveMonitor.convert_delay_to_ms (Phase 1 move,
    zero behavior change). Known limitation, pinned in
    tests/unit/test_delay_parsing.py: a narrow no-break space as the SOLE
    separator before the unit ('-0.075<U+202F>s') fails to parse and returns
    None — scheduled to be fixed when the watcher rework takes ownership of
    this parser and adds full locale-variant coverage.
    """
    try:
        normalized = (delay_str.replace(' s', '')
                      .replace('\u202f', '')  # narrow no-break space
                      .replace(' ', '')
                      .replace(',', '.'))
        delay_seconds = float(normalized)
        # Clamp to reasonable bounds (-10s to +10s) to avoid junk values
        delay_seconds = max(-10.0, min(delay_seconds, 10.0))
        return int(delay_seconds * 1000)
    except (ValueError, AttributeError):
        return None


def is_complete(profile):
    """True when every axis of the profile was detected (no 'unknown')."""
    if profile is None:
        return False
    return formats.UNKNOWN not in (
        profile.hdr_type,
        str(profile.fps_type),
        profile.audio_format,
    )


def should_apply(profile, new_install, hdr_enabled):
    """Decide whether an offset may be applied for this profile.

    Args:
        profile: StreamProfile or None.
        new_install: bool — onboarding not completed yet.
        hdr_enabled: bool — the `enable_<hdr>` setting for profile.hdr_type
            (caller resolves it; pass False when profile is None).

    Returns:
        (allowed, reason) — reason is None when allowed, else one of
        'new_install', 'no_profile', 'unknown_format', 'hdr_disabled'.
    """
    if new_install:
        return False, 'new_install'
    if profile is None:
        return False, 'no_profile'
    if not is_complete(profile):
        return False, 'unknown_format'
    if not hdr_enabled:
        return False, 'hdr_disabled'
    return True, None
