"""Routing shim: typed dispatcher events -> the legacy string EventBus.

MIGRATION(p7): this module replaces the legacy EventManager and dies with the
legacy components. It exists so OffsetManager, SeekBacks, and ActiveMonitor
run UNCHANGED — same subscribe/unsubscribe/publish surface, same
playback_state dict, same event names, same log lines — while every handler
now executes on the dispatcher thread instead of Kodi's callback pump.

Thread model:
- Typed Kodi events arrive via the dispatcher (already on its thread) and are
  translated here into legacy state updates + EventBus publishes.
- Legacy components publish (ActiveMonitor's USER_ADJUSTMENT) and
  AvChangeFilter's verify thread confirms codecs from OTHER threads; both are
  marshaled back by posting internal events, so the EventBus only ever fires
  on the dispatcher thread.

This is legacy-bridging code, so unlike the rest of aom.app it may import
legacy modules (and, through them, Kodi APIs). Log lines are kept verbatim
from EventManager for field-log comparability during the migration.
"""

import time
from dataclasses import dataclass, field

import xbmc

from resources.lib.av_change_filter import AvChangeFilter
from resources.lib.event_bus import EventBus
from resources.lib.logger import log
from resources.lib.aom.app import events


@dataclass(frozen=True)
class _LegacyPublish:
    """Marshal a legacy publish from any thread onto the dispatcher thread."""
    name: str
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)


@dataclass(frozen=True)
class _CodecObserved:
    """AvChangeFilter's verify thread confirmed a stable codec."""
    codec: str


class LegacyEventRouter:
    """Drop-in replacement for EventManager's component-facing surface."""

    def __init__(self, dispatcher, stream_info, settings_facade):
        self._dispatcher = dispatcher
        self.event_bus = EventBus(
            log_runtimes=settings_facade.debug_logging_enabled())
        self.av_change_filter = AvChangeFilter(stream_info)
        self.playback_state = {
            'start_time': None,
            'av_started': False,
            'last_event': None,
            'last_audio_codec': None,
        }

        dispatcher.subscribe(events.PlaybackStarted, self._on_playback_started)
        dispatcher.subscribe(events.AvChanged, self._on_av_changed)
        dispatcher.subscribe(events.PlaybackStopped, self._on_playback_stopped)
        dispatcher.subscribe(events.PlaybackEnded, self._on_playback_ended)
        dispatcher.subscribe(events.Paused, self._on_paused)
        dispatcher.subscribe(events.Resumed, self._on_resumed)
        dispatcher.subscribe(events.SeekOccurred, self._on_seek)
        dispatcher.subscribe(events.SeekChapter, self._on_seek_chapter)
        dispatcher.subscribe(events.SpeedChanged, self._on_speed_changed)
        dispatcher.subscribe(_LegacyPublish, self._on_legacy_publish)
        dispatcher.subscribe(_CodecObserved, self._on_codec_observed)

    # -- legacy component surface (unchanged from EventManager) ---------------

    def subscribe(self, event_name, callback):
        self.event_bus.subscribe(event_name, callback)

    def unsubscribe(self, event_name, callback):
        self.event_bus.unsubscribe(event_name, callback)

    def publish(self, event_name, *args, **kwargs):
        """Thread-safe: marshals the publish onto the dispatcher thread."""
        self._dispatcher.post(_LegacyPublish(event_name, args, kwargs))

    # -- typed-event handlers (dispatcher thread) ------------------------------

    def _on_playback_started(self, _event):
        log("AOM_EventManager: AV started", xbmc.LOGDEBUG)
        # start_time deliberately stays wall-clock: the legacy grace-period
        # check in OffsetManager compares it against time.time().
        self.playback_state['start_time'] = time.time()
        self.playback_state['av_started'] = True
        self.playback_state['last_audio_codec'] = None
        self.av_change_filter.on_playback_start()
        self._publish_here('AV_STARTED')

    def _on_av_changed(self, _event):
        log("AOM_EventManager: AV change event received", xbmc.LOGDEBUG)
        # The filter probes synchronously (dispatcher thread — acceptable
        # interim, was Kodi's pump before) and confirms from its verify
        # thread; both callbacks below marshal back via post().
        self.av_change_filter.handle_av_change(
            lambda: self.playback_state['av_started'],
            lambda: self._dispatcher.post(_LegacyPublish('ON_AV_CHANGE')),
            lambda codec: self._dispatcher.post(_CodecObserved(codec)),
        )

    def _on_playback_stopped(self, _event):
        log("AOM_EventManager: Playback stopped", xbmc.LOGDEBUG)
        self._reset_playback_state()
        self._publish_here('PLAYBACK_STOPPED')

    def _on_playback_ended(self, _event):
        log("AOM_EventManager: Playback ended", xbmc.LOGDEBUG)
        self._reset_playback_state()
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

    def _on_codec_observed(self, event):
        self.playback_state['last_audio_codec'] = event.codec

    # -- internals ---------------------------------------------------------------

    def _publish_here(self, event_name, *args, **kwargs):
        """Publish on the EventBus (must already be on the dispatcher thread)."""
        self.event_bus.publish(event_name, *args, **kwargs)
        self.playback_state['last_event'] = event_name

    def _reset_playback_state(self):
        self.playback_state['start_time'] = None
        self.playback_state['av_started'] = False
        self.playback_state['last_audio_codec'] = None
        self.av_change_filter.on_playback_stop()
