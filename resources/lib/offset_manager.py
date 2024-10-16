import xbmc
import xbmcgui
import json
import threading
from resources.lib.settings_manager import SettingsManager
from resources.lib.stream_info import StreamInfo

class OffsetManager:
    def __init__(self, event_manager, stream_info):
        self.event_manager = event_manager
        self.stream_info = stream_info
        self.settings_manager = SettingsManager()
        self.monitor_thread = None
        self.monitor_active = False
        self.enable_active_monitoring = False

    def start(self):
        # Subscribe to AV events
        self.event_manager.subscribe('AV_STARTED', self.on_av_started)
        self.event_manager.subscribe('ON_AV_CHANGE', self.on_av_change)
        self.event_manager.subscribe('PLAYBACK_STOPPED', self.on_playback_stopped)

    def stop(self):
        # Unsubscribe from AV events
        self.event_manager.unsubscribe('AV_STARTED', self.on_av_started)
        self.event_manager.unsubscribe('ON_AV_CHANGE', self.on_av_change)
        self.event_manager.unsubscribe('PLAYBACK_STOPPED', self.on_playback_stopped)
        self.stop_monitoring()

    def on_av_started(self):
        # Reload settings to ensure the latest values are used
        self.settings_manager = SettingsManager()
        self.apply_audio_offset()
        # Cache the value of enable_active_monitoring setting
        self.enable_active_monitoring = self.settings_manager.get_boolean_setting('enable_active_monitoring')
        self.start_monitoring()

    def on_av_change(self):
        self.apply_audio_offset()

    def on_playback_stopped(self):
        self.stop_monitoring()

    def apply_audio_offset(self):
        # Get stream information from StreamInfo
        hdr_type = self.stream_info.info.get('hdr_type')
        audio_format = self.stream_info.info.get('audio_format')
        
        # Log the HDR type and audio format being used
        xbmc.log(f"OffsetManager: Applying audio offset for HDR type '{hdr_type}' and audio format '{audio_format}'", xbmc.LOGINFO)
        
        # Check if HDR type is enabled in settings
        if not self.settings_manager.is_hdr_enabled(hdr_type):
            xbmc.log(f"OffsetManager: HDR type {hdr_type} is not enabled in settings", xbmc.LOGINFO)
            return

        # Retrieve the audio delay for the combination of HDR type and audio format
        delay_ms = self.settings_manager.get_audio_delay(hdr_type, audio_format)
        delay_seconds = delay_ms / 1000.0

        # Send JSON-RPC call to set the audio delay on the current player
        player_id = self.stream_info.info.get('player_id')
        if player_id is not None:
            self.set_audio_delay(player_id, delay_seconds)
        else:
            xbmc.log("OffsetManager: No valid player ID found to set audio delay", xbmc.LOGERROR)

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
            xbmc.log(f"OffsetManager: Failed to set audio offset: {response_json['error']}", xbmc.LOGERROR)
        else:
            xbmc.log(f"OffsetManager: Audio offset set to {delay_seconds} seconds", xbmc.LOGINFO)

    def start_monitoring(self):
        # Start monitoring only if active monitoring is enabled
        if not self.enable_active_monitoring:
            xbmc.log("OffsetManager: Active monitoring is not enabled in settings", xbmc.LOGINFO)
            return

        # Start a new thread to monitor audio offset changes
        self.monitor_active = True
        self.monitor_thread = threading.Thread(target=self.monitor_audio_offset)
        self.monitor_thread.start()

    def stop_monitoring(self):
        # Stop the monitoring thread if it is running
        self.monitor_active = False
        if self.monitor_thread is not None:
            self.monitor_thread.join()
            self.monitor_thread = None

    def monitor_audio_offset(self):
        dialog_open = False
        final_offset = None
        monitor = xbmc.Monitor()

        while self.monitor_active and not monitor.abortRequested():
            # Check if the audio offset dialog is open
            dialog_id = xbmcgui.getCurrentWindowDialogId()
            if dialog_id == 10145 and not dialog_open:
                dialog_open = True
            elif dialog_id != 10145 and dialog_open:
                dialog_open = False
                if final_offset is not None:
                    # Convert final offset to milliseconds and store in settings
                    try:
                        delay_ms = int(float(final_offset.replace(' s', '')) * 1000)
                        hdr_type = self.stream_info.info.get('hdr_type')
                        audio_format = self.stream_info.info.get('audio_format')
                        setting_id = f"{hdr_type}_{audio_format}"
                        self.settings_manager.store_audio_delay(setting_id, delay_ms)
                        xbmc.log(f"OffsetManager: Stored final audio offset {delay_ms} ms for setting ID '{setting_id}'", xbmc.LOGINFO)
                    except ValueError:
                        xbmc.log("OffsetManager: Failed to convert final offset to milliseconds", xbmc.LOGERROR)

            if dialog_open:
                # Poll the audio delay value
                audiodelay = xbmc.getInfoLabel('Player.AudioDelay')
                if audiodelay:
                    final_offset = audiodelay

            # Wait for 500ms before the next check
            if monitor.waitForAbort(0.5):
                break

# Usage example:
# offset_manager = OffsetManager(event_manager, stream_info)
# offset_manager.start()