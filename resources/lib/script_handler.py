"""Handler module containing supporting script functions such as 
playing the test video or launching the settings.
"""

import sys
import xbmcaddon
from resources.lib.test_video import TestVideoManager


def handle_script_call():
    """Handle the main script functionality."""
    if len(sys.argv) > 1 and sys.argv[1] == 'play_test_video':
        test_video = TestVideoManager()
        test_video.play_test_video()
    else:
        # Open addon settings when no specific argument is provided
        addon = xbmcaddon.Addon()
        addon.openSettings()
