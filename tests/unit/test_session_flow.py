"""Integration-style session flow tests on fakes (Phase 3/4 gate evidence).

Wires the REAL ServiceRuntime graph (dispatcher, tracker, router, detector,
platform recorder, offset manager, seek backs) under Kodistubs, with the Kodi
I/O seams swapped: the detector's gateway becomes a scriptable FakeGateway,
the dispatcher's clock a FakeClock (so the probe/verify timers are driven
deterministically with run_pending), and set_audio_delay/notifications are
captured. Covers: provisional apply -> release on STABLE, late-codec probe
chasing, in-place reopen supersession, stale detector-event inertness,
AV-change storms collapsing to one apply, and post-stop AV events.
"""

import pytest

from resources.lib import rpc_client
from resources.lib.aom.app import events
from resources.lib.aom.app.stream_detector import INFOLABEL_FPS, INFOLABEL_HDR
from resources.lib.aom.domain.stream_state import StreamState
from tests.fakes import FakeClock, FakeGateway


# Keyed by the production constants so a renamed infolabel cannot silently
# degrade the scripted stream while these tests stay green.
INFOLABELS = {
    INFOLABEL_FPS: '23.976',
    INFOLABEL_HDR: 'dolbyvision',
}


@pytest.fixture
def rig(monkeypatch):
    applied = []
    monkeypatch.setattr(rpc_client, 'set_audio_delay',
                        lambda player_id, seconds: applied.append(
                            (player_id, round(seconds * 1000))) or True)

    from resources.lib.aom.runtime import ServiceRuntime
    runtime = ServiceRuntime()

    # Deterministic time everywhere: every clock-holding component gets the
    # same FakeClock, so timers, session birth times, and the seek quiet
    # window all move only when the test advances it.
    clock = FakeClock()
    runtime.dispatcher._clock = clock
    runtime.session_tracker._clock = clock
    runtime.seek_scheduler._clock = clock
    runtime.seek_coordinator._clock = clock

    # The platform seam: script what the "player" reports via the fake
    # gateway; mutate its attributes between pumps to change the stream.
    # Every gateway consumer gets the same fake (detector reads; the seek
    # coordinator probes vendor properties and executes seeks through it;
    # the adjustment watcher polls Player.AudioDelay).
    gateway = FakeGateway(infolabels=dict(INFOLABELS))
    runtime.detector._gateway = gateway
    runtime.seek_coordinator._gateway = gateway
    runtime.adjustment_watcher._gateway = gateway

    # --- settings seams (facade instance shared across components) ------------
    facade = runtime.offset_manager.settings_facade
    monkeypatch.setattr(facade, 'is_new_install', lambda: False)
    monkeypatch.setattr(facade, 'is_hdr_enabled', lambda hdr: True)
    monkeypatch.setattr(facade, 'fps_override_enabled', lambda hdr: False)
    monkeypatch.setattr(facade, 'get_offset_ms', lambda profile: -125)
    # Hermeticity: the platform recorder's writes must not reach the stubs'
    # shared settings state.
    monkeypatch.setattr(facade, 'store_boolean_if_changed',
                        lambda setting_id, value: None)

    # Hermeticity: the blanket False keeps the adjustment watcher ineligible
    # (no recurring WatchTick timers muddying the pump) and disables
    # seek-backs, so flow tests only see the events they drive.
    monkeypatch.setattr(runtime.offset_manager.settings_manager,
                        'get_setting_boolean', lambda setting_id: False)

    notified = []
    monkeypatch.setattr(runtime.offset_manager.notification_handler,
                        'notify_audio_offset_applied',
                        lambda ms, profile: notified.append(
                            (ms, profile.setting_id())))

    # Components subscribe as run() would; the dispatcher stays un-started and
    # is pumped manually. (The seek scheduler subscribed at construction.)
    runtime.offset_manager.start()
    return runtime, clock, gateway, applied, notified


def _settle(runtime, clock, seconds=1.0):
    """Let the detector's pending verification window elapse and fire."""
    clock.advance(seconds)
    runtime.dispatcher.run_pending()


