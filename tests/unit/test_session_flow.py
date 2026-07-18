"""Integration-style session flow tests on fakes (phase-gate evidence).

Wires the REAL ServiceRuntime graph (dispatcher, tracker, detector, platform
recorder, offset applier, notifier, seek scheduler, adjustment watcher) under
Kodistubs, with the Kodi I/O seams swapped: every gateway consumer gets one
scriptable FakeGateway, every clock-holding component the same FakeClock (so
probe/verify/seek/watch timers are driven deterministically with
run_pending), settings reads are monkeypatched on the single Settings
adapter, and applies/toasts are captured at the gateway/notifier boundaries.

Covers: provisional apply -> release on STABLE, late-codec probe chasing,
in-place reopen supersession, stale detector-event inertness, AV-change
storms collapsing to one apply, blip-revert suppression, failed-RPC retry,
the applied-before-RPC watcher contract (both boundary-pinned and end-to-end
via real watch ticks), seek quiet-window timing from session start, and
post-stop AV events.
"""

import pytest

from resources.lib.aom.app import events
from resources.lib.aom.app.notifier import (STRING_OFFSET_APPLIED,
                                            STRING_OFFSET_SAVED)
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
    from resources.lib.aom.runtime import ServiceRuntime
    runtime = ServiceRuntime()

    # Deterministic time everywhere: every clock-holding component gets the
    # same FakeClock, so timers, session birth times, the seek quiet window,
    # and the watcher cadences all move only when the test advances it.
    clock = FakeClock()
    runtime.dispatcher._clock = clock
    runtime.session_tracker._clock = clock
    runtime.seek_scheduler._clock = clock
    runtime.seek_coordinator._clock = clock
    runtime.notifier._clock = clock
    runtime.adjustment_watcher._clock = clock

    # The platform seam: script what the "player" reports via the fake
    # gateway; mutate its attributes between pumps to change the stream.
    # Every gateway consumer gets the same fake (detector reads; the applier
    # sets the delay; the seek coordinator probes vendor properties and
    # executes seeks; the adjustment watcher polls Player.AudioDelay).
    gateway = FakeGateway(infolabels=dict(INFOLABELS))
    runtime.detector._gateway = gateway
    runtime.offset_applier._gateway = gateway
    runtime.seek_coordinator._gateway = gateway
    runtime.adjustment_watcher._gateway = gateway

    # Applies captured in legacy (player_id, ms) shape at the RPC boundary.
    applied = []
    gateway.set_audio_delay = (
        lambda player_id, seconds: applied.append(
            (player_id, round(seconds * 1000))) or True)

    # --- settings seams (the single Settings adapter, shared by all) ----------
    settings = runtime.settings
    monkeypatch.setattr(settings, 'is_hdr_enabled', lambda hdr: True)
    monkeypatch.setattr(settings, 'fps_override_enabled', lambda hdr: False)
    monkeypatch.setattr(runtime.offsets, 'get', lambda profile: -125)
    # Hermeticity: the platform recorder's writes must not reach the stubs'
    # shared settings state; seek-backs and the watcher are off unless a test
    # enables them, so flow tests only see the events they drive.
    monkeypatch.setattr(settings, 'store_boolean_if_changed',
                        lambda setting_id, value: True)
    monkeypatch.setattr(settings, 'seek_back_config',
                        lambda reason: (False, 0))
    monkeypatch.setattr(settings, 'active_monitoring_enabled', lambda: False)

    # Toasts captured at the notifier's assembly boundary: pending/dedupe
    # logic still runs, only the gui/settings reads are skipped.
    notified = []
    monkeypatch.setattr(
        runtime.notifier, '_toast',
        lambda string_id, ms, profile: notified.append(
            (string_id, ms, profile.setting_id())))

    # The dispatcher stays un-started and is pumped manually; every component
    # subscribed at construction, exactly as run() relies on.
    return runtime, clock, gateway, applied, notified


def _settle(runtime, clock, seconds=1.0):
    """Let the detector's pending verification window elapse and fire."""
    clock.advance(seconds)
    runtime.dispatcher.run_pending()


def _applied_toasts(notified):
    return [(ms, key) for kind, ms, key in notified
            if kind == STRING_OFFSET_APPLIED]


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
    assert _applied_toasts(notified) == [(-125, 'dolbyvision_all_truehd')]
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
    assert _applied_toasts(notified) == [(-125, 'dolbyvision_all_truehd')]


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
    assert _applied_toasts(notified)[-1] == (-125, 'dolbyvision_all_eac3')
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
    assert applied == [(1, -125)]             # offset applied before any seek
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


def test_blip_and_revert_announces_no_change(rig):
    # A codec blip that reverts (no net change) re-earns STABLE but announces
    # nothing: no re-apply, no toast, and no 'adjust' seek request (legacy's
    # duplicate-codec filter never fired an event for a reverting blip).
    runtime, clock, gateway, applied, notified = rig

    runtime.dispatcher.post(events.PlaybackStarted())
    runtime.dispatcher.run_pending()
    _settle(runtime, clock)
    session = runtime.session_tracker.current
    assert session.stream_state is StreamState.STABLE

    baseline_applied, baseline_notified = len(applied), len(notified)

    gateway.codec = 'none'                   # blip: profile goes incomplete
    runtime.dispatcher.post(events.AvChanged())
    runtime.dispatcher.run_pending()
    assert session.stream_state is StreamState.STABILIZING

    gateway.codec = 'truehd'                 # reverts inside the window
    _settle(runtime, clock)
    assert session.stream_state is StreamState.STABLE
    assert len(applied) == baseline_applied
    assert len(notified) == baseline_notified
    assert 'aom.seek.adjust' not in runtime.dispatcher._active_keys


