"""Seek backs module submits player seek commands based on playback events.

Per-playback state (paused flag, per-event seek debounce, last seek activity,
startup-change skip) lives on the PlaybackSession — a new session IS the
reset, so this module keeps no per-playback state of its own. The PM4K
busy-recency timestamp deliberately stays on the instance: PM4K's own seeks
span in-place reopens, so its grace window must survive session turnover.

All interval math uses time.monotonic (wall-clock changes must not distort
debounce windows).
"""

import xbmc
import time
from resources.lib import rpc_client
from resources.lib.logger import log


class SeekBacks:
    def __init__(self, event_manager, settings_manager, settings_facade,
                 session_tracker):
        self.event_manager = event_manager
        self.settings_manager = settings_manager
        self.settings_facade = settings_facade
        self.sessions = session_tracker
        # Cross-session on purpose (see module docstring). None = never seen
        # busy (0.0 would be a wrong sentinel for the arbitrary-epoch
        # monotonic clock).
        self._last_pm4k_busy = None
        self._events = {
            'AV_STARTED': self.on_av_started,
            'ON_AV_CHANGE': self.on_av_change,
            'PLAYBACK_RESUMED': self.on_av_unpause,
            'PLAYBACK_PAUSED': self.on_playback_paused,
            'USER_ADJUSTMENT': self.on_user_adjustment,
            'PLAYBACK_SEEK': self.on_playback_seek,
        }

    def start(self):
        """Start the seek backs module by subscribing to relevant events."""
        for event, callback in self._events.items():
            self.event_manager.subscribe(event, callback)

    def stop(self):
        """Stop the seek backs module and clean up subscriptions."""
        for event, callback in self._events.items():
            self.event_manager.unsubscribe(event, callback)

    def on_av_started(self):
        """Handle AV started event (fresh session carries fresh state)."""
        session = self.sessions.current
        if session is None:
            return
        self.perform_seek_back('resume', session)

    def on_av_change(self):
        """Handle AV change event."""
        session = self.sessions.current
        if session is None:
            return
        if not session.initial_av_change_consumed:
            # Plain first-call latch: the session's first confirmed AV change
            # is startup settling, so no 'adjust' seek-back for it. (Only
            # incidentally aligned with the stream-state machine.)
            session.initial_av_change_consumed = True
            log("AOM_SeekBacks: Skipping initial AV change (startup)", xbmc.LOGDEBUG)
            return

        self.perform_seek_back('adjust', session)

    def on_av_unpause(self):
        """Handle playback resume event."""
        session = self.sessions.current
        if session is None:
            return
        session.paused = False
        self.perform_seek_back('unpause', session)

    def on_playback_paused(self):
        """Handle playback paused event."""
        session = self.sessions.current
        if session is not None:
            session.paused = True

    def on_playback_seek(self, *args, **kwargs):
        """Handle any Kodi seek (regardless of source)."""
        session = self.sessions.current
        if session is not None:
            session.last_seek_activity = time.monotonic()

    def on_user_adjustment(self):
        """Handle user adjustment event."""
        log("AOM_SeekBacks: Processing user adjustment event", xbmc.LOGDEBUG)
        session = self.sessions.current
        if session is None:
            return
        # Check if seek back is enabled for changes (user adjustments)
        enabled, _ = self.settings_facade.seek_back_config('change')
        if enabled:
            self.perform_seek_back('change', session)
        else:
            log("AOM_SeekBacks: Seek back for user adjustments is disabled", xbmc.LOGDEBUG)

    def _pm4k_playback_busy(self, log_if_busy=True):
        """Check Plex Mod 4 Kodi flags to avoid overlapping seeks.

        PM4K sets properties to '1' while it is running its own seeks. If PM4K
        is not installed, getInfoLabel returns the label string or empty, so we
        only treat an exact '1' as active.
        """
        plex_props = {
            'playback_seeking': xbmc.getInfoLabel('Window(10000).Property(script.plex.playback_seeking)'),
            'playback_initializing': xbmc.getInfoLabel('Window(10000).Property(script.plex.playback_initializing)')
        }

        for name, value in plex_props.items():
            if value == '1':
                self._last_pm4k_busy = time.monotonic()
                if log_if_busy:
                    log(f"AOM_SeekBacks: PM4K indicates {name}; deferring seek back", xbmc.LOGDEBUG)
                return True
        return False

    def _pm4k_recently_busy(self, grace_seconds=2.5):
        """Check if PM4K was busy recently to avoid back-to-back seeks."""
        if self._last_pm4k_busy is None:
            return False
        return (time.monotonic() - self._last_pm4k_busy) < grace_seconds

    def _wait_for_pm4k_idle(self, timeout=6.0):
        """Poll for PM4K to go idle so we can safely seek after startup."""
        monitor = xbmc.Monitor()
        end_time = time.monotonic() + timeout
        while time.monotonic() < end_time:
            if not self._pm4k_playback_busy(log_if_busy=False):
                return True
            if monitor.waitForAbort(0.1):
                return False
        log("AOM_SeekBacks: PM4K remained busy after waiting; skipping startup seek back", xbmc.LOGDEBUG)
        return False

    def _should_perform_seek_back(self, event_type, session,
                                  ignore_pm4k_recent=False,
                                  ignore_recent_kodi_seek=False):
        """Check if seek back should be performed based on current conditions.

        Returns:
            tuple: (should_seek, seek_seconds) or (False, None) if seek is not needed
        """
        # One seek back at a time, 2s cooldown across ALL trigger types. The
        # cross-type reach also restores the suppression the legacy
        # seek_in_progress flag provided: a different-type trigger landing
        # during a settle window would otherwise run back-to-back with the
        # first seek once dispatch serializes them.
        now = time.monotonic()
        last_own_seek = max(session.seek_history.values(), default=None)
        if last_own_seek is not None and now - last_own_seek < 2:
            log(f"AOM_SeekBacks: Skipping seek back on {event_type} - too soon "
                f"after the previous seek back", xbmc.LOGDEBUG)
            return False, None

        if session.paused:
            log(f"AOM_SeekBacks: Playback is paused, skipping seek back "
                f"on {event_type}", xbmc.LOGDEBUG)
            return False, None

        if self._pm4k_playback_busy():
            return False, None

        if not ignore_pm4k_recent and self._pm4k_recently_busy():
            log(f"AOM_SeekBacks: PM4K was busy moments ago; skipping seek back on {event_type}",
                xbmc.LOGDEBUG)
            return False, None

        if not ignore_recent_kodi_seek:
            if (event_type in ('unpause', 'resume')
                    and session.last_seek_activity is not None
                    and (now - session.last_seek_activity) < 2.5):
                log(f"AOM_SeekBacks: Recent Kodi seek detected; skipping {event_type} seek back to avoid double-seek",
                    xbmc.LOGDEBUG)
                return False, None

        enabled, seek_seconds = self.settings_facade.seek_back_config(event_type)
        if not enabled:
            log(f"AOM_SeekBacks: Seek back on {event_type} (setting: enable_seek_back_{event_type}) "
                f"is not enabled", xbmc.LOGDEBUG)
            return False, None

        if seek_seconds <= 0:
            log(f"AOM_SeekBacks: Invalid seek back seconds ({seek_seconds}) "
                f"for {event_type}", xbmc.LOGWARNING)
            return False, None

        return True, seek_seconds

    def _execute_seek_command(self, seconds, event_type, session):
        """Execute the JSON-RPC seek command.

        Returns:
            bool: True if seek was successful, False otherwise
        """
        log(f"AOM_SeekBacks: Attempting to seek back {seconds} seconds "
            f"on {event_type}", xbmc.LOGDEBUG)

        # Use active player id if available
        player_id = rpc_client.get_active_player_id()
        success = rpc_client.seek_back(seconds, player_id=player_id if player_id != -1 else None)
        if success:
            now = time.monotonic()
            session.seek_history[event_type] = now
            session.last_seek_activity = now
        return success

    def perform_seek_back(self, event_type, session):
        """Perform seek back operation based on event type and current conditions.

        Runs entirely on the dispatcher thread, so the session cannot change
        under us mid-settle (single-threaded dispatch); the legacy
        seek-in-progress reentrancy flag is gone because reentrancy is now
        structurally impossible.
        """
        try:
            ignore_pm4k_recent = False
            ignore_recent_kodi_seek = (event_type == 'resume')
            if event_type == 'resume' and self._pm4k_playback_busy(log_if_busy=False):
                log("AOM_SeekBacks: PM4K busy on startup; waiting before issuing seek back",
                    xbmc.LOGDEBUG)
                if not self._wait_for_pm4k_idle():
                    return
                ignore_pm4k_recent = True

            should_seek, seek_seconds = self._should_perform_seek_back(
                event_type, session,
                ignore_pm4k_recent=ignore_pm4k_recent,
                ignore_recent_kodi_seek=ignore_recent_kodi_seek)

            if not should_seek:
                return

            # Required delay for stream settling; abort-aware. Poll PM4K during this window
            # so we can skip if it was active shortly before we issue our seek.
            monitor = xbmc.Monitor()
            end_time = time.monotonic() + 2.0
            while time.monotonic() < end_time:
                # Capture brief PM4K activity without spamming logs
                self._pm4k_playback_busy(log_if_busy=False)
                if monitor.waitForAbort(0.1):
                    return

            # Re-check PM4K after settling to avoid double-seeks if it just ran
            if self._pm4k_playback_busy():
                return
            if not ignore_pm4k_recent and self._pm4k_recently_busy():
                log(f"AOM_SeekBacks: Skipping {event_type} seek back after settle due to recent PM4K activity",
                    xbmc.LOGDEBUG)
                return

            log(f"AOM_SeekBacks: Will seek back {seek_seconds} seconds on {event_type} "
                f"(setting: {event_type})", xbmc.LOGDEBUG)

            if not self._execute_seek_command(seek_seconds, event_type, session):
                log(f"AOM_SeekBacks: Seek back operation failed for {event_type}",
                    xbmc.LOGWARNING)

        except Exception as e:
            log(f"AOM_SeekBacks: Error in perform_seek_back: {str(e)}",
                xbmc.LOGERROR)
