# resources/lib/settings_manager.py

import xbmc
import xbmcaddon


class SettingsManager:
    def __init__(self):
        # Initialize the Addon object to access settings
        self.addon = xbmcaddon.Addon('script.audiooffsetmanager')
        self.settings = self.addon.getSettings()

    def get_boolean_setting(self, setting_id):
        """Retrieve the boolean setting using Settings.getBool()."""
        return self.settings.getBool(setting_id)

    def get_integer_setting(self, setting_id):
        """Retrieve the integer setting using Settings.getInt()."""
        return self.settings.getInt(setting_id)

    def get_audio_delay(self, hdr_type, audio_format):
        """
        Get the appropriate audio delay based on the combination of HDR type and audio codec.
        For example, for Dolby Vision and TrueHD, retrieve the setting 'dolbyvision_truehd'.
        """
        setting_id = f"{hdr_type}_{audio_format}"
        delay = self.get_integer_setting(setting_id)
        return delay

    def store_audio_delay(self, setting_id, delay_ms):
        """Store the updated audio delay in the add-on settings (in milliseconds)."""
        xbmc.log(f"AOM_SettingsManager: Storing delay for {setting_id}: {delay_ms} ms", xbmc.LOGDEBUG)
        self.settings.setInt(setting_id, delay_ms)

    def store_platform_hdr_full(self, platform_hdr_full):
        """Store the platform HDR full setting."""
        xbmc.log(f"AOM_SettingsManager: Storing platform HDR full: {platform_hdr_full}", xbmc.LOGDEBUG)
        self.settings.setBool("platform_hdr_full", platform_hdr_full)
        self.settings.setBool("platform_hdr_full2", platform_hdr_full)

    def store_advanced_hlg(self, advanced_hlg):
        """Store the advanced HLG setting."""
        xbmc.log(f"AOM_SettingsManager: Storing advanced HLG: {advanced_hlg}", xbmc.LOGDEBUG)
        self.settings.setBool("advanced_hlg", advanced_hlg)

    def store_new_install(self, new_install):
        """Store the new install setting."""
        xbmc.log(f"AOM_SettingsManager: Storing new install: {new_install}", xbmc.LOGDEBUG)
        self.settings.setBool("new_install", new_install)

    def is_hdr_enabled(self, hdr_type):
        """
        Check if the HDR type is enabled in the settings.
        For example, check if 'enable_dolbyvision' is enabled for Dolby Vision.
        """
        setting_id = f"enable_{hdr_type}"
        return self.get_boolean_setting(setting_id)


# Usage example:
# settings_manager = SettingsManager()
# enable_seek_back = settings_manager.get_boolean_setting('enable_seek_back_adjust')
# seek_back_duration = settings_manager.get_integer_setting('seek_back_adjust_seconds')
# settings_manager.store_platform_hdr_full(True)
# settings_manager.store_advanced_hlg(True)
# settings_manager.store_new_install(False)
