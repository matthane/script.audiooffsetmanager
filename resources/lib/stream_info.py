# resources/lib/modules/stream_info.py

import xbmc
import xbmcgui
import time
import json

class StreamInfo:
    def __init__(self, event_manager):
        self.event_manager = event_manager
        self.info = {}

    def start(self):
        # Subscribe to relevant events from the event manager
        self.event_manager.subscribe('AV_STARTED', self.on_av_started)
        self.event_manager.subscribe('PLAYBACK_STOPPED', self.on_playback_stopped)
        self.event_manager.subscribe('PLAYBACK_ENDED', self.on_playback_stopped)
        self.event_manager.subscribe('ON_AV_CHANGE', self.on_av_change)

    def stop(self):
        # Unsubscribe from relevant events
        self.event_manager.unsubscribe('AV_STARTED', self.on_av_started)
        self.event_manager.unsubscribe('PLAYBACK_STOPPED', self.on_playback_stopped)
        self.event_manager.unsubscribe('PLAYBACK_ENDED', self.on_playback_stopped)
        self.event_manager.unsubscribe('ON_AV_CHANGE', self.on_av_change)

    def on_av_started(self):
        # Gather initial playback details
        self.info = self.gather_stream_info()
        xbmc.log(f"StreamInfo: AV Started with info: {self.info}", xbmc.LOGINFO)

    def on_av_change(self):
        # Gather updated playback details after stream change
        self.info = self.gather_stream_info()
        xbmc.log(f"StreamInfo: AV Change detected with updated info: {self.info}", xbmc.LOGINFO)

    def on_playback_stopped(self):
        # Clear the stream information when playback stops
        self.info = {}
        xbmc.log("StreamInfo: Playback stopped, clearing stream info", xbmc.LOGINFO)

    def gather_stream_info(self):
        # Retrieve stream information
        player_id = self.get_player_id()
        audio_format, audio_channels = self.get_audio_info(player_id)
        hdr_type = xbmc.getInfoLabel('Player.Process(video.source.hdr.type)')
        hdr_type = hdr_type.replace('+', 'plus').replace(' ', '').lower()
        if not hdr_type:
            hdr_type = 'sdr'
        gamut_info = xbmc.getInfoLabel('Player.Process(amlogic.eoft_gamut)')

        # Check for HLG detection based on gamut_info
        if hdr_type == 'sdr' and 'hlg' in gamut_info.lower():
            hdr_type = 'hlg'

        # Construct a dictionary of stream information
        stream_info = {
            'player_id': player_id,
            'audio_format': audio_format,
            'audio_channels': audio_channels,
            'hdr_type': hdr_type,
            'gamut_info': gamut_info
        }
        return stream_info

    def get_player_id(self):
        # Use JSON-RPC to retrieve the player ID, retrying up to 10 times if necessary
        for attempt in range(10):
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

            xbmc.log(f"StreamInfo: Invalid player ID, retrying... ({attempt + 1}/10)", xbmc.LOGINFO)
            time.sleep(0.5)

        xbmc.log("StreamInfo: Failed to retrieve valid player ID after 10 attempts", xbmc.LOGERROR)
        return -1

    def get_audio_info(self, player_id):
        # Use JSON-RPC to retrieve audio codec and channel count, retrying if 'none' is detected
        for attempt in range(10):
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

                    return audio_format, audio_channels

            xbmc.log(f"StreamInfo: Invalid audio format 'none', retrying... ({attempt + 1}/10)", xbmc.LOGINFO)
            time.sleep(0.5)

        xbmc.log("StreamInfo: Failed to retrieve valid audio information after 10 attempts", xbmc.LOGERROR)
        return "unknown", "unknown"