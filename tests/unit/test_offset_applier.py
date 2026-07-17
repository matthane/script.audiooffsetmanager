"""Unit tests for aom.app.offset_applier (OffsetApplier).

Rig pattern shared with the sibling app suites: FakeClock + manually pumped
Dispatcher + real SessionTracker (subscribed first), a scriptable FakeGateway,
and small local settings/offset fakes (the applier's read surface is tiny).
OffsetApplied posts are collected off the bus.

The applied-before-RPC ordering contract also has cross-component pins in
test_session_flow.py; here it is asserted directly at the gateway boundary.
"""

import pytest

from resources.lib.aom.app import events
from resources.lib.aom.app.dispatcher import Dispatcher
from resources.lib.aom.app.offset_applier import OffsetApplier
from resources.lib.aom.app.session import SessionTracker
from resources.lib.aom.domain.profile import StreamProfile
from resources.lib.aom.domain.stream_state import StreamState
from tests.fakes import FakeClock, FakeGateway, FakeOffsetTable


def make_profile(hdr_type='dolbyvision', fps_type='all', audio_format='truehd',
                 player_id=1):
    return StreamProfile(hdr_type=hdr_type, fps_type=fps_type,
                         audio_format=audio_format, video_fps=23,
                         player_id=player_id, audio_channels=8)


class FakeSettings:
    """The applier's settings read surface: gating inputs only."""

    def __init__(self):
        self.new_install = False
        self.hdr_enabled = True

    def is_new_install(self):
        return self.new_install

    def is_hdr_enabled(self, hdr_type):
        return self.hdr_enabled


class Rig:
    def __init__(self):
        self.clock = FakeClock()
        self.errors = []
        self.debug = []
        self.warnings = []
        self.dispatcher = Dispatcher(clock=self.clock,
                                     log_error=self.errors.append,
                                     log_debug=self.debug.append)
        self.tracker = SessionTracker(self.dispatcher, clock=self.clock,
                                      log_debug=self.debug.append)
        self.gateway = FakeGateway()
        self.settings = FakeSettings()
        self.offsets = FakeOffsetTable()
        self.applier = OffsetApplier(
            self.dispatcher, self.tracker, self.gateway, self.settings,
            self.offsets, log_debug=self.debug.append,
            log_warning=self.warnings.append)
        self.announced = []
        self.dispatcher.subscribe(events.OffsetApplied, self.announced.append)

    def post(self, event):
        self.dispatcher.post(event)
        self.dispatcher.run_pending()

    @property
    def session(self):
        return self.tracker.current

    def start(self, profile, offset_ms=-125):
        """Session with a hand-set profile (the detector isn't in the rig)."""
        self.post(events.PlaybackStarted())
        session = self.session
        session.profile = profile
        session.mark_profile_built()        # STARTING -> STABILIZING
        self.offsets.offsets[profile.setting_id()] = offset_ms
        return session

    def profile_changed(self):
        self.post(events.ProfileChanged(session_id=self.session.session_id))

    def logged(self, needle):
        return any(needle in line for line in self.debug)


@pytest.fixture
def rig():
    return Rig()


