"""MIGRATION(p7): re-export shim over the single-shot aom.kodi gateway.

The retrying JSON-RPC helpers moved to ``aom.kodi.gateway.KodiGateway`` as
single-shot calls — patience (retry budgets, jittered spacing) now lives in
the app-layer scheduler as cancelable events, not in blocking sleeps here.

Only ``set_audio_delay`` still has a legacy caller (OffsetManager);
``get_active_player_id`` and ``seek_back`` lost theirs when the seek
scheduler replaced SeekBacks (it calls the injected gateway directly), and
``get_audio_info`` lost its callers to the stream detector.

The gateway instance is a lazily-memoized module singleton — a deliberate,
shim-scoped exception to the no-global-state convention (module functions
cannot take constructor injection); it is created on first call, never at
import, so importing this module performs no Kodi I/O. This shim dies with
the legacy modules in Phase 7, leaving the runtime's injected gateway as
the single instance.
"""

from resources.lib.aom.kodi.gateway import KodiGateway
from resources.lib.logger import log

_gateway = None


def _get_gateway():
    global _gateway
    if _gateway is None:
        _gateway = KodiGateway(log=log)
    return _gateway


def set_audio_delay(player_id, delay_seconds):
    """Set audio delay; logs errors but does not raise."""
    return _get_gateway().set_audio_delay(player_id, delay_seconds)
