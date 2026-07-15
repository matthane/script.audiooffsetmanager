"""Offset manager module to receive playback events and assign audio offsets as needed.

Detection is the StreamDetector's job: the profile is read from the current
PlaybackSession (the detector is its sole writer), always freshly at the
moment of use — never captured across events. The injected ``stream_info``
is the MIGRATION(p7) session-backed shim, kept only for the debug snapshot;
this module's own decisions read ``session.profile``. Manual-adjustment
detection is the AdjustmentWatcher's job: this module only consumes its
typed, session-stamped ``UserOffsetSaved`` (runtime-wired) to notify.
"""

import xbmc
from resources.lib.aom.domain import policies
from resources.lib.aom.domain.stream_state import StreamState
from resources.lib import rpc_client
from resources.lib.logger import log
from resources.lib.debug_snapshot import log_snapshot


class OffsetManager:
    def __init__(self, event_manager, settings_manager, stream_info,
                 notification_handler, settings_facade, session_tracker):
        self.event_manager = event_manager
        self.settings_manager = settings_manager
        self.settings_facade = settings_facade
        self.stream_info = stream_info
        self.notification_handler = notification_handler
        self.sessions = session_tracker
        self._events = {
            'AV_STARTED': self.on_av_started,
            'PROFILE_CHANGED': self.on_profile_changed,
            'ON_AV_CHANGE': self.on_av_change,
        }

    def start(self):
        """Start the offset manager by subscribing to relevant events."""
        for event, callback in self._events.items():
            self.event_manager.subscribe(event, callback)

    def stop(self):
        """Stop the offset manager and clean up subscriptions."""
        for event, callback in self._events.items():
            self.event_manager.unsubscribe(event, callback)

    def on_av_started(self):
        """Handle AV started event (per-playback resets are session-borne).

        The profile is still None here — the detector's first probe hasn't
        run — so this is a skip pass; kept for legacy log/flow parity.
        MIGRATION(p7): the real apply trigger is PROFILE_CHANGED; the typed
        rebuild must NOT wire PlaybackStarted -> apply.
        """
        self._handle_av_event()

    def on_profile_changed(self):
        """Handle the detector adopting a (new) profile: the apply trigger."""
        self._handle_av_event()

    def on_av_change(self):
        """Handle the legacy stream-settled event (releases notifications)."""
        self._handle_av_event()

    def on_user_offset_saved(self, event):
        """Notify for a manual offset the AdjustmentWatcher stored.

        Runtime-wired to the typed ``UserOffsetSaved`` (MIGRATION(p7): moves
        to the Notifier). The profile/ms ride on the event as captured at
        store time, so the toast always describes exactly what was stored —
        the legacy USER_ADJUSTMENT wire re-read the live profile and settings
        instead, so a reopen between store and dispatch could describe the
        wrong stream; the session stamp now drops that case outright. The
        legacy "only when the monitor is running" gate is inherent: the event
        exists only because the watcher (which enforces eligibility) stored.
        """
        if not self.sessions.is_alive(event.session_id):
            log(f"AOM_OffsetManager: dropping manual-offset notification for "
                f"superseded session #{event.session_id}", xbmc.LOGDEBUG)
            return
        self.notification_handler.notify_manual_offset_saved(event.ms, event.profile)
        log(f"AOM_OffsetManager: Notified user about manual offset change to {event.ms}ms",
            xbmc.LOGDEBUG)
        log_snapshot("USER_ADJUST", self.stream_info, self.settings_facade, extra={"delay_ms": event.ms})

    def _handle_av_event(self):
        """Common handler for AV-related events."""
        session = self.sessions.current
        if session is None:
            log("AOM_OffsetManager: no active session; ignoring AV event",
                xbmc.LOGDEBUG)
            return
        self.apply_audio_offset(session)
        log_snapshot("AV_EVENT", self.stream_info, self.settings_facade)

    def _should_apply_offset(self, profile):
        """Check if audio offset should be applied based on current conditions.

        The decision itself lives in aom.domain.policies.should_apply (single
        source of truth); this method resolves the inputs and logs the reason.
        """
        hdr_enabled = (profile is not None and
                       self.settings_facade.is_hdr_enabled(profile.hdr_type))
        allowed, reason = policies.should_apply(
            profile,
            new_install=self.settings_facade.is_new_install(),
            hdr_enabled=hdr_enabled)
        if allowed:
            return True

        if reason == 'new_install':
            log("AOM_OffsetManager: New install detected. Skipping "
                "audio offset application.", xbmc.LOGDEBUG)
        elif reason == 'no_profile':
            log("AOM_OffsetManager: No stream profile available; skipping offset", xbmc.LOGDEBUG)
        elif reason == 'unknown_format':
            log(f"AOM_OffsetManager: Skipping audio offset - Unknown format detected "
                f"(HDR: {profile.hdr_type}, Audio: {profile.audio_format}, "
                f"FPS: {profile.fps_type})", xbmc.LOGDEBUG)
        elif reason == 'hdr_disabled':
            log(f"AOM_OffsetManager: HDR type {profile.hdr_type} is not "
                f"enabled in settings", xbmc.LOGDEBUG)
        return False

    def apply_audio_offset(self, session):
        """Apply audio offset for the session's current profile and settings."""
        try:
            # Freshly derived at the moment of use: the detector is the sole
            # writer of session.profile, on this same dispatcher thread.
            profile = session.profile
            if not self._should_apply_offset(profile):
                return

            setting_id = profile.setting_id()
            delay_ms = self.settings_facade.get_offset_ms(profile)

            if delay_ms is None:
                log(f"AOM_OffsetManager: No audio delay found for setting ID: {setting_id}",
                    xbmc.LOGDEBUG)
                return

            already_applied = session.applied == (setting_id, delay_ms)

            if already_applied:
                log(f"AOM_OffsetManager: Offset already applied for {setting_id} at {delay_ms}ms; skipping duplicate apply",
                    xbmc.LOGDEBUG)
                self._maybe_send_pending_notification(session, profile)
                return

            if profile.player_id != -1:
                # Provisional until the stream stabilizes: the notification is
                # held on the session and released on the STABLE transition
                # (which precedes ON_AV_CHANGE delivery by queue order).
                suppress_notification = session.stream_state is not StreamState.STABLE
                if suppress_notification:
                    session.pending_notification = (setting_id, delay_ms)
                    log("AOM_OffsetManager: Suppressing notification until stream stabilizes",
                        xbmc.LOGDEBUG)
                else:
                    session.pending_notification = None

                # Bookkeeping BEFORE the RPC (DESIGN: AdjustmentWatcher
                # self-echo): the moment Kodi's delay can reflect our write,
                # session.applied already equals it, so the watcher can never
                # misread our own apply as a user adjustment. Restored on
                # failure — recording a failed apply would let the dedupe
                # guard block every retry for the rest of the session.
                previous_applied = session.applied
                session.applied = (setting_id, delay_ms)
                success = self.set_audio_delay(
                    profile.player_id, delay_ms / 1000.0, profile,
                    notify=not suppress_notification)
                if not success:
                    session.applied = previous_applied
                    log(f"AOM_OffsetManager: audio delay RPC failed for "
                        f"{setting_id}; will retry on the next AV event",
                        xbmc.LOGWARNING)
            else:
                log("AOM_OffsetManager: No valid player ID found to set "
                    "audio delay", xbmc.LOGDEBUG)

        except Exception as e:
            log(f"AOM_OffsetManager: Error applying audio offset: {str(e)}",
                xbmc.LOGERROR)

    def set_audio_delay(self, player_id, delay_seconds, profile, notify=True):
        """Set the audio delay using JSON-RPC; returns True on success.

        `profile` is the caller's freshly-read session profile — passed in so
        the notification is keyed to the exact profile the apply decision used.
        """
        success = rpc_client.set_audio_delay(player_id, delay_seconds)
        if success:
            # round(), not int(): the seconds value is a float round-trip of
            # an integer ms offset, and truncation would display 29ms as 28.
            delay_ms = int(round(delay_seconds * 1000))

            # Send notification for automatic offset application
            # This is only called for automatic offset application (not manual adjustments)
            if notify:
                self.notification_handler.notify_audio_offset_applied(delay_ms, profile)
            log_snapshot("APPLY_OFFSET", self.stream_info, self.settings_facade,
                         extra={"delay_ms": delay_ms, "notified": notify})
        return success

    def _maybe_send_pending_notification(self, session, profile):
        """Send the session's pending notification once the stream is STABLE.

        `profile` MUST be freshly read by the caller (session.profile at the
        moment of the event) — passing a profile captured during an earlier
        event would release/drop the pending toast against a stale key
        (settings-doctrine hazard).
        """
        if session.pending_notification is None:
            return

        if session.stream_state is not StreamState.STABLE:
            return

        pending_setting_id, pending_delay_ms = session.pending_notification
        if pending_setting_id != profile.setting_id():
            # Profile changed; drop pending notification
            session.pending_notification = None
            return

        self.notification_handler.notify_audio_offset_applied(pending_delay_ms, profile)
        log("AOM_OffsetManager: Released pending offset notification after stream stabilization",
            xbmc.LOGDEBUG)
        session.pending_notification = None
