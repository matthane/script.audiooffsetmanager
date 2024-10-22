# resources/lib/play_test_video.py

import xbmc
import xbmcgui
import xbmcaddon
import xbmcvfs
import sys


def play_test_video():
    """Play the test video for 5 seconds and return to addon settings."""
    addon = xbmcaddon.Addon()
    addon_path = xbmcvfs.translatePath(addon.getAddonInfo('path'))
    test_video_path = addon_path + '/resources/media/test-video.mp4'

    if not xbmcvfs.exists(test_video_path):
        xbmcgui.Dialog().notification('Error', 'Test video not found',
                                      xbmcgui.NOTIFICATION_ERROR, 5000)
        return

    # Play the video
    xbmc.Player().play(test_video_path)

    # Show notification while video is playing
    xbmcgui.Dialog().notification('Audio Offset Manager',
                                  'Please wait...',
                                  xbmcgui.NOTIFICATION_INFO, 5000)

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

if __name__ == "__main__":
    # Check if the script is being run with a launch argument
    if len(sys.argv) > 1 and sys.argv[1] == 'play_test_video':
        play_test_video()
