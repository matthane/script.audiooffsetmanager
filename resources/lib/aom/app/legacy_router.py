"""Routing shim: typed dispatcher events -> the legacy string EventBus.

MIGRATION(p7): this module replaces the legacy EventManager and dies with the
legacy components. It exists so OffsetManager, SeekBacks, and ActiveMonitor
run their legacy logic — same subscribe/unsubscribe/publish surface, same
event names, same log lines — while every handler executes on the dispatcher
thread instead of Kodi's callback pump.

Per-playback state lives on the PlaybackSession (owned by SessionTracker,
which subscribes to the lifecycle events BEFORE this router — dispatch order
follows subscription order — so the session already exists/died when this
router's handlers run). Detection is the StreamDetector's job: it owns
``session.profile`` and every stream-state transition, and this router only
TRANSLATES its typed events for the legacy consumers — ``ProfileChanged``
becomes ``PROFILE_CHANGED`` (the offset-apply trigger) and
``StreamStabilized`` becomes ``ON_AV_CHANGE`` (the legacy "stream settled"
signal: notification release, change seek-backs). Events stamped with a
superseded session_id are dropped: an in-place reopen makes the old
session's in-flight work inert by construction.

Thread model: typed Kodi events arrive on the dispatcher thread; legacy
components publish (ActiveMonitor's USER_ADJUSTMENT) from their own threads
via publish(), which marshals through post().

This is legacy-bridging code, so unlike the rest of aom.app it may import
legacy modules (and, through them, Kodi APIs). Log lines are kept verbatim
from EventManager for field-log comparability during the migration.

Known interim cost (removed by the seek phase): SeekBacks' blocking
settle/PM4K waits still stall the single dispatcher thread, serializing
paths legacy ran concurrently (ActiveMonitor's USER_ADJUSTMENT fired inline
on the monitor thread and now queues behind a stall). Accepted for the
construction phases; eliminated when the seek scheduler lands.
"""

from dataclasses import dataclass, field

import xbmc

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

    def __init__(self, dispatcher, session_tracker, settings_facade):
        self._dispatcher = dispatcher
        self._sessions = session_tracker
        self.event_bus = EventBus(
            log_runtimes=settings_facade.debug_logging_enabled())

        dispatcher.subscribe(events.PlaybackStarted, self._on_playback_started)
        dispatcher.subscribe(events.PlaybackStopped, self._on_playback_stopped)
        dispatcher.subscribe(events.PlaybackEnded, self._on_playback_ended)
        dispatcher.subscribe(events.Paused, self._on_paused)
        dispatcher.subscribe(events.Resumed, self._on_resumed)
        dispatcher.subscribe(events.SeekOccurred, self._on_seek)
        dispatcher.subscribe(events.SeekChapter, self._on_seek_chapter)
        dispatcher.subscribe(events.SpeedChanged, self._on_speed_changed)
        dispatcher.subscribe(events.ProfileChanged, self._on_profile_changed)
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
        # fresh session; the StreamDetector (subscribed after us) starts its
        # probe chain once this handler's AV_STARTED publish has run.
        self._publish_here('AV_STARTED')

    def _on_profile_changed(self, event):
        """Detector adopted a (new) profile: the legacy apply trigger."""
        if not self._sessions.is_alive(event.session_id):
            log(f"AOM_EventManager: dropping stale profile change for "
                f"session #{event.session_id}", xbmc.LOGDEBUG)
            return
        self._publish_here('PROFILE_CHANGED')

    def _on_stream_stabilized(self, event):
        """Detector confirmed stability (session already marked STABLE):
        publish the legacy "stream settled" signal.

        MIGRATION(p7): ON_AV_CHANGE survives only as this translation; the
        name disappears with the legacy bus once OffsetManager and SeekBacks
        are rebuilt on typed events.
        """
        if not self._sessions.is_alive(event.session_id):
            log(f"AOM_EventManager: dropping stale stabilization for session "
                f"#{event.session_id}", xbmc.LOGDEBUG)
            return
        self._publish_here('ON_AV_CHANGE')

    def _on_playback_stopped(self, _event):
        log("AOM_EventManager: Playback stopped", xbmc.LOGDEBUG)
        self._publish_here('PLAYBACK_STOPPED')

    def _on_playback_ended(self, _event):
        log("AOM_EventManager: Playback ended", xbmc.LOGDEBUG)
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
