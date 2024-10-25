"""Active monitor module to detect user changes in audio offset values during playback."""

import xbmc
import xbmcgui
import threading
from resources.lib.settings_manager import SettingsManager


class ActiveMonitor:
    def __init__(self, event_manager, stream_info, offset_manager):
        self.event_manager = event_manager
        self.stream_info = stream_info
        self.offset_manager = offset_manager
        self.settings_manager = SettingsManager()
        self.monitor_thread = None
        self.monitor_active = False
        self.playback_active = False
        self.last_audio_delay = None
        self.last_stored_audio_delay = None
        self.last_processed_delay = None

    def start(self):
        if not self.monitor_active:
            self.monitor_active = True
            self.playback_active = True
            self.update_stream_info()
            self.update_last_stored_audio_delay()
            self.monitor_thread = threading.Thread(target=self.monitor_audio_offset)
            self.monitor_thread.start()
            xbmc.log("AOM_ActiveMonitor: Active monitoring started", xbmc.LOGDEBUG)

    def stop(self):
        if self.monitor_active:
            self.monitor_active = False
            self.playback_active = False
            if self.monitor_thread is not None:
                self.monitor_thread.join()
                self.monitor_thread = None
            xbmc.log("AOM_ActiveMonitor: Active monitoring stopped", xbmc.LOGDEBUG)

    def update_stream_info(self):
        self.stream_info.update_stream_info()
        xbmc.log(f"AOM_ActiveMonitor: Updated stream info: {self.stream_info.info}", xbmc.LOGDEBUG)

    def update_last_stored_audio_delay(self):
        stream_info = self.stream_info.info
        hdr_type = stream_info['hdr_type']
        fps_type = stream_info['video_fps_type']
        audio_format = stream_info['audio_format']
        
        if hdr_type == 'unknown' or fps_type == 'unknown' or audio_format == 'unknown':
            xbmc.log(f"AOM_ActiveMonitor: Invalid stream info (HDR: {hdr_type}, "
                     f"FPS: {fps_type}, Audio: {audio_format}). "
                     f"Skipping audio delay update.", xbmc.LOGDEBUG)
            return

        try:
            setting_id = f"{hdr_type}_{fps_type}_{audio_format}"
            self.last_stored_audio_delay = self.settings_manager.get_setting_integer(setting_id)
            self.last_processed_delay = self.last_stored_audio_delay
            xbmc.log(f"AOM_ActiveMonitor: Updated last stored audio delay to "
                     f"{self.last_stored_audio_delay} for HDR type {hdr_type}, "
                     f"FPS type {fps_type}, and audio format {audio_format}", 
                     xbmc.LOGDEBUG)
        except Exception as e:
            xbmc.log(f"AOM_ActiveMonitor: Error updating last stored audio delay: {str(e)}",
                     xbmc.LOGERROR)

    def convert_delay_to_ms(self, delay_str):
        """Convert delay string (e.g., '-0.075 s') to milliseconds integer."""
        try:
            # Remove ' s' suffix and convert to float
            delay_seconds = float(delay_str.replace(' s', ''))
            # Convert to milliseconds
            return int(delay_seconds * 1000)
        except (ValueError, AttributeError):
            return None

    def monitor_audio_offset(self):
        monitor = xbmc.Monitor()
        audio_settings_open = False
        dialog_open = False

        while self.monitor_active and self.playback_active and not monitor.abortRequested():
            # Check if the audio settings dialog is open
            dialog_id = xbmcgui.getCurrentWindowDialogId()
            if dialog_id == 10124 and not audio_settings_open:
                audio_settings_open = True
                # Reset last_processed_delay when opening audio settings
                self.last_processed_delay = None

            if audio_settings_open:
                if dialog_id != 10124:
                    audio_settings_open = False
                    # Start a search period for the audio offset slider
                    start_time = xbmc.getGlobalIdleTime()
                    while (xbmc.getGlobalIdleTime() - start_time) < 1:
                        dialog_id = xbmcgui.getCurrentWindowDialogId()
                        if dialog_id == 10145:
                            dialog_open = True
                            break
                        if monitor.waitForAbort(0.1):
                            return

            if dialog_open:
                current_audio_delay = xbmc.getInfoLabel('Player.AudioDelay')
                if current_audio_delay != self.last_audio_delay:
                    self.last_audio_delay = current_audio_delay

                if dialog_id != 10145:
                    dialog_open = False
                    current_delay_ms = self.convert_delay_to_ms(self.last_audio_delay)
                    
                    # Only process if the delay has changed and hasn't been processed yet
                    if (current_delay_ms is not None and 
                        current_delay_ms != self.last_processed_delay):
                        self.process_audio_delay_change(self.last_audio_delay)
                        self.last_processed_delay = current_delay_ms

            # Wait based on current state
            if audio_settings_open or dialog_open:
                wait_time = 0.25  # Poll every 250ms while dialogs are open
            else:
                wait_time = 1  # Poll every second during regular playback

            if monitor.waitForAbort(wait_time):
                break

    def process_audio_delay_change(self, audio_delay):
        try:
            xbmc.log(f"AOM_ActiveMonitor: Processing final selected audio delay: {audio_delay}",
                     xbmc.LOGDEBUG)
            delay_ms = self.convert_delay_to_ms(audio_delay)
            if delay_ms is None:
                return

            stream_info = self.stream_info.info
            hdr_type = stream_info['hdr_type']
            fps_type = stream_info['video_fps_type']
            audio_format = stream_info['audio_format']
            
            if hdr_type == 'unknown' or fps_type == 'unknown' or audio_format == 'unknown':
                xbmc.log(f"AOM_ActiveMonitor: Invalid stream info (HDR: {hdr_type}, "
                         f"FPS: {fps_type}, Audio: {audio_format}). "
                         f"Skipping audio delay processing.", xbmc.LOGDEBUG)
                return

            setting_id = f"{hdr_type}_{fps_type}_{audio_format}"
            current_delay_ms = self.settings_manager.get_setting_integer(setting_id)
            
            if delay_ms != current_delay_ms:
                self.settings_manager.store_setting_integer(setting_id, delay_ms)
                xbmc.log(f"AOM_ActiveMonitor: Stored audio offset {delay_ms} ms for "
                         f"HDR type '{hdr_type}', FPS type '{fps_type}', "
                         f"and audio format '{audio_format}'", xbmc.LOGDEBUG)
                self.event_manager.publish('USER_ADJUSTMENT')
                self.last_stored_audio_delay = delay_ms
        except Exception as e:
            xbmc.log(f"AOM_ActiveMonitor: Error processing audio delay change: {str(e)}",
                     xbmc.LOGERROR)
