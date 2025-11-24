"""Seek backs module submits player seek commands based on playback events."""

import xbmc
import time
from resources.lib.settings_manager import SettingsManager
from resources.lib.settings_facade import SettingsFacade
from resources.lib import rpc_client
from resources.lib.logger import log


class SeekBacks:
    # Event type mapping for settings
    SETTING_TYPE_MAP = {
        'resume': 'resume',
        'adjust': 'adjust',
        'unpause': 'unpause',
        'change': 'change'  # Keep 'change' separate from 'adjust'
    }

    def __init__(self, event_manager, settings_manager=None, settings_facade=None):
        self.event_manager = event_manager
        self.settings_manager = settings_manager or SettingsManager()
        self.settings_facade = settings_facade or SettingsFacade(self.settings_manager)
        self.playback_state = {
            'paused': False,
            'last_seek_time': 0,  # Track the last time we performed a seek
            'initial_av_change_seen': False,
            'seek_in_progress': False,
            'last_seek_by_event': {}
        }

    def start(self):
        """Start the seek backs module by subscribing to relevant events."""
        events = {
            'AV_STARTED': self.on_av_started,
            'ON_AV_CHANGE': self.on_av_change,
            'PLAYBACK_RESUMED': self.on_av_unpause,
            'PLAYBACK_PAUSED': self.on_playback_paused,
            'USER_ADJUSTMENT': self.on_user_adjustment,
            'PLAYBACK_STOPPED': self.on_playback_stopped,
            'PLAYBACK_ENDED': self.on_playback_stopped  # Use same handler for both stop and end
        }
        for event, callback in events.items():
            self.event_manager.subscribe(event, callback)

    def stop(self):
        """Stop the seek backs module and clean up subscriptions."""
        events = {
            'AV_STARTED': self.on_av_started,
            'ON_AV_CHANGE': self.on_av_change,
            'PLAYBACK_RESUMED': self.on_av_unpause,
            'PLAYBACK_PAUSED': self.on_playback_paused,
            'USER_ADJUSTMENT': self.on_user_adjustment,
            'PLAYBACK_STOPPED': self.on_playback_stopped,
            'PLAYBACK_ENDED': self.on_playback_stopped
        }
        for event, callback in events.items():
            self.event_manager.unsubscribe(event, callback)

    def on_av_started(self):
        """Handle AV started event."""
        # Reset playback state when new playback starts
        self.playback_state['paused'] = False
        self.playback_state['initial_av_change_seen'] = False
        self.perform_seek_back('resume')

    def on_av_change(self):
        """Handle AV change event."""
        if not self.playback_state.get('initial_av_change_seen'):
            self.playback_state['initial_av_change_seen'] = True
            log("AOM_SeekBacks: Skipping initial AV change (startup)", xbmc.LOGDEBUG)
            return

        self.perform_seek_back('adjust')

    def on_av_unpause(self):
        """Handle playback resume event."""
        xbmc.sleep(500)  # Small delay to avoid race condition on flag
        self.playback_state['paused'] = False
        self.perform_seek_back('unpause')

    def on_playback_paused(self):
        """Handle playback paused event."""
        self.playback_state['paused'] = True

    def on_playback_stopped(self):
        """Handle playback stopped/ended event."""
        log("AOM_SeekBacks: Playback stopped/ended, resetting playback state", xbmc.LOGDEBUG)
        self.playback_state['paused'] = False
        self.playback_state['last_seek_time'] = 0
        self.playback_state['initial_av_change_seen'] = False
        self.playback_state['seek_in_progress'] = False

    def on_user_adjustment(self):
        """Handle user adjustment event."""
        log("AOM_SeekBacks: Processing user adjustment event", xbmc.LOGDEBUG)
        # Check if seek back is enabled for changes (user adjustments)
        enabled, _ = self.settings_facade.seek_back_config('change')
        if enabled:
            self.perform_seek_back('change')
        else:
            log("AOM_SeekBacks: Seek back for user adjustments is disabled", xbmc.LOGDEBUG)

    def _get_setting_type(self, event_type):
        """Get the correct setting type based on event type.
        
        Args:
            event_type: The type of event triggering the seek back
            
        Returns:
            str: The corresponding setting type
        """
        return self.SETTING_TYPE_MAP.get(event_type, event_type)

    def _should_perform_seek_back(self, event_type):
        """Check if seek back should be performed based on current conditions.
        
        Args:
            event_type: The type of event triggering the seek back
            
        Returns:
            tuple: (should_seek, seek_seconds) or (False, None) if seek is not needed
        """
        # Check if we've performed a seek back recently (within 2 seconds, per event type)
        current_time = time.time()
        last_by_type = self.playback_state['last_seek_by_event'].get(event_type, 0)
        if current_time - last_by_type < 2:
            log(f"AOM_SeekBacks: Skipping seek back on {event_type} - too soon after last seek of this type",
                xbmc.LOGDEBUG)
            return False, None

        if self.playback_state.get('seek_in_progress'):
            log(f"AOM_SeekBacks: Seek back already in progress; skipping {event_type}",
                xbmc.LOGDEBUG)
            return False, None

        if self.playback_state['paused']:
            log(f"AOM_SeekBacks: Playback is paused, skipping seek back "
                f"on {event_type}", xbmc.LOGDEBUG)
            return False, None

        setting_type = self._get_setting_type(event_type)
        enabled, seek_seconds = self.settings_facade.seek_back_config(setting_type)
        if not enabled:
            log(f"AOM_SeekBacks: Seek back on {event_type} (setting: enable_seek_back_{setting_type}) "
                f"is not enabled", xbmc.LOGDEBUG)
            return False, None

        if seek_seconds <= 0:
            log(f"AOM_SeekBacks: Invalid seek back seconds ({seek_seconds}) "
                f"for {event_type}", xbmc.LOGWARNING)
            return False, None

        log(f"AOM_SeekBacks: Will seek back {seek_seconds} seconds on {event_type} "
            f"(setting: {setting_type})", xbmc.LOGDEBUG)
        return True, seek_seconds

    def _execute_seek_command(self, seconds, event_type):
        """Execute the JSON-RPC seek command.
        
        Args:
            seconds: Number of seconds to seek back
            event_type: The type of event that triggered the seek
            
        Returns:
            bool: True if seek was successful, False otherwise
        """
        log(f"AOM_SeekBacks: Attempting to seek back {seconds} seconds "
            f"on {event_type}", xbmc.LOGDEBUG)

        # Use active player id if available
        player_id = rpc_client.get_active_player_id()
        success = rpc_client.seek_back(seconds, player_id=player_id if player_id != -1 else None)
        if success:
            self.playback_state['last_seek_time'] = time.time()
            self.playback_state['last_seek_by_event'][event_type] = time.time()
        return success

    def perform_seek_back(self, event_type):
        """Perform seek back operation based on event type and current conditions.
        
        Args:
            event_type: The type of event triggering the seek back
        """
        try:
            should_seek, seek_seconds = self._should_perform_seek_back(event_type)
            
            if not should_seek:
                return

            self.playback_state['seek_in_progress'] = True
                
            # Required delay for stream settling; abort-aware
            monitor = xbmc.Monitor()
            if monitor.waitForAbort(2.0):
                return
            
            if not self._execute_seek_command(seek_seconds, event_type):
                log(f"AOM_SeekBacks: Seek back operation failed for {event_type}",
                    xbmc.LOGWARNING)
                
        except Exception as e:
            log(f"AOM_SeekBacks: Error in perform_seek_back: {str(e)}",
                xbmc.LOGERROR)
        finally:
            self.playback_state['seek_in_progress'] = False
