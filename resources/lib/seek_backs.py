import xbmc
import json
from resources.lib.settings_manager import SettingsManager

class SeekBacks:
    def __init__(self, event_manager):
        self.event_manager = event_manager
        self.settings_manager = SettingsManager()

    def start(self):
        # Subscribe to AV events
        self.event_manager.subscribe('AV_STARTED', self.on_av_started)
        self.event_manager.subscribe('ON_AV_CHANGE', self.on_av_change)
        self.event_manager.subscribe('PLAYBACK_RESUMED', self.on_av_unpause)

    def stop(self):
        # Unsubscribe from AV events
        self.event_manager.unsubscribe('AV_STARTED', self.on_av_started)
        self.event_manager.unsubscribe('ON_AV_CHANGE', self.on_av_change)
        self.event_manager.unsubscribe('PLAYBACK_RESUMED', self.on_av_unpause)

    def on_av_started(self):
        self.perform_seek_back('resume')

    def on_av_change(self):
        self.perform_seek_back('adjust')

    def on_av_unpause(self):
        self.perform_seek_back('unpause')

    def perform_seek_back(self, event_type):
        # Reload settings to ensure the latest values are used
        self.settings_manager = SettingsManager()
        # Delay for 2 seconds to allow the stream to settle before seeking back
        xbmc.sleep(2000)
        # Check settings for seek back configuration based on the specific setting IDs
        seek_enabled = self.settings_manager.get_boolean_setting(f'enable_seek_back_{event_type}')
        seek_seconds = self.settings_manager.get_integer_setting(f'seek_back_{event_type}_seconds')

        if not seek_enabled:
            xbmc.log(f"SeekBacks: Seek back on {event_type} is not enabled in settings", xbmc.LOGINFO)
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
            xbmc.log(f"SeekBacks: Failed to perform seek back: {response_json['error']}", xbmc.LOGERROR)
        else:
            xbmc.log(f"SeekBacks: Seeked back by {seek_seconds} seconds on {event_type}", xbmc.LOGINFO)

# Usage example:
# seek_backs = SeekBacks(event_manager)
# seek_backs.start()