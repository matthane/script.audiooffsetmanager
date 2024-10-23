# service.py

import xbmc
import xbmcaddon
from resources.lib.addon_manager import AddonManager

addon = xbmcaddon.Addon()
addon_id = addon.getAddonInfo('id')


def main():
    addon_manager = AddonManager()
    addon_manager.start()

    monitor = xbmc.Monitor()
    while not monitor.abortRequested():
        if monitor.waitForAbort(10):
            break

    addon_manager.stop()


if __name__ == '__main__':
    main()
