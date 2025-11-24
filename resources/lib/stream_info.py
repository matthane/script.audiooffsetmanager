"""Stream Info module used to gather stream HDR and audio format information."""

import xbmc
from resources.lib.settings_manager import SettingsManager
from resources.lib.settings_facade import SettingsFacade
from resources.lib.stream_profile import StreamProfile
from resources.lib import rpc_client
from resources.lib.logger import log


class StreamInfo:
    def __init__(self, settings_manager=None, settings_facade=None):
        self.profile = None
        self.metadata = {}
        self.settings_manager = settings_manager or SettingsManager()
        self.settings_facade = settings_facade or SettingsFacade(self.settings_manager)
        self.new_install = self.settings_manager.get_setting_boolean('new_install')
        self.valid_audio_formats = ['truehd', 'eac3', 'ac3', 'dtshd_ma', 'dtshd_hra', 'dca', 'pcm']
        self.valid_hdr_types = ['dolbyvision', 'hdr10', 'hdr10plus', 'hlg', 'sdr']
        self.valid_fps_types = [23, 24, 25, 29, 30, 50, 59, 60]

    def update_stream_info(self):
        # Gather updated playback details
        self.profile, self.metadata = self.gather_stream_info()
        log(f"AOM_StreamInfo: Updated stream profile: {self.profile}", xbmc.LOGDEBUG)

    def clear_stream_info(self):
        # Clear the stream information
        self.profile = None
        self.metadata = {}
        log("AOM_StreamInfo: Cleared stream info", xbmc.LOGDEBUG)

    def is_valid_infolabel(self, label, value):
        return value and value.strip() and value.lower() != label.lower()

    def gather_stream_info(self):
        # Get player ID
        player_id = self.get_player_id()
        
        # Get audio information (only if player is valid)
        if player_id == -1:
            log("AOM_StreamInfo: No active player, skipping audio info retrieval", xbmc.LOGDEBUG)
            audio_format, audio_channels = 'unknown', 'unknown'
        else:
            audio_format, audio_channels = self.get_audio_info(player_id)
            if audio_format not in self.valid_audio_formats:
                log(f"AOM_StreamInfo: Invalid audio format detected: {audio_format}", xbmc.LOGDEBUG)
                audio_format = 'unknown'
        
        # Get FPS information
        fps_label = 'Player.Process(videofps)'
        fps_info = xbmc.getInfoLabel(fps_label)
        
        try:
            fps_value = int(float(fps_info))
            fps_type = fps_value if fps_value in self.valid_fps_types else 'unknown'
            if fps_type != 'unknown':
                log(f"AOM_StreamInfo: Valid FPS type detected: {fps_type}", xbmc.LOGDEBUG)
            else:
                log(f"AOM_StreamInfo: Non-standard FPS value: {fps_value}", xbmc.LOGDEBUG)
        except (ValueError, TypeError):
            fps_value = None
            fps_type = 'unknown'
            log(f"AOM_StreamInfo: Unable to parse FPS value: {fps_info}", xbmc.LOGDEBUG)
        
        # Get HDR information
        hdr_label = 'Player.Process(video.source.hdr.type)'
        hdr_type = xbmc.getInfoLabel(hdr_label)
        log(f"AOM_StreamInfo: Raw HDR type: '{hdr_type}'", xbmc.LOGDEBUG)
        
        # Check platform HDR support
        if self.is_valid_infolabel(hdr_label, hdr_type):
            platform_hdr_full = True
            log("AOM_StreamInfo: Platform HDR full support detected", xbmc.LOGDEBUG)
        else:
            platform_hdr_full = False
            hdr_type = xbmc.getInfoLabel('VideoPlayer.HdrType')
            log("AOM_StreamInfo: Using fallback HDR detection", xbmc.LOGDEBUG)
        
        # Process HDR type
        hdr_type = hdr_type.replace('+', 'plus').replace(' ', '').lower()
        if not hdr_type or hdr_type == hdr_label.lower():
            hdr_type = 'sdr'
        elif hdr_type == 'hlghdr':
            hdr_type = 'hlg'
        
        if hdr_type not in self.valid_hdr_types:
            log(f"AOM_StreamInfo: Invalid HDR type detected: {hdr_type}", xbmc.LOGDEBUG)
            hdr_type = 'unknown'
        
        # Get gamut information
        gamut_label = 'Player.Process(amlogic.eoft_gamut)'
        gamut_info = xbmc.getInfoLabel(gamut_label)
        gamut_info_valid = self.is_valid_infolabel(gamut_label, gamut_info)
        
        if not gamut_info_valid:
            gamut_info = 'not available'
        
        # Check for HLG detection based on gamut_info
        if hdr_type == 'sdr' and gamut_info_valid and 'hlg' in gamut_info.lower():
            hdr_type = 'hlg'
            log("AOM_StreamInfo: HLG detected via gamut info", xbmc.LOGDEBUG)
        
        # Store platform capabilities on every playback
        self.settings_facade.store_boolean_if_changed('platform_hdr_full', platform_hdr_full)
        advanced_hlg = gamut_info_valid
        self.settings_facade.store_boolean_if_changed('advanced_hlg', advanced_hlg)
        log("AOM_StreamInfo: Updated platform capabilities", xbmc.LOGDEBUG)
        
        # Handle new install flag if needed
        if self.new_install:
            self.new_install = False
            self.settings_facade.store_boolean_if_changed('new_install', self.new_install)
            log("AOM_StreamInfo: Updated new install flag", xbmc.LOGDEBUG)

        # Check if FPS type should be overridden based on HDR setting
        if hdr_type != 'unknown':
            fps_enabled = self.settings_facade.fps_override_enabled(hdr_type)
            log(f"AOM_StreamInfo: Checking FPS override for '{hdr_type}' = {fps_enabled}", xbmc.LOGDEBUG)

            if not fps_enabled:
                fps_type = 'all'
                log("AOM_StreamInfo: FPS type overridden to 'all' due to override setting", xbmc.LOGDEBUG)
            else:
                log(f"AOM_StreamInfo: Keeping original FPS type '{fps_type}'", xbmc.LOGDEBUG)

        # Construct immutable profile and auxiliary metadata
        profile = StreamProfile(
            hdr_type=hdr_type,
            fps_type=fps_type,
            audio_format=audio_format,
            video_fps=fps_value,
            player_id=player_id,
            audio_channels=audio_channels
        )
        metadata = {
            'gamut_info': gamut_info,
            'gamut_info_valid': gamut_info_valid,
            'platform_hdr_full': platform_hdr_full
        }

        log(f"AOM_StreamInfo: Gathered stream profile {profile} with metadata {metadata}", xbmc.LOGDEBUG)
        return profile, metadata

    def get_player_id(self):
        """Retrieve active player id via RPC helper."""
        return rpc_client.get_active_player_id()

    def get_audio_info(self, player_id):
        """Retrieve audio codec and channels via RPC helper with validation."""
        audio_format, audio_channels = rpc_client.get_audio_info(player_id)

        # Check if the reported format contains any of our valid formats
        reported_format = audio_format.lower()
        for valid_format in self.valid_audio_formats:
            if valid_format in reported_format:
                audio_format = valid_format
                break
        else:
            # If no valid format is found, assume PCM unless unknown
            if audio_format not in ['unknown', 'none']:
                audio_format = 'pcm'

        return audio_format, audio_channels
