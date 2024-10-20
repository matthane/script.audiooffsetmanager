# resources/lib/play_test_video.py

import xbmc
import xbmcgui
import xbmcaddon
import xbmcvfs


def play_test_video():
    """Play the test video for 5 seconds and return to addon settings."""
    addon = xbmcaddon.Addon()
    addon_path = xbmcvfs.translatePath(addon.getAddonInfo('path'))
    test_video_path = addon_path + '/resources/media/test-video.mp4'

    if not xbmcvfs.exists(test_video_path):
        xbmcgui.Dialog().notification('Error', 'Test video not found',
                                      xbmcgui.NOTIFICATION_ERROR, 5000)
        return

    xbmc.Player().play(test_video_path)
    xbmcgui.Dialog().notification('Audio Offset Manager',
                                  'Please wait...',
                                  xbmcgui.NOTIFICATION_INFO, 5000)
    xbmc.sleep(5000)
    xbmc.Player().stop()

    xbmcgui.Dialog().notification('Audio Offset Manager',
                                  'Success! Addon initialized',
                                  xbmcgui.NOTIFICATION_INFO, 10000)
    xbmc.executebuiltin('Addon.OpenSettings(script.audiooffsetmanager)')
