"""Event manager module receives callback functions from Kodi regarding
playback events, filters them, and posts them to subscribers/other modules.
"""

import xbmc
import time


class EventManager(xbmc.Player):
    def __init__(self):
        super().__init__()
        self._subscribers = {}
        self.playback_start_time = None
        self.last_av_change_time = 0
        self.av_started = False
        self.last_event = None
        self.ignore_next_av_change = False

    def subscribe(self, event_name, callback):
        if event_name not in self._subscribers:
            self._subscribers[event_name] = []
        self._subscribers[event_name].append(callback)

    def unsubscribe(self, event_name, callback):
        if event_name in self._subscribers:
            self._subscribers[event_name].remove(callback)
            if not self._subscribers[event_name]:
                del self._subscribers[event_name]

    def publish(self, event_name, *args, **kwargs):
        if event_name in self._subscribers:
            for callback in self._subscribers[event_name]:
                callback(*args, **kwargs)
        self.last_event = event_name

        # Set flag to ignore the next AV change if certain events are published
        if event_name in ['PLAYBACK_SEEK', 'PLAYBACK_SEEK_CHAPTER',
                          'PLAYBACK_SPEED_CHANGED']:
            self.ignore_next_av_change = True

    def onAVStarted(self):
        xbmc.log("AOM_EventManager: AV started", xbmc.LOGDEBUG)
        self.playback_start_time = time.time()
        self.av_started = True
        self.publish('AV_STARTED')

    def onAVChange(self):
        # Only publish AV change if AV has started and playback has been
        # ongoing for more than 2 seconds
        if not self.av_started:
            return

        if self.playback_start_time and (time.time() - self.playback_start_time) < 2:
            return

        # Ensure there is at least a 1-second delay between AV change notifications
        current_time = time.time()
        if current_time - self.last_av_change_time < 1:
            return

        # Ignore the first AV change that comes after certain events
        if self.ignore_next_av_change:
            self.ignore_next_av_change = False
            return

        self.last_av_change_time = current_time
        xbmc.log("AOM_EventManager: AV stream changed", xbmc.LOGDEBUG)
        self.publish('ON_AV_CHANGE')

    def onPlayBackStopped(self):
        xbmc.log("AOM_EventManager: Playback stopped", xbmc.LOGDEBUG)
        self.playback_start_time = None
        self.av_started = False
        self.publish('PLAYBACK_STOPPED')

    def onPlayBackEnded(self):
        xbmc.log("AOM_EventManager: Playback ended", xbmc.LOGDEBUG)
        self.playback_start_time = None
        self.av_started = False
        self.publish('PLAYBACK_ENDED')

    def onPlayBackPaused(self):
        xbmc.log("AOM_EventManager: Playback paused", xbmc.LOGDEBUG)
        self.publish('PLAYBACK_PAUSED')

    def onPlayBackResumed(self):
        xbmc.log("AOM_EventManager: Playback resumed", xbmc.LOGDEBUG)
        self.publish('PLAYBACK_RESUMED')

    def onPlayBackSeek(self, time, seekOffset):
        xbmc.log(f"AOM_EventManager: Playback seek to time {time} with offset "
                 f"{seekOffset}", xbmc.LOGDEBUG)
        self.publish('PLAYBACK_SEEK', time, seekOffset)

    def onPlayBackSeekChapter(self, chapter):
        xbmc.log(f"AOM_EventManager: Playback seek to chapter {chapter}",
                 xbmc.LOGDEBUG)
        self.publish('PLAYBACK_SEEK_CHAPTER', chapter)

    def onPlayBackSpeedChanged(self, speed):
        xbmc.log(f"AOM_EventManager: Playback speed changed to {speed}",
                 xbmc.LOGDEBUG)
        self.publish('PLAYBACK_SPEED_CHANGED', speed)
