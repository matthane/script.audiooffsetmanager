"""Service entry point for Audio Offset Manager addon."""

import xbmc
from resources.lib.addon_manager import AddonManager


if __name__ == '__main__':
    addon_manager = AddonManager()
    addon_manager.start()
    monitor = xbmc.Monitor()
    monitor.waitForAbort()
    addon_manager.stop()