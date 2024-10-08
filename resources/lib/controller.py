import xbmc
import time
from resources.lib.watcher import Watcher
from resources.lib.user import UserSettings

class AudioDelayAdjuster(xbmc.Monitor):
    def __init__(self):
        super().__init__()
        self.user_settings = UserSettings()
        self.watcher = Watcher()
        self.load_user_settings()
        self.player = AudioDelayPlayer(self)

    def load_user_settings(self):
        """
        Loads user settings from the configuration.
        """
        (self.latency_settings, self.enable_seek_back, self.seek_back_seconds,
         self.hdr_control_settings, self.enable_seek_back_resume,
         self.seek_back_resume_seconds, self.enable_seek_back_unpause,
         self.seek_back_unpause_seconds) = self.user_settings.load_settings()

    def run(self):
        """
        Main loop to monitor settings changes and start player monitoring.
        """
        while not self.abortRequested():
            if self.waitForAbort(1):
                break
            if self.player.isPlayingVideo():
                if not self.player.playback_started:
                    # Playback just started
                    self.player.playback_started = True
                    xbmc.log("Playback started", xbmc.LOGDEBUG)
                    # Execute seek back on start/resume if enabled
                    if self.enable_seek_back_resume:
                        xbmc.log(f"Seek back on start/resume is enabled. Seeking back {self.seek_back_resume_seconds} seconds.", xbmc.LOGDEBUG)
                        self.player.seek_backwards(self.watcher.get_player_id(), self.seek_back_resume_seconds)
                    else:
                        xbmc.log("Seek back on start/resume is disabled.", xbmc.LOGDEBUG)
                    xbmc.sleep(1000)  # Wait 1 second to ensure playback is fully started
                    self.player.check_and_adjust_delay()
                else:
                    # Periodically check for changes during playback
                    self.player.check_and_adjust_delay()
            elif not self.player.isPlayingVideo() and self.player.playback_started:
                # Playback just stopped
                xbmc.log("Playback stopped", xbmc.LOGDEBUG)
                self.player.playback_started = False

    def onSettingsChanged(self):
        """
        Called when user settings are changed to reload settings.
        """
        xbmc.log("Settings changed, reloading settings", xbmc.LOGDEBUG)
        self.load_user_settings()


class AudioDelayPlayer(xbmc.Player):
    def __init__(self, adjuster):
        super().__init__()
        self.adjuster = adjuster
        self.watcher = adjuster.watcher
        self.last_codec = None
        self.last_video_format = None
        self.last_channel_count = None
        self.playback_started = False
        self.paused_time = 0

    def onPlayBackPaused(self):
        """
        Called when playback is paused.
        """
        self.paused_time = time.time()
        xbmc.log(f"Playback paused at time: {self.paused_time}", xbmc.LOGDEBUG)

    def onPlayBackResumed(self):
        """
        Called when playback is resumed after being paused.
        """
        if self.adjuster.enable_seek_back_unpause:
            xbmc.log(f"Seek back on unpause is enabled. Waiting 1 second before seeking back {self.adjuster.seek_back_unpause_seconds} seconds.", xbmc.LOGDEBUG)
            xbmc.sleep(1000)  # Wait 1 second before seeking back
            self.seek_backwards(self.watcher.get_player_id(), self.adjuster.seek_back_unpause_seconds)
        else:
            xbmc.log("Seek back on unpause is disabled.", xbmc.LOGDEBUG)

    def check_and_adjust_delay(self):
        """
        Checks the current playback status and adjusts audio delay based on the user settings and content type.
        """
        xbmc.log("Checking and adjusting audio delay", xbmc.LOGDEBUG)
        # Get the player ID
        player_id = self.watcher.get_player_id()
        if player_id is None:
            xbmc.log("No active player found. Cannot adjust audio delay.", xbmc.LOGWARNING)
            return

        # Get the current audio stream details
        audio_stream = self.watcher.get_current_audio_stream(player_id)
        if not audio_stream:
            xbmc.log("No audio stream found. Cannot adjust audio delay.", xbmc.LOGWARNING)
            return

        # Get the current HDR type
        video_format = self.watcher.get_current_hdr_type()
        xbmc.log(f"Detected HDR type: {video_format}", xbmc.LOGINFO)

        # Check if HDR type is enabled in the settings
        if not self.adjuster.hdr_control_settings.get(f"enable_{video_format}", False):
            xbmc.log(f"Audio offset control disabled for HDR type: {video_format}", xbmc.LOGDEBUG)
            return

        # Determine the audio format (codec and channel count)
        codec, channel_count = self.watcher.determine_audio_format(audio_stream)

        # Only adjust if the codec, channel count, or video format has changed
        if codec != self.last_codec or channel_count != self.last_channel_count or video_format != self.last_video_format:
            xbmc.log(f"Audio Codec Changed: {codec}, Channels: {channel_count}, Video Format: {video_format}", xbmc.LOGDEBUG)
            self.last_codec = codec
            self.last_channel_count = channel_count
            self.last_video_format = video_format

            # Determine the delay based on the codec and video format
            delay_key = f"{video_format}_{codec}"
            delay = self.adjuster.latency_settings.get(delay_key, 0.0) / 1000.0  # Convert ms to seconds
            if delay != 0:
                xbmc.log(f"Setting audio offset to {delay * 1000:.0f} ms for {video_format.upper()} + {codec.upper()}", xbmc.LOGDEBUG)
            else:
                xbmc.log(f"No offset applied for this combination: {video_format.upper()} + {codec.upper()}", xbmc.LOGDEBUG)

            # Set the audio delay using JSON-RPC
            self.set_audio_delay(player_id, delay)

            # Perform seek-back if enabled
            if self.adjuster.enable_seek_back:
                xbmc.log(f"Seek back is enabled. Seeking back {self.adjuster.seek_back_seconds} seconds.", xbmc.LOGDEBUG)
                xbmc.sleep(1000)  # Wait 1 second before seeking back
                self.seek_backwards(player_id, self.adjuster.seek_back_seconds)
            else:
                xbmc.log("Seek back is disabled.", xbmc.LOGDEBUG)
        else:
            xbmc.log("Audio codec, channel count, and video format unchanged. No adjustment needed.", xbmc.LOGDEBUG)

    def set_audio_delay(self, player_id, delay):
        """
        Sets the audio delay using Kodi's JSON-RPC interface.
        """
        response = self.watcher.json_rpc_request({
            "jsonrpc": "2.0",
            "method": "Player.SetAudioDelay",
            "params": {
                "playerid": player_id,
                "offset": delay
            },
            "id": 1
        })
        xbmc.log(f"SetAudioDelay response: {response}", xbmc.LOGDEBUG)

    def seek_backwards(self, player_id, seconds):
        """
        Seeks the playback backwards by the specified number of seconds.
        """
        xbmc.log(f"Attempting to seek back {seconds} seconds.", xbmc.LOGDEBUG)
        response = self.watcher.json_rpc_request({
            "jsonrpc": "2.0",
            "method": "Player.Seek",
            "params": {
                "playerid": player_id,
                "value": {
                    "seconds": -seconds
                }
            },
            "id": 1
        })
        xbmc.log(f"SeekBackwards response: {response}", xbmc.LOGDEBUG)

if __name__ == '__main__':
    adjuster = AudioDelayAdjuster()
    adjuster.run()