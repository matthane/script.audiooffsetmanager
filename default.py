import xbmc
import xbmcaddon

from resources.lib.controller import AudioDelayAdjuster, AudioDelayPlayer

def main():
    adjuster = AudioDelayAdjuster()
    player = AudioDelayPlayer(adjuster)
    adjuster.run()

if __name__ == '__main__':
    main()