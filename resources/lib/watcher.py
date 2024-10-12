import xbmc
import json
import re

class Watcher:
    """
    The Watcher class is responsible for interacting with the Kodi JSON-RPC API to obtain player and media information.
    """

    def get_player_id(self):
        """
        Retrieves the active player ID using JSON-RPC.
        Returns:
            int: The player ID if a player is active, otherwise None.
        """
        response = self.json_rpc_request({
            "jsonrpc": "2.0",
            "method": "Player.GetActivePlayers",
            "id": 1
        })
        if response and 'result' in response and response['result']:
            return response['result'][0]['playerid']
        return None

    def get_current_audio_stream(self, player_id):
        """
        Retrieves the current audio stream details of the active player.
        Args:
            player_id (int): The ID of the active player.
        Returns:
            dict: The audio stream details if available, otherwise None.
        """
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

    def determine_audio_format(self, audio_stream):
        """
        Determines the audio format based on the audio stream details.
        Args:
            audio_stream (dict): The audio stream details.
        Returns:
            tuple: A tuple containing the codec (str) and channel count (int).
        """
        codec = audio_stream.get('codec', '').lower()
        channel_count = audio_stream.get('channels', 0)

        # Remove 'pt-' prefix if present
        if codec.startswith('pt-'):
            codec = codec[3:]

        # DTS-HD MA with more than 6 channels is considered DTS:X
        if codec == 'dtshd_ma' and channel_count > 6:
            codec = 'dtsx'

        return codec, channel_count

    def json_rpc_request(self, payload):
        """
        Sends a JSON-RPC request to Kodi and parses the response.
        Args:
            payload (dict): The JSON-RPC payload to send.
        Returns:
            dict: The parsed JSON response.
        """
        request = json.dumps(payload)
        response = xbmc.executeJSONRPC(request)
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            xbmc.log(f"Invalid JSON response: {response}", xbmc.LOGERROR)
            return {}

    def get_video_properties(self):
        """
        Retrieves video properties related to EOTF, Gamut, and HDR using InfoLabels.
        Adjusts hdr_type if necessary based on eotf_gamut and hdr_type_confirm.
        Returns:
            dict: A dictionary containing relevant video properties.
        """
        properties = {}
        info_labels = {
            'eotf_gamut': 'Player.Process(amlogic.eoft_gamut)',           # EOTF and Gamut information
            'hdr_type': 'VideoPlayer.HdrType',                            # General Kodi InfoLabel for HDR type
            'hdr_type_confirm': 'Player.Process(video.source.hdr.type)',  # Detailed InfoLabel for platforms like CoreELEC
        }

        for key, label in info_labels.items():
            value = xbmc.getInfoLabel(label)
            if value == label or value == '':
                # InfoLabel is not available or returned empty
                value = None
            else:
                xbmc.log(f"Video Property - {key}: {value}", xbmc.LOGDEBUG)
            properties[key] = value

        # Determine hdr_type using hdr_type_confirm if available
        hdr_type_confirm = properties.get('hdr_type_confirm')
        hdr_type = properties.get('hdr_type') or 'sdr'

        if hdr_type_confirm:
            # Replace '+' with 'plus', remove other special characters, convert to lowercase
            hdr_type_raw = hdr_type_confirm  # Save the raw value for logging
            hdr_type = hdr_type_confirm.replace('+', 'plus')
            hdr_type = re.sub(r'\W+', '', hdr_type).lower()
            xbmc.log(f"Using hdr_type_confirm: {hdr_type_raw} -> {hdr_type}", xbmc.LOGDEBUG)
        else:
            hdr_type_raw = hdr_type  # Save the raw value for logging
            hdr_type = hdr_type.replace('+', 'plus')
            hdr_type = re.sub(r'\W+', '', hdr_type).lower()
            xbmc.log(f"Using hdr_type: {hdr_type_raw} -> {hdr_type}", xbmc.LOGDEBUG)

        eotf_gamut = properties.get('eotf_gamut') or ''

        # Adjust hdr_type if necessary to catch all HLG videos
        if hdr_type == 'sdr' and 'hlg' in eotf_gamut.lower():
            hdr_type = 'hlg'
            xbmc.log(f"Adjusted HDR Type to 'hlg' based on EOTF/Gamut: {eotf_gamut}", xbmc.LOGDEBUG)

        properties['hdr_type'] = hdr_type  # Update hdr_type in properties

        return properties