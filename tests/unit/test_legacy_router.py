"""Behavioral tests for the legacy event router (MIGRATION shim) + runtime wiring.

The router must be a drop-in for the deleted EventManager: same event names
and args on the legacy bus, same playback_state bookkeeping, with cross-thread
publishes marshaled onto the dispatcher. These tests pin that contract and the
runtime ordering guarantees that protect it.
"""

import threading

import pytest

from resources.lib.aom.app import events
from resources.lib.aom.app.dispatcher import Dispatcher
from resources.lib.aom.app.legacy_router import (LegacyEventRouter,
                                                 _CodecObserved,
                                                 _LegacyPublish)
from resources.lib.settings_facade import SettingsFacade
from resources.lib.settings_manager import SettingsManager
from resources.lib.stream_info import StreamInfo
from tests.fakes import FakeClock


@pytest.fixture
def rig():
    errors = []
    dispatcher = Dispatcher(clock=FakeClock(), log_error=errors.append)
    manager = SettingsManager()
    facade = SettingsFacade(manager)
    stream_info = StreamInfo(manager, facade)
    router = LegacyEventRouter(dispatcher, stream_info, facade)
    return dispatcher, router, errors


def test_service_runtime_graph_wiring():
    # Full composition-root construction under Kodistubs: required constructor
    # args are all wired, and every component shares the router instance.
    from resources.lib.aom.runtime import ServiceRuntime
    runtime = ServiceRuntime()
    assert runtime.offset_manager.event_manager is runtime.router
    assert runtime.seek_backs.event_manager is runtime.router
    assert runtime.offset_manager.stream_info is runtime.router.av_change_filter.stream_info


def test_typed_events_translate_to_legacy_names_and_args(rig):
    dispatcher, router, errors = rig
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


def test_playback_state_bookkeeping(rig):
    dispatcher, router, _errors = rig
    assert router.playback_state['av_started'] is False

    dispatcher.post(events.PlaybackStarted())
    dispatcher.run_pending()
    assert router.playback_state['av_started'] is True
    assert router.playback_state['start_time'] is not None
    assert router.playback_state['last_audio_codec'] is None

    dispatcher.post(events.PlaybackStopped())
    dispatcher.run_pending()
    assert router.playback_state['av_started'] is False
    assert router.playback_state['start_time'] is None
    assert router.playback_state['last_audio_codec'] is None


def test_events_queued_before_subscribe_are_not_lost(rig):
    # The runtime starts the dispatcher AFTER components subscribe, so events
    # the bridges queue during construction reach a complete graph. This pins
    # the queue-holds-events property that ordering relies on.
    dispatcher, router, _errors = rig
    dispatcher.post(events.PlaybackStarted())      # queued pre-subscription
    seen = []
    router.subscribe('AV_STARTED', lambda: seen.append('AV_STARTED'))
    dispatcher.run_pending()
    assert seen == ['AV_STARTED']


def test_cross_thread_publish_marshals_to_pump(rig):
    dispatcher, router, _errors = rig
    seen = []
    router.subscribe('USER_ADJUSTMENT', lambda: seen.append('USER_ADJ'))

    worker = threading.Thread(target=lambda: router.publish('USER_ADJUSTMENT'))
    worker.start()
    worker.join()
    assert seen == []                  # only queued so far
    dispatcher.run_pending()
    assert seen == ['USER_ADJ']        # delivered on the pump


def test_codec_observed_is_visible_when_on_av_change_fires(rig):
    # The verify thread posts _CodecObserved BEFORE ON_AV_CHANGE; queue FIFO
    # must make the codec visible to the ON_AV_CHANGE subscriber (legacy
    # parity: set-then-publish).
    dispatcher, router, _errors = rig
    codec_at_delivery = []
    router.subscribe(
        'ON_AV_CHANGE',
        lambda: codec_at_delivery.append(router.playback_state['last_audio_codec']))

    dispatcher.post(_CodecObserved('truehd'))
    dispatcher.post(_LegacyPublish('ON_AV_CHANGE'))
    dispatcher.run_pending()

    assert codec_at_delivery == ['truehd']


def test_av_changed_wires_filter_callbacks(rig):
    dispatcher, router, _errors = rig
    captured = {}

    class RecordingFilter:
        def handle_av_change(self, is_active, on_stable, set_codec):
            captured['is_active'] = is_active
            captured['on_stable'] = on_stable
            captured['set_codec'] = set_codec

    router.av_change_filter = RecordingFilter()
    dispatcher.post(events.PlaybackStarted())
    dispatcher.post(events.AvChanged())
    dispatcher.run_pending()

    # is_active reflects live playback state.
    assert captured['is_active']() is True

    # Simulate the verify thread confirming: codec first, then stable.
    seen = []
    router.subscribe(
        'ON_AV_CHANGE',
        lambda: seen.append(router.playback_state['last_audio_codec']))
    captured['set_codec']('eac3')
    captured['on_stable']()
    dispatcher.run_pending()
    assert seen == ['eac3']


def test_codec_observed_after_stop_is_benign(rig):
    # Documented parity: a late _CodecObserved for a dead session leaves a
    # stale codec in state (harmless — nothing applies without a profile) and
    # the next playback start resets it.
    dispatcher, router, _errors = rig
    dispatcher.post(events.PlaybackStopped())
    dispatcher.post(_CodecObserved('truehd'))
    dispatcher.run_pending()
    assert router.playback_state['last_audio_codec'] == 'truehd'
    assert router.playback_state['av_started'] is False

    dispatcher.post(events.PlaybackStarted())
    dispatcher.run_pending()
    assert router.playback_state['last_audio_codec'] is None
