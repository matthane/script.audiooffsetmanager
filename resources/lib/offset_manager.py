"""Offset manager module to receive playback events and assign audio offsets as needed.
This module also controls the deployment of the Active Monitor when it's enabled.
"""

import xbmc
from resources.lib.active_monitor import ActiveMonitor
from resources.lib.aom.domain import formats, policies
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
        self.active_monitor = None
        self._monitor_session_id = None
        self._events = {
            'AV_STARTED': self.on_av_started,
            'ON_AV_CHANGE': self.on_av_change,
            'PLAYBACK_STOPPED': self.on_playback_stopped,
            'PLAYBACK_ENDED': self.on_playback_stopped,
            'USER_ADJUSTMENT': self.on_user_adjustment
        }

    def start(self):
        """Start the offset manager by subscribing to relevant events."""
        for event, callback in self._events.items():
            self.event_manager.subscribe(event, callback)

    def stop(self):
        """Stop the offset manager and clean up subscriptions."""
        for event, callback in self._events.items():
            self.event_manager.unsubscribe(event, callback)
        self.stop_active_monitor()

    def on_av_started(self):
        """Handle AV started event (per-playback resets are session-borne)."""
        self._handle_av_event()

    def on_av_change(self):
        """Handle AV change event."""
        self._handle_av_event()

    def on_playback_stopped(self):
        """Handle playback stopped event."""
        self.stream_info.clear_stream_info()
        self.stop_active_monitor()
        
    def on_user_adjustment(self):
        """Handle user adjustment event (manual offset change)."""
        # Only send notification if active monitor is enabled
        if self.active_monitor is not None and self.stream_info.profile is not None:
            # Get the current audio delay from settings
            profile = self.stream_info.profile
            delay_ms = self.settings_manager.get_setting_integer(profile.setting_id())

            # Send notification about the manual offset change
            self.notification_handler.notify_manual_offset_saved(delay_ms, profile)
            log(f"AOM_OffsetManager: Notified user about manual offset change to {delay_ms}ms",
                xbmc.LOGDEBUG)
            log_snapshot("USER_ADJUST", self.stream_info, self.settings_facade, extra={"delay_ms": delay_ms})

    def _handle_av_event(self):
        """Common handler for AV-related events."""
        session = self.sessions.current
        if session is None:
            log("AOM_OffsetManager: no active session; ignoring AV event",
                xbmc.LOGDEBUG)
            return
        self.stream_info.update_stream_info()
        # session.profile stays unwritten during the migration (the live
        # profile is stream_info.profile; a session mirror could diverge).
        if policies.is_complete(self.stream_info.profile):
            session.mark_profile_built()
        self.apply_audio_offset(session)
        log_snapshot("AV_EVENT", self.stream_info, self.settings_facade)
        self.manage_active_monitor(session)

    def _should_apply_offset(self):
        """Check if audio offset should be applied based on current conditions.

        The decision itself lives in aom.domain.policies.should_apply (single
        source of truth); this method resolves the inputs and logs the reason.
        """
        profile = self.stream_info.profile
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
        """Apply audio offset based on current stream information and settings."""
        try:
            if not self._should_apply_offset():
                return

            profile = self.stream_info.profile
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

                self.set_audio_delay(profile.player_id, delay_ms / 1000.0,
                                     notify=not suppress_notification)
                session.applied = (setting_id, delay_ms)
                if not suppress_notification:
                    self._maybe_send_pending_notification(session, profile)
            else:
                log("AOM_OffsetManager: No valid player ID found to set "
                    "audio delay", xbmc.LOGDEBUG)

        except Exception as e:
            log(f"AOM_OffsetManager: Error applying audio offset: {str(e)}",
                xbmc.LOGERROR)

    def set_audio_delay(self, player_id, delay_seconds, notify=True):
        """Set the audio delay using JSON-RPC."""
        success = rpc_client.set_audio_delay(player_id, delay_seconds)
        if success:
            # Convert seconds to milliseconds for notification
            delay_ms = int(delay_seconds * 1000)

            # Send notification for automatic offset application
            # This is only called for automatic offset application (not manual adjustments)
            if self.stream_info.profile is not None:
                if notify:
                    self.notification_handler.notify_audio_offset_applied(delay_ms, self.stream_info.profile)
                log_snapshot("APPLY_OFFSET", self.stream_info, self.settings_facade,
                             extra={"delay_ms": delay_ms, "notified": notify})

    def _should_start_active_monitor(self):
        """Determine if active monitor should be started based on current conditions.

        Deliberately a PARTIAL unknown-check (hdr + fps, not audio): the
        monitor may run while audio is unknown; its own write path
        re-validates the full profile before storing anything.
        """
        profile = self.stream_info.profile
        if profile is None:
            return False

        active_monitoring_enabled = self.settings_manager.get_setting_boolean('enable_active_monitoring')
        hdr_type = profile.hdr_type
        fps_type = profile.fps_type
        hdr_type_enabled = self.settings_manager.get_setting_boolean(f'enable_{hdr_type}')

        return (active_monitoring_enabled and
                hdr_type_enabled and
                hdr_type != formats.UNKNOWN and
                fps_type != formats.UNKNOWN)

    def manage_active_monitor(self, session):
        """Manage the active monitor state based on current conditions."""
        log(f"AOM_OffsetManager: Checking active monitor status - "
            f"HDR: {self.stream_info.profile.hdr_type if self.stream_info.profile else 'unknown'}, "
            f"FPS: {self.stream_info.profile.fps_type if self.stream_info.profile else 'unknown'}",
            xbmc.LOGDEBUG)

        if (self.active_monitor is not None
                and self._monitor_session_id != session.session_id):
            # In-place reopen: the running monitor's tracked delays belong to
            # a superseded session — never let them leak into this one.
            log("AOM_OffsetManager: Active monitor belongs to superseded "
                f"session #{self._monitor_session_id}; restarting", xbmc.LOGDEBUG)
            self.stop_active_monitor()

        if self._should_start_active_monitor():
            self.start_active_monitor(session)
        else:
            self.stop_active_monitor()

    def _maybe_send_pending_notification(self, session, profile):
        """Send the session's pending notification once the stream is STABLE.

        `profile` MUST be freshly derived by the caller (read from
        stream_info immediately after update_stream_info) — passing a
        profile captured during an earlier event would release/drop the
        pending toast against a stale key (settings-doctrine hazard).
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

    def start_active_monitor(self, session):
        """Start the active monitor if it's not already running."""
        if self.active_monitor is None:
            self.active_monitor = ActiveMonitor(
                self.event_manager,
                self.stream_info,
                self,
                self.settings_manager
            )
            self.active_monitor.start()
            self._monitor_session_id = session.session_id
            log("AOM_OffsetManager: Active monitor started", xbmc.LOGDEBUG)

    def stop_active_monitor(self):
        """Stop the active monitor if it's running."""
        if self.active_monitor is not None:
            self.active_monitor.stop()
            self.active_monitor = None
            self._monitor_session_id = None
            log("AOM_OffsetManager: Active monitor stopped", xbmc.LOGDEBUG)
