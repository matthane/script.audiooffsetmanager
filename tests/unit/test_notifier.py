"""Unit tests for aom.app.notifier (Notifier).

Driven exactly like test_adjustment_watcher / test_seek_scheduler: a FakeClock
plus a manually pumped Dispatcher, a real SessionTracker (subscribed FIRST so
the Notifier always sees a live session), a FakeGui recording toasts, a small
local fake settings object, and a real Notifier. Sessions start by posting
``PlaybackStarted``; the profile is set by hand and stream-state is driven with
the session's ``mark_profile_built()`` / ``mark_stable()`` (the detector is not
in the rig).

The dedupe window is derived from ``Notifier.DEDUPE_SECONDS`` so a retune can
never leave these tests green-but-wrong against a stale float.
"""

import pytest

from resources.lib.aom.app import events
from resources.lib.aom.app.dispatcher import Dispatcher
from resources.lib.aom.app.notifier import (
    Notifier, STRING_OFFSET_APPLIED, STRING_OFFSET_SAVED)
from resources.lib.aom.app.session import SessionTracker
from resources.lib.aom.domain.profile import StreamProfile
from tests.fakes import FakeClock, FakeGui


DEDUPE = Notifier.DEDUPE_SECONDS
DURATION_MS = 3000


def make_profile(hdr_type='dolbyvision', fps_type='all', audio_format='truehd',
                 player_id=1):
    """A complete profile; keys dolbyvision_all_truehd, summary 'DV | TrueHD'."""
    return StreamProfile(hdr_type=hdr_type, fps_type=fps_type,
                         audio_format=audio_format, video_fps=23,
                         player_id=player_id, audio_channels=8)


class FakeSettings:
    """The notification read surface: an enabled flag and a duration value."""

    def __init__(self, enabled=True, duration_ms=DURATION_MS):
        self.enabled = enabled
        self.duration = duration_ms

    def notifications_enabled(self):
        return self.enabled

    def notification_duration_ms(self):
        return self.duration


class Rig:
    """The Notifier assembled on fakes; pump with post/advance."""

    def __init__(self):
        self.clock = FakeClock()
        self.errors = []
        self.debug = []
        self.dispatcher = Dispatcher(clock=self.clock,
                                     log_error=self.errors.append,
                                     log_debug=self.debug.append)
        # Tracker subscribes lifecycle FIRST (rig convention / dispatch order).
        self.tracker = SessionTracker(self.dispatcher, clock=self.clock,
                                      log_debug=self.debug.append)
        self.gui = FakeGui()
        self.settings = FakeSettings()
        self.notifier = Notifier(self.dispatcher, self.tracker, self.settings,
                                 self.gui, clock=self.clock,
                                 log_debug=self.debug.append)

    # -- pumping ----------------------------------------------------------------

    def post(self, event):
        self.dispatcher.post(event)
        self.dispatcher.run_pending()

    def advance(self, seconds):
        self.clock.advance(seconds)
        self.dispatcher.run_pending()

    # -- convenience ------------------------------------------------------------

    @property
    def session(self):
        return self.tracker.current

    @property
    def toasts(self):
        return self.gui.notifications

    def start(self, profile=None):
        """Begin a session and hand it a profile; return the session."""
        self.post(events.PlaybackStarted())
        session = self.session
        session.profile = profile
        return session

    def mark_stable(self, session):
        """STARTING -> STABILIZING -> STABLE (detector-order parity)."""
        session.mark_profile_built()
        session.mark_stable()

    def logged(self, needle):
        return any(needle in line for line in self.debug)


@pytest.fixture
def rig():
    return Rig()


def test_manual_save_supersedes_a_held_provisional_toast(rig):
    # A user adjustment landing INSIDE the provisional window makes the held
    # ms stale: releasing it on stabilization would announce a value that no
    # longer applies (legacy cleared the pending toast on its non-suppressed
    # apply path before the equivalent sequence could surface it). The manual
    # save clears the hold; stabilization then releases nothing.
    profile = make_profile()
    session = rig.start(profile)

    rig.post(events.OffsetApplied(session_id=session.session_id,
                                  profile=profile, ms=30, provisional=True))
    assert session.pending_notification is not None
    assert rig.toasts == []

    rig.post(events.UserOffsetSaved(session_id=session.session_id,
                                    profile=profile, ms=50))
    assert session.pending_notification is None       # hold superseded
    assert rig.toasts == [("#32093: +50 ms\nDV | TrueHD", DURATION_MS)]

    rig.mark_stable(session)
    rig.post(events.StreamStabilized(session_id=session.session_id))
    assert rig.toasts == [("#32093: +50 ms\nDV | TrueHD", DURATION_MS)]
    # No stale "applied +30" ever surfaces.


