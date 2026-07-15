"""Unit tests for PlaybackSession + SessionTracker (Pillar B primitives)."""

from resources.lib.aom.app import events
from resources.lib.aom.app.dispatcher import Dispatcher
from resources.lib.aom.app.session import PlaybackSession, SessionTracker
from resources.lib.aom.domain.stream_state import StreamState
from tests.fakes import FakeClock


def make_rig():
    clock = FakeClock(start=100.0)
    errors = []
    dispatcher = Dispatcher(clock=clock, log_error=errors.append)
    tracker = SessionTracker(dispatcher, clock=clock)
    return dispatcher, tracker, clock, errors


def test_no_session_before_playback():
    _dispatcher, tracker, _clock, _errors = make_rig()
    assert tracker.current is None
    assert tracker.is_alive(1) is False


def test_session_created_on_playback_started():
    dispatcher, tracker, clock, _errors = make_rig()
    dispatcher.post(events.PlaybackStarted())
    dispatcher.run_pending()

    session = tracker.current
    assert session is not None
    assert session.session_id == 1
    assert session.started_at == clock()
    assert session.stream_state is StreamState.STARTING
    assert session.profile is None
    assert session.applied is None
    assert session.pending_notification is None
    assert session.paused is False
    assert session.initial_av_change_consumed is False
    assert session.seek_history == {}
    assert tracker.is_alive(1) is True


def test_session_destroyed_on_stop_and_end():
    dispatcher, tracker, _clock, _errors = make_rig()
    for ending in (events.PlaybackStopped(), events.PlaybackEnded()):
        dispatcher.post(events.PlaybackStarted())
        dispatcher.run_pending()
        live_id = tracker.current.session_id
        dispatcher.post(ending)
        dispatcher.run_pending()
        assert tracker.current is None
        assert tracker.is_alive(live_id) is False


def test_in_place_reopen_supersedes_session():
    dispatcher, tracker, _clock, _errors = make_rig()
    dispatcher.post(events.PlaybackStarted())
    dispatcher.run_pending()
    first = tracker.current
    first.stream_state = StreamState.STABLE
    first.applied = ('dolbyvision_all_truehd', -125)

    # No stop in between: a second start supersedes in place.
    dispatcher.post(events.PlaybackStarted())
    dispatcher.run_pending()
    second = tracker.current
    assert second is not first
    assert second.session_id == 2
    assert second.stream_state is StreamState.STARTING
    assert second.applied is None
    assert tracker.is_alive(first.session_id) is False
    assert tracker.is_alive(second.session_id) is True


def test_session_ids_never_reused():
    dispatcher, tracker, _clock, _errors = make_rig()
    seen_ids = []
    for _ in range(3):
        dispatcher.post(events.PlaybackStarted())
        dispatcher.post(events.PlaybackStopped())
        dispatcher.run_pending()
    dispatcher.post(events.PlaybackStarted())
    dispatcher.run_pending()
    assert tracker.current.session_id == 4


def test_stop_without_session_is_noop():
    dispatcher, tracker, _clock, _errors = make_rig()
    dispatcher.post(events.PlaybackStopped())
    dispatcher.run_pending()
    assert tracker.current is None
