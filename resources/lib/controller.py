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
        settings = self.user_settings.load_settings()
        (self.latency_settings, self.enable_seek_back, self.seek_back_seconds,
         self.hdr_control_settings, self.enable_seek_back_resume,
         self.seek_back_resume_seconds, self.enable_seek_back_unpause,
         self.seek_back_unpause_seconds) = settings

    def run(self):
        """
        Main loop to monitor settings changes and start player monitoring.
        """
        while not self.abortRequested():
            if self.waitForAbort(1):
                break
            if self.player.isPlayingVideo():
                if not self.player.playback_started:
                    self.on_playback_start()
                else:
                    self.player.check_and_adjust_delay()
                    self.player.check_user_audio_delay_change()
            elif self.player.playback_started:
                self.on_playback_stop()

    def on_playback_start(self):
        """
        Handles actions when playback starts.
        """
        # Reload settings on playback start
        self.load_user_settings()
        self.player.reset_last_values()
        self.player.playback_started = True

        xbmc.log("Playback started", xbmc.LOGDEBUG)

        # Perform seek back on resume/start if enabled
        if self.enable_seek_back_resume:
            xbmc.log(f"Seek back on start/resume is enabled. Seeking back {self.seek_back_resume_seconds} seconds.", xbmc.LOGDEBUG)
            self.player.seek_backwards(self.watcher.get_player_id(), self.seek_back_resume_seconds)
        else:
            xbmc.log("Seek back on start/resume is disabled.", xbmc.LOGDEBUG)

        xbmc.sleep(1000)  # Wait 1 second for playback to fully start
        self.player.check_and_adjust_delay()

    def on_playback_stop(self):
        """
        Handles actions when playback stops.
        """
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
        self.reset_last_values()
        self.playback_started = False
        self.paused_time = 0
        self.last_audio_delay = None
        self.playback_start_time = None

    def reset_last_values(self):
        """
        Resets the values of codec, channel count, and HDR type.
        """
        self.last_codec = None
        self.last_channel_count = None
        self.last_hdr_type = None

    def onPlayBackStarted(self):
        """
        Called when playback starts.
        """
        self.playback_start_time = time.time()
        xbmc.log(f"Playback started at time: {self.playback_start_time}", xbmc.LOGDEBUG)

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
            xbmc.sleep(1000)
            self.seek_backwards(self.watcher.get_player_id(), self.adjuster.seek_back_unpause_seconds)
        else:
            xbmc.log("Seek back on unpause is disabled.", xbmc.LOGDEBUG)

    def check_and_adjust_delay(self):
        """
        Checks the current playback status and adjusts audio delay based on user settings and content type.
        """
        xbmc.log("Checking and adjusting audio delay", xbmc.LOGDEBUG)

        video_properties = self.watcher.get_video_properties()
        hdr_type = video_properties.get('hdr_type', 'sdr')
        eotf_gamut = video_properties.get('eotf_gamut', 'unknown')

        xbmc.log(f"HDR Type: {hdr_type}, EOTF/Gamut: {eotf_gamut}", xbmc.LOGINFO)

        player_id = self.watcher.get_player_id()
        if player_id is None:
            xbmc.log("No active player found. Cannot adjust audio delay.", xbmc.LOGWARNING)
            return

        audio_stream = self.watcher.get_current_audio_stream(player_id)
        if not audio_stream:
            xbmc.log("No audio stream found. Cannot adjust audio delay.", xbmc.LOGWARNING)
            return

        codec, channel_count = self.watcher.determine_audio_format(audio_stream)

        if codec != self.last_codec or channel_count != self.last_channel_count or hdr_type != self.last_hdr_type:
            xbmc.log(f"Audio Codec Changed: {codec}, Channels: {channel_count}, HDR Type: {hdr_type}", xbmc.LOGDEBUG)
            self.last_codec, self.last_channel_count, self.last_hdr_type = codec, channel_count, hdr_type

            delay_key = f"delay_{hdr_type}_{codec}"
            delay = self.adjuster.user_settings.addon.getSettingInt(delay_key) / 1000.0

            if delay != 0:
                xbmc.log(f"Setting audio offset to {delay * 1000:.0f} ms for {hdr_type.upper()} + {codec.upper()}", xbmc.LOGDEBUG)
            else:
                xbmc.log(f"No offset applied for this combination: {hdr_type.upper()} + {codec.upper()}", xbmc.LOGDEBUG)

            self.set_audio_delay(player_id, delay)

            if self.adjuster.enable_seek_back:
                xbmc.log(f"Seek back is enabled. Seeking back {self.adjuster.seek_back_seconds} seconds.", xbmc.LOGDEBUG)
                xbmc.sleep(1000)
                self.seek_backwards(player_id, self.adjuster.seek_back_seconds)
        else:
            xbmc.log("Audio codec, channel count, and HDR type unchanged. No adjustment needed.", xbmc.LOGDEBUG)

    def check_user_audio_delay_change(self):
        """
        Checks if the user has manually changed the audio delay and updates settings accordingly.
        """
        current_delay_str = xbmc.getInfoLabel('Player.AudioDelay')
        if current_delay_str:
            try:
                current_delay = float(current_delay_str.split(' ')[0])
                if self.last_audio_delay is None or current_delay != self.last_audio_delay:
                    if self.playback_start_time and (time.time() - self.playback_start_time) > 1:
                        xbmc.log(f"User changed audio delay to {current_delay} seconds.", xbmc.LOGDEBUG)
                        self.last_audio_delay = current_delay

                        delay_key = f"delay_{self.last_hdr_type}_{self.last_codec}"
                        self.adjuster.user_settings.addon.setSetting(delay_key, str(int(current_delay * 1000)))
                        xbmc.log(f"Updated settings for {delay_key} with new delay: {current_delay * 1000:.0f} ms", xbmc.LOGDEBUG)
            except ValueError:
                xbmc.log(f"Unable to parse audio delay value: {current_delay_str}", xbmc.LOGWARNING)

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