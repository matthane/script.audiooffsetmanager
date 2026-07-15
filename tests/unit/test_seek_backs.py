"""Unit tests for SeekBacks gating against the session (Phase 3 review pins).

Covers the cross-type cooldown (the invariant the legacy seek_in_progress
flag provided) and the None sentinels for monotonic timestamps.
"""

import time

from resources.lib.aom.app.session import PlaybackSession
from resources.lib.seek_backs import SeekBacks


class StubFacade:
    def seek_back_config(self, event_type):
        return True, 4


def make_seek_backs():
    # The gates under test run before any event_manager/settings_manager use.
    return SeekBacks(event_manager=None, settings_manager=None,
                     settings_facade=StubFacade(), session_tracker=None)


def make_session(**overrides):
    session = PlaybackSession(session_id=1, started_at=100.0)
    for key, value in overrides.items():
        setattr(session, key, value)
    return session


def test_fresh_session_allows_seek():
    # None sentinels must not false-trigger any recency guard.
    seek_backs = make_seek_backs()
    session = make_session()
    assert seek_backs._should_perform_seek_back('adjust', session) == (True, 4)


def test_cross_type_cooldown_blocks_other_seek_types():
    # A 'change' arriving within 2s of an 'unpause' seek is suppressed —
    # the invariant the deleted seek_in_progress flag used to provide.
    seek_backs = make_seek_backs()
    session = make_session()
    session.seek_history['unpause'] = time.monotonic()
    assert seek_backs._should_perform_seek_back('change', session) == (False, None)


def test_cooldown_expires():
    seek_backs = make_seek_backs()
    session = make_session()
    session.seek_history['unpause'] = time.monotonic() - 2.5
    assert seek_backs._should_perform_seek_back('change', session) == (True, 4)


def test_paused_session_blocks_seek():
    seek_backs = make_seek_backs()
    session = make_session(paused=True)
    assert seek_backs._should_perform_seek_back('adjust', session) == (False, None)


def test_recent_seek_activity_blocks_unpause_but_not_adjust():
    seek_backs = make_seek_backs()
    session = make_session(last_seek_activity=time.monotonic())
    assert seek_backs._should_perform_seek_back('unpause', session) == (False, None)
    assert seek_backs._should_perform_seek_back('adjust', session) == (True, 4)
