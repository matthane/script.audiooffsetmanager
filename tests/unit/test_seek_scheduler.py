"""Unit tests for aom.app.seek_scheduler (SeekScheduler + ExternalSeekCoordinator).

Driven exactly like test_stream_detector / test_dispatcher: a FakeClock plus
Dispatcher.run_pending() pumping, with a Rig that assembles the scheduler on
fakes. Seeks are observed through FakeGateway.seeks (a list of
(seconds, player_id)); reciprocity/vendor signals through its
window_properties.

Timing facts the tests rely on (from the module):

* ExecuteSeek attempt #1 is scheduled at delay 0, so it fires on the NEXT
  pump with no clock advance; a deferred attempt re-schedules RECHECK (0.5s)
  later, key-replaced so only one attempt per reason is ever live.
* The session's ``started_at`` counts as seek activity, so a fresh seek must
  wait QUIET_WINDOW (2.0s) from playback start before it can execute — this
  is how the legacy mandatory 2s post-start settle is reproduced.
* Per-reason DEBOUNCE (2.0s) is measured from that reason's last EXECUTED
  seek; DEADLINE (8.0s) is measured from the request.
* Seeks execute only when ``session.stream_state is STABLE``; tests reach
  STABLE via the session's own transitions (mark_profile_built + mark_stable)
  and give the session a real StreamProfile so player_id resolves.

Race note (pinned, not incidental): when two reasons become eligible on the
SAME pump, the reason whose attempt-chain started FIRST fires first (lower
scheduler seq perpetuates through the lock-step 0.5s reschedules). Tests that
depend on cross-type ordering exploit this deterministically.
"""

import pytest

from resources.lib.aom.app import events
from resources.lib.aom.app.dispatcher import Dispatcher
from resources.lib.aom.app.seek_scheduler import (
    SeekScheduler,
    ExternalSeekCoordinator,
)
from resources.lib.aom.app.session import SessionTracker
from resources.lib.aom.domain.profile import StreamProfile
from resources.lib.aom.domain.stream_state import StreamState
from tests.fakes import FakeClock, FakeFacade, FakeGateway


VENDOR_PROP = ExternalSeekCoordinator.VENDOR_BUSY_PROPERTIES[0]  # plex seeking
RECIPROCAL = ExternalSeekCoordinator.RECIPROCAL_PROPERTY

# Timing constants derive from the scheduler so retuning cannot leave these
# tests green-but-wrong against a stale window.
QUIET = SeekScheduler.QUIET_WINDOW_SECONDS
DEADLINE = SeekScheduler.DEADLINE_SECONDS
RECHECK = SeekScheduler.RECHECK_SECONDS
DEBOUNCE = SeekScheduler.DEBOUNCE_SECONDS
GRACE = SeekScheduler.STABILITY_GRACE_SECONDS
DEADLINE_STEPS = int(DEADLINE / RECHECK)


def make_profile(player_id=1):
    # A complete DV/TrueHD profile — only player_id is load-bearing here (the
    # scheduler reads profile.player_id when executing), the rest is realistic
    # filler so the frozen dataclass is valid.
    return StreamProfile(hdr_type='dolbyvision', fps_type='all',
                         audio_format='truehd', video_fps=23,
                         player_id=player_id, audio_channels=8)


