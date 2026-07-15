"""Seek-back scheduling: the quiet-window policy, enforced by rescheduling.

Replaces SeekBacks' six interacting guards (PM4K busy check, 2.5s
recently-busy window, 6s wait-for-idle loop, 2.5s recent-Kodi-seek window,
per-event debounce, mandatory 2s settle sleep) with ONE rule, decided by the
pure ``policies.seek_decision`` and enforced by ``ExecuteSeek`` events that
re-check every 0.5s instead of blocking the dispatcher:

    Do not seek until there has been no seek activity — ours, another
    addon's, or the user's — for QUIET_WINDOW seconds. Defer by
    rescheduling. Give up DEADLINE seconds after the request.

Behavior mapping from legacy SeekBacks (parity unless noted):

- Triggers: PlaybackStarted -> 'resume'; Resumed -> 'unpause' (and the
  session paused flag lives here now); a change-announcing StreamStabilized
  (after the per-session startup latch) -> 'adjust'; USER_ADJUSTMENT
  (legacy bus, wired by the runtime — MIGRATION(p6): the typed
  UserOffsetSaved replaces it when the adjustment watcher lands) -> 'change'.
- Per-reason trigger debounce: a trigger within DEBOUNCE_SECONDS of that
  reason's last EXECUTED seek is dropped (legacy seek_history semantics);
  a re-trigger while the same reason is still pending key-replaces the
  pending attempt (storms collapse structurally).
- Cross-type suppression: a request that one of our own seeks has already
  served (executed after the request was made) is abandoned by the policy —
  the legacy cross-type cooldown, without dropping genuine later triggers.
- The legacy mandatory 2s settle falls out of session-start-as-activity:
  QUIET_WINDOW from ``session.started_at`` reproduces it.
- Seeks execute only when the session is STABLE (replacing the settle sleep
  with the stream-state machine; new for 'unpause'/'change' — a seek during
  renegotiation now waits for stability instead of firing blind).
- Pause cancels: a pending seek firing while paused is abandoned.
- Stale requests are inert: ExecuteSeek is session-stamped, pending state is
  session-checked, and stop/end cancels the timers — the legacy
  stop+autostart edge (a settling seek firing into a newly-started item)
  is structurally impossible.

``ExternalSeekCoordinator`` owns the vendor knowledge as DATA (PM4K's two
busy properties today; the next seek-happy addon is a list entry) plus the
reciprocity signal: while we execute a seek, our own home-window property
``script.audiooffsetmanager.seeking`` is set to '1' so other addons can
extend us the courtesy we extend PM4K. Its busy-recency timestamp is
deliberately cross-session (vendor seeks span in-place reopens — legacy
``_last_pm4k_busy`` parity).

Pure app layer: Kodi I/O through the injected gateway, settings through the
injected facade, log sinks injected; no Kodi imports.
"""

import time

from resources.lib.aom.app import events
from resources.lib.aom.domain import policies
from resources.lib.aom.domain.stream_state import StreamState


class ExternalSeekCoordinator:
    """One quiet-window activity view over all seek-activity signals."""

    # Vendor busy signals as data: home-window properties that read '1'
    # while that addon is running its own seeks.
    VENDOR_BUSY_PROPERTIES = (
        'script.plex.playback_seeking',
        'script.plex.playback_initializing',
    )
    RECIPROCAL_PROPERTY = 'script.audiooffsetmanager.seeking'

    def __init__(self, gateway, clock=time.monotonic, *, log_debug):
        self._gateway = gateway
        self._clock = clock
        self._log = log_debug
        # Cross-session on purpose (see module docstring). None = never seen.
        self._last_vendor_busy = None

    def vendor_busy(self):
        """Probe the vendor list; a busy vendor also counts as activity."""
        for name in self.VENDOR_BUSY_PROPERTIES:
            if self._gateway.window_property(name) == '1':
                self._last_vendor_busy = self._clock()
                self._log(f"AOM_SeekCoordinator: {name} indicates seek "
                          f"activity; deferring")
                return True
        return False

    def last_activity(self, session):
        """Most recent seek-like activity relevant to this session.

        Session start counts as activity (reproducing the legacy post-start
        settle); SeekOccurred and our own executed seeks feed
        ``session.last_seek_activity``; vendor busy sightings are
        coordinator-wide (they outlive sessions).
        """
        candidates = [session.started_at]
        if session.last_seek_activity is not None:
            candidates.append(session.last_seek_activity)
        if self._last_vendor_busy is not None:
            candidates.append(self._last_vendor_busy)
        return max(candidates)

    def execute_seek(self, seconds, player_id):
        """Run one seek with the reciprocity property set around it."""
        self._gateway.set_window_property(self.RECIPROCAL_PROPERTY, '1')
        try:
            return self._gateway.seek_back(seconds, player_id=player_id)
        finally:
            self._gateway.clear_window_property(self.RECIPROCAL_PROPERTY)


