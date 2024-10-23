"""Offset manager module to receive playback events and assign audio offsets as needed.
This module also controls the deployment of the Active Monitor when it's enabled.
"""

import xbmc
import json
from resources.lib.settings_manager import SettingsManager
from resources.lib.stream_info import StreamInfo
from resources.lib.active_monitor import ActiveMonitor


class OffsetManager:
    def __init__(self, event_manager):
        self.event_manager = event_manager
        self.stream_info = StreamInfo()
        self.settings_manager = SettingsManager()
        self.active_monitor = None

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
        self.stop_active_monitor()

    def on_av_started(self):
        # Reload settings to ensure the latest values are used
        self.settings_manager = SettingsManager()
        self.stream_info.update_stream_info()
        self.apply_audio_offset()
        self.manage_active_monitor()

    def on_av_change(self):
        # Reload settings to ensure the latest values are used
        self.settings_manager = SettingsManager()
        self.stream_info.update_stream_info()
        self.apply_audio_offset()
        self.manage_active_monitor()

    def on_playback_stopped(self):
        self.stream_info.clear_stream_info()
        self.stop_active_monitor()

    def apply_audio_offset(self):
        try:
            # Check if it's a new install
            if self.settings_manager.get_setting_boolean('new_install'):
                xbmc.log("AOM_OffsetManager: New install detected. Skipping "
                         "audio offset application.", xbmc.LOGDEBUG)
                return

            # Get stream information from StreamInfo
            stream_info = self.stream_info.info
            hdr_type = stream_info['hdr_type']
            audio_format = stream_info['audio_format']
            fps_type = stream_info['video_fps_type']
            player_id = stream_info['player_id']

            # Log current stream information
            xbmc.log(f"AOM_OffsetManager: Current stream info - HDR: {hdr_type}, "
                     f"Audio: {audio_format}, FPS: {fps_type}", xbmc.LOGDEBUG)

            # Skip if using unknown formats
            if hdr_type == 'unknown' or audio_format == 'unknown' or fps_type == 'unknown':
                xbmc.log(f"AOM_OffsetManager: Skipping audio offset - Unknown format detected "
                         f"(HDR: {hdr_type}, Audio: {audio_format}, FPS: {fps_type})", 
                         xbmc.LOGDEBUG)
                return

            # Check if HDR type is enabled in settings
            if not self.settings_manager.get_setting_boolean(f'enable_{hdr_type}'):
                xbmc.log(f"AOM_OffsetManager: HDR type {hdr_type} is not "
                         f"enabled in settings", xbmc.LOGDEBUG)
                return

            # Retrieve the audio delay using the new setting ID format that includes fps_type
            setting_id = f"{hdr_type}_{fps_type}_{audio_format}"
            delay_ms = self.settings_manager.get_setting_integer(setting_id)
            if delay_ms is None:
                xbmc.log(f"AOM_OffsetManager: No audio delay found for setting ID: {setting_id}",
                         xbmc.LOGDEBUG)
                return

            delay_seconds = delay_ms / 1000.0

            # Log the stream details and delay being used
            xbmc.log(f"AOM_OffsetManager: Applying audio offset of {delay_seconds} seconds "
                     f"for setting ID '{setting_id}'", xbmc.LOGDEBUG)

            # Set audio delay if we have a valid player
            if player_id != -1:
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

    def manage_active_monitor(self):
        stream_info = self.stream_info.info
        active_monitoring_enabled = self.settings_manager.get_setting_boolean('enable_active_monitoring')
        hdr_type = stream_info['hdr_type']
        fps_type = stream_info['video_fps_type']
        hdr_type_enabled = self.settings_manager.get_setting_boolean(f'enable_{hdr_type}')

        # Log active monitor status check
        xbmc.log(f"AOM_OffsetManager: Checking active monitor status - "
                 f"HDR: {hdr_type}, FPS: {fps_type}, "
                 f"Monitoring enabled: {active_monitoring_enabled}, "
                 f"HDR type enabled: {hdr_type_enabled}", xbmc.LOGDEBUG)

        if (active_monitoring_enabled and hdr_type_enabled and 
            hdr_type != 'unknown' and fps_type != 'unknown'):
            self.start_active_monitor()
        else:
            self.stop_active_monitor()

    def start_active_monitor(self):
        if self.active_monitor is None:
            self.active_monitor = ActiveMonitor(self.event_manager, self.stream_info, self)
            self.active_monitor.start()
            xbmc.log("AOM_OffsetManager: Active monitor started", xbmc.LOGDEBUG)

    def stop_active_monitor(self):
        if self.active_monitor is not None:
            self.active_monitor.stop()
            self.active_monitor = None
            xbmc.log("AOM_OffsetManager: Active monitor stopped", xbmc.LOGDEBUG)
