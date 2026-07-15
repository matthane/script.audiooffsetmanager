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
subscription order).

Pure Python: no Kodi imports; logging callables are injected.
"""

import time
from dataclasses import dataclass, field

from resources.lib.aom.app import events
from resources.lib.aom.domain.stream_state import StreamState


def _noop(_message):
    return None


@dataclass
class PlaybackSession:
    session_id: int
    started_at: float                       # monotonic (interval math only)
    stream_state: StreamState = StreamState.STARTING
    profile: object = None                  # StreamProfile, set per AV event
    applied: tuple = None                   # (setting_key, delay_ms) dedupe guard
    pending_notification: tuple = None      # (setting_key, delay_ms) awaiting STABLE
    paused: bool = False
    initial_av_change_consumed: bool = False  # startup 'adjust' seek-back skip
    last_seek_activity: float = 0.0         # monotonic; any seek, any source
    seek_history: dict = field(default_factory=dict)  # reason -> monotonic ts


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
        """True while the given session is still the live one."""
        return self.current is not None and self.current.session_id == session_id

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
