"""Behavioral tests for the legacy event router (MIGRATION shim) + runtime wiring.

The router must reproduce the deleted EventManager's component-facing surface
(event names/args on the legacy bus, publish marshaling) with per-playback
state now owned by the PlaybackSession. These tests pin that contract, the
FIFO stabilization ordering, and the session-stamped staleness drops.
"""

import threading

import pytest

from resources.lib.aom.app import events
from resources.lib.aom.app.dispatcher import Dispatcher
from resources.lib.aom.app.legacy_router import (LegacyEventRouter,
                                                 _AvChangeStable,
                                                 _LegacyPublish)
from resources.lib.aom.app.session import SessionTracker
from resources.lib.aom.domain.stream_state import StreamState
from resources.lib.settings_facade import SettingsFacade
from resources.lib.settings_manager import SettingsManager
from resources.lib.stream_info import StreamInfo
from tests.fakes import FakeClock


@pytest.fixture
def rig():
    errors = []
    dispatcher = Dispatcher(clock=FakeClock(), log_error=errors.append)
    tracker = SessionTracker(dispatcher)
    manager = SettingsManager()
    facade = SettingsFacade(manager)
    stream_info = StreamInfo(manager, facade)
    router = LegacyEventRouter(dispatcher, tracker, stream_info, facade)
    return dispatcher, tracker, router, errors


def _start_playback(dispatcher, tracker):
    dispatcher.post(events.PlaybackStarted())
    dispatcher.run_pending()
    return tracker.current


def test_service_runtime_graph_wiring():
    # Full composition-root construction under Kodistubs: required constructor
    # args are all wired, and every component shares the tracker + router.
    from resources.lib.aom.runtime import ServiceRuntime
    runtime = ServiceRuntime()
    assert runtime.offset_manager.event_manager is runtime.router
    assert runtime.seek_backs.event_manager is runtime.router
    assert runtime.offset_manager.sessions is runtime.session_tracker
    assert runtime.seek_backs.sessions is runtime.session_tracker


def test_typed_events_translate_to_legacy_names_and_args(rig):
    dispatcher, _tracker, router, errors = rig
    seen = []
    router.subscribe('AV_STARTED', lambda: seen.append(('AV_STARTED',)))
    router.subscribe('PLAYBACK_STOPPED', lambda: seen.append(('PLAYBACK_STOPPED',)))
    router.subscribe('PLAYBACK_ENDED', lambda: seen.append(('PLAYBACK_ENDED',)))
    router.subscribe('PLAYBACK_PAUSED', lambda: seen.append(('PLAYBACK_PAUSED',)))
    router.subscribe('PLAYBACK_RESUMED', lambda: seen.append(('PLAYBACK_RESUMED',)))
    router.subscribe('PLAYBACK_SEEK', lambda t, o: seen.append(('PLAYBACK_SEEK', t, o)))
    router.subscribe('PLAYBACK_SEEK_CHAPTER', lambda c: seen.append(('PLAYBACK_SEEK_CHAPTER', c)))
    router.subscribe('PLAYBACK_SPEED_CHANGED', lambda s: seen.append(('PLAYBACK_SPEED_CHANGED', s)))

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
        ('PLAYBACK_PAUSED',),
        ('PLAYBACK_RESUMED',),
        ('PLAYBACK_SEEK', 1234, -10),
        ('PLAYBACK_SEEK_CHAPTER', 3),
        ('PLAYBACK_SPEED_CHANGED', 2),
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


def test_cross_thread_publish_marshals_to_pump(rig):
    dispatcher, _tracker, router, _errors = rig
    seen = []
    router.subscribe('USER_ADJUSTMENT', lambda: seen.append('USER_ADJ'))

    worker = threading.Thread(target=lambda: router.publish('USER_ADJUSTMENT'))
    worker.start()
    worker.join()
    assert seen == []                  # only queued so far
    dispatcher.run_pending()
    assert seen == ['USER_ADJ']        # delivered on the pump


def test_stabilization_marks_session_stable_before_on_av_change(rig):
    # The verify thread posts StreamStabilized then _AvChangeStable; FIFO must
    # make STABLE visible to the ON_AV_CHANGE subscriber (legacy parity with
    # set-then-publish).
    dispatcher, tracker, router, _errors = rig
    session = _start_playback(dispatcher, tracker)

    state_at_delivery = []
    router.subscribe(
        'ON_AV_CHANGE',
        lambda: state_at_delivery.append(tracker.current.stream_state))

    dispatcher.post(events.StreamStabilized(session_id=session.session_id))
    dispatcher.post(_AvChangeStable(session_id=session.session_id))
    dispatcher.run_pending()

    assert state_at_delivery == [StreamState.STABLE]


def test_stale_confirmations_for_superseded_session_are_dropped(rig):
    dispatcher, tracker, router, _errors = rig
    first = _start_playback(dispatcher, tracker)

    # In-place reopen supersedes the first session.
    second = _start_playback(dispatcher, tracker)
    assert second.session_id != first.session_id

    seen = []
    router.subscribe('ON_AV_CHANGE', lambda: seen.append('ON_AV_CHANGE'))
    dispatcher.post(events.StreamStabilized(session_id=first.session_id))
    dispatcher.post(_AvChangeStable(session_id=first.session_id))
    dispatcher.run_pending()

    assert seen == []                                       # stale: dropped
    assert second.stream_state is StreamState.STARTING      # untouched


def test_av_changed_wires_filter_callbacks_and_regresses_state(rig):
    dispatcher, tracker, router, _errors = rig
    captured = {}

    class RecordingFilter:
        def on_playback_start(self):
            pass

        def on_playback_stop(self):
            pass

        def handle_av_change(self, is_active, on_stable, set_codec):
            captured['is_active'] = is_active
            captured['on_stable'] = on_stable
            captured['set_codec'] = set_codec
            return True   # a verification was scheduled

    router.av_change_filter = RecordingFilter()
    session = _start_playback(dispatcher, tracker)
    session.stream_state = StreamState.STABLE   # pretend already stabilized

    dispatcher.post(events.AvChanged())
    dispatcher.run_pending()

    # A genuinely scheduled verification regresses STABLE -> STABILIZING.
    assert session.stream_state is StreamState.STABILIZING
    # The codec value has no consumer anymore.
    assert captured['set_codec'] is None
    # is_active is session-scoped: True now, False once superseded.
    assert captured['is_active']() is True

    # Simulate the verify thread confirming.
    seen = []
    router.subscribe('ON_AV_CHANGE', lambda: seen.append('ON_AV_CHANGE'))
    captured['on_stable']()
    dispatcher.run_pending()
    assert session.stream_state is StreamState.STABLE
    assert seen == ['ON_AV_CHANGE']

    # After supersession the captured probe is inert.
    _start_playback(dispatcher, tracker)
    assert captured['is_active']() is False


def test_duplicate_av_change_does_not_regress_state(rig):
    dispatcher, tracker, router, _errors = rig

    class IgnoringFilter:
        def on_playback_start(self):
            pass

        def on_playback_stop(self):
            pass

        def handle_av_change(self, is_active, on_stable, set_codec):
            return False   # duplicate/no-op event: nothing scheduled

    router.av_change_filter = IgnoringFilter()
    session = _start_playback(dispatcher, tracker)
    session.stream_state = StreamState.STABLE

    dispatcher.post(events.AvChanged())
    dispatcher.run_pending()
    assert session.stream_state is StreamState.STABLE   # not regressed
