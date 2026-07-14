"""Seek backs module submits player seek commands based on playback events."""

import xbmc
import time
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

    def __init__(self, event_manager, settings_manager, settings_facade):
        self.event_manager = event_manager
        self.settings_manager = settings_manager
        self.settings_facade = settings_facade
        self.playback_state = {
            'paused': False,
            'last_seek_time': 0,  # Track the last time we performed a seek
            'initial_av_change_seen': False,
            'seek_in_progress': False,
            'last_seek_by_event': {},
            'last_pm4k_busy': 0,
            'last_kodi_seek': 0
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
            'PLAYBACK_ENDED': self.on_playback_stopped,  # Use same handler for both stop and end
            'PLAYBACK_SEEK': self.on_playback_seek
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
            'PLAYBACK_ENDED': self.on_playback_stopped,
            'PLAYBACK_SEEK': self.on_playback_seek
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
        self.playback_state['last_kodi_seek'] = 0
        self.playback_state['initial_av_change_seen'] = False
        self.playback_state['seek_in_progress'] = False

    def on_playback_seek(self, *args, **kwargs):
        """Handle any Kodi seek (regardless of source)."""
        self.playback_state['last_kodi_seek'] = time.time()

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

    def _pm4k_playback_busy(self, log_if_busy=True):
        """Check Plex Mod 4 Kodi flags to avoid overlapping seeks.

        PM4K sets properties to '1' while it is running its own seeks. If PM4K
        is not installed, getInfoLabel returns the label string or empty, so we
        only treat an exact '1' as active.
        """
        plex_props = {
            'playback_seeking': xbmc.getInfoLabel('Window(10000).Property(script.plex.playback_seeking)'),
            'playback_initializing': xbmc.getInfoLabel('Window(10000).Property(script.plex.playback_initializing)')
        }

        for name, value in plex_props.items():
            if value == '1':
                self.playback_state['last_pm4k_busy'] = time.time()
                if log_if_busy:
                    log(f"AOM_SeekBacks: PM4K indicates {name}; deferring seek back", xbmc.LOGDEBUG)
                return True
        return False

    def _pm4k_recently_busy(self, grace_seconds=2.5):
        """Check if PM4K was busy recently to avoid back-to-back seeks."""
        last_busy = self.playback_state.get('last_pm4k_busy', 0)
        return (time.time() - last_busy) < grace_seconds

    def _wait_for_pm4k_idle(self, timeout=6.0):
        """Poll for PM4K to go idle so we can safely seek after startup."""
        monitor = xbmc.Monitor()
        end_time = time.time() + timeout
        while time.time() < end_time:
            if not self._pm4k_playback_busy(log_if_busy=False):
                return True
            if monitor.waitForAbort(0.1):
                return False
        log("AOM_SeekBacks: PM4K remained busy after waiting; skipping startup seek back", xbmc.LOGDEBUG)
        return False

    def _should_perform_seek_back(self, event_type, ignore_pm4k_recent=False,
                                  ignore_recent_kodi_seek=False):
        """Check if seek back should be performed based on current conditions.
        
        Args:
            event_type: The type of event triggering the seek back
            ignore_pm4k_recent: Skip recent-PM4K grace window when we've
                already waited for PM4K to go idle on startup
            ignore_recent_kodi_seek: Skip recent-Kodi-seek guard (used for
                startup so invisible PM4K seeks don't block our own)
            
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

        if self._pm4k_playback_busy():
            return False, None

        if not ignore_pm4k_recent and self._pm4k_recently_busy():
            log(f"AOM_SeekBacks: PM4K was busy moments ago; skipping seek back on {event_type}",
                xbmc.LOGDEBUG)
            return False, None

        if not ignore_recent_kodi_seek:
            last_kodi_seek = self.playback_state.get('last_kodi_seek', 0)
            if event_type in ('unpause', 'resume') and (time.time() - last_kodi_seek) < 2.5:
                log(f"AOM_SeekBacks: Recent Kodi seek detected; skipping {event_type} seek back to avoid double-seek",
                    xbmc.LOGDEBUG)
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
            self.playback_state['last_kodi_seek'] = time.time()
        return success

    def perform_seek_back(self, event_type):
        """Perform seek back operation based on event type and current conditions.
        
        Args:
            event_type: The type of event triggering the seek back
        """
        try:
            ignore_pm4k_recent = False
            ignore_recent_kodi_seek = (event_type == 'resume')
            if event_type == 'resume' and self._pm4k_playback_busy(log_if_busy=False):
                log("AOM_SeekBacks: PM4K busy on startup; waiting before issuing seek back",
                    xbmc.LOGDEBUG)
                if not self._wait_for_pm4k_idle():
                    return
                ignore_pm4k_recent = True

            should_seek, seek_seconds = self._should_perform_seek_back(
                event_type,
                ignore_pm4k_recent=ignore_pm4k_recent,
                ignore_recent_kodi_seek=ignore_recent_kodi_seek)
            
            if not should_seek:
                return

            self.playback_state['seek_in_progress'] = True
                
            # Required delay for stream settling; abort-aware. Poll PM4K during this window
            # so we can skip if it was active shortly before we issue our seek.
            monitor = xbmc.Monitor()
            end_time = time.time() + 2.0
            while time.time() < end_time:
                # Capture brief PM4K activity without spamming logs
                self._pm4k_playback_busy(log_if_busy=False)
                if monitor.waitForAbort(0.1):
                    return

            # Re-check PM4K after settling to avoid double-seeks if it just ran
            if self._pm4k_playback_busy():
                return
            if not ignore_pm4k_recent and self._pm4k_recently_busy():
                log(f"AOM_SeekBacks: Skipping {event_type} seek back after settle due to recent PM4K activity",
                    xbmc.LOGDEBUG)
                return

            log(f"AOM_SeekBacks: Will seek back {seek_seconds} seconds on {event_type} "
                f"(setting: {self._get_setting_type(event_type)})", xbmc.LOGDEBUG)
            
            if not self._execute_seek_command(seek_seconds, event_type):
                log(f"AOM_SeekBacks: Seek back operation failed for {event_type}",
                    xbmc.LOGWARNING)
                
        except Exception as e:
            log(f"AOM_SeekBacks: Error in perform_seek_back: {str(e)}",
                xbmc.LOGERROR)
        finally:
            self.playback_state['seek_in_progress'] = False
