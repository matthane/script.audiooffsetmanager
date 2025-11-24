"""Helper to debounce AV change events based on codec stability."""

import threading
import xbmc
from resources.lib.logger import log


class AvChangeFilter:
    def __init__(self, stream_info, log_prefix="AOM_EventManager", monitor=None):
        self.stream_info = stream_info
        self.log_prefix = log_prefix
        self.last_audio_codec = None
        self.monitor = monitor or xbmc.Monitor()
        self._sequence = 0
        self._lock = threading.Lock()

    def on_playback_start(self):
        self.last_audio_codec = None

    def on_playback_stop(self):
        self.last_audio_codec = None

    def handle_av_change(self, is_playback_active, on_stable_callback, set_last_codec=None):
        """Debounce AV changes until codec stabilizes for 1s."""
        if not is_playback_active():
            return

        current_codec = self._get_current_audio_codec()
        if current_codec is None:
            log(f"{self.log_prefix}: Codec not available yet, skipping event",
                xbmc.LOGDEBUG)
            return

        if current_codec == self.last_audio_codec:
            log(f"{self.log_prefix}: Duplicate AV change event for codec '{current_codec}', ignoring",
                xbmc.LOGDEBUG)
            return

        log(f"{self.log_prefix}: Codec change detected: '{self.last_audio_codec}' -> '{current_codec}', "
            f"scheduling stability verification", xbmc.LOGDEBUG)
        self._schedule_codec_verification(current_codec, is_playback_active, on_stable_callback, set_last_codec)

    def _get_current_audio_codec(self):
        """Get current audio codec using StreamInfo module."""
        player_id = self.stream_info.get_player_id()
        if player_id == -1:
            return None

        audio_format, _ = self.stream_info.get_audio_info(player_id)

        # Treat 'unknown' or 'none' as codec not available yet
        if audio_format in ['unknown', 'none']:
            return None

        return audio_format

    def _schedule_codec_verification(self, expected_codec, is_playback_active, on_stable_callback, set_last_codec):
        """Wait 1 second, then verify codec is still the expected value before publishing."""

        with self._lock:
            self._sequence += 1
            seq = self._sequence

        def verify():
            # Wait 1 second (or until Kodi abort)
            if self.monitor.waitForAbort(1.0):
                return  # Kodi is shutting down

            # If a newer AV change was scheduled, skip this verification
            with self._lock:
                if seq != self._sequence:
                    return

            # Check if playback still active
            if not is_playback_active():
                log(f"{self.log_prefix}: Playback stopped during codec verification for '{expected_codec}'",
                    xbmc.LOGDEBUG)
                return

            # Verify codec is still what we expect (stable)
            current_codec = self._get_current_audio_codec()

            if current_codec == expected_codec:
                log(f"{self.log_prefix}: Codec '{expected_codec}' verified stable after 1s, processing change",
                    xbmc.LOGDEBUG)
                self.last_audio_codec = current_codec
                if set_last_codec:
                    set_last_codec(current_codec)
                on_stable_callback()
            else:
                log(f"{self.log_prefix}: Codec unstable: expected '{expected_codec}' but found '{current_codec}', ignoring",
                    xbmc.LOGDEBUG)

        thread = threading.Thread(target=verify)
        thread.daemon = True
        thread.start()
