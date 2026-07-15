"""Playback sessions: one object owns ALL per-playback state.

A ``PlaybackSession`` is created on ``PlaybackStarted`` and destroyed on
stop/end. A new playback while one is live (in-place reopen) tears the old
session down and starts a fresh one — so "reset logic" does not exist: a new
session IS the reset, and anything still referencing the old ``session_id``
is inert by construction.

``SessionTracker`` owns the current session and its lifecycle. Its
``PlaybackStarted``/``PlaybackStopped``/``PlaybackEnded`` handlers must be
subscribed BEFORE any component that reads the session for the same events
(the runtime constructs it first, and dispatcher dispatch follows
subscription order; tests/contract pin this). Note the stop/end ordering
consequence: by the time other PLAYBACK_STOPPED/ENDED handlers run, the
session is already gone — the ending session is deliberately not exposed.

Stream-state transitions go through the ``mark_*`` methods so the legal
diagram (see aom.domain.stream_state) lives in ONE place; illegal requests
are ignored and reported via the return value instead of corrupting state.

Pure Python: no Kodi imports; logging callables are injected.
"""

import time
from dataclasses import dataclass, field
from typing import Optional

from resources.lib.aom.app import events
from resources.lib.aom.domain.stream_state import StreamState


def _noop(_message):
    return None


@dataclass
class PlaybackSession:
    session_id: int
    # Monotonic session birth time. No consumer during Phase 3; becomes the
    # seek quiet-window's "session start counts as seek activity" input when
    # the seek scheduler lands (DESIGN: ExternalSeekCoordinator).
    started_at: float
    stream_state: StreamState = StreamState.STARTING
    # The session's profile. Written ONLY by the StreamDetector (its sole
    # writer), on the dispatcher thread; read cross-thread by ActiveMonitor
    # through the StreamInfo shim (an atomic reference read of a frozen
    # dataclass — no partial states are observable).
    profile: object = None
    # True while a profile (re)adoption has happened since the last
    # StreamStabilized post. The detector consumes it to stamp
    # StreamStabilized.profile_changed, which the router uses to suppress
    # the legacy ON_AV_CHANGE for pure re-confirmations (a codec blip that
    # reverted) — legacy's duplicate-codec filter never fired for those.
    profile_changed_since_stabilized: bool = False
    applied: tuple = None                   # (setting_key, delay_ms) dedupe guard
    pending_notification: tuple = None      # (setting_key, delay_ms) awaiting STABLE
    paused: bool = False
    # How many times this session has earned STABLE. Written only by
    # mark_stable() (the diagram's one edge into STABLE); the detector stamps
    # StreamStabilized.initial from it, which replaced the scheduler's
    # startup-skip latch (initial_av_change_consumed) — the "is this startup
    # settling?" question is now answered by the state machine itself.
    stabilized_count: int = 0
    # Monotonic timestamps; None = never (a 0.0 sentinel would be wrong for
    # monotonic clocks, whose epoch is arbitrary).
    last_seek_activity: Optional[float] = None
    seek_history: dict = field(default_factory=dict)  # reason -> monotonic ts
    # AdjustmentWatcher observation state. The baseline is the last delay
    # value accounted for (ours, or already stored): only a CHANGE away from
    # it can become a user adjustment, so a pre-existing delay the watcher
    # first observes (e.g. left behind by a failed apply RPC) is adopted
    # silently, never stored. watch_pending is the quiescence candidate:
    # (observed_ms, first_seen_monotonic).
    watch_baseline_ms: Optional[int] = None
    watch_pending: tuple = None

    # -- stream-state transitions (the only sanctioned writers) ---------------

    def mark_profile_built(self):
        """STARTING -> STABILIZING once a complete profile exists."""
        if self.stream_state is StreamState.STARTING:
            self.stream_state = StreamState.STABILIZING
            return True
        return False

    def mark_verifying(self):
        """Any state -> STABILIZING: a codec verification is now pending."""
        changed = self.stream_state is not StreamState.STABILIZING
        self.stream_state = StreamState.STABILIZING
        return changed

    def mark_stable(self):
        """STABILIZING -> STABLE (the diagram's only edge into STABLE).

        A confirmation landing on STARTING means no verification was ever
        requested for this session — refuse rather than jump states; the
        caller logs it. Returns True when the transition happened. A failed
        verification no longer strands STABILIZING: the StreamDetector
        re-schedules verification until the profile settles (the recovery
        edge).
        """
        if self.stream_state is StreamState.STABILIZING:
            self.stream_state = StreamState.STABLE
            self.stabilized_count += 1
            return True
        return self.stream_state is StreamState.STABLE


class SessionTracker:
    """Owns the current PlaybackSession; allocates monotonically rising ids."""

    def __init__(self, dispatcher, clock=time.monotonic, log_debug=None):
        self._clock = clock
        self._log = log_debug or _noop
        self.current = None
        self._next_id = 1
        dispatcher.subscribe(events.PlaybackStarted, self._on_started)
        dispatcher.subscribe(events.PlaybackStopped, self._on_ended)
        dispatcher.subscribe(events.PlaybackEnded, self._on_ended)
        # The tracker owns generic session state, so the paused flag is
        # written here (not by whichever consumer happens to need it) —
        # subscription order guarantees it is current before any other
        # handler of the same event reads it.
        dispatcher.subscribe(events.Paused, self._on_paused)
        dispatcher.subscribe(events.Resumed, self._on_resumed)

    def is_alive(self, session_id):
        """True while the given session is still the live one.

        All remaining callers run on the dispatcher thread (the deleted
        AvChangeFilter verify thread was the cross-thread caller; today the
        only cross-thread READER of session state is the StreamInfo shim's
        profile property). The single read of self.current is kept: it is
        free, and it makes the method safe for any future off-thread caller
        without a change here.
        """
        current = self.current
        return current is not None and current.session_id == session_id

    def _on_started(self, _event):
        if self.current is not None:
            # In-place reopen: the old session is superseded; every scheduled
            # or marshaled event stamped with its id is now inert.
            self._log(f"AOM_SessionTracker: superseding session "
                      f"#{self.current.session_id} (in-place reopen)")
        self.current = PlaybackSession(session_id=self._next_id,
                                       started_at=self._clock())
        self._next_id += 1
        self._log(f"AOM_SessionTracker: session #{self.current.session_id} started")

    def _on_ended(self, _event):
        if self.current is not None:
            self._log(f"AOM_SessionTracker: session #{self.current.session_id} ended")
        self.current = None

    def _on_paused(self, _event):
        if self.current is not None:
            self.current.paused = True

    def _on_resumed(self, _event):
        if self.current is not None:
            self.current.paused = False
