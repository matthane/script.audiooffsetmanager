import xbmc
import json

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

    def get_current_hdr_type(self):
        """
        Retrieves the current HDR type of the playing video using an infolabel.
        Returns:
            str: The HDR type (e.g., 'hdr10', 'dolbyvision', 'hlg'). Defaults to 'sdr' if no HDR type is detected.
        """
        hdr_type = xbmc.getInfoLabel('VideoPlayer.HdrType').lower()
        if not hdr_type:
            hdr_type = 'sdr'
        return hdr_type

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

        # DTS-HD MA with 8 channels is considered DTS:X
        if codec == 'dtshd_ma' and channel_count == 8:
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