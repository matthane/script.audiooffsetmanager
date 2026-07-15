"""Behavioral tests for the legacy event router (MIGRATION shim) + runtime wiring.

The router must reproduce the deleted EventManager's component-facing surface
(event names on the legacy bus) while detection and stream-state transitions
belong to the StreamDetector. These tests pin the translation contract
(ProfileChanged -> PROFILE_CHANGED, StreamStabilized -> ON_AV_CHANGE), the
session-stamped staleness drops, and the load-bearing subscription order in
the runtime graph. (The cross-thread publish marshaling died with
ActiveMonitor, its last producer.)
"""

import pytest

from resources.lib.aom.app import events
from resources.lib.aom.app.dispatcher import Dispatcher
from resources.lib.aom.app.legacy_router import LegacyEventRouter
from resources.lib.aom.app.session import SessionTracker
from resources.lib.aom.domain.stream_state import StreamState
from resources.lib.settings_facade import SettingsFacade
from resources.lib.settings_manager import SettingsManager
from tests.fakes import FakeClock


@pytest.fixture
def rig():
    errors = []
    dispatcher = Dispatcher(clock=FakeClock(), log_error=errors.append)
    tracker = SessionTracker(dispatcher)
    manager = SettingsManager()
    facade = SettingsFacade(manager)
    router = LegacyEventRouter(dispatcher, tracker, facade)
    return dispatcher, tracker, router, errors


def _start_playback(dispatcher, tracker):
    dispatcher.post(events.PlaybackStarted())
    dispatcher.run_pending()
    return tracker.current


def test_service_runtime_graph_wiring():
    # Full composition-root construction under Kodistubs: required constructor
    # args are all wired, and every component shares the tracker + dispatcher.
    from resources.lib.aom.runtime import ServiceRuntime
    runtime = ServiceRuntime()
    assert runtime.offset_manager.event_manager is runtime.router
    assert runtime.offset_manager.sessions is runtime.session_tracker
    assert runtime.detector._sessions is runtime.session_tracker
    assert runtime.detector._dispatcher is runtime.dispatcher
    assert runtime.seek_scheduler._sessions is runtime.session_tracker
    assert runtime.seek_scheduler._coordinator is runtime.seek_coordinator
    # The StreamInfo shim reads through the same tracker the detector writes.
    assert runtime.offset_manager.stream_info._sessions is runtime.session_tracker
    # The watcher shares the graph's tracker and dispatcher.
    assert runtime.adjustment_watcher._sessions is runtime.session_tracker
    assert runtime.adjustment_watcher._dispatcher is runtime.dispatcher
    # The scheduler's 'change' trigger and the manual-offset notification
    # (MIGRATION(p7): still on OffsetManager until the Notifier split) both
    # ride the typed, session-stamped UserOffsetSaved — the legacy
    # USER_ADJUSTMENT bus wire is gone.
    saved_handlers = runtime.dispatcher._subscribers[events.UserOffsetSaved]
    assert runtime.seek_scheduler._on_user_offset_saved in saved_handlers
    assert runtime.offset_manager.on_user_offset_saved in saved_handlers
    assert 'USER_ADJUSTMENT' not in runtime.router.event_bus._subscribers


def test_runtime_subscription_order_is_pinned():
    # Load-bearing invariants: dispatch follows subscription order, so for the
    # lifecycle events the tracker must run FIRST (the session exists / is
    # torn down before anyone reads it), the router SECOND (AV_STARTED is
    # published before probing starts), and the detector AFTER the router.
    from resources.lib.aom.runtime import ServiceRuntime
    from resources.lib.aom.app.stream_detector import StreamDetector
    runtime = ServiceRuntime()
    subs = runtime.dispatcher._subscribers

    for event_type in (events.PlaybackStarted, events.PlaybackStopped,
                       events.PlaybackEnded):
        first_handler = subs[event_type][0]
        assert getattr(first_handler, '__self__', None) is runtime.session_tracker, (
            f"{event_type.__name__}: SessionTracker must be the first "
            f"subscriber, found {first_handler!r}")

    started_owners = [getattr(h, '__self__', None)
                      for h in subs[events.PlaybackStarted]]
    assert started_owners.index(runtime.router) < started_owners.index(
        runtime.detector), "router must publish AV_STARTED before the detector probes"
    # Detection events are the detector's alone.
    assert all(isinstance(getattr(h, '__self__', None), StreamDetector)
               for h in subs[events.ProbeStream])
    assert all(isinstance(getattr(h, '__self__', None), StreamDetector)
               for h in subs[events.VerifyStream])


