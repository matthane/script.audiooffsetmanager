"""Platform capability recorder: the detection side effects, made explicit.

This component performs the platform-capability writes
(``platform_hdr_full`` / ``advanced_hlg``, store-if-changed on every probe)
as an event-driven consumer of ``StreamProbed``, so detection itself stays
pure. The flags drive settings-UI visibility: capability-gated elements
appear once the first playback stores them.

No session guard on purpose: platform facts are session-independent — a
probe stamped with a superseded session still observed the real platform.

Writes defer while the addon settings dialog is open (settings-state
doctrine: its save-on-close would clobber them). A skipped probe is not
retried explicitly — the values are re-observed and re-stored by the next
gather, so nothing is lost, only delayed.

Pure app layer: no Kodi imports; settings via the injected adapter, the
dialog question via the injected gateway.
"""

from resources.lib.aom.app import events


class PlatformRecorder:
    def __init__(self, dispatcher, gateway, settings, *, log_debug):
        self._gateway = gateway
        self._settings = settings
        self._log = log_debug
        dispatcher.subscribe(events.StreamProbed, self._on_probed)

    def _on_probed(self, event):
        if self._gateway.settings_dialog_open():
            # Deferred, not dropped: the next probe re-observes everything.
            self._log("AOM_PlatformRecorder: settings dialog open; "
                      "deferring platform writes")
            return
        self._settings.store_boolean_if_changed('platform_hdr_full',
                                                event.platform_hdr_full)
        self._settings.store_boolean_if_changed('advanced_hlg',
                                                event.advanced_hlg)
