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
        try:
            return self.settings.getBool(setting_id)
        except:
            xbmc.log(f"AOM_SettingsManager: Error getting boolean setting '{setting_id}'. Returning False.", xbmc.LOGWARNING)
            return False

    def get_integer_setting(self, setting_id):
        """Retrieve the integer setting using Settings.getInt()."""
        try:
            return self.settings.getInt(setting_id)
        except:
            xbmc.log(f"AOM_SettingsManager: Error getting integer setting '{setting_id}'. Returning 0.", xbmc.LOGWARNING)
            return 0

    def get_string_setting(self, setting_id):
        """Retrieve the string setting using Settings.getString()."""
        try:
            return self.settings.getString(setting_id)
        except:
            xbmc.log(f"AOM_SettingsManager: Error getting string setting '{setting_id}'. Returning empty string.", xbmc.LOGWARNING)
            return ""

    def get_audio_delay(self, hdr_type, audio_format):
        """
        Get the appropriate audio delay based on the combination of HDR type and audio codec.
        For example, for Dolby Vision and TrueHD, retrieve the setting 'dolbyvision_truehd'.
        """
        if hdr_type is None or audio_format is None:
            xbmc.log(f"AOM_SettingsManager: Invalid hdr_type ({hdr_type}) or audio_format ({audio_format}). Returning 0.", xbmc.LOGWARNING)
            return 0
        
        setting_id = f"{hdr_type}_{audio_format}"
        delay = self.get_integer_setting(setting_id)
        return delay

    def store_audio_delay(self, setting_id, delay_ms):
        """Store the updated audio delay in the add-on settings (in milliseconds)."""
        try:
            xbmc.log(f"AOM_SettingsManager: Storing delay for {setting_id}: {delay_ms} ms", xbmc.LOGDEBUG)
            self.settings.setInt(setting_id, delay_ms)
        except:
            xbmc.log(f"AOM_SettingsManager: Error storing delay for '{setting_id}'.", xbmc.LOGWARNING)

    def store_platform_hdr_full(self, platform_hdr_full):
        """Store the platform HDR full setting."""
        try:
            xbmc.log(f"AOM_SettingsManager: Storing platform HDR full: {platform_hdr_full}", xbmc.LOGDEBUG)
            self.settings.setBool("platform_hdr_full", platform_hdr_full)
        except:
            xbmc.log("AOM_SettingsManager: Error storing platform HDR full setting.", xbmc.LOGWARNING)

    def store_advanced_hlg(self, advanced_hlg):
        """Store the advanced HLG setting."""
        try:
            xbmc.log(f"AOM_SettingsManager: Storing advanced HLG: {advanced_hlg}", xbmc.LOGDEBUG)
            self.settings.setBool("advanced_hlg", advanced_hlg)
        except:
            xbmc.log("AOM_SettingsManager: Error storing advanced HLG setting.", xbmc.LOGWARNING)

    def store_new_install(self, new_install):
        """Store the new install setting."""
        try:
            xbmc.log(f"AOM_SettingsManager: Storing new install: {new_install}", xbmc.LOGDEBUG)
            self.settings.setBool("new_install", new_install)
        except:
            xbmc.log("AOM_SettingsManager: Error storing new install setting.", xbmc.LOGWARNING)

    def is_hdr_enabled(self, hdr_type):
        """
        Check if the HDR type is enabled in the settings.
        For example, check if 'enable_dolbyvision' is enabled for Dolby Vision.
        """
        if hdr_type is None:
            xbmc.log("AOM_SettingsManager: Invalid hdr_type (None). Returning False.", xbmc.LOGWARNING)
            return False
        
        setting_id = f"enable_{hdr_type}"
        return self.get_boolean_setting(setting_id)


# Usage example:
# settings_manager = SettingsManager()
# enable_seek_back = settings_manager.get_boolean_setting('enable_seek_back_adjust')
# seek_back_duration = settings_manager.get_integer_setting('seek_back_adjust_seconds')
# test_video_path = settings_manager.get_string_setting('test_video')
# settings_manager.store_platform_hdr_full(True)
# settings_manager.store_advanced_hlg(True)
# settings_manager.store_new_install(False)
