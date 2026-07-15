"""User-facing offset notifications — the app-layer toast owner.

Replaces the legacy NotificationHandler AND the pending-notification dance
OffsetManager used to run inline (``_maybe_send_pending_notification`` plus the
provisional-suppression block in ``apply_audio_offset``). Everything about
"should a toast fire, and which message" now lives here, driven by typed
events on the dispatcher thread:

* ``OffsetApplied`` — an automatic apply. A provisional apply (the stream is
  not yet STABLE) does NOT toast; its message is HELD on
  ``session.pending_notification`` and released on the session's next
  ``StreamStabilized``. A non-provisional apply toasts immediately and clears
  any pending hold.
* ``StreamStabilized`` — releases a held provisional toast, but only if the
  profile still keys the same setting id it was held under: a profile that
  changed underneath drops the stale toast (settings-doctrine — never toast a
  stale key). The setting id is re-derived FRESH from ``session.profile`` at
  release time.
* ``UserOffsetSaved`` — a manual adjustment the AdjustmentWatcher stored.
  Toasts from the event's own profile/ms (captured at store time on the
  dispatcher thread); session/settings are deliberately NOT re-read.

Deferral-until-stable and the 1s duplicate-suppression window are both ported
from the legacy path. The dedupe clock is the injected ``time.monotonic`` — a
deliberate upgrade from the legacy ``time.time``, which mis-measured the
window across wall-clock adjustments.

Settings (``notifications_enabled`` / ``notification_duration_ms``) are read
through the injected facade; toasts go through the injected gui. Pure app
layer: stdlib + ``resources.lib.aom`` only.
"""

import time

from resources.lib.aom.app import events
from resources.lib.aom.domain.stream_state import StreamState

STRING_OFFSET_APPLIED = 32092
STRING_OFFSET_SAVED = 32093


class Notifier:
    """Owns offset toasts: deferral-until-stable and the 1s dedupe window."""

    DEDUPE_SECONDS = 1.0

    def __init__(self, dispatcher, session_tracker, settings, gui,
                 clock=time.monotonic, *, log_debug):
        self._sessions = session_tracker
        self._settings = settings
        self._gui = gui
        self._clock = clock
        self._log = log_debug
        # Dedupe state: (string_id, setting_id, ms) and its monotonic stamp.
        self._last_toast = None
        self._last_toast_at = None

        dispatcher.subscribe(events.OffsetApplied, self._on_offset_applied)
        dispatcher.subscribe(events.UserOffsetSaved, self._on_user_offset_saved)
        dispatcher.subscribe(events.StreamStabilized, self._on_stream_stabilized)

    # -- handlers (dispatcher thread) -------------------------------------------

    def _on_offset_applied(self, event):
        if not self._sessions.is_alive(event.session_id):
            return
        session = self._sessions.current
        if event.provisional:
            # Held until the stream stabilizes; the release path re-derives the
            # key from the live profile and drops the toast if it changed.
            session.pending_notification = (event.profile.setting_id(), event.ms)
            self._log("AOM_Notifier: holding provisional notification until "
                      "the stream stabilizes")
            return
        session.pending_notification = None
        self._toast(STRING_OFFSET_APPLIED, event.ms, event.profile)

    def _on_stream_stabilized(self, event):
        if not self._sessions.is_alive(event.session_id):
            return
        session = self._sessions.current
        if session.pending_notification is None:
            return
        # Defensive parity with the legacy release check: only release once the
        # session is genuinely STABLE.
        if session.stream_state is not StreamState.STABLE:
            return
        pending_setting_id, pending_ms = session.pending_notification
        # Read the profile FRESH: a profile that changed underneath must not
        # release a toast against a stale key (settings-doctrine).
        profile = session.profile
        if profile is None or pending_setting_id != profile.setting_id():
            session.pending_notification = None
            return
        session.pending_notification = None
        self._toast(STRING_OFFSET_APPLIED, pending_ms, profile)
        self._log("AOM_Notifier: Released pending offset notification after "
                  "stream stabilization")

    def _on_user_offset_saved(self, event):
        if not self._sessions.is_alive(event.session_id):
            return
        # The payload is the profile/ms captured at store time by the watcher;
        # do NOT re-read session/settings for the message.
        self._toast(STRING_OFFSET_SAVED, event.ms, event.profile)

    # -- internals --------------------------------------------------------------

    def _toast(self, string_id, ms, profile):
        if not self._settings.notifications_enabled():
            return

        now = self._clock()
        key = (string_id, profile.setting_id(), ms)
        if key == self._last_toast and self._last_toast_at is not None \
                and now - self._last_toast_at < self.DEDUPE_SECONDS:
            return

        sign = '+' if ms > 0 else ''
        message = (f"{self._gui.localized(string_id)}: {sign}{ms} ms\n"
                   f"{profile.summary(include_fps=True)}")

        self._gui.notification(message, self._settings.notification_duration_ms())
        self._log(f"AOM_Notifier: {message}")
        self._last_toast = key
        self._last_toast_at = now
