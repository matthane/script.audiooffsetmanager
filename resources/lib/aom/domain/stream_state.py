"""Stream stability state machine — the ONE answer to "has the stream settled?"

    STARTING ──(profile built)──▶ STABILIZING ──(codec held ~1s)──▶ STABLE
                                       ▲                               │
                                       └──(codec change detected)──────┘

Replaces the three parallel heuristics the legacy code used (the 2.0s startup
grace window, cross-component codec mirrors, and SeekBacks' first-change
flag). Consumers ask one question: ``session.stream_state is StreamState.STABLE``.

Pure Python: no Kodi imports.
"""

from enum import Enum


class StreamState(Enum):
    STARTING = 'starting'        # session exists, no complete profile yet
    STABILIZING = 'stabilizing'  # profile built, codec not yet confirmed stable
    STABLE = 'stable'            # codec held through the verification window
