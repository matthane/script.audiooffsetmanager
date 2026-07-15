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
    # The session's profile. UNWRITTEN during the migration phases: the live
    # profile is stream_info.profile (mutated by the monitor thread too, so a
    # mirror here could silently diverge). The stream detector becomes the
    # sole writer when it lands.
    profile: object = None
    applied: tuple = None                   # (setting_key, delay_ms) dedupe guard
    pending_notification: tuple = None      # (setting_key, delay_ms) awaiting STABLE
    paused: bool = False
    # Plain first-call latch for the startup 'adjust' seek-back skip. Only
    # incidentally aligned with the state machine (ON_AV_CHANGE happens to
    # follow the first STABLE); do not assume a stronger coupling.
    initial_av_change_consumed: bool = False
    # Monotonic timestamps; None = never (a 0.0 sentinel would be wrong for
    # monotonic clocks, whose epoch is arbitrary).
    last_seek_activity: Optional[float] = None
    seek_history: dict = field(default_factory=dict)  # reason -> monotonic ts

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
        caller logs it. Returns True when the transition happened.

        Known limitation (documented, consequence-free this phase): a failed
        verification leaves the session STABILIZING with no automatic
        recovery edge — recovery requires the next confirmation. The stream
        detector replaces this with scheduled re-verification.
        """
        if self.stream_state is StreamState.STABILIZING:
            self.stream_state = StreamState.STABLE
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

    def is_alive(self, session_id):
        """True while the given session is still the live one.

        Called from the AvChangeFilter verify thread as well as the
        dispatcher thread: read self.current exactly ONCE so a concurrent
        teardown can never null it between a check and a dereference.
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
