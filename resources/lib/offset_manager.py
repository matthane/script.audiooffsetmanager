"""Offset manager module to receive playback events and assign audio offsets as needed.
This module also controls the deployment of the Active Monitor when it's enabled.
"""

import xbmc
from resources.lib.settings_manager import SettingsManager
from resources.lib.settings_facade import SettingsFacade
from resources.lib.stream_info import StreamInfo
from resources.lib.active_monitor import ActiveMonitor
from resources.lib.notification_handler import NotificationHandler
from resources.lib import rpc_client
from resources.lib.logger import log
from resources.lib.debug_snapshot import log_snapshot


class OffsetManager:
    def __init__(self, event_manager, settings_manager=None, stream_info=None, notification_handler=None, settings_facade=None):
        self.event_manager = event_manager
        self.settings_manager = settings_manager or SettingsManager()
        self.settings_facade = settings_facade or SettingsFacade(self.settings_manager)
        self.stream_info = stream_info or StreamInfo(self.settings_manager, self.settings_facade)
        self.notification_handler = notification_handler or NotificationHandler(self.settings_manager, self.settings_facade)
        self.active_monitor = None
        self._last_applied = None
        self._events = {
            'AV_STARTED': self.on_av_started,
            'ON_AV_CHANGE': self.on_av_change,
            'PLAYBACK_STOPPED': self.on_playback_stopped,
            'PLAYBACK_ENDED': self.on_playback_stopped,
            'USER_ADJUSTMENT': self.on_user_adjustment
        }

    def start(self):
        """Start the offset manager by subscribing to relevant events."""
        for event, callback in self._events.items():
            self.event_manager.subscribe(event, callback)

    def stop(self):
        """Stop the offset manager and clean up subscriptions."""
        for event, callback in self._events.items():
            self.event_manager.unsubscribe(event, callback)
        self.stop_active_monitor()

    def on_av_started(self):
        """Handle AV started event."""
        self._handle_av_event()

    def on_av_change(self):
        """Handle AV change event."""
        self._handle_av_event()

    def on_playback_stopped(self):
        """Handle playback stopped event."""
        self.stream_info.clear_stream_info()
        self._last_applied = None
        self.stop_active_monitor()
        
    def on_user_adjustment(self):
        """Handle user adjustment event (manual offset change)."""
        # Only send notification if active monitor is enabled
        if self.active_monitor is not None and self.stream_info.profile is not None:
            # Get the current audio delay from settings
            profile = self.stream_info.profile
            delay_ms = self.settings_manager.get_setting_integer(profile.setting_id())

            # Send notification about the manual offset change
            self.notification_handler.notify_manual_offset_saved(delay_ms, profile)
            log(f"AOM_OffsetManager: Notified user about manual offset change to {delay_ms}ms",
                xbmc.LOGDEBUG)
            log_snapshot("USER_ADJUST", self.stream_info, self.settings_facade, extra={"delay_ms": delay_ms})

    def _handle_av_event(self):
        """Common handler for AV-related events."""
        self.stream_info.update_stream_info()
        self.apply_audio_offset()
        log_snapshot("AV_EVENT", self.stream_info, self.settings_facade)
        self.manage_active_monitor()

    def _should_apply_offset(self):
        """Check if audio offset should be applied based on current conditions."""
        if self.settings_facade.is_new_install():
            log("AOM_OffsetManager: New install detected. Skipping "
                "audio offset application.", xbmc.LOGDEBUG)
            return False

        profile = self.stream_info.profile
        if profile is None:
            log("AOM_OffsetManager: No stream profile available; skipping offset", xbmc.LOGDEBUG)
            return False

        # Check for unknown formats
        if any(value == 'unknown' for value in [profile.hdr_type, profile.audio_format, str(profile.fps_type)]):
            log(f"AOM_OffsetManager: Skipping audio offset - Unknown format detected "
                f"(HDR: {profile.hdr_type}, Audio: {profile.audio_format}, "
                f"FPS: {profile.fps_type})", xbmc.LOGDEBUG)
            return False

        # Check if HDR type is enabled
        if not self.settings_facade.is_hdr_enabled(profile.hdr_type):
            log(f"AOM_OffsetManager: HDR type {profile.hdr_type} is not "
                f"enabled in settings", xbmc.LOGDEBUG)
            return False

        return True

    def apply_audio_offset(self):
        """Apply audio offset based on current stream information and settings."""
        try:
            if not self._should_apply_offset():
                return

            profile = self.stream_info.profile
            setting_id = profile.setting_id()
            delay_ms = self.settings_facade.get_offset_ms(profile)

            if delay_ms is None:
                log(f"AOM_OffsetManager: No audio delay found for setting ID: {setting_id}",
                    xbmc.LOGDEBUG)
                return

            if self._last_applied == (setting_id, delay_ms):
                log(f"AOM_OffsetManager: Offset already applied for {setting_id} at {delay_ms}ms; skipping duplicate apply",
                    xbmc.LOGDEBUG)
                return

            if profile.player_id != -1:
                self.set_audio_delay(profile.player_id, delay_ms / 1000.0)
                self._last_applied = (setting_id, delay_ms)
            else:
                log("AOM_OffsetManager: No valid player ID found to set "
                    "audio delay", xbmc.LOGDEBUG)

        except Exception as e:
            log(f"AOM_OffsetManager: Error applying audio offset: {str(e)}",
                xbmc.LOGERROR)

    def set_audio_delay(self, player_id, delay_seconds):
        """Set the audio delay using JSON-RPC."""
        success = rpc_client.set_audio_delay(player_id, delay_seconds)
        if success:
            # Convert seconds to milliseconds for notification
            delay_ms = int(delay_seconds * 1000)

            # Send notification for automatic offset application
            # This is only called for automatic offset application (not manual adjustments)
            if self.stream_info.profile is not None:
                self.notification_handler.notify_audio_offset_applied(delay_ms, self.stream_info.profile)
                log_snapshot("APPLY_OFFSET", self.stream_info, self.settings_facade, extra={"delay_ms": delay_ms})

    def _should_start_active_monitor(self):
        """Determine if active monitor should be started based on current conditions."""
        profile = self.stream_info.profile
        if profile is None:
            return False

        active_monitoring_enabled = self.settings_manager.get_setting_boolean('enable_active_monitoring')
        hdr_type = profile.hdr_type
        fps_type = profile.fps_type
        hdr_type_enabled = self.settings_manager.get_setting_boolean(f'enable_{hdr_type}')

        return (active_monitoring_enabled and 
                hdr_type_enabled and 
                hdr_type != 'unknown' and 
                fps_type != 'unknown')

    def manage_active_monitor(self):
        """Manage the active monitor state based on current conditions."""
        log(f"AOM_OffsetManager: Checking active monitor status - "
            f"HDR: {self.stream_info.profile.hdr_type if self.stream_info.profile else 'unknown'}, "
            f"FPS: {self.stream_info.profile.fps_type if self.stream_info.profile else 'unknown'}",
            xbmc.LOGDEBUG)

        if self._should_start_active_monitor():
            self.start_active_monitor()
        else:
            self.stop_active_monitor()

    def start_active_monitor(self):
        """Start the active monitor if it's not already running."""
        if self.active_monitor is None:
            self.active_monitor = ActiveMonitor(
                self.event_manager,
                self.stream_info,
                self,
                self.settings_manager
            )
            self.active_monitor.start()
            log("AOM_OffsetManager: Active monitor started", xbmc.LOGDEBUG)

    def stop_active_monitor(self):
        """Stop the active monitor if it's running."""
        if self.active_monitor is not None:
            self.active_monitor.stop()
            self.active_monitor = None
            log("AOM_OffsetManager: Active monitor stopped", xbmc.LOGDEBUG)
