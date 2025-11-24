"""Event manager module receives callback functions from Kodi regarding
playback events, filters them, and posts them to subscribers/other modules.
"""

import time
import xbmc
from resources.lib.settings_manager import SettingsManager
from resources.lib.settings_facade import SettingsFacade
from resources.lib.stream_info import StreamInfo
from resources.lib.av_change_filter import AvChangeFilter
from resources.lib.logger import log
from resources.lib.event_bus import EventBus


class EventManager(xbmc.Player):
    def __init__(self, settings_manager=None, stream_info=None, settings_facade=None, event_bus=None):
        super().__init__()
        self.settings_manager = settings_manager or SettingsManager()
        self.settings_facade = settings_facade or SettingsFacade(self.settings_manager)
        self.stream_info = stream_info or StreamInfo(self.settings_manager, self.settings_facade)
        self.av_change_filter = AvChangeFilter(self.stream_info)
        self.event_bus = event_bus or EventBus(log_runtimes=self.settings_facade.debug_logging_enabled())
        self.playback_state = {
            'start_time': None,
            'av_started': False,
            'last_event': None,
            'last_audio_codec': None
        }

    def subscribe(self, event_name, callback):
        self.event_bus.subscribe(event_name, callback)

    def unsubscribe(self, event_name, callback):
        self.event_bus.unsubscribe(event_name, callback)

    def publish(self, event_name, *args, **kwargs):
        self.event_bus.publish(event_name, *args, **kwargs)
        self.playback_state['last_event'] = event_name

    def onAVStarted(self):
        log("AOM_EventManager: AV started", xbmc.LOGDEBUG)
        self.playback_state['start_time'] = time.time()
        self.playback_state['av_started'] = True
        self.playback_state['last_audio_codec'] = None  # Reset codec tracking
        self.av_change_filter.on_playback_start()
        self.publish('AV_STARTED')

    def onAVChange(self):
        log("AOM_EventManager: AV change event received", xbmc.LOGDEBUG)
        self.av_change_filter.handle_av_change(
            lambda: self.playback_state['av_started'],
            lambda: self.publish('ON_AV_CHANGE'),
            lambda codec: self.playback_state.__setitem__('last_audio_codec', codec)
        )

    def onPlayBackStopped(self):
        log("AOM_EventManager: Playback stopped", xbmc.LOGDEBUG)
        self.playback_state['start_time'] = None
        self.playback_state['av_started'] = False
        self.playback_state['last_audio_codec'] = None
        self.av_change_filter.on_playback_stop()
        self.publish('PLAYBACK_STOPPED')

    def onPlayBackEnded(self):
        log("AOM_EventManager: Playback ended", xbmc.LOGDEBUG)
        self.playback_state['start_time'] = None
        self.playback_state['av_started'] = False
        self.playback_state['last_audio_codec'] = None
        self.av_change_filter.on_playback_stop()
        self.publish('PLAYBACK_ENDED')

    def onPlayBackPaused(self):
        log("AOM_EventManager: Playback paused", xbmc.LOGDEBUG)
        self.publish('PLAYBACK_PAUSED')

    def onPlayBackResumed(self):
        log("AOM_EventManager: Playback resumed", xbmc.LOGDEBUG)
        self.publish('PLAYBACK_RESUMED')

    def onPlayBackSeek(self, time, seekOffset):
        log(f"AOM_EventManager: Playback seek to time {time} with offset "
            f"{seekOffset}", xbmc.LOGDEBUG)
        self.publish('PLAYBACK_SEEK', time, seekOffset)

    def onPlayBackSeekChapter(self, chapter):
        log(f"AOM_EventManager: Playback seek to chapter {chapter}",
            xbmc.LOGDEBUG)
        self.publish('PLAYBACK_SEEK_CHAPTER', chapter)

    def onPlayBackSpeedChanged(self, speed):
        log(f"AOM_EventManager: Playback speed changed to {speed}",
            xbmc.LOGDEBUG)
        self.publish('PLAYBACK_SPEED_CHANGED', speed)
