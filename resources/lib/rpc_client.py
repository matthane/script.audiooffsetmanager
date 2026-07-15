"""MIGRATION(p7): re-export shim over the single-shot aom.kodi gateway.

The retrying JSON-RPC helpers moved to ``aom.kodi.gateway.KodiGateway`` as
single-shot calls — patience (retry budgets, jittered spacing) now lives in
the app-layer scheduler as cancelable events, not in blocking sleeps here.

Only the functions legacy modules still call are re-exported:

- ``set_audio_delay`` (OffsetManager) and ``seek_back`` (SeekBacks) were
  already single-shot; behavior is identical (log prefix is now
  ``AOM_Gateway``).
- ``get_active_player_id`` (SeekBacks) is now SINGLE-SHOT. Its retry loop
  only ever mattered at playback start; SeekBacks calls it mid-playback,
  where the player id resolves on the first attempt.
- ``get_audio_info`` had no remaining callers (StreamInfo's gather became
  the stream detector) and is gone.

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


def get_active_player_id():
    """Return the active player id or -1 (single shot; see module docstring)."""
    return _get_gateway().active_player_id()


def set_audio_delay(player_id, delay_seconds):
    """Set audio delay; logs errors but does not raise."""
    return _get_gateway().set_audio_delay(player_id, delay_seconds)


def seek_back(seconds, player_id=None):
    """Seek backward by seconds; returns True on success."""
    return _get_gateway().seek_back(seconds, player_id=player_id)
