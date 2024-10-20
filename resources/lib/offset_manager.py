# resources/lib/offset_manager.py

import xbmc
import json
from resources.lib.settings_manager import SettingsManager
from resources.lib.stream_info import StreamInfo


class OffsetManager:
    def __init__(self, event_manager):
        self.event_manager = event_manager
        self.stream_info = StreamInfo()
        self.settings_manager = SettingsManager()

    def start(self):
        # Subscribe to AV events
        self.event_manager.subscribe('AV_STARTED', self.on_av_started)
        self.event_manager.subscribe('ON_AV_CHANGE', self.on_av_change)
        self.event_manager.subscribe('PLAYBACK_STOPPED', self.on_playback_stopped)
        self.event_manager.subscribe('PLAYBACK_ENDED', self.on_playback_stopped)

    def stop(self):
        # Unsubscribe from AV events
        self.event_manager.unsubscribe('AV_STARTED', self.on_av_started)
        self.event_manager.unsubscribe('ON_AV_CHANGE', self.on_av_change)
        self.event_manager.unsubscribe('PLAYBACK_STOPPED', self.on_playback_stopped)
        self.event_manager.unsubscribe('PLAYBACK_ENDED', self.on_playback_stopped)

    def on_av_started(self):
        # Reload settings to ensure the latest values are used
        self.settings_manager = SettingsManager()
        self.stream_info.update_stream_info()
        self.apply_audio_offset()

    def on_av_change(self):
        # Reload settings to ensure the latest values are used
        self.settings_manager = SettingsManager()
        self.stream_info.update_stream_info()
        self.apply_audio_offset()

    def on_playback_stopped(self):
        self.stream_info.clear_stream_info()

    def apply_audio_offset(self):
        try:
            # Check if it's a new install
            if self.settings_manager.get_boolean_setting('new_install'):
                xbmc.log("AOM_OffsetManager: New install detected. Skipping "
                         "audio offset application.", xbmc.LOGDEBUG)
                return

            # Get stream information from StreamInfo
            hdr_type = self.stream_info.info.get('hdr_type')
            audio_format = self.stream_info.info.get('audio_format')

            # Check if we have valid hdr_type and audio_format
            if not hdr_type or not audio_format:
                xbmc.log(f"AOM_OffsetManager: Invalid hdr_type ({hdr_type}) or "
                         f"audio_format ({audio_format}). Skipping audio "
                         f"offset application.", xbmc.LOGDEBUG)
                return

            # Check if HDR type is enabled in settings
            if not self.settings_manager.is_hdr_enabled(hdr_type):
                xbmc.log(f"AOM_OffsetManager: HDR type {hdr_type} is not "
                         f"enabled in settings", xbmc.LOGDEBUG)
                return

            # Retrieve the audio delay for the combination of HDR type and audio format
            delay_ms = self.settings_manager.get_audio_delay(hdr_type, audio_format)
            if delay_ms is None:
                xbmc.log(f"AOM_OffsetManager: No audio delay found for HDR "
                         f"type {hdr_type} and audio format {audio_format}",
                         xbmc.LOGDEBUG)
                return

            delay_seconds = delay_ms / 1000.0

            # Log the HDR type, audio format, and delay being used
            xbmc.log(f"AOM_OffsetManager: Applying audio offset of "
                     f"{delay_seconds} seconds for HDR type '{hdr_type}' "
                     f"and audio format '{audio_format}'", xbmc.LOGDEBUG)

            # Send JSON-RPC call to set the audio delay on the current player
            player_id = self.stream_info.info.get('player_id')
            if player_id is not None and player_id != -1:
                self.set_audio_delay(player_id, delay_seconds)
            else:
                xbmc.log("AOM_OffsetManager: No valid player ID found to set "
                         "audio delay", xbmc.LOGDEBUG)

        except Exception as e:
            xbmc.log(f"AOM_OffsetManager: Error applying audio offset: {str(e)}",
                     xbmc.LOGERROR)

    def set_audio_delay(self, player_id, delay_seconds):
        try:
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
                xbmc.log(f"AOM_OffsetManager: Failed to set audio offset: "
                         f"{response_json['error']}", xbmc.LOGWARNING)
            else:
                xbmc.log(f"AOM_OffsetManager: Audio offset set to "
                         f"{delay_seconds} seconds", xbmc.LOGDEBUG)
        except Exception as e:
            xbmc.log(f"AOM_OffsetManager: Error setting audio delay: {str(e)}",
                     xbmc.LOGERROR)
