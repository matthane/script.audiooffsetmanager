"""Module for handling test video playback functionality."""

import xbmc
import xbmcgui
import xbmcaddon
import xbmcvfs


class TestVideoManager:
    """Manages test video playback functionality."""
    
    def __init__(self):
        self.addon = xbmcaddon.Addon()
        self.addon_path = xbmcvfs.translatePath(self.addon.getAddonInfo('path'))
        self.test_video_path = xbmcvfs.translatePath(self.addon_path + '/resources/media/test-video.mp4')

    def play_test_video(self):
        """Play the test video for 5 seconds and return to addon settings."""
        if not xbmcvfs.exists(self.test_video_path):
            xbmcgui.Dialog().notification('Error', 'Test video not found',
                                        xbmcgui.NOTIFICATION_ERROR, 5000)
            return

        # Play the video
        xbmc.Player().play(self.test_video_path)

        # Show notification while video is playing
        xbmcgui.Dialog().notification('Audio Offset Manager',
                                    'Please wait...',
                                    xbmcgui.NOTIFICATION_INFO, 10000)

        # Wait for 5 seconds
        xbmc.sleep(5000)

        # Stop the video
        xbmc.Player().stop()

        # Show success notification
        xbmcgui.Dialog().notification('Audio Offset Manager',
                                    'Success! Test video completed',
                                    xbmcgui.NOTIFICATION_INFO, 10000)

        # Open addon settings
        xbmc.executebuiltin('Addon.OpenSettings(script.audiooffsetmanager)')
