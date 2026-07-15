"""Typed events dispatched on the aom dispatcher.

Events are frozen dataclasses dispatched by type (subscribe registers against
the class). Payloads are explicit fields — never positional *args.

The catalog below is the full target set. The "player/monitor" group is live
now (posted by the Kodi bridges); the later groups are defined ahead of the
components that will post/consume them, so the contract is reviewable in one
place. Pure Python: no Kodi imports.
"""

from dataclasses import dataclass


# --- Player/monitor events (posted by kodi.player_bridge / monitor_bridge) --

@dataclass(frozen=True)
class PlaybackStarted:
    """Kodi onAVStarted: audio and video are rendering."""


@dataclass(frozen=True)
class AvChanged:
    """Kodi onAVChange: raw, noisy; stability is judged downstream."""


@dataclass(frozen=True)
class PlaybackStopped:
    """Kodi onPlayBackStopped: user stopped playback."""


@dataclass(frozen=True)
class PlaybackEnded:
    """Kodi onPlayBackEnded: playback reached the end."""


@dataclass(frozen=True)
class Paused:
    """Kodi onPlayBackPaused."""


@dataclass(frozen=True)
class Resumed:
    """Kodi onPlayBackResumed."""


@dataclass(frozen=True)
class SeekOccurred:
    """Kodi onPlayBackSeek — any seek, from any source (feeds quiet window)."""
    time_ms: int
    offset_ms: int


@dataclass(frozen=True)
class SeekChapter:
    """Kodi onPlayBackSeekChapter."""
    chapter: int


@dataclass(frozen=True)
class SpeedChanged:
    """Kodi onPlayBackSpeedChanged."""
    speed: int


@dataclass(frozen=True)
class SettingsChanged:
    """Kodi Monitor.onSettingsChanged: refresh cached flags; never write here."""


# --- Detection events (posted/consumed from the StreamDetector phase on) ----

@dataclass(frozen=True)
class ProbeStream:
    """Self-scheduled stream probe attempt for a session."""
    session_id: int
    attempt: int


@dataclass(frozen=True)
class VerifyStream:
    """Scheduled whole-profile stability verification (key-replaced)."""
    session_id: int
    seq: int


@dataclass(frozen=True)
class StreamProbed:
    """A detection pass observed the platform (consumed by PlatformRecorder).

    Posted on EVERY gather — probes, AV-change re-probes, and verifications —
    matching legacy StreamInfo, which stored platform capabilities on every
    gather. Carries facts, not decisions: the recorder owns the writes.
    """
    session_id: int
    platform_hdr_full: bool
    advanced_hlg: bool


@dataclass(frozen=True)
class StreamStabilized:
    """The session's profile held for the verification window."""
    session_id: int


@dataclass(frozen=True)
class ProfileChanged:
    """The session's profile was created or replaced."""
    session_id: int


# --- Offset/adjustment events -----------------------------------------------

@dataclass(frozen=True)
class OffsetApplied:
    """An offset was applied via JSON-RPC (provisional until STABLE)."""
    session_id: int
    profile: object  # StreamProfile
    ms: int
    provisional: bool


@dataclass(frozen=True)
class UserOffsetSaved:
    """The adjustment watcher stored a user's manual offset change."""
    profile: object  # StreamProfile
    ms: int


# --- Seek scheduling events --------------------------------------------------

@dataclass(frozen=True)
class ExecuteSeek:
    """Self-scheduled seek execution attempt (re-validated at fire time)."""
    session_id: int
    reason: str
    attempt: int


# --- Watcher events -----------------------------------------------------------

@dataclass(frozen=True)
class WatchTick:
    """Recurring adjustment-watcher poll tick for a session."""
    session_id: int