def test_failed_apply_rpc_is_retried_on_next_stabilization(rig):
    # A failed Player.SetAudioDelay must not stay recorded as applied — the
    # dedupe guard would block every retry for the rest of the session.
    runtime, clock, gateway, applied, notified = rig

    calls = {'n': 0}

    def flaky_set_audio_delay(player_id, seconds):
        calls['n'] += 1
        if calls['n'] == 1:
            return False                     # first apply attempt fails
        applied.append((player_id, round(seconds * 1000)))
        return True

    gateway.set_audio_delay = flaky_set_audio_delay

    runtime.dispatcher.post(events.PlaybackStarted())
    runtime.dispatcher.run_pending()
    session = runtime.session_tracker.current
    assert applied == []                     # RPC failed
    assert session.applied is None           # NOT recorded as applied

    _settle(runtime, clock)                  # StreamStabilized retries
    assert applied == [(1, -125)]
    assert session.applied == ('dolbyvision_all_truehd', -125)
    assert _applied_toasts(notified) == [(-125, 'dolbyvision_all_truehd')]


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
    assert _applied_toasts(notified)[-1] == (-125, 'dolbyvision_all_eac3')


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


def test_applied_is_recorded_before_the_rpc_executes(rig):
    # The AdjustmentWatcher's self-echo suppression depends on this exact
    # ordering contract: at the instant Kodi's delay can reflect our write,
    # session.applied must already equal it. Pinned AT the RPC boundary so a
    # future applier change cannot silently flip back to the legacy
    # record-after-success order.
    runtime, _clock, gateway, _applied, _notified = rig

    seen_at_rpc = []

    def rpc(player_id, seconds):
        session = runtime.session_tracker.current
        seen_at_rpc.append((session.applied, round(seconds * 1000)))
        return True

    gateway.set_audio_delay = rpc

    runtime.dispatcher.post(events.PlaybackStarted())
    runtime.dispatcher.run_pending()

    assert seen_at_rpc == [(('dolbyvision_all_truehd', -125), -125)]


def test_auto_apply_never_emits_user_offset_saved(rig, monkeypatch):
    # End-to-end self-echo: with the watcher armed and Kodi's infolabel
    # echoing our own automatic apply, ticks must adopt the value as
    # baseline — never store it or post UserOffsetSaved (which would toast
    # the user and fire a 'change' seek for our own write).
    runtime, clock, gateway, _applied, _notified = rig

    monkeypatch.setattr(runtime.settings, 'active_monitoring_enabled',
                        lambda: True)
    stored = []
    monkeypatch.setattr(runtime.offsets, 'store',
                        lambda profile, ms: stored.append(
                            (profile.setting_id(), ms)) or True)
    saved = []
    runtime.dispatcher.subscribe(events.UserOffsetSaved, saved.append)

    runtime.dispatcher.post(events.PlaybackStarted())
    runtime.dispatcher.run_pending()
    session = runtime.session_tracker.current
    assert session.applied == ('dolbyvision_all_truehd', -125)

    # Kodi's Player.AudioDelay now echoes the applied value.
    gateway.infolabels['Player.AudioDelay'] = '-0.125 s'
    for _ in range(4):                         # several idle polls
        clock.advance(1.0)
        runtime.dispatcher.run_pending()

    assert session.watch_baseline_ms == -125   # adopted as ours
    assert stored == []
    assert saved == []


def test_user_offset_saved_notifies_live_session_only(rig):
    # The manual-offset toast consumes the watcher's typed event: it
    # describes the payload captured at store time, and a stamp from a
    # superseded session is dropped. (The legacy USER_ADJUSTMENT wire carried
    # no payload and no stamp, so a reopen between store and dispatch made
    # the notification describe the NEW stream's profile.)
    runtime, _clock, _gateway, _applied, notified = rig

    runtime.dispatcher.post(events.PlaybackStarted())
    runtime.dispatcher.run_pending()
    session = runtime.session_tracker.current
    profile = session.profile

    runtime.dispatcher.post(events.UserOffsetSaved(
        session_id=session.session_id, profile=profile, ms=-75))
    runtime.dispatcher.run_pending()
    manual = [(ms, key) for kind, ms, key in notified
              if kind == STRING_OFFSET_SAVED]
    assert manual == [(-75, 'dolbyvision_all_truehd')]

    # In-place reopen already queued ahead of the stale-stamped event: by the
    # time the event dispatches, its session is superseded -> no toast.
    runtime.dispatcher.post(events.PlaybackStarted())
    runtime.dispatcher.post(events.UserOffsetSaved(
        session_id=session.session_id, profile=profile, ms=-100))
    runtime.dispatcher.run_pending()
    manual = [(ms, key) for kind, ms, key in notified
              if kind == STRING_OFFSET_SAVED]
    assert manual == [(-75, 'dolbyvision_all_truehd')]


def test_av_event_after_stop_is_ignored(rig):
    runtime, _clock, _gateway, applied, _notified = rig

    runtime.dispatcher.post(events.PlaybackStarted())
    runtime.dispatcher.post(events.PlaybackStopped())
    runtime.dispatcher.run_pending()
    assert runtime.session_tracker.current is None
    applied_count = len(applied)

    # No session: neither the detector nor the applier react.
    runtime.dispatcher.post(events.AvChanged())
    runtime.dispatcher.post(events.ProfileChanged(session_id=1))
    runtime.dispatcher.post(events.StreamStabilized(session_id=1))
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
