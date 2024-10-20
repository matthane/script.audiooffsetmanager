# resources/lib/onboard.py

import xbmc
import xbmcgui


class OnboardManager:
    def __init__(self, settings_manager, stream_info):
        self.settings_manager = settings_manager
        self.stream_info = stream_info

    def play_test_video(self):
        """Play the test video for 5 seconds and return to addon settings."""
        video_path = self.settings_manager.get_string_setting('test_video')
        if not video_path:
            xbmcgui.Dialog().notification('Error', 'No test video selected',
                                          xbmcgui.NOTIFICATION_ERROR, 5000)
            return

        # Play the video
        xbmc.Player().play(video_path)

        # Show notification while video is playing
        xbmcgui.Dialog().notification('Audio Offset Manager',
                                      'Please wait...',
                                      xbmcgui.NOTIFICATION_INFO, 5000)

        # Gather platform capabilities
        self.gather_platform_capabilities()

        # Wait for 5 seconds
        xbmc.sleep(5000)

        # Stop the video
        xbmc.Player().stop()


        # Show success notification
        xbmcgui.Dialog().notification('Audio Offset Manager',
                                      'Success! Addon initialized',
                                      xbmcgui.NOTIFICATION_INFO, 5000)

        # Open addon settings
        xbmc.executebuiltin('Addon.OpenSettings(script.audiooffsetmanager)')

    def gather_platform_capabilities(self):
        """Gather and store key information about platform capabilities."""
        self.stream_info.update_stream_info()
        
        # Store platform HDR full support
        platform_hdr_full = self.stream_info.info.get('platform_hdr_full', False)
        self.settings_manager.store_platform_hdr_full(platform_hdr_full)
        
        # Store advanced HLG support
        gamut_info = self.stream_info.info.get('gamut_info', 'not available')
        advanced_hlg = gamut_info != 'not available'
        self.settings_manager.store_advanced_hlg(advanced_hlg)
        
        # Log the gathered information
        xbmc.log(f"AOM_Onboard: Platform HDR full support: {platform_hdr_full}", xbmc.LOGINFO)
        xbmc.log(f"AOM_Onboard: Advanced HLG support: {advanced_hlg}", xbmc.LOGINFO)
        
        # Set new_install to False as we've gathered the initial platform capabilities
        self.settings_manager.store_new_install(False)
