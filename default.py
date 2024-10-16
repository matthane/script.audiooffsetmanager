import xbmc
from resources.lib.addon_manager import AddonManager

# Initialize and start the addon manager
addon_manager = AddonManager()
addon_manager.start()

# Keep the script running
xbmc.Monitor().waitForAbort()

# On script exit, stop the addon manager
addon_manager.stop()