def test_startup_apply_is_provisional_then_released_on_stable(rig):
    runtime, clock, _gateway, applied, notified = rig

    runtime.dispatcher.post(events.PlaybackStarted())
    runtime.dispatcher.run_pending()

    session = runtime.session_tracker.current
    assert applied == [(1, -125)]                      # offset applied at once
    assert notified == []                              # ...but held (provisional)
    assert session.stream_state is StreamState.STABILIZING
    assert session.applied == ('dolbyvision_all_truehd', -125)
    assert session.pending_notification == ('dolbyvision_all_truehd', -125)
    assert session.profile.setting_id() == 'dolbyvision_all_truehd'

    _settle(runtime, clock)

    assert session.stream_state is StreamState.STABLE
    assert applied == [(1, -125)]                      # dedupe: no re-apply
    assert notified == [(-125, 'dolbyvision_all_truehd')]   # released exactly once
    assert session.pending_notification is None


def test_late_codec_is_chased_by_the_probe_chain(rig):
    # Legacy blocked inside rpc retries while the codec negotiated; the
    # detector chases it with scheduled probes instead — same patience, no
    # blocking. Jittered spacing is <= 0.6s, so advancing 0.6s per pump fires
    # exactly one probe per step.
    runtime, clock, gateway, applied, _notified = rig
    gateway.codec = 'none'

    runtime.dispatcher.post(events.PlaybackStarted())
    runtime.dispatcher.run_pending()
    session = runtime.session_tracker.current
    assert applied == []                               # nothing to apply yet
    assert session.profile is None
    assert session.stream_state is StreamState.STARTING

    _settle(runtime, clock, 0.6)                       # probe 2: still none
    assert applied == []

    gateway.codec = 'truehd'                           # negotiation finished
    _settle(runtime, clock, 0.6)                       # probe 3 completes

    assert session.profile.setting_id() == 'dolbyvision_all_truehd'
    assert applied == [(1, -125)]
    assert session.stream_state is StreamState.STABILIZING

    _settle(runtime, clock)                            # verify -> STABLE
    assert session.stream_state is StreamState.STABLE


def test_in_place_reopen_supersedes_and_drops_pending(rig):
    runtime, clock, _gateway, applied, notified = rig

    runtime.dispatcher.post(events.PlaybackStarted())
    runtime.dispatcher.run_pending()
    first = runtime.session_tracker.current
    assert first.pending_notification is not None

    # Reopen without a stop: fresh session, fresh apply.
    runtime.dispatcher.post(events.PlaybackStarted())
    runtime.dispatcher.run_pending()
    second = runtime.session_tracker.current
    assert second.session_id != first.session_id
    assert applied == [(1, -125), (1, -125)]           # re-applied for new session

    # Stale detector events for the dead session are inert.
    runtime.dispatcher.post(events.StreamStabilized(session_id=first.session_id))
    runtime.dispatcher.post(events.ProfileChanged(session_id=first.session_id))
    runtime.dispatcher.post(events.VerifyStream(session_id=first.session_id, seq=999))
    runtime.dispatcher.run_pending()
    assert notified == []                              # nothing released
    assert second.stream_state is StreamState.STABILIZING
    assert applied == [(1, -125), (1, -125)]           # no stale re-apply

    # The live session still settles normally.
    _settle(runtime, clock)
    assert second.stream_state is StreamState.STABLE
    assert notified == [(-125, 'dolbyvision_all_truehd')]


def test_mid_play_change_applies_immediately_and_notifies_on_stable(rig):
    # Intentional Phase 4 strengthening (documented in stream_detector):
    # the new offset is applied the moment the change is observed —
    # ~1s earlier than legacy's post-debounce apply — while the
    # notification still waits for the stream to re-stabilize.
    runtime, clock, gateway, applied, notified = rig

    runtime.dispatcher.post(events.PlaybackStarted())
    runtime.dispatcher.run_pending()
    session = runtime.session_tracker.current
    _settle(runtime, clock)
    assert len(notified) == 1

    gateway.codec = 'eac3'
    runtime.dispatcher.post(events.AvChanged())
    runtime.dispatcher.run_pending()

    assert applied == [(1, -125), (1, -125)]           # applied at once
    assert session.applied == ('dolbyvision_all_eac3', -125)
    assert session.stream_state is StreamState.STABILIZING
    assert len(notified) == 1                          # held until re-stable
    assert session.pending_notification == ('dolbyvision_all_eac3', -125)

    _settle(runtime, clock)
    assert session.stream_state is StreamState.STABLE
    assert notified[-1] == (-125, 'dolbyvision_all_eac3')
    assert session.pending_notification is None


