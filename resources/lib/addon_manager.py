"""Addon Manager module to start up the service and delegate script launch."""

from resources.lib.stream_info import StreamInfo
from resources.lib.event_manager import EventManager
from resources.lib.settings_manager import SettingsManager
from resources.lib.offset_manager import OffsetManager
from resources.lib.seek_backs import SeekBacks


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

    def start(self):
        # Start all components
        self.offset_manager.start()
        self.seek_backs.start()

    def stop(self):
        # Stop all components
        self.offset_manager.stop()
        self.seek_backs.stop()
