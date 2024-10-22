# default.py

import sys
import xbmc
import xbmcaddon
from resources.lib.addon_manager import AddonManager

addon = xbmcaddon.Addon()
addon_id = addon.getAddonInfo('id')


def main():
    addon_manager = AddonManager()
    addon_manager.start()

    if len(sys.argv) > 1 and sys.argv[1] == 'play_test_video':
        addon_manager.play_test_video()
    else:
        monitor = xbmc.Monitor()
        while not monitor.abortRequested():
            if monitor.waitForAbort(10):
                break

    addon_manager.stop()


if __name__ == '__main__':
    main()
