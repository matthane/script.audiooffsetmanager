# resources/lib/offset_manager.py

import xbmc
import json
from resources.lib.settings_manager import SettingsManager
from resources.lib.stream_info import StreamInfo


class OffsetManager:
    def __init__(self, event_manager, stream_info):
        self.event_manager = event_manager
        self.stream_info = stream_info
        self.settings_manager = SettingsManager()

    def start(self):
        # Subscribe to AV events
        self.event_manager.subscribe('AV_STARTED', self.on_av_started)
        self.event_manager.subscribe('ON_AV_CHANGE', self.on_av_change)

    def stop(self):
        # Unsubscribe from AV events
        self.event_manager.unsubscribe('AV_STARTED', self.on_av_started)
        self.event_manager.unsubscribe('ON_AV_CHANGE', self.on_av_change)

    def on_av_started(self):
        # Reload settings to ensure the latest values are used
        self.settings_manager = SettingsManager()
        self.apply_audio_offset()

    def on_av_change(self):
        self.apply_audio_offset()

    def apply_audio_offset(self):
        # Get stream information from StreamInfo
        hdr_type = self.stream_info.info.get('hdr_type')
        audio_format = self.stream_info.info.get('audio_format')

        # Retrieve the audio delay for the combination of HDR type and audio format
        delay_ms = self.settings_manager.get_audio_delay(hdr_type, audio_format)
        delay_seconds = delay_ms / 1000.0

        # Log the HDR type, audio format, and delay being used
        xbmc.log(f"AOM_OffsetManager: Applying audio offset of {delay_seconds} seconds for HDR type '{hdr_type}' and audio format '{audio_format}'", xbmc.LOGINFO)

        # Check if HDR type is enabled in settings
        if not self.settings_manager.is_hdr_enabled(hdr_type):
            xbmc.log(f"AOM_OffsetManager: HDR type {hdr_type} is not enabled in settings", xbmc.LOGINFO)
            return

        # Send JSON-RPC call to set the audio delay on the current player
        player_id = self.stream_info.info.get('player_id')
        if player_id is not None:
            self.set_audio_delay(player_id, delay_seconds)
        else:
            xbmc.log("AOM_OffsetManager: No valid player ID found to set audio delay", xbmc.LOGERROR)

    def set_audio_delay(self, player_id, delay_seconds):
        request = json.dumps({
            "jsonrpc": "2.0",
            "method": "Player.SetAudioDelay",
            "params": {
                "playerid": player_id,
                "offset": delay_seconds
            },
            "id": 1
        })
        response = xbmc.executeJSONRPC(request)
        response_json = json.loads(response)
        if "error" in response_json:
            xbmc.log(f"AOM_OffsetManager: Failed to set audio offset: {response_json['error']}", xbmc.LOGERROR)
        else:
            xbmc.log(f"AOM_OffsetManager: Audio offset set to {delay_seconds} seconds", xbmc.LOGDEBUG)

# Usage example:
# offset_manager = OffsetManager(event_manager, stream_info)
# offset_manager.start()
