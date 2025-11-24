"""Addon-level logging helper with toggle-controlled escalation."""

import xbmc
from resources.lib.settings_manager import SettingsManager
from resources.lib.settings_facade import SettingsFacade

_shared_facade = None


def _get_facade(settings_facade=None, settings_manager=None):
    """Return a SettingsFacade, caching a shared instance."""
    global _shared_facade
    if settings_facade:
        return settings_facade
    if _shared_facade is not None:
        return _shared_facade
    manager = settings_manager or SettingsManager()
    _shared_facade = SettingsFacade(manager)
    return _shared_facade


def log(message, level=xbmc.LOGDEBUG, settings_facade=None, settings_manager=None, prefix="[AOM]"):
    """Log with optional debug escalation based on addon toggle."""
    facade = _get_facade(settings_facade, settings_manager)
    effective_level = level
    if level == xbmc.LOGDEBUG and facade.debug_logging_enabled():
        effective_level = xbmc.LOGINFO
    # Avoid double-tagging if caller already prefixes
    use_prefix = "" if (message.startswith("[AOM]") or message.startswith("AOM_")) else prefix
    xbmc.log(f"{use_prefix} {message}".strip(), effective_level)