class TestApplyPath:

    def test_applies_on_profile_changed_and_announces_provisional(self, rig):
        profile = make_profile()
        session = rig.start(profile, offset_ms=-125)

        rig.profile_changed()

        assert rig.gateway.applied == [(1, -0.125)]
        assert session.applied == ('dolbyvision_all_truehd', -125)
        assert len(rig.announced) == 1
        announced = rig.announced[0]
        assert announced.session_id == session.session_id
        assert announced.profile == profile
        assert announced.ms == -125
        assert announced.provisional is True       # not yet STABLE
        assert rig.logged('session#1')             # describe() snapshot line

    def test_stable_session_announces_non_provisional(self, rig):
        profile = make_profile()
        session = rig.start(profile)
        session.mark_stable()                       # STABILIZING -> STABLE

        rig.profile_changed()

        assert rig.announced[0].provisional is False

    def test_applied_is_recorded_before_the_rpc(self, rig):
        # The watcher self-echo contract, pinned at the gateway boundary.
        profile = make_profile()
        session = rig.start(profile, offset_ms=-75)
        seen = []

        original = rig.gateway.set_audio_delay

        def spying(player_id, delay_seconds):
            seen.append(session.applied)
            return original(player_id, delay_seconds)

        rig.gateway.set_audio_delay = spying
        rig.profile_changed()

        assert seen == [('dolbyvision_all_truehd', -75)]

    def test_dedupe_skips_second_apply_for_same_offset(self, rig):
        profile = make_profile()
        rig.start(profile)
        rig.profile_changed()
        rig.post(events.StreamStabilized(session_id=rig.session.session_id))

        assert len(rig.gateway.applied) == 1        # retry edge deduped
        assert len(rig.announced) == 1
        assert rig.logged('skipping duplicate apply')

    def test_changed_offset_reapplies(self, rig):
        profile = make_profile()
        session = rig.start(profile, offset_ms=-125)
        rig.profile_changed()

        rig.offsets.offsets[profile.setting_id()] = -150   # user re-configured
        rig.post(events.StreamStabilized(session_id=session.session_id))

        assert rig.gateway.applied == [(1, -0.125), (1, -0.150)]
        assert session.applied == ('dolbyvision_all_truehd', -150)

    def test_failed_rpc_restores_applied_and_retries_on_stabilization(self, rig):
        profile = make_profile()
        session = rig.start(profile)

        calls = []

        def failing(player_id, delay_seconds):
            calls.append((player_id, delay_seconds))
            return False

        rig.gateway.set_audio_delay = failing
        rig.profile_changed()

        assert session.applied is None              # restored on failure
        assert rig.announced == []                  # no announcement
        assert any('will retry' in m for m in rig.warnings)

        rig.gateway.set_audio_delay = lambda p, s: calls.append((p, s)) or True
        rig.post(events.StreamStabilized(session_id=session.session_id))

        assert len(calls) == 2                      # the retry edge fired
        assert session.applied == ('dolbyvision_all_truehd', -125)
        assert len(rig.announced) == 1

    def test_zero_offset_is_applied(self, rig):
        # OffsetTable.get always answers an int; 0 means "reset the delay",
        # not "missing" (the legacy None branch is gone).
        profile = make_profile()
        session = rig.start(profile, offset_ms=0)

        rig.profile_changed()

        assert rig.gateway.applied == [(1, 0.0)]
        assert session.applied == ('dolbyvision_all_truehd', 0)


class TestGating:

    def test_new_install_skips(self, rig):
        rig.settings.new_install = True
        rig.start(make_profile())
        rig.profile_changed()
        assert rig.gateway.applied == []
        assert rig.logged('New install detected')

    def test_hdr_disabled_skips(self, rig):
        rig.settings.hdr_enabled = False
        rig.start(make_profile())
        rig.profile_changed()
        assert rig.gateway.applied == []
        assert rig.logged('not enabled in settings')

    def test_incomplete_profile_skips(self, rig):
        rig.start(make_profile(audio_format='unknown'))
        rig.profile_changed()
        assert rig.gateway.applied == []
        assert rig.logged('Unknown format detected')

    def test_no_profile_skips(self, rig):
        rig.post(events.PlaybackStarted())
        rig.post(events.ProfileChanged(session_id=rig.session.session_id))
        assert rig.gateway.applied == []
        assert rig.logged('No stream profile available')

    def test_invalid_player_id_skips(self, rig):
        rig.start(make_profile(player_id=-1))
        rig.profile_changed()
        assert rig.gateway.applied == []
        assert rig.logged('No valid player ID')

    def test_stale_session_stamp_is_inert(self, rig):
        rig.start(make_profile())
        rig.post(events.ProfileChanged(session_id=999))
        assert rig.gateway.applied == []
        assert rig.announced == []
