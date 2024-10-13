import xbmc
import xbmcaddon

from resources.lib.controller import AudioDelayAdjuster

def main():
    adjuster = AudioDelayAdjuster()
    adjuster.run()

if __name__ == '__main__':
    main()