class Rig:
    """The scheduler graph assembled on fakes; pump with post/advance."""

    def __init__(self, gateway=None):
        self.clock = FakeClock()
        self.errors = []
        self.debug = []
        self.warnings = []
        self.dispatcher = Dispatcher(clock=self.clock,
                                     log_error=self.errors.append)
        # Tracker subscribes lifecycle FIRST so the scheduler always sees a
        # live session on PlaybackStarted (dispatch follows subscription order).
        self.tracker = SessionTracker(self.dispatcher, clock=self.clock)
        self.gateway = gateway if gateway is not None else FakeGateway()
        self.facade = FakeFacade()
        self.coordinator = ExternalSeekCoordinator(
            self.gateway, clock=self.clock, log_debug=self.debug.append)
        self.scheduler = SeekScheduler(
            self.dispatcher, self.tracker, self.facade, self.coordinator,
            clock=self.clock, log_debug=self.debug.append,
            log_warning=self.warnings.append)

    @property
    def session(self):
        return self.tracker.current

    @property
    def seeks(self):
        return self.gateway.seeks

    @property
    def pending(self):
        """Reasons with a live scheduled attempt — the request state IS the
        key-replaced timer, so pendingness is read off the dispatcher."""
        return {reason for reason in SeekScheduler.REASONS
                if f'aom.seek.{reason}' in self.dispatcher._active_keys}

    def pending_request(self, reason):
        """The live queued ExecuteSeek event for a reason (or None)."""
        key = f'aom.seek.{reason}'
        live_seq = self.dispatcher._active_keys.get(key)
        for _fire_at, seq, timer_key, event in self.dispatcher._timers:
            if timer_key == key and seq == live_seq:
                return event
        return None

    def post(self, event):
        self.dispatcher.post(event)
        self.dispatcher.run_pending()

    def advance(self, seconds):
        self.clock.advance(seconds)
        self.dispatcher.run_pending()

    def start(self):
        self.post(events.PlaybackStarted())

    def make_stable(self, player_id=1):
        """Give the current session a profile and drive it to STABLE."""
        session = self.session
        session.profile = make_profile(player_id)
        session.mark_profile_built()   # STARTING -> STABILIZING
        session.mark_stable()          # STABILIZING -> STABLE
        assert session.stream_state is StreamState.STABLE

    def logged(self, needle):
        return any(needle in line for line in self.debug)


@pytest.fixture
def rig():
    return Rig()


# ============================================================================
# Triggers & per-reason debounce
# ============================================================================

