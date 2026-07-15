"""MIGRATION(p6): session-backed shim preserving StreamInfo's read surface.

Detection moved to aom.app.stream_detector (scheduled single-shot probes,
whole-profile verification); the detector is the sole writer of
``session.profile``. This shim exists only for the two legacy readers that
still expect a StreamInfo-shaped object — ActiveMonitor and the debug
snapshot — and it reads THROUGH the live session, so a superseded playback
can never serve a stale profile. It dies with ActiveMonitor when the
adjustment watcher lands (Phase 6).
"""

import xbmc
from resources.lib.logger import log


class StreamInfo:
    def __init__(self, session_tracker):
        self._sessions = session_tracker

    @property
    def profile(self):
        """The current session's profile (None between playbacks).

        Read from the ActiveMonitor thread as well as the dispatcher thread:
        read ``current`` exactly ONCE so a concurrent teardown can never null
        it between the check and the dereference.
        """
        current = self._sessions.current
        return current.profile if current is not None else None

    def update_stream_info(self):
        """No-op: the StreamDetector owns detection now.

        ActiveMonitor calls this at start; the profile it goes on to read is
        the one the detector just wrote for this same session.
        """
        log("AOM_StreamInfo: detection is owned by the stream detector; "
            "profile read through the live session", xbmc.LOGDEBUG)
