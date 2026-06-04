"""Module for handling test video playback functionality."""

import xbmc
import xbmcgui
import xbmcaddon
import xbmcvfs
from resources.lib.logger import log


class TestVideoManager:
    """Manages test video playback functionality."""
    
    def __init__(self):
        self.addon = xbmcaddon.Addon()
        self.addon_path = xbmcvfs.translatePath(self.addon.getAddonInfo('path'))
        self.test_video_path = xbmcvfs.translatePath(self.addon_path + '/resources/media/test-video.mp4')
        self.addon_icon = self.addon.getAddonInfo('icon')

    def play_test_video(self):
        """Play the test video for 5 seconds and return to addon settings."""
        if not xbmcvfs.exists(self.test_video_path):
            xbmcgui.Dialog().notification('$ADDON[script.audiooffsetmanager 32094]', '$ADDON[script.audiooffsetmanager 32095]',
                                        xbmcgui.NOTIFICATION_ERROR, 5000)
            return

        # Play the video
        xbmc.Player().play(self.test_video_path)

        # Show notification while video is playing
        xbmcgui.Dialog().notification('Audio Offset Manager',
                                    '$ADDON[script.audiooffsetmanager 32096]...',
                                    self.addon_icon, 10000)

        # Wait for 5 seconds
        xbmc.sleep(5000)

        # Stop the video
        xbmc.Player().stop()

        # Show success notification
        xbmcgui.Dialog().notification('Audio Offset Manager',
                                    '$ADDON[script.audiooffsetmanager 32097]',
                                    self.addon_icon, 10000)

        # Open addon settings
        xbmc.executebuiltin('Addon.OpenSettings(script.audiooffsetmanager)')
        
    def bypass_test_video(self):
        """Bypass the test video by setting new_install to false.

        This runs from the bypass action button, which uses <close>true</close>
        so the settings dialog is already closed by the time we write. That
        ordering matters: writing new_install while the dialog is open would let
        the dialog's save-on-close overwrite us, so the change wouldn't stick.
        Kodi's settings object is a live proxy (no manual reload is possible or
        needed); the only requirement is to write while the dialog is closed.
        """
        try:
            # Dialog is already closed (button close=true), so this write sticks.
            settings = self.addon.getSettings()
            settings.setBool('new_install', False)

            log("AOM_TestVideoManager: Successfully bypassed test video requirement", xbmc.LOGINFO)
            # Show success notification
            xbmcgui.Dialog().notification('Audio Offset Manager',
                                        '$ADDON[script.audiooffsetmanager 32098]',
                                        self.addon_icon, 3000)

            # Let the write settle to disk before the dialog reopens and reads it.
            xbmc.sleep(500)

            # Re-open addon settings to refresh them
            xbmc.executebuiltin('Addon.OpenSettings(script.audiooffsetmanager)')
        except Exception as e:
            log(f"AOM_TestVideoManager: Failed to bypass test video requirement: {str(e)}", xbmc.LOGWARNING)
            # Show error notification
            xbmcgui.Dialog().notification('Error',
                                        '$ADDON[script.audiooffsetmanager 32099]',
                                        xbmcgui.NOTIFICATION_ERROR, 3000)
