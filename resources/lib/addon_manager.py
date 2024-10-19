# resources/lib/addon_manager.py

from resources.lib.stream_info import StreamInfo
from resources.lib.event_manager import EventManager
from resources.lib.settings_manager import SettingsManager
from resources.lib.offset_manager import OffsetManager
from resources.lib.seek_backs import SeekBacks
from resources.lib.active_monitor import ActiveMonitor
from resources.lib.onboard import OnboardManager


class AddonManager:
    def __init__(self):
        # Initialize the event manager
        self.event_manager = EventManager()

        # Initialize the settings manager
        self.settings_manager = SettingsManager()

        # Initialize stream info module
        self.stream_info = StreamInfo(self.event_manager)

        # Initialize offset manager
        self.offset_manager = OffsetManager(self.event_manager, self.stream_info)

        # Initialize seek backs
        self.seek_backs = SeekBacks(self.event_manager)

        # Initialize active monitor
        self.active_monitor = ActiveMonitor(
            self.event_manager,
            self.stream_info,
            self.offset_manager
        )

        # Initialize onboard manager with access to all components
        self.onboard_manager = OnboardManager(
            self.settings_manager,
            self.event_manager,
            self.stream_info,
            self.offset_manager,
            self.seek_backs,
            self.active_monitor
        )

    def start(self):
        # Start all components
        self.stream_info.start()
        self.offset_manager.start()
        self.seek_backs.start()
        self.active_monitor.start()
        self.onboard_manager.start()

    def stop(self):
        # Stop all components
        self.stream_info.stop()
        self.offset_manager.stop()
        self.seek_backs.stop()
        self.active_monitor.stop()
        self.onboard_manager.stop()

    def play_test_video(self):
        """Delegate to onboard manager to play test video."""
        self.onboard_manager.play_test_video()
