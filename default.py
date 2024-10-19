import xbmc
import sys
from resources.lib.addon_manager import AddonManager

# Initialize the addon manager
addon_manager = AddonManager()

# Check if we're being called with arguments
if len(sys.argv) > 1:
    if sys.argv[1] == 'play_test_video':
        addon_manager.play_test_video()
else:
    # Start the addon manager for normal operation
    addon_manager.start()

    # Keep the script running
    xbmc.Monitor().waitForAbort()

    # On script exit, stop the addon manager
    addon_manager.stop()
