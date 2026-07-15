"""Integration-style session flow tests on fakes (Phase 3 gate evidence).

Wires the REAL ServiceRuntime graph (dispatcher, tracker, router, offset
manager, seek backs) under Kodistubs, with the Kodi I/O seams monkeypatched:
RPC probes return a scripted stream, set_audio_delay/notifications are
captured, and stabilization confirmations are posted as the verify thread
would. Covers: provisional apply -> release on STABLE, in-place reopen
supersession, stale confirmation inertness, and post-stop AV events.
"""

import pytest
import xbmc

from resources.lib import rpc_client
from resources.lib.aom.app import events
from resources.lib.aom.app.legacy_router import _AvChangeStable
from resources.lib.aom.domain.stream_state import StreamState


INFOLABELS = {
    'Player.Process(videofps)': '23.976',
    'Player.Process(video.source.hdr.type)': 'dolbyvision',
}


@pytest.fixture
def rig(monkeypatch):
    # --- Kodi I/O seams -------------------------------------------------------
    monkeypatch.setattr(xbmc, 'getInfoLabel',
                        lambda label: INFOLABELS.get(label, ''))
    monkeypatch.setattr(rpc_client, 'get_active_player_id', lambda **kw: 1)

    stream = {'codec': 'truehd'}
    monkeypatch.setattr(rpc_client, 'get_audio_info',
                        lambda player_id, **kw: (stream['codec'], 8))

    applied = []
    monkeypatch.setattr(rpc_client, 'set_audio_delay',
                        lambda player_id, seconds: applied.append(
                            (player_id, round(seconds * 1000))) or True)

    from resources.lib.aom.runtime import ServiceRuntime
    runtime = ServiceRuntime()

    # --- settings seams (facade instance shared across components) ------------
    facade = runtime.offset_manager.settings_facade
    monkeypatch.setattr(facade, 'is_new_install', lambda: False)
    monkeypatch.setattr(facade, 'is_hdr_enabled', lambda hdr: True)
    monkeypatch.setattr(facade, 'fps_override_enabled', lambda hdr: False)
    monkeypatch.setattr(facade, 'get_offset_ms', lambda profile: -125)

    notified = []
    monkeypatch.setattr(runtime.offset_manager.notification_handler,
                        'notify_audio_offset_applied',
                        lambda ms, profile: notified.append(
                            (ms, profile.setting_id())))

    # Components subscribe as run() would; the dispatcher stays un-started and
    # is pumped manually.
    runtime.offset_manager.start()
    runtime.seek_backs.start()
    return runtime, applied, notified, stream


def _confirm_stability(runtime, session_id):
    """Post what the AvChangeFilter verify thread posts, in its FIFO order."""
    runtime.dispatcher.post(events.StreamStabilized(session_id=session_id))
    runtime.dispatcher.post(_AvChangeStable(session_id=session_id))


def test_startup_apply_is_provisional_then_released_on_stable(rig):
    runtime, applied, notified, _stream = rig

    runtime.dispatcher.post(events.PlaybackStarted())
    runtime.dispatcher.run_pending()

    session = runtime.session_tracker.current
    assert applied == [(1, -125)]                      # offset applied at once
    assert notified == []                              # ...but held (provisional)
    assert session.stream_state is StreamState.STABILIZING
    assert session.applied == ('dolbyvision_all_truehd', -125)
    assert session.pending_notification == ('dolbyvision_all_truehd', -125)

    _confirm_stability(runtime, session.session_id)
    runtime.dispatcher.run_pending()

    assert session.stream_state is StreamState.STABLE
    assert applied == [(1, -125)]                      # dedupe: no re-apply
    assert notified == [(-125, 'dolbyvision_all_truehd')]   # released exactly once
    assert session.pending_notification is None


def test_in_place_reopen_supersedes_and_drops_pending(rig):
    runtime, applied, notified, _stream = rig

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

    # Stale confirmations for the dead session are inert.
    _confirm_stability(runtime, first.session_id)
    runtime.dispatcher.run_pending()
    assert notified == []                              # nothing released
    assert second.stream_state is StreamState.STABILIZING

    # The live session still releases normally.
    _confirm_stability(runtime, second.session_id)
    runtime.dispatcher.run_pending()
    assert notified == [(-125, 'dolbyvision_all_truehd')]


def test_mid_play_codec_change_applies_and_notifies_immediately(rig):
    runtime, applied, notified, stream = rig

    runtime.dispatcher.post(events.PlaybackStarted())
    runtime.dispatcher.run_pending()
    session = runtime.session_tracker.current
    _confirm_stability(runtime, session.session_id)
    runtime.dispatcher.run_pending()
    assert len(notified) == 1

    # The stream's codec changes; the (simulated) verify thread re-confirms.
    stream['codec'] = 'eac3'
    _confirm_stability(runtime, session.session_id)
    runtime.dispatcher.run_pending()

    assert applied == [(1, -125), (1, -125)]           # re-applied for eac3 key
    assert session.applied == ('dolbyvision_all_eac3', -125)
    assert notified[-1] == (-125, 'dolbyvision_all_eac3')   # immediate (STABLE)
    assert session.pending_notification is None


def test_av_event_after_stop_is_ignored(rig):
    runtime, applied, _notified, _stream = rig

    runtime.dispatcher.post(events.PlaybackStarted())
    runtime.dispatcher.post(events.PlaybackStopped())
    runtime.dispatcher.run_pending()
    assert runtime.session_tracker.current is None
    applied_count = len(applied)

    # A straggler AV_STARTED-less publish path: no session -> no apply.
    runtime.router.publish('ON_AV_CHANGE')
    runtime.dispatcher.run_pending()
    assert len(applied) == applied_count


def test_pause_state_lives_on_session(rig):
    runtime, _applied, _notified, _stream = rig

    runtime.dispatcher.post(events.PlaybackStarted())
    runtime.dispatcher.post(events.Paused())
    runtime.dispatcher.run_pending()
    assert runtime.session_tracker.current.paused is True

    runtime.dispatcher.post(events.Resumed())
    runtime.dispatcher.run_pending()
    assert runtime.session_tracker.current.paused is False
