# resources/lib/onboard_manager.py

import sys
from play_test_video import play_test_video


def main():
    """Entry point for the onboarding process."""
    if len(sys.argv) > 1 and sys.argv[1] == 'play_test_video':
        play_test_video()


if __name__ == "__main__":
    main()
