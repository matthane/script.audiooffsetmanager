"""Routing shim: typed dispatcher events -> the legacy string EventBus.

MIGRATION(p7): this module replaces the legacy EventManager and dies with the
legacy components. It exists so OffsetManager, SeekBacks, and ActiveMonitor
run their legacy logic — same subscribe/unsubscribe/publish surface, same
event names, same log lines — while every handler executes on the dispatcher
thread instead of Kodi's callback pump.

Per-playback state lives on the PlaybackSession (owned by SessionTracker,
which subscribes to the lifecycle events BEFORE this router — dispatch order
follows subscription order — so the session already exists/died when this
router's handlers run). The AvChangeFilter's verify thread marshals its
confirmation back as two session-stamped posts in FIFO order:
StreamStabilized (marks the session STABLE) then _AvChangeStable (publishes
the legacy ON_AV_CHANGE) — so subscribers observe STABLE state, exactly like
the legacy set-then-publish. Confirmations stamped with a superseded
session_id are dropped: an in-place reopen makes the old session's in-flight
verifications inert by construction.

Thread model: typed Kodi events arrive on the dispatcher thread; legacy
components publish (ActiveMonitor's USER_ADJUSTMENT) from their own threads
via publish(), which marshals through post().

This is legacy-bridging code, so unlike the rest of aom.app it may import
legacy modules (and, through them, Kodi APIs). Log lines are kept verbatim
from EventManager for field-log comparability during the migration.

Known interim cost (removed by the detector/seek phases): blocking legacy
handlers — SeekBacks' settle/PM4K waits and AvChangeFilter's synchronous
codec probe — now stall the single dispatcher thread. That serializes paths
legacy ran concurrently (ActiveMonitor's USER_ADJUSTMENT fired inline on the
monitor thread; verify-thread publishes ran on their own thread), so during a
stall those are DELAYED where legacy would have run them in parallel. The
stall radius is wider than pre-migration, accepted for the construction
phases and eliminated when the blocking handlers are rebuilt as scheduled,
non-blocking components.
"""

from dataclasses import dataclass, field

import xbmc

from resources.lib.av_change_filter import AvChangeFilter
from resources.lib.event_bus import EventBus
from resources.lib.logger import log
from resources.lib.aom.app import events


# eq=False: keeps object-identity hashing — frozen+eq would auto-generate a
# __hash__ over the fields and the mutable kwargs dict would make instances
# unhashable the moment anything hashes one.
@dataclass(frozen=True, eq=False)
class _LegacyPublish:
    """Marshal a legacy publish from any thread onto the dispatcher thread."""
    name: str
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)


