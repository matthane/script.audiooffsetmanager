# resources/lib/active_monitor.py

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
        hdr_type = self.stream_info.info.get('hdr_type')
        audio_format = self.stream_info.info.get('audio_format')
        
        if hdr_type is None or audio_format is None:
            xbmc.log(f"AOM_ActiveMonitor: Invalid hdr_type ({hdr_type}) or audio_format "
                     f"({audio_format}). Skipping audio delay update.", xbmc.LOGDEBUG)
            return

        try:
            setting_id = f"{hdr_type}_{audio_format}"
            self.last_stored_audio_delay = self.settings_manager.get_setting_integer(setting_id)
            xbmc.log(f"AOM_ActiveMonitor: Updated last stored audio delay to "
                     f"{self.last_stored_audio_delay} for HDR type {hdr_type} "
                     f"and audio format {audio_format}", xbmc.LOGDEBUG)
        except Exception as e:
            xbmc.log(f"AOM_ActiveMonitor: Error updating last stored audio delay: {str(e)}",
                     xbmc.LOGERROR)

    def monitor_audio_offset(self):
        monitor = xbmc.Monitor()
        audio_settings_open = False
        dialog_open = False

        while self.monitor_active and self.playback_active and not monitor.abortRequested():
            # Check if the audio settings dialog is open
            dialog_id = xbmcgui.getCurrentWindowDialogId()
            if dialog_id == 10124 and not audio_settings_open:
                audio_settings_open = True

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
                    if self.last_audio_delay != self.last_stored_audio_delay:
                        self.process_audio_delay_change(self.last_audio_delay)
                        self.last_stored_audio_delay = self.last_audio_delay

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
            delay_ms = int(float(audio_delay.replace(' s', '')) * 1000)  # Convert to milliseconds
            hdr_type = self.stream_info.info.get('hdr_type')
            audio_format = self.stream_info.info.get('audio_format')
            
            if hdr_type is None or audio_format is None:
                xbmc.log(f"AOM_ActiveMonitor: Invalid hdr_type ({hdr_type}) or audio_format "
                         f"({audio_format}). Skipping audio delay processing.", xbmc.LOGDEBUG)
                return

            setting_id = f"{hdr_type}_{audio_format}"
            current_delay_ms = self.settings_manager.get_setting_integer(setting_id)
            
            if delay_ms != current_delay_ms:
                self.settings_manager.store_setting_integer(setting_id, delay_ms)
                xbmc.log(f"AOM_ActiveMonitor: Stored audio offset {delay_ms} ms for setting ID "
                         f"'{setting_id}'", xbmc.LOGDEBUG)
                self.event_manager.publish('USER_ADJUSTMENT')
        except ValueError:
            xbmc.log("AOM_ActiveMonitor: Failed to convert audio delay to milliseconds",
                     xbmc.LOGDEBUG)
        except Exception as e:
            xbmc.log(f"AOM_ActiveMonitor: Error processing audio delay change: {str(e)}",
                     xbmc.LOGERROR)