class SeekScheduler:
    """Plans seeks on triggering events; executes only when STABLE + quiet."""

    QUIET_WINDOW_SECONDS = 2.0
    DEADLINE_SECONDS = 8.0
    RECHECK_SECONDS = 0.5
    DEBOUNCE_SECONDS = 2.0

    def __init__(self, dispatcher, session_tracker, settings_facade,
                 coordinator, clock=time.monotonic, *, log_debug):
        self._dispatcher = dispatcher
        self._sessions = session_tracker
        self._settings = settings_facade
        self._coordinator = coordinator
        self._clock = clock
        self._log = log_debug
        # Pending requests: reason -> (session_id, requested_at). Component-
        # local like the detector's discovery bookkeeping: entries are
        # session-stamped (stale fires are dropped) and cleared on
        # stop/end/supersede, so session turnover resets them for free.
        self._pending = {}

        dispatcher.subscribe(events.PlaybackStarted, self._on_playback_started)
        dispatcher.subscribe(events.Paused, self._on_paused)
        dispatcher.subscribe(events.Resumed, self._on_resumed)
        dispatcher.subscribe(events.SeekOccurred, self._on_seek_occurred)
        dispatcher.subscribe(events.StreamStabilized, self._on_stream_stabilized)
        dispatcher.subscribe(events.ExecuteSeek, self._on_execute_seek)
        dispatcher.subscribe(events.PlaybackStopped, self._on_playback_ended)
        dispatcher.subscribe(events.PlaybackEnded, self._on_playback_ended)

    # -- triggers (dispatcher thread) -------------------------------------------

    def _on_playback_started(self, _event):
        session = self._sessions.current
        if session is None:
            return
        # Fresh session: pending entries from a superseded one are stale.
        self._cancel_all_pending()
        self._request('resume', session)

    def _on_paused(self, _event):
        session = self._sessions.current
        if session is not None:
            session.paused = True

    def _on_resumed(self, _event):
        session = self._sessions.current
        if session is None:
            return
        session.paused = False
        self._request('unpause', session)

    def _on_seek_occurred(self, _event):
        session = self._sessions.current
        if session is not None:
            session.last_seek_activity = self._clock()

    def _on_stream_stabilized(self, event):
        if not self._sessions.is_alive(event.session_id):
            return
        if not event.profile_changed:
            return  # pure re-confirmation: nothing changed, nothing to replay
        session = self._sessions.current
        if not session.initial_av_change_consumed:
            # The session's first change-announcing stabilization is startup
            # settling, not an adjustment (legacy latch semantics; unified
            # with the state machine when the adjustment watcher lands).
            session.initial_av_change_consumed = True
            self._log("AOM_SeekScheduler: Skipping initial AV change (startup)")
            return
        self._request('adjust', session)

    def on_user_adjustment(self):
        """Legacy-bus USER_ADJUSTMENT trigger (runtime-wired, MIGRATION(p6))."""
        session = self._sessions.current
        if session is None:
            return
        self._request('change', session)

    def _on_playback_ended(self, _event):
        self._cancel_all_pending()

    # -- execution ---------------------------------------------------------------

    def _on_execute_seek(self, event):
        if not self._sessions.is_alive(event.session_id):
            return
        pending = self._pending.get(event.reason)
        if pending is None or pending[0] != event.session_id:
            return  # superseded request
        session = self._sessions.current
        _, requested_at = pending

        if session.paused:
            # Pause cancels: replaying into a paused player is pointless and
            # the seek would fire on unpause anyway (its own trigger).
            self._log(f"AOM_SeekScheduler: Playback is paused; cancelling "
                      f"{event.reason} seek back")
            del self._pending[event.reason]
            return

        enabled, seek_seconds = self._settings.seek_back_config(event.reason)
        if not enabled or seek_seconds <= 0:
            self._log(f"AOM_SeekScheduler: Seek back on {event.reason} is "
                      f"not enabled (or has no length); cancelling")
            del self._pending[event.reason]
            return

        now = self._clock()
        if session.stream_state is not StreamState.STABLE:
            # Stability replaces the legacy settle sleep; the deadline still
            # bounds a stream that never stabilizes.
            self._defer_or_abandon(event, now, requested_at,
                                   why='stream not stable yet')
            return

        if self._coordinator.vendor_busy():
            self._defer_or_abandon(event, now, requested_at,
                                   why='vendor busy')
            return

        last_own_seek = max(session.seek_history.values(), default=None)
        decision = policies.seek_decision(
            now=now,
            requested_at=requested_at,
            last_activity=self._coordinator.last_activity(session),
            last_own_seek=last_own_seek,
            quiet_window=self.QUIET_WINDOW_SECONDS,
            deadline=self.DEADLINE_SECONDS)

        if decision == 'defer':
            self._reschedule(event)
            return
        if decision == 'abandon':
            self._log(f"AOM_SeekScheduler: Abandoning {event.reason} seek "
                      f"back (already served or deadline passed)")
            del self._pending[event.reason]
            return

        self._log(f"AOM_SeekScheduler: Seeking back {seek_seconds} seconds "
                  f"on {event.reason}")
        success = self._coordinator.execute_seek(
            seek_seconds, session.profile.player_id)
        if success:
            executed_at = self._clock()
            session.seek_history[event.reason] = executed_at
            session.last_seek_activity = executed_at
        else:
            self._log(f"AOM_SeekScheduler: Seek back failed on "
                      f"{event.reason}")
        del self._pending[event.reason]

    # -- internals ----------------------------------------------------------------

    def _request(self, reason, session):
        now = self._clock()
        last_executed = session.seek_history.get(reason)
        if last_executed is not None and \
                now - last_executed < self.DEBOUNCE_SECONDS:
            self._log(f"AOM_SeekScheduler: Skipping {reason} seek back - "
                      f"too soon after the previous one")
            return
        # A re-trigger while pending key-replaces the attempt chain and
        # restarts the deadline (the newest user action is the one served).
        self._pending[reason] = (session.session_id, now)
        self._dispatcher.schedule(
            0.0,
            events.ExecuteSeek(session_id=session.session_id, reason=reason,
                               attempt=1),
            key=self._key(reason))

    def _defer_or_abandon(self, event, now, requested_at, why):
        if now - requested_at >= self.DEADLINE_SECONDS:
            self._log(f"AOM_SeekScheduler: Abandoning {event.reason} seek "
                      f"back after {self.DEADLINE_SECONDS}s ({why})")
            del self._pending[event.reason]
            return
        self._log(f"AOM_SeekScheduler: Deferring {event.reason} seek back "
                  f"({why})")
        self._reschedule(event)

    def _reschedule(self, event):
        self._dispatcher.schedule(
            self.RECHECK_SECONDS,
            events.ExecuteSeek(session_id=event.session_id,
                               reason=event.reason,
                               attempt=event.attempt + 1),
            key=self._key(event.reason))

    def _cancel_all_pending(self):
        for reason in list(self._pending):
            self._dispatcher.cancel(self._key(reason))
        self._pending.clear()

    @staticmethod
    def _key(reason):
        return f'aom.seek.{reason}'
