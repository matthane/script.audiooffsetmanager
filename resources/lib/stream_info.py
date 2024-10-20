# resources/lib/stream_info.py

import xbmc
import xbmcgui
import time
import json
from resources.lib.settings_manager import SettingsManager


class StreamInfo:
    def __init__(self):
        self.info = {}
        self.settings_manager = SettingsManager()
        self.new_install = self.settings_manager.get_setting_boolean('new_install')
        self.valid_audio_formats = ['truehd', 'eac3', 'ac3', 'dtsx', 'dtshd_ma', 'dca', 'pcm']
        self.valid_hdr_types = ['dolbyvision', 'hdr10', 'hdr10plus', 'hlg', 'sdr']

    def update_stream_info(self):
        # Gather updated playback details
        self.info = self.gather_stream_info()
        xbmc.log(f"AOM_StreamInfo: Updated stream info: {self.info}", xbmc.LOGDEBUG)

    def clear_stream_info(self):
        # Clear the stream information
        self.info = {}
        xbmc.log("AOM_StreamInfo: Cleared stream info", xbmc.LOGDEBUG)

    def is_valid_infolabel(self, label, value):
        return value and value.strip() and value.lower() != label.lower()

    def gather_stream_info(self):
        # Retrieve stream information
        player_id = self.get_player_id()
        audio_format, audio_channels = self.get_audio_info(player_id)
        
        # Enhanced HDR detection with fallback to generic Kodi infolabel
        hdr_label = 'Player.Process(video.source.hdr.type)'
        hdr_type = xbmc.getInfoLabel(hdr_label)
        xbmc.log(f"AOM_StreamInfo: Raw HDR type: '{hdr_type}'", xbmc.LOGDEBUG)
        
        if self.is_valid_infolabel(hdr_label, hdr_type):
            platform_hdr_full = True
            xbmc.log("AOM_StreamInfo: Platform HDR full support detected", xbmc.LOGDEBUG)
        else:
            hdr_type = xbmc.getInfoLabel('VideoPlayer.HdrType')
            platform_hdr_full = False
            xbmc.log("AOM_StreamInfo: Platform HDR full support not detected", xbmc.LOGDEBUG)
        
        xbmc.log(f"AOM_StreamInfo: Final HDR type: '{hdr_type}', Platform HDR full: {platform_hdr_full}", xbmc.LOGDEBUG)

        gamut_label = 'Player.Process(amlogic.eoft_gamut)'
        gamut_info = xbmc.getInfoLabel(gamut_label)
        xbmc.log(f"AOM_StreamInfo: Raw gamut info: '{gamut_info}'", xbmc.LOGDEBUG)
        gamut_info_valid = self.is_valid_infolabel(gamut_label, gamut_info)
        xbmc.log(f"AOM_StreamInfo: Gamut info valid: {gamut_info_valid}", xbmc.LOGDEBUG)
        
        
        self.settings_manager.store_setting_boolean('platform_hdr_full', platform_hdr_full)
        
        # Check if gamut_info is valid and set advanced_hlg accordingly
        if gamut_info_valid:
            advanced_hlg = True
            self.settings_manager.store_setting_boolean('advanced_hlg', advanced_hlg)
            xbmc.log("AOM_StreamInfo: Stored advanced_hlg as True", xbmc.LOGDEBUG)
        else:
            advanced_hlg = False
            self.settings_manager.store_setting_boolean('advanced_hlg', advanced_hlg)
            xbmc.log("AOM_StreamInfo: Stored advanced_hlg as False", xbmc.LOGDEBUG)
        
        self.new_install = False
        self.settings_manager.store_setting_boolean('new_install', self.new_install)
        xbmc.log("AOM_StreamInfo: Stored settings and set new_install to False", xbmc.LOGDEBUG)

        hdr_type = hdr_type.replace('+', 'plus').replace(' ', '').lower()
        if not hdr_type or hdr_type == hdr_label.lower():
            hdr_type = 'sdr'
        elif hdr_type == 'hlghdr':
            hdr_type = 'hlg'
        
        if not gamut_info_valid:
            gamut_info = 'not available'

        # Check for HLG detection based on gamut_info
        if hdr_type == 'sdr' and gamut_info_valid and 'hlg' in gamut_info.lower():
            hdr_type = 'hlg'

        # Construct a dictionary of stream information
        stream_info = {
            'player_id': player_id,
            'audio_channels': audio_channels,
            'gamut_info': gamut_info,
            'platform_hdr_full': platform_hdr_full,
            'gamut_info_valid': gamut_info_valid
        }

        # Only include hdr_type and audio_format if they are valid
        if audio_format in self.valid_audio_formats:
            stream_info['audio_format'] = audio_format
        else:
            xbmc.log(f"AOM_StreamInfo: Invalid audio format detected: {audio_format}. "
                     f"Not including in stream info.", xbmc.LOGDEBUG)

        if hdr_type in self.valid_hdr_types:
            stream_info['hdr_type'] = hdr_type
        else:
            xbmc.log(f"AOM_StreamInfo: Invalid HDR type detected: {hdr_type}. "
                     f"Not including in stream info.", xbmc.LOGDEBUG)

        return stream_info

    def get_player_id(self):
        # Use JSON-RPC to retrieve the player ID, retrying up to 10 times if necessary
        for attempt in range(10):
            try:
                request = json.dumps({
                    "jsonrpc": "2.0",
                    "method": "Player.GetActivePlayers",
                    "id": 1
                })
                response = xbmc.executeJSONRPC(request)
                response_json = json.loads(response)

                if "result" in response_json and len(response_json["result"]) > 0:
                    player_id = response_json["result"][0].get("playerid", -1)
                    if player_id != -1:
                        return player_id

                xbmc.log(f"AOM_StreamInfo: Invalid player ID, retrying... ({attempt + 1}/10)",
                         xbmc.LOGDEBUG)
                time.sleep(0.5)
            except Exception as e:
                xbmc.log(f"AOM_StreamInfo: Error getting player ID: {str(e)}",
                         xbmc.LOGERROR)
                time.sleep(0.5)

        xbmc.log("AOM_StreamInfo: Failed to retrieve valid player ID after 10 attempts",
                 xbmc.LOGWARNING)
        return -1

    def get_audio_info(self, player_id):
        # Use JSON-RPC to retrieve audio codec and channel count, retrying if 'none' is detected
        for attempt in range(10):
            try:
                request = json.dumps({
                    "jsonrpc": "2.0",
                    "method": "Player.GetProperties",
                    "params": {
                        "playerid": player_id,
                        "properties": ["currentaudiostream"]
                    },
                    "id": 1
                })
                response = xbmc.executeJSONRPC(request)
                response_json = json.loads(response)

                if "result" in response_json and "currentaudiostream" in response_json["result"]:
                    audio_stream = response_json["result"]["currentaudiostream"]
                    audio_format = audio_stream.get("codec", "unknown").replace('pt-', '')
                    audio_channels = audio_stream.get("channels", "unknown")

                    if audio_format != 'none':
                        # Advanced logic for DTS-HD MA detection
                        if audio_format == 'dtshd_ma' and isinstance(audio_channels, int) and audio_channels > 6:
                            audio_format = 'dtsx'
                        # New check for PCM
                        elif audio_format not in self.valid_audio_formats and audio_format != 'unknown':
                            audio_format = 'pcm'

                        return audio_format, audio_channels

                xbmc.log(f"AOM_StreamInfo: Invalid audio format 'none', retrying... ({attempt + 1}/10)",
                         xbmc.LOGDEBUG)
                time.sleep(0.5)
            except Exception as e:
                xbmc.log(f"AOM_StreamInfo: Error getting audio info: {str(e)}",
                         xbmc.LOGERROR)
                time.sleep(0.5)

        xbmc.log("AOM_StreamInfo: Failed to retrieve valid audio information after 10 attempts",
                 xbmc.LOGWARNING)
        return "unknown", "unknown"
