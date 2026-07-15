"""Platform capability recorder: the detection side effects, made explicit.

Legacy StreamInfo.gather_stream_info wrote three settings inline on every
gather; this component performs the same writes as an event-driven consumer
of ``StreamProbed``, so detection itself stays pure:

- ``platform_hdr_full`` / ``advanced_hlg`` — store-if-changed on every probe
  (legacy parity: stored on every gather).
- ``new_install`` — read once at service start and cleared on the first
  observed probe of this service lifetime (legacy parity: StreamInfo read it
  in ``__init__`` and flipped it during the first gather). Queue order
  preserves the legacy flip-before-apply sequence: the detector posts
  ``StreamProbed`` before ``ProfileChanged``, so the flag is cleared before
  the offset applier's ``is_new_install`` gate reads it.

No session guard on purpose: platform facts are session-independent — a
probe stamped with a superseded session still observed the real platform.

Writes happen only during playback (probe events), the same exposure window
as legacy; the store-if-changed guard keeps the settings-dialog hazard
surface identical (see CLAUDE.md's settings-state doctrine).

Pure app layer: no Kodi imports; settings access via the injected facade.
"""

from resources.lib.aom.app import events


class PlatformRecorder:
    def __init__(self, dispatcher, settings_facade, *, log_debug):
        self._settings = settings_facade
        self._log = log_debug
        self._new_install = settings_facade.is_new_install()
        dispatcher.subscribe(events.StreamProbed, self._on_probed)

    def _on_probed(self, event):
        self._settings.store_boolean_if_changed('platform_hdr_full',
                                                event.platform_hdr_full)
        self._settings.store_boolean_if_changed('advanced_hlg',
                                                event.advanced_hlg)
        if self._new_install:
            self._new_install = False
            self._settings.store_boolean_if_changed('new_install', False)
            self._log("AOM_PlatformRecorder: new-install flag cleared on "
                      "first playback")
