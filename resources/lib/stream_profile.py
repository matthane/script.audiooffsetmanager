from dataclasses import dataclass


@dataclass(frozen=True)
class StreamProfile:
    """Immutable stream characteristics used for settings lookups and display."""

    hdr_type: str
    fps_type: object  # Accept str/int to match existing sources
    audio_format: str
    video_fps: object
    player_id: int
    audio_channels: object

    _AUDIO_NAMES = {
        'truehd': 'TrueHD',
        'eac3': 'DD+',
        'ac3': 'DD',
        'dtshd_ma': 'DTS-HD MA',
        'dtshd_hra': 'DTS-HD HRA',
        'dca': 'DTS',
        'pcm': 'PCM',
        'unknown': 'Unknown Format'
    }

    _HDR_NAMES = {
        'dolbyvision': 'DV',
        'hdr10': 'HDR10',
        'hdr10plus': 'HDR10+',
        'hlg': 'HLG',
        'sdr': 'SDR'
    }

    _FPS_NAMES = {
        '23': '23.98',
        '24': '24.00',
        '25': '25.00',
        '29': '29.97',
        '30': '30.00',
        '50': '50.00',
        '59': '59.94',
        '60': '60.00'
    }

    def setting_id(self):
        """ID used for settings grid: <hdr>_<fps>_<audio>."""
        return f"{self.hdr_type}_{self._fps_key()}_{self.audio_format}"

    def display_hdr(self):
        return self._HDR_NAMES.get(self.hdr_type, self.hdr_type)

    def display_audio(self):
        return self._AUDIO_NAMES.get(self.audio_format, self.audio_format)

    def display_fps(self):
        fps_key = self._fps_key()
        return self._FPS_NAMES.get(fps_key, str(fps_key))

    def summary(self, include_fps=True):
        fps_key = self._fps_key()
        hdr_label = self.display_hdr()
        audio_label = self.display_audio()

        if include_fps and str(fps_key).lower() != 'all':
            fps_label = self.display_fps()
            return f"{hdr_label} | {fps_label} FPS | {audio_label}"
        return f"{hdr_label} | {audio_label}"

    def _fps_key(self):
        return str(self.fps_type)
