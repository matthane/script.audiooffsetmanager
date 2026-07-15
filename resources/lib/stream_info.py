"""MIGRATION(p7): session-backed shim preserving StreamInfo's read surface.

Detection moved to aom.app.stream_detector (scheduled single-shot probes,
whole-profile verification); the detector is the sole writer of
``session.profile``. This shim exists only for the debug snapshot, the one
legacy reader that still expects a StreamInfo-shaped object, and it reads
THROUGH the live session, so a superseded playback can never serve a stale
profile. It dies with debug_snapshot in the Phase 7 splits. (ActiveMonitor,
the other reader — and the reason this was once read cross-thread — was
replaced by the dispatcher-driven AdjustmentWatcher in Phase 6.)
"""


class StreamInfo:
    def __init__(self, session_tracker):
        self._sessions = session_tracker

    @property
    def profile(self):
        """The current session's profile (None between playbacks).

        Reads ``current`` exactly ONCE so even an off-thread caller could
        never have it nulled between the check and the dereference (free
        insurance; every remaining caller is on the dispatcher thread).
        """
        current = self._sessions.current
        return current.profile if current is not None else None