class LegacyEventRouter:
    """Drop-in replacement for EventManager's component-facing surface."""

    def __init__(self, dispatcher, session_tracker, stream_info, settings_facade):
        self._dispatcher = dispatcher
        self._sessions = session_tracker
        self.event_bus = EventBus(
            log_runtimes=settings_facade.debug_logging_enabled())
        self.av_change_filter = AvChangeFilter(stream_info)

        dispatcher.subscribe(events.PlaybackStarted, self._on_playback_started)
        dispatcher.subscribe(events.AvChanged, self._on_av_changed)
        dispatcher.subscribe(events.PlaybackStopped, self._on_playback_stopped)
        dispatcher.subscribe(events.PlaybackEnded, self._on_playback_ended)
        dispatcher.subscribe(events.Paused, self._on_paused)
        dispatcher.subscribe(events.Resumed, self._on_resumed)
        dispatcher.subscribe(events.SeekOccurred, self._on_seek)
        dispatcher.subscribe(events.SeekChapter, self._on_seek_chapter)
        dispatcher.subscribe(events.SpeedChanged, self._on_speed_changed)
        dispatcher.subscribe(events.StreamStabilized, self._on_stream_stabilized)
        dispatcher.subscribe(_LegacyPublish, self._on_legacy_publish)

    # -- legacy component surface (unchanged from EventManager) ---------------

    def subscribe(self, event_name, callback):
        self.event_bus.subscribe(event_name, callback)

    def unsubscribe(self, event_name, callback):
        self.event_bus.unsubscribe(event_name, callback)

    def publish(self, event_name, *args, **kwargs):
        """Thread-safe: marshals the publish onto the dispatcher thread."""
        self._dispatcher.post(_LegacyPublish(event_name, args, kwargs))

    def set_log_runtimes(self, enabled):
        """Refresh the legacy bus's per-subscriber runtime logging flag."""
        self.event_bus.log_runtimes = enabled

    # -- typed-event handlers (dispatcher thread) ------------------------------

    def _on_playback_started(self, _event):
        log("AOM_EventManager: AV started", xbmc.LOGDEBUG)
        # The SessionTracker (subscribed before us) has already created the
        # fresh session; there is no reset bookkeeping left to do here.
        self.av_change_filter.on_playback_start()
        self._publish_here('AV_STARTED')

    def _on_av_changed(self, _event):
        log("AOM_EventManager: AV change event received", xbmc.LOGDEBUG)
        session = self._sessions.current
        if session is None:
            return
        sid = session.session_id
        # The filter probes synchronously — this can block the dispatcher for
        # seconds on RPC retries (see the module docstring's interim note) —
        # and confirms from its verify thread; the callbacks marshal back via
        # session-stamped posts. The codec value itself has no consumer left
        # (the state machine replaced codec mirroring), hence set_last_codec=None.
        scheduled = self.av_change_filter.handle_av_change(
            lambda: self._sessions.is_alive(sid),
            lambda: self._on_verify_confirmed(sid),
            None,
        )
        if scheduled:
            # A verification is pending: stability (re-)earned on confirm.
            session.mark_verifying()

    def _on_verify_confirmed(self, session_id):
        # VERIFY THREAD: marshal the confirmation onto the dispatcher.
        self._dispatcher.post(events.StreamStabilized(session_id=session_id))

    def _on_stream_stabilized(self, event):
        """Mark STABLE, then publish ON_AV_CHANGE — one handler, so the
        legacy set-then-publish ordering is local and self-evident.

        MIGRATION(p7): this is currently the only STABLE-transition wiring in
        the codebase; when this shim dies, the stream detector must own the
        transition (it posts StreamStabilized itself in the target design).
        """
        session = self._sessions.current
        if session is None or session.session_id != event.session_id:
            log(f"AOM_EventManager: dropping stale stabilization for session "
                f"#{event.session_id}", xbmc.LOGDEBUG)
            return
        if not session.mark_stable():
            # Confirmation without a pending verification (session still
            # STARTING): refuse the state jump, but still publish — legacy
            # published unconditionally on confirmation.
            log(f"AOM_EventManager: ignoring STABLE transition for session "
                f"#{event.session_id} in state {session.stream_state.value}",
                xbmc.LOGDEBUG)
        self._publish_here('ON_AV_CHANGE')

    def _on_playback_stopped(self, _event):
        log("AOM_EventManager: Playback stopped", xbmc.LOGDEBUG)
        self.av_change_filter.on_playback_stop()
        self._publish_here('PLAYBACK_STOPPED')

    def _on_playback_ended(self, _event):
        log("AOM_EventManager: Playback ended", xbmc.LOGDEBUG)
        self.av_change_filter.on_playback_stop()
        self._publish_here('PLAYBACK_ENDED')

    def _on_paused(self, _event):
        log("AOM_EventManager: Playback paused", xbmc.LOGDEBUG)
        self._publish_here('PLAYBACK_PAUSED')

    def _on_resumed(self, _event):
        log("AOM_EventManager: Playback resumed", xbmc.LOGDEBUG)
        self._publish_here('PLAYBACK_RESUMED')

    def _on_seek(self, event):
        log(f"AOM_EventManager: Playback seek to time {event.time_ms} with offset "
            f"{event.offset_ms}", xbmc.LOGDEBUG)
        self._publish_here('PLAYBACK_SEEK', event.time_ms, event.offset_ms)

    def _on_seek_chapter(self, event):
        log(f"AOM_EventManager: Playback seek to chapter {event.chapter}",
            xbmc.LOGDEBUG)
        self._publish_here('PLAYBACK_SEEK_CHAPTER', event.chapter)

    def _on_speed_changed(self, event):
        log(f"AOM_EventManager: Playback speed changed to {event.speed}",
            xbmc.LOGDEBUG)
        self._publish_here('PLAYBACK_SPEED_CHANGED', event.speed)

    def _on_legacy_publish(self, event):
        self._publish_here(event.name, *event.args, **event.kwargs)

    # -- internals ---------------------------------------------------------------

    def _publish_here(self, event_name, *args, **kwargs):
        """Publish on the EventBus (must already be on the dispatcher thread)."""
        self.event_bus.publish(event_name, *args, **kwargs)
