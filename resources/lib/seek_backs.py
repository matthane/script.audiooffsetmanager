# resources/lib/seek_backs.py

import xbmc
import json
from resources.lib.settings_manager import SettingsManager


class SeekBacks:
    def __init__(self, event_manager):
        self.event_manager = event_manager
        self.settings_manager = SettingsManager()
        self.playback_paused = False

    def start(self):
        # Subscribe to AV events
        self.event_manager.subscribe('AV_STARTED', self.on_av_started)
        self.event_manager.subscribe('ON_AV_CHANGE', self.on_av_change)
        self.event_manager.subscribe('PLAYBACK_RESUMED', self.on_av_unpause)
        self.event_manager.subscribe('PLAYBACK_PAUSED', self.on_playback_paused)
        self.event_manager.subscribe('USER_ADJUSTMENT', self.on_user_adjustment)

    def stop(self):
        # Unsubscribe from AV events
        self.event_manager.unsubscribe('AV_STARTED', self.on_av_started)
        self.event_manager.unsubscribe('ON_AV_CHANGE', self.on_av_change)
        self.event_manager.unsubscribe('PLAYBACK_RESUMED', self.on_av_unpause)
        self.event_manager.unsubscribe('PLAYBACK_PAUSED', self.on_playback_paused)
        self.event_manager.unsubscribe('USER_ADJUSTMENT', self.on_user_adjustment)

    def on_av_started(self):
        self.perform_seek_back('resume')

    def on_av_change(self):
        self.perform_seek_back('adjust')

    def on_av_unpause(self):
        xbmc.sleep(500)  # Small delay to avoid race condition on flag
        self.playback_paused = False
        self.perform_seek_back('unpause')

    def on_playback_paused(self):
        self.playback_paused = True

    def on_user_adjustment(self):
        # Perform seek back if enabled for USER_ADJUSTMENT
        self.perform_seek_back('change')

    def perform_seek_back(self, event_type):
        # Do not perform seek back if playback is paused
        if self.playback_paused:
            xbmc.log(f"AOM_SeekBacks: Playback is paused, skipping seek back on {event_type}", xbmc.LOGDEBUG)
            return

        # Reload settings to ensure the latest values are used
        self.settings_manager = SettingsManager()
        # Delay for 2 seconds to allow the stream to settle before seeking back
        xbmc.sleep(2000)
        # Check settings for seek back configuration based on the specific setting IDs
        seek_enabled = self.settings_manager.get_boolean_setting(f'enable_seek_back_{event_type}')
        seek_seconds = self.settings_manager.get_integer_setting(f'seek_back_{event_type}_seconds')

        if not seek_enabled:
            xbmc.log(f"AOM_SeekBacks: Seek back on {event_type} is not enabled in settings", xbmc.LOGDEBUG)
            return

        # Send JSON-RPC call to perform seek back
        request = {
            "jsonrpc": "2.0",
            "method": "Player.Seek",
            "params": {
                "playerid": 1,
                "value": {"seconds": -seek_seconds}
            },
            "id": 1
        }
        response = xbmc.executeJSONRPC(json.dumps(request))
        response_json = json.loads(response)
        if "error" in response_json:
            xbmc.log(f"AOM_SeekBacks: Failed to perform seek back: {response_json['error']}", xbmc.LOGDEBUG)
        else:
            xbmc.log(f"AOM_SeekBacks: Seeked back by {seek_seconds} seconds on {event_type}", xbmc.LOGDEBUG)


# Usage example:
# seek_backs = SeekBacks(event_manager)
# seek_backs.start()