class TestTriggersAndDebounce:

    def test_playback_started_resume_seek_fires_once_when_stable_and_quiet(self, rig):
        # PlaybackStarted requests 'resume'. The seek must wait STABLE and the
        # quiet window from started_at (0.0): at clock 2.0 exactly one seek
        # executes with the configured seconds and the profile's player_id.
        rig.start()
        rig.make_stable(player_id=7)
        assert rig.seeks == []            # not quiet yet (0s since start)

        rig.advance(2.0)                  # quiet window from started_at elapses
        assert rig.seeks == [(4, 7)]      # seconds=4 (default), player_id=7
        assert 'resume' not in rig.pending

    def test_per_reason_debounce_drops_then_allows(self, rig):
        # A second trigger for the same reason within DEBOUNCE of its EXECUTED
        # seek is dropped ("too soon"); after DEBOUNCE it goes through again.
        # (Triggers land strictly AFTER the prior execution instant — a
        # same-instant trigger is served-abandoned by the policy, like the
        # legacy cooldown.)
        rig.start()
        rig.make_stable()
        rig.advance(QUIET)                # resume seek at t=2.0

        rig.advance(RECHECK)              # t=2.5
        rig.post(events.Resumed())        # unpause requested at t=2.5
        rig.advance(QUIET - RECHECK)      # quiet from the resume seek -> t=4.0
        assert rig.seeks == [(4, 1), (4, 1)]
        assert rig.session.seek_history['unpause'] == 4.0

        # Re-trigger unpause at t=4.0, 0s after the executed one -> dropped
        # before it is even scheduled (no live attempt).
        rig.post(events.Resumed())
        assert rig.seeks == [(4, 1), (4, 1)]     # no new seek
        assert 'unpause' not in rig.pending      # dropped, not queued
        assert rig.logged('too soon')

        # After DEBOUNCE and with the window quiet again, it fires.
        rig.advance(DEBOUNCE)             # clock -> 6.0
        rig.post(events.Resumed())        # 6.0 - 4.0 == DEBOUNCE, allowed
        assert rig.seeks == [(4, 1), (4, 1), (4, 1)]

    def test_retrigger_while_pending_key_replaces_to_one_seek(self, rig):
        # Two Resumed events before the attempt executes collapse to ONE seek:
        # the second _request key-replaces the first pending attempt.
        rig.start()
        rig.make_stable()
        rig.advance(QUIET)                # resume seek executes at t=2.0
        rig.advance(RECHECK)              # t=2.5 (strictly after the seek)

        rig.dispatcher.post(events.Resumed())
        rig.dispatcher.post(events.Resumed())
        rig.dispatcher.run_pending()      # both handled; second replaces first
        assert 'unpause' in rig.pending
        assert rig.seeks == [(4, 1)]      # still just the resume seek (deferred)

        rig.advance(QUIET - RECHECK)      # quiet from the resume seek -> fires ONCE
        assert rig.seeks == [(4, 1), (4, 1)]

    def test_paused_and_resumed_toggle_session_flag_and_request_unpause(self, rig):
        rig.start()
        rig.make_stable()

        rig.post(events.Paused())
        assert rig.session.paused is True

        rig.post(events.Resumed())
        assert rig.session.paused is False
        assert 'unpause' in rig.pending   # Resumed requested an 'unpause' seek

    def test_initial_stabilization_skipped_then_adjust(self, rig):
        # A change-announcing StreamStabilized stamped ``initial`` is the
        # startup settle: it requests nothing (the detector derives the stamp
        # from the state machine's stabilization count — the Phase 6
        # replacement for the consumed-latch semantics). A non-initial one
        # requests 'adjust'; profile_changed=False never requests.
        rig.start()
        rig.make_stable()
        sid = rig.session.session_id

        rig.post(events.StreamStabilized(session_id=sid, profile_changed=True,
                                         initial=True))
        assert 'adjust' not in rig.pending
        assert rig.logged('Skipping initial')

        # A pure re-confirmation (profile_changed=False) is inert — with or
        # without the initial stamp.
        rig.post(events.StreamStabilized(session_id=sid, profile_changed=False))
        assert 'adjust' not in rig.pending
        rig.post(events.StreamStabilized(session_id=sid, profile_changed=False,
                                         initial=True))
        assert 'adjust' not in rig.pending

        rig.post(events.StreamStabilized(session_id=sid, profile_changed=True))
        assert 'adjust' in rig.pending

    def test_user_offset_saved_requests_change_and_stale_stamp_is_inert(self, rig):
        # No session yet -> a UserOffsetSaved is a no-op (nothing scheduled).
        rig.post(events.UserOffsetSaved(session_id=1, profile=None, ms=-50))
        assert rig.pending == set()
        assert rig.seeks == []

        rig.start()
        rig.make_stable()
        sid = rig.session.session_id

        # A stamp from a superseded session is inert: a store racing an
        # in-place reopen can never seek the new session.
        rig.post(events.UserOffsetSaved(session_id=sid + 1, profile=None,
                                        ms=-50))
        assert 'change' not in rig.pending

        rig.post(events.UserOffsetSaved(session_id=sid, profile=None, ms=-50))
        assert 'change' in rig.pending

    def test_user_initiated_apply_requests_change_but_auto_apply_never_does(self, rig):
        rig.start()
        rig.make_stable()
        sid = rig.session.session_id

        # Automatic applies (detector adoption, stabilization retry) carry
        # the default stamp and must never seek.
        rig.post(events.OffsetApplied(session_id=sid, profile=None, ms=-50,
                                      provisional=False))
        assert 'change' not in rig.pending

        # A stale stamp is inert, same as UserOffsetSaved.
        rig.post(events.OffsetApplied(session_id=sid + 1, profile=None,
                                      ms=-50, provisional=False,
                                      user_initiated=True))
        assert 'change' not in rig.pending

        # The settings-dialog edit replays like the slider adjustment it is.
        rig.post(events.OffsetApplied(session_id=sid, profile=None, ms=-50,
                                      provisional=False, user_initiated=True))
        assert 'change' in rig.pending


# ============================================================================
# Execution guards (each pins one legacy guard's replacement)
# ============================================================================

