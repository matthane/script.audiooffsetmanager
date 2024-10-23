"""Script entry point for Audio Offset Manager addon."""

import sys
from resources.lib.addon_manager import AddonManager


if __name__ == '__main__' and len(sys.argv) > 1 and sys.argv[1] == 'play_test_video':
    addon_manager = AddonManager()
    addon_manager.start()
    addon_manager.play_test_video()
    addon_manager.stop()
