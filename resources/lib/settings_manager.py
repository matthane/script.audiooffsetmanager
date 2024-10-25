"""Settings manager module to provide methods for other modules to interface with 
the addon settings.
"""

import xbmc
import xbmcaddon


class SettingsManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SettingsManager, cls).__new__(cls)
            # Initialize the instance attributes
            cls._instance.addon = xbmcaddon.Addon('script.audiooffsetmanager')
            cls._instance.settings = cls._instance.addon.getSettings()
        return cls._instance

    def reload_if_needed(self):
        """Public method to reload settings when explicitly needed."""
        self.settings = self.addon.getSettings()

    def get_setting_boolean(self, setting_id):
        """Retrieve the boolean setting using Settings.getBool()."""
        try:
            return self.settings.getBool(setting_id)
        except:
            xbmc.log(f"AOM_SettingsManager: Error getting boolean setting "
                     f"'{setting_id}'. Returning False.", xbmc.LOGWARNING)
            return False

    def get_setting_integer(self, setting_id):
        """Retrieve the integer setting using Settings.getInt()."""
        try:
            return self.settings.getInt(setting_id)
        except:
            xbmc.log(f"AOM_SettingsManager: Error getting integer setting "
                     f"'{setting_id}'. Returning 0.", xbmc.LOGWARNING)
            return 0

    def get_setting_string(self, setting_id):
        """Retrieve the string setting using Settings.getString()."""
        try:
            return self.settings.getString(setting_id)
        except:
            xbmc.log(f"AOM_SettingsManager: Error getting string setting "
                     f"'{setting_id}'. Returning empty string.", xbmc.LOGWARNING)
            return ""

    def store_setting_boolean(self, setting_id, value):
        """Store a boolean setting."""
        try:
            xbmc.log(f"AOM_SettingsManager: Storing boolean setting {setting_id}: "
                     f"{value}", xbmc.LOGDEBUG)
            self.settings.setBool(setting_id, value)
        except:
            xbmc.log(f"AOM_SettingsManager: Error storing boolean setting "
                     f"'{setting_id}'.", xbmc.LOGWARNING)

    def store_setting_integer(self, setting_id, value):
        """Store an integer setting."""
        try:
            xbmc.log(f"AOM_SettingsManager: Storing integer setting {setting_id}: "
                     f"{value}", xbmc.LOGDEBUG)
            self.settings.setInt(setting_id, value)
        except:
            xbmc.log(f"AOM_SettingsManager: Error storing integer setting "
                     f"'{setting_id}'.", xbmc.LOGWARNING)

    def store_setting_string(self, setting_id, value):
        """Store a string setting."""
        try:
            xbmc.log(f"AOM_SettingsManager: Storing string setting {setting_id}: "
                     f"{value}", xbmc.LOGDEBUG)
            self.settings.setString(setting_id, value)
        except:
            xbmc.log(f"AOM_SettingsManager: Error storing string setting "
                     f"'{setting_id}'.", xbmc.LOGWARNING)