class TestExecutionGuards:

    def test_defers_until_stable_then_executes(self, rig):
        # Not STABLE -> the attempt defers on the 0.5s cadence; once STABLE and
        # the window is quiet it executes exactly once.
        rig.start()                       # STARTING, resume requested
        rig.advance(0.5)
        rig.advance(0.5)
        rig.advance(0.5)                  # t=1.5, still STARTING
        assert rig.seeks == []
        assert 'resume' in rig.pending    # still deferring, not abandoned

        rig.make_stable()
        rig.advance(0.5)                  # t=2.0: STABLE + quiet -> seek
        assert rig.seeks == [(4, 1)]

    def test_never_stabilizes_seeks_after_stability_grace(self, rig):
        # A session that never reaches STABLE does NOT lose its replay: the
        # stability preference only holds for STABILITY_GRACE, after which
        # the quiet window alone decides (legacy sought blind after 2s on
        # every stream; abandoning would regress undetectable streams).
        rig.start()                       # resume requested at t=0.0, never stable
        rig.advance(QUIET)                # t=2.0: quiet, but within the grace
        assert rig.seeks == []
        assert rig.logged('stream not stable yet')

        rig.advance(GRACE - QUIET)        # t=4.0: grace over -> quiet decides
        # No profile exists, so the coordinator resolved the player itself
        # (FakeGateway.active_player_id() -> 1).
        assert rig.seeks == [(4, 1)]
        assert 'resume' not in rig.pending
        assert rig.errors == []           # no handler blew up along the way

    def test_pause_before_due_attempt_cancels(self, rig):
        # A pending seek that fires while the session is paused is abandoned
        # (replaying into a paused player is pointless; unpause will re-trigger).
        rig.start()
        rig.make_stable()
        rig.session.paused = True         # paused before the attempt comes due

        rig.advance(2.0)                  # attempt fires -> cancelled by pause
        assert rig.seeks == []
        assert 'resume' not in rig.pending
        assert rig.logged('paused')

        rig.advance(5.0)                  # later advances never seek
        assert rig.seeks == []

    def test_disabled_config_drops_at_trigger_time(self):
        # seek_back_config disabled -> the trigger never schedules anything
        # (legacy 'change' parity: enabled was checked at trigger time).
        rig = Rig()
        rig.facade.seek_configs['resume'] = (False, 0)
        rig.start()
        assert rig.seeks == []
        assert 'resume' not in rig.pending    # never scheduled
        assert rig.logged('not enabled')

    def test_zero_seconds_config_warns_at_trigger_time(self):
        # Enabled-but-zero-length is a user misconfiguration and must surface
        # at WARNING in normal field logs (legacy parity), not just debug.
        rig = Rig()
        rig.facade.seek_configs['resume'] = (True, 0)
        rig.start()
        assert rig.seeks == []
        assert 'resume' not in rig.pending
        assert any('Invalid seek back seconds' in m for m in rig.warnings)

    def test_disabled_mid_defer_cancels_at_fire_time(self, rig):
        # The trigger-time check is the primary; a toggle-off DURING the
        # defer window is still honored when the attempt would execute.
        rig.start()
        rig.make_stable()
        rig.facade.seek_configs['resume'] = (False, 0)   # toggled off mid-defer
        rig.advance(QUIET)
        assert rig.seeks == []
        assert rig.logged('no longer enabled')

    def test_vendor_busy_recorded_even_before_stable(self, rig):
        # Vendors are probed on EVERY attempt, including pre-STABLE defers: a
        # PM4K 'initializing' phase during our stabilization must land in the
        # activity view, or we would seek right into its finishing seek.
        rig.start()                       # never stabilized
        rig.gateway.window_properties[VENDOR_PROP] = '1'
        rig.advance(RECHECK)              # a pre-STABLE attempt fires
        assert rig.coordinator._last_vendor_busy is not None
        assert rig.seeks == []

    def test_vendor_busy_defers_and_recently_busy_window_bridges_a_clear(self, rig):
        # A busy vendor property defers the attempt AND records the sighting;
        # after the property clears, the attempt still defers until QUIET_WINDOW
        # past the sighting (the recently-busy window lives in the activity feed).
        rig.start()
        rig.make_stable()
        rig.gateway.window_properties[VENDOR_PROP] = '1'

        rig.advance(2.0)                  # t=2.0: STABLE + quiet-from-start, but busy
        assert rig.seeks == []
        assert rig.coordinator._last_vendor_busy == 2.0   # sighting recorded

        del rig.gateway.window_properties[VENDOR_PROP]    # vendor goes idle
        rig.advance(0.5)                  # t=2.5: not busy, but 0.5s < 2.0 since sighting
        assert rig.seeks == []

        rig.advance(1.5)                  # t=4.0: 2.0s since the sighting -> seek
        assert rig.seeks == [(4, 1)]

    def test_vendor_busy_forever_is_bounded_by_deadline(self, rig):
        # Even a vendor that never goes idle cannot pin us forever: the DEADLINE
        # abandons the attempt.
        rig.start()
        rig.make_stable()
        rig.gateway.window_properties[VENDOR_PROP] = '1'
        for _ in range(DEADLINE_STEPS):
            rig.advance(0.5)              # march to t=8.0 while vendor stays busy
        assert rig.seeks == []
        assert 'resume' not in rig.pending
        assert rig.logged('Abandoning resume')

    def test_seek_occurred_feeds_quiet_window(self, rig):
        # SeekOccurred (any seek, from any source) records activity on the
        # session; a pending seek then defers until QUIET_WINDOW past it.
        rig.start()
        rig.make_stable()
        rig.advance(QUIET)                # resume seek at t=2.0 (activity=2.0)
        rig.advance(RECHECK)              # t=2.5 (strictly after the seek)

        rig.post(events.UserOffsetSaved(       # 'change' requested at t=2.5
            session_id=rig.session.session_id, profile=None, ms=-50))

        rig.advance(RECHECK)              # t=3.0
        rig.dispatcher.post(events.SeekOccurred(time_ms=0, offset_ms=0))
        rig.dispatcher.run_pending()      # activity bumped to 3.0

        rig.advance(QUIET - RECHECK)      # t=4.5: WITHOUT the SeekOccurred the
        assert rig.seeks == [(4, 1)]      # change would have fired at 4.0/4.5

        rig.advance(RECHECK)              # t=5.0: QUIET past the SeekOccurred
        assert rig.seeks == [(4, 1), (4, 1)]   # 'change' seek finally executes

    def test_cross_type_served_abandons(self, rig):
        # 'unpause' requested first, then 'adjust'. When both become eligible,
        # the older chain (unpause) fires first and executes; the 'adjust'
        # attempt then finds one of our own seeks executed AT/AFTER its
        # request and abandons as already served.
        rig.start()
        rig.make_stable()
        rig.advance(QUIET)                # resume seek at t=2.0
        rig.advance(RECHECK)              # t=2.5 (strictly after the seek)

        sid = rig.session.session_id
        rig.post(events.Resumed())        # 'unpause' requested first (t=2.5)
        # initial defaults to False: a mid-play change, no startup skip.
        rig.post(events.StreamStabilized(session_id=sid, profile_changed=True))
        assert 'unpause' in rig.pending and 'adjust' in rig.pending

        rig.advance(QUIET - RECHECK)      # t=4.0: both eligible; unpause wins
        assert rig.session.seek_history.get('unpause') == 4.0
        assert 'adjust' not in rig.session.seek_history   # adjust never executed
        assert 'adjust' not in rig.pending
        assert rig.logged('Abandoning adjust')
        assert rig.seeks == [(4, 1), (4, 1)]   # resume + unpause only

    def test_same_instant_trigger_is_served_by_that_instants_seek(self, rig):
        # The >= boundary: a trigger requested at the exact instant one of our
        # seeks executes is treated as served (the safe side against a double
        # rewind — legacy's cooldown dropped it too).
        rig.start()
        rig.make_stable()
        rig.advance(QUIET)                # resume executes at t=2.0
        rig.post(events.Resumed())        # 'unpause' requested at exactly t=2.0

        rig.advance(DEADLINE)             # plenty of time to fire if it could
        assert rig.session.seek_history.get('unpause') is None
        assert rig.logged('Abandoning unpause')
        assert rig.seeks == [(4, 1)]      # only the resume seek ever ran