# ============================================================================
# Immediate (non-provisional) application
# ============================================================================

class TestImmediateApply:

    def test_non_provisional_toasts_immediately_with_legacy_message(self, rig):
        profile = make_profile()
        session = rig.start(profile)

        rig.post(events.OffsetApplied(session_id=session.session_id,
                                      profile=profile, ms=-125,
                                      provisional=False))

        assert rig.toasts == [("#32092: -125 ms\nDV | TrueHD", DURATION_MS)]
        assert session.pending_notification is None

    def test_non_provisional_clears_any_prior_pending(self, rig):
        profile = make_profile()
        session = rig.start(profile)
        session.pending_notification = (profile.setting_id(), -999)

        rig.post(events.OffsetApplied(session_id=session.session_id,
                                      profile=profile, ms=-50,
                                      provisional=False))
        assert session.pending_notification is None
        assert rig.toasts == [("#32092: -50 ms\nDV | TrueHD", DURATION_MS)]


# ============================================================================
# Deferral until STABLE
# ============================================================================

class TestDeferral:

    def test_provisional_holds_then_stabilization_releases_once(self, rig):
        profile = make_profile()
        session = rig.start(profile)

        rig.post(events.OffsetApplied(session_id=session.session_id,
                                      profile=profile, ms=-75,
                                      provisional=True))
        assert session.pending_notification == (profile.setting_id(), -75)
        assert rig.toasts == []

        # Detector marks STABLE, THEN posts StreamStabilized (queue order).
        rig.mark_stable(session)
        rig.post(events.StreamStabilized(session_id=session.session_id))

        assert rig.toasts == [("#32092: -75 ms\nDV | TrueHD", DURATION_MS)]
        assert session.pending_notification is None
        assert rig.logged("Released pending offset notification")

    def test_pending_dropped_when_profile_changed_underneath(self, rig):
        profile_a = make_profile(hdr_type='dolbyvision', audio_format='truehd')
        profile_b = make_profile(hdr_type='hdr10', audio_format='eac3')
        assert profile_a.setting_id() != profile_b.setting_id()
        session = rig.start(profile_a)

        rig.post(events.OffsetApplied(session_id=session.session_id,
                                      profile=profile_a, ms=-75,
                                      provisional=True))
        # Profile swapped before stabilization: the held key is now stale.
        session.profile = profile_b
        rig.mark_stable(session)
        rig.post(events.StreamStabilized(session_id=session.session_id))

        assert rig.toasts == []
        assert session.pending_notification is None

    def test_stabilization_with_no_pending_does_nothing(self, rig):
        profile = make_profile()
        session = rig.start(profile)
        rig.mark_stable(session)

        rig.post(events.StreamStabilized(session_id=session.session_id))

        assert rig.toasts == []
        assert session.pending_notification is None

    def test_stabilization_before_stable_state_does_not_release(self, rig):
        # Defensive parity: a StreamStabilized while the session is not yet
        # STABLE must not release the pending toast.
        profile = make_profile()
        session = rig.start(profile)
        rig.post(events.OffsetApplied(session_id=session.session_id,
                                      profile=profile, ms=-75,
                                      provisional=True))
        # NOT marked stable -> stream_state is STARTING.
        rig.post(events.StreamStabilized(session_id=session.session_id))

        assert rig.toasts == []
        assert session.pending_notification == (profile.setting_id(), -75)

    def test_newest_pending_wins_across_provisional_applies(self, rig):
        # A provisional apply under A, then a profile change and a NEW
        # provisional apply under B: only B's toast releases.
        profile_a = make_profile(hdr_type='dolbyvision', audio_format='truehd')
        profile_b = make_profile(hdr_type='hdr10', audio_format='eac3')
        session = rig.start(profile_a)

        rig.post(events.OffsetApplied(session_id=session.session_id,
                                      profile=profile_a, ms=-75,
                                      provisional=True))
        assert session.pending_notification == (profile_a.setting_id(), -75)

        session.profile = profile_b
        rig.post(events.OffsetApplied(session_id=session.session_id,
                                      profile=profile_b, ms=-40,
                                      provisional=True))
        assert session.pending_notification == (profile_b.setting_id(), -40)

        rig.mark_stable(session)
        rig.post(events.StreamStabilized(session_id=session.session_id))

        assert rig.toasts == [("#32092: -40 ms\nHDR10 | DD+", DURATION_MS)]
        assert session.pending_notification is None


# ============================================================================
# Manual offset saved
# ============================================================================

