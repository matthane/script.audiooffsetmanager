# resources/lib/addon_manager.py

from resources.lib.stream_info import StreamInfo
from resources.lib.event_manager import EventManager
from resources.lib.settings_manager import SettingsManager
from resources.lib.offset_manager import OffsetManager
from resources.lib.seek_backs import SeekBacks
from resources.lib.onboard import OnboardManager


class AddonManager:
    def __init__(self):
        # Initialize the event manager
        self.event_manager = EventManager()

        # Initialize the settings manager
        self.settings_manager = SettingsManager()

        # Initialize stream info module
        self.stream_info = StreamInfo()

        # Initialize offset manager
        self.offset_manager = OffsetManager(self.event_manager)

        # Initialize seek backs
        self.seek_backs = SeekBacks(self.event_manager)

        # Initialize onboard manager with settings manager and stream info
        self.onboard_manager = OnboardManager(self.settings_manager, self.stream_info)

    def start(self):
        # Start all components except onboard_manager and stream_info
        self.offset_manager.start()
        self.seek_backs.start()

    def stop(self):
        # Stop all components except onboard_manager and stream_info
        self.offset_manager.stop()
        self.seek_backs.stop()

    def play_test_video(self):
        """Delegate to onboard manager to play test video."""
        self.onboard_manager.play_test_video()
