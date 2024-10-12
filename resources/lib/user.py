import xbmcaddon
import xbmc

class UserSettings:
    """
    The UserSettings class is responsible for managing the retrieval of user-defined settings from the Kodi add-on configuration.
    """
    def __init__(self):
        # Initialize the add-on object to access settings
        self.addon = xbmcaddon.Addon()

    def load_settings(self):
        """
        Loads the user settings from the add-on configuration.
        Returns:
            tuple: A tuple containing latency settings, seek back settings, seek back seconds, HDR control settings, enable seek back on resume, seek back resume seconds, enable seek back on unpause, and seek back unpause seconds.
        """
        try:
            # Load latency settings for different audio and video formats
            latency_settings = {
                'sdr_truehd': self.addon.getSettingInt('delay_sdr_truehd'),
                'hdr10_truehd': self.addon.getSettingInt('delay_hdr10_truehd'),
                'dolbyvision_truehd': self.addon.getSettingInt('delay_dolbyvision_truehd'),
                'hlg_truehd': self.addon.getSettingInt('delay_hlg_truehd'),
                'hdr10plus_truehd': self.addon.getSettingInt('delay_hdr10plus_truehd'),
                'sdr_eac3': self.addon.getSettingInt('delay_sdr_eac3'),
                'hdr10_eac3': self.addon.getSettingInt('delay_hdr10_eac3'),
                'dolbyvision_eac3': self.addon.getSettingInt('delay_dolbyvision_eac3'),
                'hlg_eac3': self.addon.getSettingInt('delay_hlg_eac3'),
                'hdr10plus_eac3': self.addon.getSettingInt('delay_hdr10plus_eac3'),
                'sdr_ac3': self.addon.getSettingInt('delay_sdr_ac3'),
                'hdr10_ac3': self.addon.getSettingInt('delay_hdr10_ac3'),
                'dolbyvision_ac3': self.addon.getSettingInt('delay_dolbyvision_ac3'),
                'hlg_ac3': self.addon.getSettingInt('delay_hlg_ac3'),
                'hdr10plus_ac3': self.addon.getSettingInt('delay_hdr10plus_ac3'),
                'sdr_dtsx': self.addon.getSettingInt('delay_sdr_dtsx'),
                'hdr10_dtsx': self.addon.getSettingInt('delay_hdr10_dtsx'),
                'dolbyvision_dtsx': self.addon.getSettingInt('delay_dolbyvision_dtsx'),
                'hlg_dtsx': self.addon.getSettingInt('delay_hlg_dtsx'),
                'hdr10plus_dtsx': self.addon.getSettingInt('delay_hdr10plus_dtsx'),
                'sdr_dtshd_ma': self.addon.getSettingInt('delay_sdr_dtshd_ma'),
                'hdr10_dtshd_ma': self.addon.getSettingInt('delay_hdr10_dtshd_ma'),
                'dolbyvision_dtshd_ma': self.addon.getSettingInt('delay_dolbyvision_dtshd_ma'),
                'hlg_dtshd_ma': self.addon.getSettingInt('delay_hlg_dtshd_ma'),
                'hdr10plus_dtshd_ma': self.addon.getSettingInt('delay_hdr10plus_dtshd_ma'),
                'sdr_dca': self.addon.getSettingInt('delay_sdr_dca'),
                'hdr10_dca': self.addon.getSettingInt('delay_hdr10_dca'),
                'dolbyvision_dca': self.addon.getSettingInt('delay_dolbyvision_dca'),
                'hlg_dca': self.addon.getSettingInt('delay_hlg_dca'),
                'hdr10plus_dca': self.addon.getSettingInt('delay_hdr10plus_dca'),
            }

            # Load the seek back settings
            enable_seek_back = self.addon.getSettingBool('enable_seek_back')
            seek_back_seconds = self.addon.getSettingInt('seek_back_seconds')

            # Load HDR control settings
            hdr_control_settings = {
                'enable_dolbyvision': self.addon.getSettingBool('enable_dolbyvision'),
                'enable_hdr10': self.addon.getSettingBool('enable_hdr10'),
                'enable_hdr10plus': self.addon.getSettingBool('enable_hdr10plus'),
                'enable_hlg': self.addon.getSettingBool('enable_hlg'),
                'enable_sdr': self.addon.getSettingBool('enable_sdr'),
            }

            # Load the seek back on resume settings
            enable_seek_back_resume = self.addon.getSettingBool('enable_seek_back_resume')
            seek_back_resume_seconds = self.addon.getSettingInt('seek_back_resume_seconds')

            # Load the seek back on unpause settings
            enable_seek_back_unpause = self.addon.getSettingBool('enable_seek_back_unpause')
            seek_back_unpause_seconds = self.addon.getSettingInt('seek_back_unpause_seconds')

            # Validate seek back seconds range
            if not (1 <= seek_back_seconds <= 10):
                xbmc.log("Seek back seconds out of range. Resetting to default (4 seconds).", xbmc.LOGWARNING)
                seek_back_seconds = 4

            # Validate seek back resume seconds range
            if not (1 <= seek_back_resume_seconds <= 10):
                xbmc.log("Seek back resume seconds out of range. Resetting to default (4 seconds).", xbmc.LOGWARNING)
                seek_back_resume_seconds = 4

            # Validate seek back unpause seconds range
            if not (1 <= seek_back_unpause_seconds <= 10):
                xbmc.log("Seek back unpause seconds out of range. Resetting to default (4 seconds).", xbmc.LOGWARNING)
                seek_back_unpause_seconds = 4

            return (latency_settings, enable_seek_back, seek_back_seconds, hdr_control_settings,
                    enable_seek_back_resume, seek_back_resume_seconds,
                    enable_seek_back_unpause, seek_back_unpause_seconds)
        except Exception as e:
            # Log any errors that occur while loading settings and return default values
            xbmc.log(f"Error loading settings: {e}", xbmc.LOGERROR)
            return {
                'sdr_truehd': 0,
                'hdr10_truehd': 0,
                'hdr10plus_truehd': 0,
                'dolbyvision_truehd': 0,
                'hlg_truehd': 0,
                'sdr_eac3': 0,
                'hdr10_eac3': 0,
                'hdr10plus_eac3': 0,
                'dolbyvision_eac3': 0,
                'hlg_eac3': 0,
                'sdr_ac3': 0,
                'hdr10_ac3': 0,
                'hdr10plus_ac3': 0,
                'dolbyvision_ac3': 0,
                'hlg_ac3': 0,
                'sdr_dtsx': 0,
                'hdr10_dtsx': 0,
                'hdr10plus_dtsx': 0,
                'dolbyvision_dtsx': 0,
                'hlg_dtsx': 0,
                'sdr_dtshd_ma': 0,
                'hdr10_dtshd_ma': 0,
                'hdr10plus_dtshd_ma': 0,
                'dolbyvision_dtshd_ma': 0,
                'hlg_dtshd_ma': 0,
                'sdr_dca': 0,
                'hdr10_dca': 0,
                'hdr10plus_dca': 0,
                'dolbyvision_dca': 0,
                'hlg_dca': 0,
            }, True, 4, {
                'enable_dolbyvision': False,
                'enable_hdr10': False,
                'enable_hdr10plus': False,
                'enable_hlg': False,
                'enable_sdr': False,
            }, False, 4, False, 4