def test_resume_seek_waits_for_stable_and_quiet_window_from_start(rig, monkeypatch):
    # Worked-trace parity: session start counts as seek activity, so the
    # resume seek executes QUIET_WINDOW (2.0s) after start — reproducing the
    # legacy mandatory 2s settle without a bespoke constant — and only once
    # the stream is STABLE. The reciprocity property is set around the seek
    # and cleared afterwards.
    runtime, clock, gateway, applied, _notified = rig
    monkeypatch.setattr(
        runtime.seek_scheduler._settings, 'seek_back_config',
        lambda reason: (True, 4) if reason == 'resume' else (False, 0))

    runtime.dispatcher.post(events.PlaybackStarted())
    runtime.dispatcher.run_pending()          # t=0: probe adopts; seek defers
    assert applied == [(1, -125)]             # offset FIRST (ordering restored)
    assert gateway.seeks == []

    _settle(runtime, clock, 0.5)              # t=0.5: still deferring
    assert gateway.seeks == []
    _settle(runtime, clock, 0.5)              # t=1.0: verify -> STABLE; not quiet
    session = runtime.session_tracker.current
    assert session.stream_state is StreamState.STABLE
    assert gateway.seeks == []
    _settle(runtime, clock, 0.5)              # t=1.5: still inside quiet window
    assert gateway.seeks == []
    _settle(runtime, clock, 0.5)              # t=2.0: quiet -> seek executes

    assert gateway.seeks == [(4, 1)]          # configured length, live player
    assert 'script.audiooffsetmanager.seeking' not in gateway.window_properties
    assert session.seek_history['resume'] == pytest.approx(2.0)


def test_blip_and_revert_fires_no_legacy_change_event(rig):
    # A codec blip that reverts (no net change) re-earns STABLE but must NOT
    # reach the legacy bus: legacy's filter never fired ON_AV_CHANGE for it,
    # and SeekBacks would answer one with a spurious 'adjust' seek-back.
    runtime, clock, gateway, applied, notified = rig

    runtime.dispatcher.post(events.PlaybackStarted())
    runtime.dispatcher.run_pending()
    _settle(runtime, clock)
    session = runtime.session_tracker.current
    assert session.stream_state is StreamState.STABLE

    changes = []
    runtime.router.subscribe('ON_AV_CHANGE', lambda: changes.append(1))
    baseline_applied, baseline_notified = len(applied), len(notified)

    gateway.codec = 'none'                   # blip: profile goes incomplete
    runtime.dispatcher.post(events.AvChanged())
    runtime.dispatcher.run_pending()
    assert session.stream_state is StreamState.STABILIZING

    gateway.codec = 'truehd'                 # reverts inside the window
    _settle(runtime, clock)
    assert session.stream_state is StreamState.STABLE
    assert changes == []                     # suppressed: nothing announced
    assert len(applied) == baseline_applied
    assert len(notified) == baseline_notified


def test_failed_apply_rpc_is_retried_on_next_event(rig, monkeypatch):
    # A failed Player.SetAudioDelay must not be recorded as applied — the
    # dedupe guard would block every retry for the rest of the session.
    runtime, clock, _gateway, applied, notified = rig

    calls = {'n': 0}

    def flaky_set_audio_delay(player_id, seconds):
        calls['n'] += 1
        if calls['n'] == 1:
            return False                     # first apply attempt fails
        applied.append((player_id, round(seconds * 1000)))
        return True

    monkeypatch.setattr(rpc_client, 'set_audio_delay', flaky_set_audio_delay)

    runtime.dispatcher.post(events.PlaybackStarted())
    runtime.dispatcher.run_pending()
    session = runtime.session_tracker.current
    assert applied == []                     # RPC failed
    assert session.applied is None           # NOT recorded as applied

    _settle(runtime, clock)                  # STABLE -> ON_AV_CHANGE retries
    assert applied == [(1, -125)]
    assert session.applied == ('dolbyvision_all_truehd', -125)
    assert notified == [(-125, 'dolbyvision_all_truehd')]


