"""
This module handles notifications for audio offset activies.
"""

import time
import xbmc
import xbmcaddon
import xbmcgui
from resources.lib.settings_facade import SettingsFacade
from resources.lib.logger import log


class NotificationHandler:
    """
    Class for handling Kodi GUI notifications.
    """
    def __init__(self, settings_manager=None, settings_facade=None):
        """
        Initialize the notification handler.
        
        Args:
            settings_manager: The settings manager instance to check notification settings
        """
        from resources.lib.settings_manager import SettingsManager  # Local import to avoid circular

        self.settings_manager = settings_manager or SettingsManager()
        self.settings_facade = settings_facade or SettingsFacade(self.settings_manager)
        self.addon = xbmcaddon.Addon('script.audiooffsetmanager')
        self.addon_name = self.addon.getAddonInfo('name')
        self.addon_icon = self.addon.getAddonInfo('icon')
        self._last_notification = None  # (prefix, setting_id, delay_ms)
        self._last_notification_ts = 0
    
    def _send_notification(self, delay_ms, profile, prefix):
        """
        Private helper method to send a notification with audio offset information.
        
        Args:
            delay_ms: The audio delay in milliseconds
            profile: The stream profile containing details about the current stream
            prefix: The prefix text for the notification message (e.g., "Offset applied:" or "Offset saved:")
        """
        # Check if notifications are enabled in settings
        if not self.settings_facade.notifications_enabled():
            return

        setting_id = profile.setting_id()
        now = time.time()
        dedupe_key = (prefix, setting_id, delay_ms)
        # Keep a short debounce to avoid back-to-back duplicates; 1s aligns with event debounce.
        if self._last_notification == dedupe_key and (now - self._last_notification_ts) < 1:
            return
            
        # Format the delay value for display
        # Convert to appropriate format (positive = advance, negative = delay)
        sign = "+" if delay_ms > 0 else ""
        delay_text = f"{sign}{delay_ms} ms"
            
        # Get stream format information
        fps_type_str = str(profile.fps_type)

        # Create notification message using profile formatting helpers
        summary = profile.summary(include_fps=True)
        message = f"{prefix} {delay_text}\n{summary}"
        
        # Send notification
        # Get notification duration from settings (in seconds) and convert to milliseconds
        notification_duration_ms = self.settings_facade.notification_duration_ms()
        xbmcgui.Dialog().notification(
            self.addon_name,
            message,
            self.addon_icon,
            notification_duration_ms
        )
        log(f"AOM_NotificationHandler: {message}", xbmc.LOGDEBUG)
        self._last_notification = dedupe_key
        self._last_notification_ts = now
    
    def notify_audio_offset_applied(self, delay_ms, profile):
        """
        Send a notification when an audio offset is applied for the currently played video.
        This is used when playback starts or when the audio channel changes during playback.
        
        Args:
            delay_ms: The audio delay in milliseconds
            profile: The stream profile containing details about the current stream
        """
        self._send_notification(delay_ms, profile, "$ADDON[script.audiooffsetmanager 32092]:")
        
    def notify_manual_offset_saved(self, delay_ms, profile):
        """
        Send a notification when a manual audio offset change is saved.
        This is used when the user manually adjusts the audio offset during playback
        and the active monitor is enabled.
        
        Args:
            delay_ms: The audio delay in milliseconds
            profile: The stream profile containing details about the current stream
        """
        self._send_notification(delay_ms, profile, "$ADDON[script.audiooffsetmanager 32093]:")