# ============================================================================
# Reciprocity and failed seeks
# ============================================================================

class TestReciprocityAndFailure:

    def test_reciprocal_property_set_during_seek_and_cleared_after(self):
        # While WE seek, the home-window reciprocity property is '1' so other
        # addons defer to us; it is cleared once the seek returns.
        class CapturingGateway(FakeGateway):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self.reciprocal_at_seek = []

            def seek_back(self, seconds, player_id=None):
                # Capture the reciprocity flag AS the seek runs.
                self.reciprocal_at_seek.append(
                    self.window_properties.get(RECIPROCAL))
                return super().seek_back(seconds, player_id=player_id)

        rig = Rig(gateway=CapturingGateway())
        rig.start()
        rig.make_stable()
        rig.advance(2.0)                  # resume seek executes

        assert rig.seeks == [(4, 1)]
        assert rig.gateway.reciprocal_at_seek == ['1']   # set during the seek
        assert RECIPROCAL not in rig.gateway.window_properties   # cleared after

    def test_failed_seek_clears_pending_without_recording_history(self):
        # A seek the gateway reports as failed clears the pending attempt but
        # does NOT record seek_history / last_seek_activity (so it neither
        # debounces future triggers nor counts as quiet-window activity).
        class FailingGateway(FakeGateway):
            def seek_back(self, seconds, player_id=None):
                self.seeks.append((seconds, player_id))
                return False

        rig = Rig(gateway=FailingGateway())
        rig.start()
        rig.make_stable()
        rig.advance(2.0)                  # attempt fires, gateway returns False

        assert rig.seeks == [(4, 1)]      # the seek WAS attempted
        assert 'resume' not in rig.pending            # pending cleared
        assert rig.session.seek_history == {}         # history NOT updated
        assert rig.session.last_seek_activity is None
        assert rig.logged('failed')


