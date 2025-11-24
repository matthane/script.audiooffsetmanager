"""Debug snapshot helper to log current state when debug logging is enabled."""

import xbmc
from resources.lib.logger import log


def log_snapshot(event_name, stream_info, settings_facade, extra=None):
    """Emit a one-line snapshot of current profile/config if debug logging is enabled."""
    if not settings_facade.debug_logging_enabled():
        return

    profile = stream_info.profile
    if profile is None:
        log(f"[Snapshot] {event_name}: no profile available", xbmc.LOGINFO)
        return

    setting_id = profile.setting_id()
    offset_ms = settings_facade.get_offset_ms(profile)
    hdr = profile.hdr_type
    fps = profile.fps_type
    audio = profile.audio_format
    seek_enabled, seek_secs = settings_facade.seek_back_config('change')

    parts = [
        f"event={event_name}",
        f"profile={setting_id}",
        f"hdr={hdr}",
        f"fps={fps}",
        f"audio={audio}",
        f"offset_ms={offset_ms}",
        f"seek_change={'on' if seek_enabled else 'off'}@{seek_secs}s"
    ]

    if extra:
        for key, val in extra.items():
            parts.append(f"{key}={val}")

    log("[Snapshot] " + " | ".join(parts), xbmc.LOGINFO)
