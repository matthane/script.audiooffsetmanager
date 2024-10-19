# resources/lib/onboard.py

import xbmc
import xbmcgui

class OnboardManager:
    def __init__(self, settings_manager, event_manager, stream_info, offset_manager, seek_backs, active_monitor):
        self.settings_manager = settings_manager
        self.event_manager = event_manager
        self.stream_info = stream_info
        self.offset_manager = offset_manager
        self.seek_backs = seek_backs
        self.active_monitor = active_monitor

    def start(self):
        # Any initialization code can go here
        pass

    def stop(self):
        # Any cleanup code can go here
        pass

    def play_test_video(self):
        """Play the test video for 5 seconds and return to addon settings."""
        video_path = self.settings_manager.get_string_setting('test_video')
        if not video_path:
            xbmcgui.Dialog().notification('Error', 'No test video selected', xbmcgui.NOTIFICATION_ERROR, 5000)
            return

        # Play the video
        xbmc.Player().play(video_path)
        
        # Show notification while video is playing
        xbmcgui.Dialog().notification('Audio Offset Manager', 'Please wait...', xbmcgui.NOTIFICATION_INFO, 5000)
        
        # Wait for 5 seconds
        xbmc.sleep(5000)
        
        # Stop the video
        xbmc.Player().stop()
        
        # Show success notification
        xbmcgui.Dialog().notification('Audio Offset Manager', 'Success! Addon initialized', xbmcgui.NOTIFICATION_INFO, 5000)
        
        # Open addon settings
        xbmc.executebuiltin('Addon.OpenSettings(script.audiooffsetmanager)')

        # Example of interacting with other components:
        # self.stream_info.update()
        # self.offset_manager.apply_offset()
        # You can add more interactions here as needed
