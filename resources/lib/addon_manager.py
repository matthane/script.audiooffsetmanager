"""Addon Manager module to start up the service components."""

from resources.lib.event_manager import EventManager
from resources.lib.settings_manager import SettingsManager
from resources.lib.settings_facade import SettingsFacade
from resources.lib.offset_manager import OffsetManager
from resources.lib.seek_backs import SeekBacks
from resources.lib.stream_info import StreamInfo
from resources.lib.notification_handler import NotificationHandler


class AddonManager:
    def __init__(self):
        # Initialize shared dependencies
        self.settings_manager = SettingsManager()
        self.settings_facade = SettingsFacade(self.settings_manager)
        self.stream_info = StreamInfo(self.settings_manager, self.settings_facade)
        self.notification_handler = NotificationHandler(self.settings_manager, self.settings_facade)

        # Initialize the event manager
        self.event_manager = EventManager(self.settings_manager, self.stream_info, self.settings_facade)

        # Initialize offset manager
        self.offset_manager = OffsetManager(
            self.event_manager,
            self.settings_manager,
            self.stream_info,
            self.notification_handler,
            self.settings_facade
        )

        # Initialize seek backs
        self.seek_backs = SeekBacks(self.event_manager, self.settings_manager, self.settings_facade)

    def start(self):
        # Start all components
        self.offset_manager.start()
        self.seek_backs.start()

    def stop(self):
        # Stop all components
        self.offset_manager.stop()
        self.seek_backs.stop()
