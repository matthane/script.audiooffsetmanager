import xbmc
import xbmcaddon
import json
import time

class AudioDelayAdjuster(xbmc.Monitor):
    def __init__(self):
        super().__init__()
        self.player = xbmc.Player()
        self.addon = xbmcaddon.Addon()
        self.last_codec = None
        self.last_video_format = None
        self.last_channel_count = None
        self.latency_settings, self.enable_seek_back, self.seek_back_seconds, self.hdr_control_settings = self.load_settings()
        self.playback_started = False

    def run(self):
        while not self.abortRequested():
            if self.waitForAbort(1):
                break
            if self.player.isPlayingVideo():
                if not self.playback_started:
                    self.playback_started = True
                    xbmc.log("Playback started", xbmc.LOGDEBUG)
                    self.last_codec = None  # Reset last codec
                    self.last_video_format = None  # Reset last video format
                    self.last_channel_count = None  # Reset last channel count
                    self.check_and_adjust_delay()
                else:
                    self.check_and_adjust_delay()
            else:
                if self.playback_started:
                    xbmc.log("Playback stopped", xbmc.LOGDEBUG)
                self.playback_started = False
                self.last_codec = None
                self.last_video_format = None
                self.last_channel_count = None
        # Settings changes are handled via onSettingsChanged()

    def onNotification(self, sender, method, data):
        if method == "Player.OnAVStart":
            xbmc.log("Player.OnAVStart event received", xbmc.LOGDEBUG)
            self.last_codec = None  # Reset last codec
            self.last_video_format = None  # Reset last video format
            self.last_channel_count = None  # Reset last channel count
            self.check_and_adjust_delay()

    def onSettingsChanged(self):
        self.latency_settings, self.enable_seek_back, self.seek_back_seconds, self.hdr_control_settings = self.load_settings()
        xbmc.log("Dynamic Audio Offset Adjuster settings updated", xbmc.LOGDEBUG)

    def check_and_adjust_delay(self):
        # Get the player ID
        player_id = self.get_player_id()
        if player_id is None:
            return

        # Get the current audio stream details
        audio_stream = self.get_current_audio_stream(player_id)
        if not audio_stream:
            return

        # Get the current HDR type
        video_format = self.get_current_hdr_type()
        xbmc.log(f"Detected HDR type: {video_format}", xbmc.LOGINFO)

        # Check if HDR type is enabled in the settings
        if not self.hdr_control_settings.get(f"enable_{video_format}", False):
            xbmc.log(f"Audio offset control disabled for HDR type: {video_format}", xbmc.LOGDEBUG)
            return

        codec = audio_stream.get('codec', '').lower()
        channel_count = audio_stream.get('channels', 0)

        # Remove 'pt-' prefix if present
        if codec.startswith('pt-'):
            codec = codec[3:]

        # Determine the correct delay based on codec, channel count, and video format
        if codec == 'dtshd_ma':
            if channel_count == 8:
                codec = 'dtsx'
            elif channel_count == 6:
                codec = 'dtshd_ma'

        if codec != self.last_codec or channel_count != self.last_channel_count or video_format != self.last_video_format:
            xbmc.log(f"Audio Codec Changed: {codec}, Channels: {channel_count}, Video Format: {video_format}", xbmc.LOGDEBUG)
            self.last_codec = codec
            self.last_channel_count = channel_count
            self.last_video_format = video_format

            delay_key = f"{video_format}_{codec}"
            delay = self.latency_settings.get(delay_key, 0.0) / 1000.0  # Convert ms to seconds
            if delay != 0:
                xbmc.log(f"Setting audio offset to {delay * 1000:.0f} ms for {video_format.upper()} + {codec.upper()}", xbmc.LOGDEBUG)
            else:
                xbmc.log(f"No offset applied for this combination: {video_format.upper()} + {codec.upper()}", xbmc.LOGDEBUG)

            # Set the audio delay using JSON-RPC
            self.set_audio_delay(player_id, delay)

            # If seek-back is enabled, perform the seek
            if self.enable_seek_back:
                xbmc.log(f"Seek back is enabled. Seeking back {self.seek_back_seconds} seconds.", xbmc.LOGDEBUG)
                # Wait 1 second and then seek backwards by user-defined seconds
                xbmc.sleep(1000)
                self.seek_backwards(player_id, self.seek_back_seconds)
            else:
                xbmc.log("Seek back is disabled.", xbmc.LOGDEBUG)

    def load_settings(self):
        try:
            # Load the latency settings from the add-on settings (values in ms)
            latency_settings = {
                'sdr_truehd': self.addon.getSettingInt('delay_sdr_truehd'),
                'hdr10_truehd': self.addon.getSettingInt('delay_hdr10_truehd'),
                'dolbyvision_truehd': self.addon.getSettingInt('delay_dolbyvision_truehd'),
                'hlg_truehd': self.addon.getSettingInt('delay_hlg_truehd'),
                'sdr_eac3': self.addon.getSettingInt('delay_sdr_eac3'),
                'hdr10_eac3': self.addon.getSettingInt('delay_hdr10_eac3'),
                'dolbyvision_eac3': self.addon.getSettingInt('delay_dolbyvision_eac3'),
                'hlg_eac3': self.addon.getSettingInt('delay_hlg_eac3'),
                'sdr_ac3': self.addon.getSettingInt('delay_sdr_ac3'),
                'hdr10_ac3': self.addon.getSettingInt('delay_hdr10_ac3'),
                'dolbyvision_ac3': self.addon.getSettingInt('delay_dolbyvision_ac3'),
                'hlg_ac3': self.addon.getSettingInt('delay_hlg_ac3'),
                'sdr_dtsx': self.addon.getSettingInt('delay_sdr_dtsx'),
                'hdr10_dtsx': self.addon.getSettingInt('delay_hdr10_dtsx'),
                'dolbyvision_dtsx': self.addon.getSettingInt('delay_dolbyvision_dtsx'),
                'hlg_dtsx': self.addon.getSettingInt('delay_hlg_dtsx'),
                'sdr_dtshd_ma': self.addon.getSettingInt('delay_sdr_dtshd'),
                'hdr10_dtshd_ma': self.addon.getSettingInt('delay_hdr10_dtshd'),
                'dolbyvision_dtshd_ma': self.addon.getSettingInt('delay_dolbyvision_dtshd'),
                'hlg_dtshd_ma': self.addon.getSettingInt('delay_hlg_dtshd'),
                'sdr_dca': self.addon.getSettingInt('delay_sdr_dca'),
                'hdr10_dca': self.addon.getSettingInt('delay_hdr10_dca'),
                'dolbyvision_dca': self.addon.getSettingInt('delay_dolbyvision_dca'),
                'hlg_dca': self.addon.getSettingInt('delay_hlg_dca'),
            }

            # Load the seek back settings
            enable_seek_back = self.addon.getSettingBool('enable_seek_back')
            seek_back_seconds = self.addon.getSettingInt('seek_back_seconds')

            # Load HDR control settings
            hdr_control_settings = {
                'enable_dolbyvision': self.addon.getSettingBool('enable_dolbyvision'),
                'enable_hdr10': self.addon.getSettingBool('enable_hdr10'),
                'enable_hlg': self.addon.getSettingBool('enable_hlg'),
                'enable_sdr': self.addon.getSettingBool('enable_sdr'),
            }

            # Validate seek_back_seconds
            if not (1 <= seek_back_seconds <= 10):
                xbmc.log("Seek back seconds out of range. Resetting to default (4 seconds).", xbmc.LOGWARNING)
                seek_back_seconds = 4

            return latency_settings, enable_seek_back, seek_back_seconds, hdr_control_settings
        except Exception as e:
            xbmc.log(f"Error loading settings: {e}", xbmc.LOGERROR)
            # Set default values in case of error
            return {
                'sdr_truehd': 0,
                'hdr10_truehd': 0,
                'dolbyvision_truehd': 0,
                'hlg_truehd': 0,
                'sdr_eac3': 0,
                'hdr10_eac3': 0,
                'dolbyvision_eac3': 0,
                'hlg_eac3': 0,
                'sdr_ac3': 0,
                'hdr10_ac3': 0,
                'dolbyvision_ac3': 0,
                'hlg_ac3': 0,
                'sdr_dtsx': 0,
                'hdr10_dtsx': 0,
                'dolbyvision_dtsx': 0,
                'hlg_dtsx': 0,
                'sdr_dtshd_ma': 0,
                'hdr10_dtshd_ma': 0,
                'dolbyvision_dtshd_ma': 0,
                'hlg_dtshd_ma': 0,
                'sdr_dca': 0,
                'hdr10_dca': 0,
                'dolbyvision_dca': 0,
                'hlg_dca': 0,
            }, True, 4, {
                'enable_dolbyvision': True,
                'enable_hdr10': True,
                'enable_hlg': True,
                'enable_sdr': True,
            }

    def set_audio_delay(self, player_id, delay):
        # Set the audio delay using JSON-RPC
        response = self.json_rpc_request({
            "jsonrpc": "2.0",
            "method": "Player.SetAudioDelay",
            "params": {
                "playerid": player_id,
                "offset": delay
            },
            "id": 1
        })
        xbmc.log(f"SetAudioDelay response: {response}", xbmc.LOGDEBUG)

    def get_player_id(self):
        # Get active player ID
        response = self.json_rpc_request({
            "jsonrpc": "2.0",
            "method": "Player.GetActivePlayers",
            "id": 1
        })
        if response and 'result' in response and response['result']:
            return response['result'][0]['playerid']
        return None

    def get_current_audio_stream(self, player_id):
        # Get properties of the currently playing item
        response = self.json_rpc_request({
            "jsonrpc": "2.0",
            "method": "Player.GetProperties",
            "params": {
                "playerid": player_id,
                "properties": ["currentaudiostream"]
            },
            "id": 1
        })
        if response and 'result' in response:
            return response['result'].get('currentaudiostream')
        return None

    def get_current_hdr_type(self):
        # Get HDR type of the currently playing video using infolabel
        hdr_type = xbmc.getInfoLabel('VideoPlayer.HdrType').lower()
        if not hdr_type:
            hdr_type = 'sdr'
        return hdr_type

    def json_rpc_request(self, payload):
        request = json.dumps(payload)
        response = xbmc.executeJSONRPC(request)
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            xbmc.log(f"Invalid JSON response: {response}", xbmc.LOGERROR)
            return {}

    def seek_backwards(self, player_id, seconds):
        # Seek the player backwards by the specified number of seconds
        xbmc.log(f"Attempting to seek back {seconds} seconds.", xbmc.LOGDEBUG)
        response = self.json_rpc_request({
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