def test_av_change_storm_collapses_to_one_apply(rig):
    runtime, clock, gateway, applied, notified = rig

    runtime.dispatcher.post(events.PlaybackStarted())
    runtime.dispatcher.run_pending()
    _settle(runtime, clock)
    baseline = len(applied)

    # A storm of AV changes around one real codec switch.
    gateway.codec = 'eac3'
    runtime.dispatcher.post(events.AvChanged())
    runtime.dispatcher.post(events.AvChanged())
    runtime.dispatcher.post(events.AvChanged())
    runtime.dispatcher.run_pending()
    assert len(applied) == baseline + 1                # exactly one re-apply

    _settle(runtime, clock)
    session = runtime.session_tracker.current
    assert session.stream_state is StreamState.STABLE
    assert notified[-1] == (-125, 'dolbyvision_all_eac3')


def test_unchanged_av_change_is_ignored(rig):
    runtime, clock, _gateway, applied, notified = rig

    runtime.dispatcher.post(events.PlaybackStarted())
    runtime.dispatcher.run_pending()
    _settle(runtime, clock)
    session = runtime.session_tracker.current
    baseline_applied, baseline_notified = len(applied), len(notified)

    runtime.dispatcher.post(events.AvChanged())        # nothing changed
    runtime.dispatcher.run_pending()
    _settle(runtime, clock)

    assert session.stream_state is StreamState.STABLE  # never regressed
    assert len(applied) == baseline_applied
    assert len(notified) == baseline_notified


def test_user_offset_saved_notifies_live_session_only(rig, monkeypatch):
    # The manual-offset notification consumes the watcher's typed event: the
    # toast describes the payload captured at store time, and a stamp from a
    # superseded session is dropped. (The legacy USER_ADJUSTMENT wire carried
    # no payload and no stamp, so a reopen between store and dispatch made
    # the notification describe the NEW stream's profile.)
    runtime, _clock, _gateway, _applied, _notified = rig

    manual = []
    monkeypatch.setattr(runtime.offset_manager.notification_handler,
                        'notify_manual_offset_saved',
                        lambda ms, profile: manual.append(
                            (ms, profile.setting_id())))

    runtime.dispatcher.post(events.PlaybackStarted())
    runtime.dispatcher.run_pending()
    session = runtime.session_tracker.current
    profile = session.profile

    runtime.dispatcher.post(events.UserOffsetSaved(
        session_id=session.session_id, profile=profile, ms=-75))
    runtime.dispatcher.run_pending()
    assert manual == [(-75, 'dolbyvision_all_truehd')]

    # In-place reopen already queued ahead of the stale-stamped event: by the
    # time the event dispatches, its session is superseded -> no toast.
    runtime.dispatcher.post(events.PlaybackStarted())
    runtime.dispatcher.post(events.UserOffsetSaved(
        session_id=session.session_id, profile=profile, ms=-100))
    runtime.dispatcher.run_pending()
    assert manual == [(-75, 'dolbyvision_all_truehd')]


def test_av_event_after_stop_is_ignored(rig):
    runtime, _clock, _gateway, applied, _notified = rig

    runtime.dispatcher.post(events.PlaybackStarted())
    runtime.dispatcher.post(events.PlaybackStopped())
    runtime.dispatcher.run_pending()
    assert runtime.session_tracker.current is None
    applied_count = len(applied)

    # No session: neither the detector nor the offset manager react.
    runtime.dispatcher.post(events.AvChanged())
    runtime.router.publish('ON_AV_CHANGE')
    runtime.dispatcher.run_pending()
    assert len(applied) == applied_count


def test_pause_state_lives_on_session(rig):
    runtime, _clock, _gateway, _applied, _notified = rig

    runtime.dispatcher.post(events.PlaybackStarted())
    runtime.dispatcher.post(events.Paused())
    runtime.dispatcher.run_pending()
    assert runtime.session_tracker.current.paused is True

    runtime.dispatcher.post(events.Resumed())
    runtime.dispatcher.run_pending()
    assert runtime.session_tracker.current.paused is False
