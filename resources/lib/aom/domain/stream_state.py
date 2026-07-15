"""Stream stability state machine — the ONE answer to "has the stream settled?"

    STARTING ──(profile built)──▶ STABILIZING ──(codec held ~1s)──▶ STABLE
                                       ▲                               │
                                       └──(codec change detected)──────┘

Replaces the legacy 2.0s startup grace window and the cross-component codec
mirrors for NOTIFICATION settling. (SeekBacks' startup skip remains a plain
per-session latch until the detector/seek phases unify it — see
PlaybackSession.initial_av_change_consumed.) Consumers ask one question:
``session.stream_state is StreamState.STABLE``.

Known limitations during the migration (both consequence-free today, both
removed by the stream detector's scheduled re-verification):
- a failed verification (codec blipped and reverted inside the 1s window)
  leaves the session STABILIZING with no automatic recovery edge; and
- pending-notification release is polled lazily on apply events, so a
  never-confirmed stream never releases it (exactly the legacy behavior —
  legacy's grace-expiry check also only ran on apply events).

Pure Python: no Kodi imports.
"""

from enum import Enum


class StreamState(Enum):
    STARTING = 'starting'        # session exists, no complete profile yet
    STABILIZING = 'stabilizing'  # profile built, codec not yet confirmed stable
    STABLE = 'stable'            # codec held through the verification window