class TestUserOffsetSaved:

    def test_saved_toasts_from_event_profile_not_session(self, rig):
        # The toast describes the EVENT's profile/ms, even when session.profile
        # has moved on (the watcher captured it at store time).
        event_profile = make_profile(hdr_type='dolbyvision', audio_format='truehd')
        session_profile = make_profile(hdr_type='hlg', audio_format='ac3')
        session = rig.start(session_profile)

        rig.post(events.UserOffsetSaved(session_id=session.session_id,
                                        profile=event_profile, ms=60))

        assert rig.toasts == [("#32093: +60 ms\nDV | TrueHD", DURATION_MS)]


# ============================================================================
# Stale / superseded session stamps are inert
# ============================================================================

class TestStaleSessions:

    def test_offset_applied_for_dead_session_is_inert(self, rig):
        profile = make_profile()
        session = rig.start(profile)
        dead_id = session.session_id
        rig.post(events.PlaybackStopped())          # session gone
        assert rig.session is None

        rig.post(events.OffsetApplied(session_id=dead_id, profile=profile,
                                      ms=-50, provisional=False))
        assert rig.toasts == []

    def test_user_offset_saved_for_superseded_session_is_inert(self, rig):
        profile = make_profile()
        session = rig.start(profile)
        old_id = session.session_id
        rig.post(events.PlaybackStarted())          # in-place reopen -> new id
        assert rig.session.session_id != old_id

        rig.post(events.UserOffsetSaved(session_id=old_id, profile=profile,
                                        ms=-50))
        assert rig.toasts == []

    def test_stream_stabilized_for_dead_session_is_inert(self, rig):
        profile = make_profile()
        session = rig.start(profile)
        dead_id = session.session_id
        session.pending_notification = (profile.setting_id(), -50)
        rig.post(events.PlaybackStopped())

        rig.post(events.StreamStabilized(session_id=dead_id))
        assert rig.toasts == []


# ============================================================================
# Dedupe window
# ============================================================================

class TestDedupe:

    def _applied(self, rig, session, profile, ms):
        rig.post(events.OffsetApplied(session_id=session.session_id,
                                      profile=profile, ms=ms, provisional=False))

    def test_identical_within_window_suppressed_after_window_toasts(self, rig):
        profile = make_profile()
        session = rig.start(profile)

        self._applied(rig, session, profile, -50)
        self._applied(rig, session, profile, -50)          # same key, same time
        assert len(rig.toasts) == 1

        rig.advance(DEDUPE + 0.5)                           # past the window
        self._applied(rig, session, profile, -50)
        assert len(rig.toasts) == 2

    def test_different_ms_inside_window_not_suppressed(self, rig):
        profile = make_profile()
        session = rig.start(profile)

        self._applied(rig, session, profile, -50)
        self._applied(rig, session, profile, -75)          # different ms -> key differs
        assert len(rig.toasts) == 2

    def test_applied_does_not_suppress_saved(self, rig):
        # Same setting_id and ms but different string_id -> distinct dedupe key.
        profile = make_profile()
        session = rig.start(profile)

        self._applied(rig, session, profile, -50)
        rig.post(events.UserOffsetSaved(session_id=session.session_id,
                                        profile=profile, ms=-50))
        assert len(rig.toasts) == 2
        assert rig.toasts[0][0].startswith(f"#{STRING_OFFSET_APPLIED}")
        assert rig.toasts[1][0].startswith(f"#{STRING_OFFSET_SAVED}")


# ============================================================================
# Settings gate and message sign rendering
# ============================================================================

class TestSettingsGate:

    def test_disabled_suppresses_toast_but_pending_logic_still_runs(self, rig):
        rig.settings.enabled = False
        profile = make_profile()
        session = rig.start(profile)

        # Provisional hold still updates pending, without toasting.
        rig.post(events.OffsetApplied(session_id=session.session_id,
                                      profile=profile, ms=-75,
                                      provisional=True))
        assert session.pending_notification == (profile.setting_id(), -75)
        assert rig.toasts == []

        # Release still clears pending, still no toast.
        rig.mark_stable(session)
        rig.post(events.StreamStabilized(session_id=session.session_id))
        assert session.pending_notification is None
        assert rig.toasts == []


class TestSignRendering:

    @pytest.mark.parametrize("ms, rendered", [
        (75, "+75 ms"),
        (-75, "-75 ms"),
        (0, "0 ms"),
    ])
    def test_sign_rendering(self, rig, ms, rendered):
        profile = make_profile()
        session = rig.start(profile)

        rig.post(events.OffsetApplied(session_id=session.session_id,
                                      profile=profile, ms=ms, provisional=False))

        assert rig.toasts == [(f"#32092: {rendered}\nDV | TrueHD", DURATION_MS)]
