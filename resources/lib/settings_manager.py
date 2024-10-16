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
        xbmc.log(f"Storing delay for {setting_id}: {delay_ms} ms", xbmc.LOGINFO)
        self.settings.setInt(setting_id, delay_ms)

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