def test_typed_events_translate_to_legacy_names_and_args(rig):
    # Only event names with a live legacy subscriber are still published;
    # Paused/Resumed/SeekOccurred/SeekChapter/SpeedChanged became typed-only
    # (the SeekScheduler consumes them directly) and must NOT reach the bus.
    dispatcher, _tracker, router, errors = rig
    seen = []
    router.subscribe('AV_STARTED', lambda: seen.append(('AV_STARTED',)))
    router.subscribe('PLAYBACK_STOPPED', lambda: seen.append(('PLAYBACK_STOPPED',)))
    router.subscribe('PLAYBACK_ENDED', lambda: seen.append(('PLAYBACK_ENDED',)))
    for dead_name in ('PLAYBACK_PAUSED', 'PLAYBACK_RESUMED', 'PLAYBACK_SEEK',
                      'PLAYBACK_SEEK_CHAPTER', 'PLAYBACK_SPEED_CHANGED'):
        router.subscribe(dead_name,
                         lambda *a, name=dead_name, **k: seen.append((name,)))

    dispatcher.post(events.PlaybackStarted())
    dispatcher.post(events.Paused())
    dispatcher.post(events.Resumed())
    dispatcher.post(events.SeekOccurred(time_ms=1234, offset_ms=-10))
    dispatcher.post(events.SeekChapter(chapter=3))
    dispatcher.post(events.SpeedChanged(speed=2))
    dispatcher.post(events.PlaybackStopped())
    dispatcher.post(events.PlaybackEnded())
    dispatcher.run_pending()

    assert seen == [
        ('AV_STARTED',),
        ('PLAYBACK_STOPPED',),
        ('PLAYBACK_ENDED',),
    ]
    assert errors == []


def test_events_queued_before_subscribe_are_not_lost(rig):
    dispatcher, _tracker, router, _errors = rig
    dispatcher.post(events.PlaybackStarted())      # queued pre-subscription
    seen = []
    router.subscribe('AV_STARTED', lambda: seen.append('AV_STARTED'))
    dispatcher.run_pending()
    assert seen == ['AV_STARTED']


def test_profile_changed_translates_for_live_session(rig):
    dispatcher, tracker, router, _errors = rig
    session = _start_playback(dispatcher, tracker)

    seen = []
    router.subscribe('PROFILE_CHANGED', lambda: seen.append('PROFILE_CHANGED'))
    dispatcher.post(events.ProfileChanged(session_id=session.session_id))
    dispatcher.run_pending()
    assert seen == ['PROFILE_CHANGED']


def test_stream_stabilized_translates_without_touching_state(rig):
    # The detector marks the session STABLE BEFORE posting StreamStabilized;
    # the router only translates. A subscriber therefore observes whatever
    # state the detector left — pinned here with an explicitly staged one.
    dispatcher, tracker, router, _errors = rig
    session = _start_playback(dispatcher, tracker)
    session.mark_verifying()
    session.mark_stable()

    state_at_delivery = []
    router.subscribe(
        'ON_AV_CHANGE',
        lambda: state_at_delivery.append(tracker.current.stream_state))
    dispatcher.post(events.StreamStabilized(session_id=session.session_id))
    dispatcher.run_pending()

    assert state_at_delivery == [StreamState.STABLE]


def test_reconfirmation_stabilization_is_not_translated(rig):
    # profile_changed=False marks a pure re-confirmation (blip that reverted,
    # no adoption): legacy's duplicate-codec filter never fired ON_AV_CHANGE
    # there, and translating it would run a spurious 'adjust' seek-back.
    dispatcher, tracker, router, _errors = rig
    session = _start_playback(dispatcher, tracker)
    session.mark_verifying()
    session.mark_stable()

    seen = []
    router.subscribe('ON_AV_CHANGE', lambda: seen.append('ON_AV_CHANGE'))
    dispatcher.post(events.StreamStabilized(session_id=session.session_id,
                                            profile_changed=False))
    dispatcher.run_pending()
    assert seen == []

    dispatcher.post(events.StreamStabilized(session_id=session.session_id,
                                            profile_changed=True))
    dispatcher.run_pending()
    assert seen == ['ON_AV_CHANGE']


def test_stale_detector_events_for_superseded_session_are_dropped(rig):
    dispatcher, tracker, router, _errors = rig
    first = _start_playback(dispatcher, tracker)

    # In-place reopen supersedes the first session.
    second = _start_playback(dispatcher, tracker)
    assert second.session_id != first.session_id

    seen = []
    router.subscribe('ON_AV_CHANGE', lambda: seen.append('ON_AV_CHANGE'))
    router.subscribe('PROFILE_CHANGED', lambda: seen.append('PROFILE_CHANGED'))
    dispatcher.post(events.StreamStabilized(session_id=first.session_id))
    dispatcher.post(events.ProfileChanged(session_id=first.session_id))
    dispatcher.run_pending()

    assert seen == []                                       # stale: dropped
    assert second.stream_state is StreamState.STARTING      # untouched


def test_stale_detector_events_after_stop_are_dropped(rig):
    dispatcher, tracker, router, _errors = rig
    session = _start_playback(dispatcher, tracker)
    session_id = session.session_id
    dispatcher.post(events.PlaybackStopped())
    dispatcher.run_pending()

    seen = []
    router.subscribe('ON_AV_CHANGE', lambda: seen.append('ON_AV_CHANGE'))
    router.subscribe('PROFILE_CHANGED', lambda: seen.append('PROFILE_CHANGED'))
    dispatcher.post(events.StreamStabilized(session_id=session_id))
    dispatcher.post(events.ProfileChanged(session_id=session_id))
    dispatcher.run_pending()
    assert seen == []


def test_router_has_no_publish_surface():
    # The marshaling surface died with its last producer (ActiveMonitor):
    # a component reaching for the old publish() must fail loudly rather
    # than silently queue into nothing.
    assert not hasattr(LegacyEventRouter, 'publish')
