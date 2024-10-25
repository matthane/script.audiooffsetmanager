"""Script entry point for Audio Offset Manager addon."""

import sys
from resources.lib.onboard import OnboardManager


if __name__ == '__main__' and len(sys.argv) > 1 and sys.argv[1] == 'play_test_video':
    onboard_manager = OnboardManager()
    onboard_manager.play_test_video()
