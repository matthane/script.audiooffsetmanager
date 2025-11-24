"""Shared JSON-RPC helpers for Kodi interactions."""

import json
import time
import random
import xbmc
from resources.lib.logger import log


def _execute_rpc(request):
    """Execute a JSON-RPC request and return decoded JSON."""
    response = xbmc.executeJSONRPC(json.dumps(request))
    return json.loads(response)


def get_active_player_id(max_attempts=10, delay=0.5):
    """Return active player id or -1 after retries."""
    for attempt in range(max_attempts):
        try:
            response_json = _execute_rpc({
                "jsonrpc": "2.0",
                "method": "Player.GetActivePlayers",
                "id": 1
            })

            if "result" in response_json and len(response_json["result"]) > 0:
                player_id = response_json["result"][0].get("playerid", -1)
                if player_id != -1:
                    return player_id

            log(f"AOM_RPC: Invalid player ID, retrying... ({attempt + 1}/{max_attempts})",
                xbmc.LOGDEBUG)
        except Exception as e:
            log(f"AOM_RPC: Error getting player ID: {str(e)}", xbmc.LOGERROR)

        time.sleep(_jittered_delay(delay))

    log(f"AOM_RPC: Failed to retrieve valid player ID after {max_attempts} attempts",
        xbmc.LOGWARNING)
    return -1


def get_audio_info(player_id, max_attempts=10, delay=0.5):
    """Return (audio_format, audio_channels) with retries."""
    for attempt in range(max_attempts):
        try:
            response_json = _execute_rpc({
                "jsonrpc": "2.0",
                "method": "Player.GetProperties",
                "params": {
                    "playerid": player_id,
                    "properties": ["currentaudiostream"]
                },
                "id": 1
            })

            if "result" in response_json and "currentaudiostream" in response_json["result"]:
                audio_stream = response_json["result"]["currentaudiostream"]
                audio_format = audio_stream.get("codec", "unknown").replace('pt-', '')
                audio_channels = audio_stream.get("channels", "unknown")

                if audio_format != 'none':
                    return audio_format, audio_channels

            log(f"AOM_RPC: Invalid audio format 'none', retrying... ({attempt + 1}/{max_attempts})",
                xbmc.LOGDEBUG)
        except Exception as e:
            log(f"AOM_RPC: Error getting audio info: {str(e)}", xbmc.LOGERROR)

        time.sleep(_jittered_delay(delay))

    log(f"AOM_RPC: Failed to retrieve valid audio information after {max_attempts} attempts",
        xbmc.LOGWARNING)
    return "unknown", "unknown"


def set_audio_delay(player_id, delay_seconds):
    """Set audio delay; logs errors but does not raise."""
    try:
        response_json = _execute_rpc({
            "jsonrpc": "2.0",
            "method": "Player.SetAudioDelay",
            "params": {
                "playerid": player_id,
                "offset": delay_seconds
            },
            "id": 1
        })

        if "error" in response_json:
            log(f"AOM_RPC: Failed to set audio offset: {response_json['error']}",
                xbmc.LOGWARNING)
            return False

        log(f"AOM_RPC: Audio offset set to {delay_seconds} seconds", xbmc.LOGDEBUG)
        return True
    except Exception as e:
        log(f"AOM_RPC: Error setting audio delay: {str(e)}", xbmc.LOGERROR)
        return False


def seek_back(seconds, player_id=None):
    """Seek backward by seconds; returns True on success."""
    target_player_id = player_id if player_id is not None else 1
    request = {
        "jsonrpc": "2.0",
        "method": "Player.Seek",
        "params": {
            "playerid": target_player_id,
            "value": {"seconds": -seconds}
        },
        "id": 1
    }

    try:
        log(f"AOM_RPC: Attempting to seek back {seconds} seconds", xbmc.LOGDEBUG)
        response_json = _execute_rpc(request)

        if "error" in response_json:
            log(f"AOM_RPC: Failed to perform seek back: {response_json['error']}",
                xbmc.LOGWARNING)
            return False

        log(f"AOM_RPC: Successfully seeked back by {seconds} seconds", xbmc.LOGDEBUG)
        return True
    except Exception as e:
        log(f"AOM_RPC: Error executing seek command: {str(e)}", xbmc.LOGERROR)
        return False


def _jittered_delay(base_delay):
    """Return a jittered sleep time to avoid thundering herd on retries."""
    return max(0.1, base_delay * (0.8 + (random.random() * 0.4)))
