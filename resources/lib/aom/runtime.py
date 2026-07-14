"""Composition root for the service process.

Builds the dispatcher, the Kodi bridges, and the (still legacy) component
graph with explicit, REQUIRED constructor dependencies — no fallback
construction anywhere. Blocks on the monitor until Kodi aborts, then shuts
everything down in reverse order.
"""

import xbmc

from resources.lib.logger import log
from resources.lib.notification_handler import NotificationHandler
from resources.lib.offset_manager import OffsetManager
from resources.lib.seek_backs import SeekBacks
from resources.lib.settings_facade import SettingsFacade
from resources.lib.settings_manager import SettingsManager
from resources.lib.stream_info import StreamInfo
from resources.lib.aom.app import events
from resources.lib.aom.app.dispatcher import Dispatcher
from resources.lib.aom.app.legacy_router import LegacyEventRouter
from resources.lib.aom.kodi.monitor_bridge import MonitorBridge
from resources.lib.aom.kodi.player_bridge import PlayerBridge


class ServiceRuntime:
    def __init__(self):
        settings_manager = SettingsManager()
        settings_facade = SettingsFacade(settings_manager)
        stream_info = StreamInfo(settings_manager, settings_facade)
        notification_handler = NotificationHandler(settings_manager,
                                                   settings_facade)

        self._settings_facade = settings_facade
        self.dispatcher = Dispatcher(
            log_debug=lambda message: log(message, xbmc.LOGDEBUG),
            log_error=lambda message: log(message, xbmc.LOGERROR),
            log_runtimes=settings_facade.debug_logging_enabled())

        # MIGRATION(p7): the router carries the legacy EventBus surface.
        self.router = LegacyEventRouter(self.dispatcher, stream_info,
                                        settings_facade)
        self.offset_manager = OffsetManager(self.router, settings_manager,
                                            stream_info, notification_handler,
                                            settings_facade)
        self.seek_backs = SeekBacks(self.router, settings_manager,
                                    settings_facade)

        self.player_bridge = PlayerBridge(self.dispatcher)
        self.monitor = MonitorBridge(self.dispatcher)
        self.dispatcher.subscribe(events.SettingsChanged,
                                  self._on_settings_changed)

    def _on_settings_changed(self, _event):
        """Refresh cached debug flags; never write settings from here."""
        debug = self._settings_facade.debug_logging_enabled()
        self.dispatcher.log_runtimes = debug
        self.router.event_bus.log_runtimes = debug

    def run(self):
        # Subscription order is load-bearing: OffsetManager registers its
        # EventBus callbacks before SeekBacks, so offsets are applied before
        # any seek-back logic runs for the same event.
        self.dispatcher.start()
        self.offset_manager.start()
        self.seek_backs.start()
        log("AOM_Runtime: service started", xbmc.LOGDEBUG)

        self.monitor.waitForAbort()

        log("AOM_Runtime: abort requested; shutting down", xbmc.LOGDEBUG)
        self.offset_manager.stop()
        self.seek_backs.stop()
        self.dispatcher.stop()
