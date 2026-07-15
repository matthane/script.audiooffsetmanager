"""Composition root for the service process.

Builds the dispatcher, the Kodi bridges, and the (still partly legacy)
component graph with explicit, REQUIRED constructor dependencies — no
fallback construction anywhere. Blocks on the monitor until Kodi aborts,
then shuts everything down in reverse order.
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
from resources.lib.aom.app.platform_recorder import PlatformRecorder
from resources.lib.aom.app.session import SessionTracker
from resources.lib.aom.app.stream_detector import StreamDetector
from resources.lib.aom.kodi.gateway import KodiGateway
from resources.lib.aom.kodi.monitor_bridge import MonitorBridge
from resources.lib.aom.kodi.player_bridge import PlayerBridge


# The injected log sinks, bound once (named functions also read better than
# lambdas in the dispatcher's per-handler runtime logging).
def _log_debug(message):
    log(message, xbmc.LOGDEBUG)


def _log_warning(message):
    log(message, xbmc.LOGWARNING)


def _log_error(message):
    log(message, xbmc.LOGERROR)


class ServiceRuntime:
    def __init__(self):
        settings_manager = SettingsManager()
        settings_facade = SettingsFacade(settings_manager)
        notification_handler = NotificationHandler(settings_manager,
                                                   settings_facade)
        gateway = KodiGateway(log=log)

        self._settings_facade = settings_facade
        self.dispatcher = Dispatcher(
            log_debug=_log_debug,
            log_error=_log_error,
            log_runtimes=settings_facade.debug_logging_enabled())

        # Subscription order is load-bearing (dispatch follows it):
        # 1. tracker — the session exists (or is torn down) before any other
        #    handler of the same lifecycle event runs;
        # 2. router — publishes the legacy AV_STARTED before the detector
        #    starts probing (legacy event order);
        # 3. detector — owns session.profile and the stream-state machine;
        # 4. recorder — consumes the detector's StreamProbed facts.
        self.session_tracker = SessionTracker(
            self.dispatcher, log_debug=_log_debug)

        # MIGRATION(p7): the router carries the legacy EventBus surface.
        self.router = LegacyEventRouter(self.dispatcher, self.session_tracker,
                                        settings_facade)
        self.detector = StreamDetector(
            self.dispatcher, self.session_tracker, gateway, settings_facade,
            log_debug=_log_debug, log_warning=_log_warning)
        self.platform_recorder = PlatformRecorder(
            self.dispatcher, settings_facade, log_debug=_log_debug)

        # MIGRATION(p6): session-backed StreamInfo shim, read by ActiveMonitor
        # and the debug snapshot only.
        stream_info = StreamInfo(self.session_tracker)
        self.offset_manager = OffsetManager(self.router, settings_manager,
                                            stream_info, notification_handler,
                                            settings_facade,
                                            self.session_tracker)
        self.seek_backs = SeekBacks(self.router, settings_manager,
                                    settings_facade, self.session_tracker)

        self.player_bridge = PlayerBridge(self.dispatcher)
        self.monitor = MonitorBridge(self.dispatcher)
        self.dispatcher.subscribe(events.SettingsChanged,
                                  self._on_settings_changed)

    def _on_settings_changed(self, _event):
        """Refresh cached debug flags; never write settings from here."""
        debug = self._settings_facade.debug_logging_enabled()
        self.dispatcher.log_runtimes = debug
        self.router.set_log_runtimes(debug)

    def run(self):
        # Components subscribe BEFORE the dispatcher thread starts: any events
        # the bridges queued during construction are then dispatched to a
        # complete graph instead of an empty bus (matters when the service
        # (re)starts while playback is already active). Subscription order is
        # load-bearing too: OffsetManager registers its EventBus callbacks
        # before SeekBacks, so offsets are applied before any seek-back logic
        # runs for the same event.
        self.offset_manager.start()
        self.seek_backs.start()
        self.dispatcher.start()
        log("AOM_Runtime: service started", xbmc.LOGDEBUG)

        self.monitor.waitForAbort()

        log("AOM_Runtime: abort requested; shutting down", xbmc.LOGDEBUG)
        # Dispatcher first: once its thread is joined, no handler can be
        # mid-publish while the components unsubscribe from the (un-locked)
        # EventBus below. Posts arriving after stop are dropped by design.
        self.dispatcher.stop()
        self.offset_manager.stop()
        self.seek_backs.stop()
