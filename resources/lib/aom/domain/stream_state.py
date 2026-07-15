"""Stream stability state machine — the ONE answer to "has the stream settled?"

    STARTING ──(profile built)──▶ STABILIZING ──(profile held ~1s)──▶ STABLE
                                       ▲                                │
                                       └──(profile change detected)─────┘

Replaces the legacy 2.0s startup grace window and the cross-component codec
mirrors for NOTIFICATION settling. (SeekBacks' startup skip remains a plain
per-session latch until the seek phase unifies it — see
PlaybackSession.initial_av_change_consumed.) Consumers ask one question:
``session.stream_state is StreamState.STABLE``.

The StreamDetector drives every transition: stability is judged on the WHOLE
profile (HDR + FPS + audio, not just the codec), and a failed verification
re-schedules itself instead of stranding STABILIZING — every stabilization
therefore reaches STABLE and releases any pending notification promptly.

Pure Python: no Kodi imports.
"""

from enum import Enum


class StreamState(Enum):
    STARTING = 'starting'        # session exists, no complete profile yet
    STABILIZING = 'stabilizing'  # profile built, not yet confirmed stable
    STABLE = 'stable'            # whole profile held through the verify window
