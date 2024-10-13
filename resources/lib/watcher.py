import xbmc
import json
import re

class Watcher:
    """
    The Watcher class interacts with the Kodi JSON-RPC API to obtain player and media information.
    """

    def json_rpc_request(self, payload):
        """
        Sends a JSON-RPC request to Kodi and parses the response.
        Args:
            payload (dict): The JSON-RPC payload to send.
        Returns:
            dict: The parsed JSON response, or an empty dict if an error occurs.
        """
        request = json.dumps(payload)
        response = xbmc.executeJSONRPC(request)
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            xbmc.log(f"Invalid JSON response: {response}", xbmc.LOGERROR)
            return {}

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
        if response and response.get('result'):
            return response['result'][0].get('playerid')
        return None

    def get_current_audio_stream(self, player_id):
        """
        Retrieves the current audio stream details of the active player.
        Args:
            player_id (int): The ID of the active player.
        Returns:
            dict: The audio stream details, or None if not available.
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
        if response and response.get('result'):
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
        codec = codec[3:] if codec.startswith('pt-') else codec

        # DTS-HD MA with more than 6 channels is considered DTS:X
        if codec == 'dtshd_ma' and channel_count > 6:
            codec = 'dtsx'

        return codec, channel_count

    def get_video_properties(self):
        """
        Retrieves video properties related to EOTF, Gamut, and HDR using InfoLabels.
        Adjusts hdr_type if necessary based on eotf_gamut and hdr_type_confirm.
        Returns:
            dict: A dictionary containing relevant video properties.
        """
        info_labels = {
            'eotf_gamut': 'Player.Process(amlogic.eoft_gamut)',           # EOTF and Gamut info for advanced HLG detection on Amlogic devices
            'hdr_type': 'VideoPlayer.HdrType',                            # General Kodi InfoLabel for HDR type, doesn't yet report HDR10+
            'hdr_type_confirm': 'Player.Process(video.source.hdr.type)',  # Detailed InfoLabel HDR type for HDR10+ detection
        }

        properties = {key: self.get_info_label(label) for key, label in info_labels.items()}
        
        # Adjust hdr_type based on hdr_type_confirm or eotf_gamut
        hdr_type = self.clean_hdr_type(properties.get('hdr_type'), properties.get('hdr_type_confirm'))
        eotf_gamut = properties.get('eotf_gamut') or ''

        if hdr_type == 'sdr' and 'hlg' in eotf_gamut.lower():
            hdr_type = 'hlg'
            xbmc.log(f"Adjusted HDR Type to 'hlg' based on EOTF/Gamut: {eotf_gamut}", xbmc.LOGDEBUG)

        properties['hdr_type'] = hdr_type
        return properties

    def get_info_label(self, label):
        """
        Retrieves a specific InfoLabel from Kodi.
        Args:
            label (str): The InfoLabel to retrieve.
        Returns:
            str: The value of the InfoLabel, or None if not available.
        """
        value = xbmc.getInfoLabel(label)
        if value == label or value == '':
            return None
        xbmc.log(f"Video Property - {label}: {value}", xbmc.LOGDEBUG)
        return value

    def clean_hdr_type(self, hdr_type, hdr_type_confirm):
        """
        Cleans and determines the final HDR type based on provided info.
        Args:
            hdr_type (str): General HDR type InfoLabel.
            hdr_type_confirm (str): Detailed HDR type InfoLabel for HDR10+.
        Returns:
            str: The cleaned HDR type.
        """
        hdr_type = hdr_type or 'sdr'
        raw_value = hdr_type_confirm or hdr_type
        
        # Replace '+' with 'plus', remove special characters, convert to lowercase
        clean_hdr_type = raw_value.replace('+', 'plus')
        clean_hdr_type = re.sub(r'\W+', '', clean_hdr_type).lower()

        xbmc.log(f"Using HDR Type: {raw_value} -> {clean_hdr_type}", xbmc.LOGDEBUG)
        return clean_hdr_type