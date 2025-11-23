"""Event manager module receives callback functions from Kodi regarding
playback events, filters them, and posts them to subscribers/other modules.
"""

import xbmc
import time
import json
import threading


class EventManager(xbmc.Player):
    def __init__(self):
        super().__init__()
        self._subscribers = {}
        self.playback_state = {
            'start_time': None,
            'av_started': False,
            'last_event': None,
            'last_audio_codec': None
        }

    def subscribe(self, event_name, callback):
        if event_name not in self._subscribers:
            self._subscribers[event_name] = []
        self._subscribers[event_name].append(callback)

    def unsubscribe(self, event_name, callback):
        if event_name in self._subscribers:
            self._subscribers[event_name].remove(callback)
            if not self._subscribers[event_name]:
                del self._subscribers[event_name]

    def publish(self, event_name, *args, **kwargs):
        if event_name in self._subscribers:
            for callback in self._subscribers[event_name]:
                callback(*args, **kwargs)
        self.playback_state['last_event'] = event_name

    def onAVStarted(self):
        xbmc.log("AOM_EventManager: AV started", xbmc.LOGDEBUG)
        self.playback_state['start_time'] = time.time()
        self.playback_state['av_started'] = True
        self.playback_state['last_audio_codec'] = None  # Reset codec tracking
        self.publish('AV_STARTED')

    def _get_current_audio_codec(self):
        """Get current audio codec from Kodi player via JSON-RPC."""
        try:
            # Get active player ID
            request = json.dumps({
                "jsonrpc": "2.0",
                "method": "Player.GetActivePlayers",
                "id": 1
            })
            response = xbmc.executeJSONRPC(request)
            response_json = json.loads(response)

            if "result" in response_json and len(response_json["result"]) > 0:
                player_id = response_json["result"][0].get("playerid", -1)

                if player_id == -1:
                    return None

                # Get current audio stream info
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
                    codec = audio_stream.get("codec", "unknown")
                    codec = codec.replace('pt-', '').lower()

                    # Treat 'none' as codec not available yet
                    if codec == 'none':
                        return None

                    return codec
        except Exception as e:
            xbmc.log(f"AOM_EventManager: Error getting audio codec: {str(e)}",
                     xbmc.LOGDEBUG)

        return None

    def _should_process_av_change(self):
        """Check if AV change event should be processed based on codec state."""
        if not self.playback_state['av_started']:
            return False

        current_codec = self._get_current_audio_codec()

        # Can't determine codec yet - wait for next event
        if current_codec is None:
            xbmc.log("AOM_EventManager: Codec not available yet, skipping event",
                     xbmc.LOGDEBUG)
            return False

        last_codec = self.playback_state.get('last_audio_codec')

        # Same codec as last processed - duplicate event
        if current_codec == last_codec:
            xbmc.log(f"AOM_EventManager: Duplicate AV change event for codec '{current_codec}', ignoring",
                     xbmc.LOGDEBUG)
            return False

        # New codec detected - schedule delayed verification for stability
        xbmc.log(f"AOM_EventManager: Codec change detected: '{last_codec}' -> '{current_codec}', "
                 f"scheduling stability verification", xbmc.LOGDEBUG)

        self._schedule_codec_verification(current_codec)

        return False  # Don't process immediately, wait for verification

    def _schedule_codec_verification(self, expected_codec):
        """Wait 1 second, then verify codec is still the expected value before publishing."""
        def verify():
            monitor = xbmc.Monitor()

            # Wait 1 second (or until Kodi abort)
            if monitor.waitForAbort(1.0):
                return  # Kodi is shutting down

            # Check if playback still active
            if not self.playback_state['av_started']:
                xbmc.log(f"AOM_EventManager: Playback stopped during codec verification for '{expected_codec}'",
                         xbmc.LOGDEBUG)
                return

            # Verify codec is still what we expect (stable)
            current_codec = self._get_current_audio_codec()

            if current_codec == expected_codec:
                xbmc.log(f"AOM_EventManager: Codec '{expected_codec}' verified stable after 1s, processing change",
                         xbmc.LOGDEBUG)
                self.playback_state['last_audio_codec'] = current_codec
                self.publish('ON_AV_CHANGE')
            else:
                xbmc.log(f"AOM_EventManager: Codec unstable: expected '{expected_codec}' but found '{current_codec}', ignoring",
                         xbmc.LOGDEBUG)

        thread = threading.Thread(target=verify)
        thread.daemon = True
        thread.start()

    def onAVChange(self):
        xbmc.log("AOM_EventManager: AV change event received", xbmc.LOGDEBUG)
        self._should_process_av_change()

    def onPlayBackStopped(self):
        xbmc.log("AOM_EventManager: Playback stopped", xbmc.LOGDEBUG)
        self.playback_state['start_time'] = None
        self.playback_state['av_started'] = False
        self.playback_state['last_audio_codec'] = None
        self.publish('PLAYBACK_STOPPED')

    def onPlayBackEnded(self):
        xbmc.log("AOM_EventManager: Playback ended", xbmc.LOGDEBUG)
        self.playback_state['start_time'] = None
        self.playback_state['av_started'] = False
        self.playback_state['last_audio_codec'] = None
        self.publish('PLAYBACK_ENDED')

    def onPlayBackPaused(self):
        xbmc.log("AOM_EventManager: Playback paused", xbmc.LOGDEBUG)
        self.publish('PLAYBACK_PAUSED')

    def onPlayBackResumed(self):
        xbmc.log("AOM_EventManager: Playback resumed", xbmc.LOGDEBUG)
        self.publish('PLAYBACK_RESUMED')

    def onPlayBackSeek(self, time, seekOffset):
        xbmc.log(f"AOM_EventManager: Playback seek to time {time} with offset "
                 f"{seekOffset}", xbmc.LOGDEBUG)
        self.publish('PLAYBACK_SEEK', time, seekOffset)

    def onPlayBackSeekChapter(self, chapter):
        xbmc.log(f"AOM_EventManager: Playback seek to chapter {chapter}",
                 xbmc.LOGDEBUG)
        self.publish('PLAYBACK_SEEK_CHAPTER', chapter)

    def onPlayBackSpeedChanged(self, speed):
        xbmc.log(f"AOM_EventManager: Playback speed changed to {speed}",
                 xbmc.LOGDEBUG)
        self.publish('PLAYBACK_SPEED_CHANGED', speed)
