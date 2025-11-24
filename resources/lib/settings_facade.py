"""Intent-level helper over SettingsManager to centralize setting access."""

from resources.lib.settings_manager import SettingsManager


class SettingsFacade:
    def __init__(self, settings_manager=None):
        self.settings_manager = settings_manager or SettingsManager()

    def is_hdr_enabled(self, hdr_type):
        return self.settings_manager.get_setting_boolean(f"enable_{hdr_type}")

    def fps_override_enabled(self, hdr_type):
        return self.settings_manager.get_setting_boolean(f"enable_fps_{hdr_type}")

    def effective_fps_bucket(self, profile):
        """Return fps bucket honoring override flag."""
        if profile.hdr_type == 'unknown':
            return profile.fps_type
        return profile.fps_type if self.fps_override_enabled(profile.hdr_type) else 'all'

    def get_offset_ms(self, profile):
        return self.settings_manager.get_setting_integer(profile.setting_id())

    def seek_back_config(self, event_type):
        """Return (enabled, seconds) for a seek-back event."""
        setting_type = event_type
        enable_setting = f"enable_seek_back_{setting_type}"
        seconds_setting = f"seek_back_{setting_type}_seconds"

        enabled = self.settings_manager.get_setting_boolean(enable_setting)
        seconds = self.settings_manager.get_setting_integer(seconds_setting)
        seconds = max(seconds, 0)
        return enabled, seconds

    def notifications_enabled(self):
        return self.settings_manager.get_setting_boolean('enable_notifications')

    def notification_duration_ms(self):
        return self.settings_manager.get_setting_integer('notification_seconds') * 1000

    def debug_logging_enabled(self):
        return self.settings_manager.get_setting_boolean('enable_debug_logging')

    def is_new_install(self):
        return self.settings_manager.get_setting_boolean('new_install')

    def store_boolean_if_changed(self, setting_id, value):
        return self.settings_manager.store_setting_boolean(setting_id, value)

    def store_integer_if_changed(self, setting_id, value):
        return self.settings_manager.store_setting_integer(setting_id, value)
