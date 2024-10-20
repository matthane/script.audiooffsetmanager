# default.py

import xbmcaddon
from resources.lib.addon_manager import AddonManager

addon = xbmcaddon.Addon()
addon_id = addon.getAddonInfo('id')

if __name__ == '__main__':
    addon_manager = AddonManager()
    addon_manager.run()