# ============================================================================
# Staleness & session turnover
# ============================================================================

class TestStaleness:

    def test_reopen_recreates_pending_and_dead_stamped_execute_is_inert(self, rig):
        # In-place reopen: the second PlaybackStarted cancels the old session's
        # pending entries and re-creates them for the new session; an ExecuteSeek
        # stamped with the dead session id is dropped by the is_alive guard.
        rig.start()                       # session #1, resume pending (deferred)
        first_id = rig.session.session_id
        assert rig.pending_request('resume').session_id == first_id

        rig.post(events.PlaybackStarted())    # reopen without a stop
        second = rig.session
        assert second.session_id != first_id
        assert rig.tracker.is_alive(first_id) is False
        # Pending re-created under the NEW session id (old entry superseded).
        assert rig.pending_request('resume').session_id == second.session_id

        # A manually posted ExecuteSeek stamped with the dead session is inert.
        rig.post(events.ExecuteSeek(session_id=first_id, reason='resume',
                                    requested_at=0.0))
        assert rig.seeks == []

        # The new session's own chain still proceeds to a seek.
        rig.make_stable()
        rig.advance(2.0)
        assert rig.seeks == [(4, 1)]

    def test_playback_stopped_cancels_pending(self, rig):
        rig.start()
        rig.make_stable()
        assert 'resume' in rig.pending

        rig.post(events.PlaybackStopped())
        assert rig.tracker.current is None
        assert rig.pending == set()          # cancelled on stop

        rig.advance(10.0)                 # later advances never seek
        assert rig.seeks == []

    def test_execution_records_seek_history_and_activity(self, rig):
        # On a successful execution both seek_history[reason] and
        # last_seek_activity are stamped on the SESSION (session-borne state).
        rig.start()
        rig.make_stable()
        rig.advance(2.0)
        assert rig.seeks == [(4, 1)]
        assert rig.session.seek_history == {'resume': 2.0}
        assert rig.session.last_seek_activity == 2.0
