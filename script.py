import sys
import xbmcaddon
from resources.lib.addon_manager import AddonManager

addon = xbmcaddon.Addon()
addon_id = addon.getAddonInfo('id')


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'play_test_video':
        addon_manager = AddonManager()
        addon_manager.start()
        addon_manager.play_test_video()
        addon_manager.stop()


if __name__ == '__main__':
    main()
